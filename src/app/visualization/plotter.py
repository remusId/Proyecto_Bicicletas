"""Renderizado de un mapa PNG legible con la ruta calculada."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.collections import LineCollection
from matplotlib.patches import FancyArrowPatch

EARTH_RADIUS_M = 6_371_008.8
MERCATOR_RADIUS_M = 6_378_137.0
MAX_MERCATOR_LAT = 85.05112878

# ancho (pt), color y estilo de línea por tipo de vía
HIGHWAY_STYLES: dict[str, tuple[float, str, Any]] = {
    "motorway": (2.6, "#9e9e9e", "solid"),
    "motorway_link": (2.0, "#a6a6a6", "solid"),
    "trunk": (2.4, "#a3a3a3", "solid"),
    "trunk_link": (1.9, "#aaaaaa", "solid"),
    "primary": (2.3, "#a8a8a8", "solid"),
    "primary_link": (1.9, "#b0b0b0", "solid"),
    "secondary": (1.9, "#b4b4b4", "solid"),
    "secondary_link": (1.6, "#bababa", "solid"),
    "tertiary": (1.5, "#bdbdbd", "solid"),
    "tertiary_link": (1.3, "#c2c2c2", "solid"),
    "unclassified": (1.1, "#c8c8c8", "solid"),
    "road": (1.1, "#c8c8c8", "solid"),
    "residential": (1.0, "#cbcbcb", "solid"),
    "living_street": (0.9, "#d0d0d0", "solid"),
    "service": (0.7, "#d6d6d6", "solid"),
    "cycleway": (1.3, "#5f9e4a", "solid"),
    "path": (0.8, "#c4c4c4", (0, (3, 2))),
    "track": (0.8, "#c4c4c4", (0, (3, 2))),
    "bridleway": (0.8, "#c4c4c4", (0, (3, 2))),
    "footway": (0.8, "#c0c0c0", (0, (2, 2))),
    "pedestrian": (0.9, "#c0c0c0", (0, (2, 2))),
    "steps": (0.8, "#b8b8b8", (0, (1.5, 1.5))),
}
DEFAULT_STYLE: tuple[float, str, Any] = (0.7, "#d5d5d5", "solid")

ROUTE_COLOR = "#e00000"
ROUTE_LINEWIDTH = 5.2
ROUTE_HALO_LINEWIDTH = 9.0

NICE_SCALE_METERS = (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000)
MAX_BACKGROUND_LABELS = 30


class RouteRenderer:
    """Dibuja red vial, ruta, etiquetas y elementos de orientación en un PNG."""

    def __init__(
        self,
        *,
        margin_m: float = 150.0,
        dpi: int = 200,
        figsize: tuple[float, float] = (10.0, 10.0),
        labels: bool = True,
        basemap: str | None = None,
    ) -> None:
        if margin_m < 0.0:
            raise ValueError("El margen debe ser no negativo.")
        if dpi < 50:
            raise ValueError("El dpi debe ser al menos 50.")
        self.margin_m = float(margin_m)
        self.dpi = int(dpi)
        self.figsize = figsize
        self.labels = bool(labels)
        self.basemap = basemap
        self.warnings: list[str] = []
        self._lat0 = 0.0
        self._scale = 1.0
        self._label_candidates: dict[str, tuple[float, list[tuple[float, float]]]] = {}
        self._route_name_candidates: dict[str, tuple[float, list[tuple[float, float]]]] = {}
        self._transformer: Any = None
        self._crs: Any = None

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    def render(
        self,
        result: Any,
        out_path: str | Path = "route.png",
        show: bool = False,
    ) -> Path:
        """Genera el PNG y devuelve su ruta."""
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        graph = getattr(result, "graph", None)
        raw_nodes = getattr(result, "nodes", ()) or ()
        route_nodes = [node for node in raw_nodes if graph is not None and node in graph]
        if graph is None or len(route_nodes) < 2:
            raise ValueError("No hay grafo o ruta suficientes para graficar.")

        self.warnings = []
        self._label_candidates = {}
        self._route_name_candidates = {}
        self._setup_projection(graph, route_nodes)

        route_pts = self._route_polyline(graph, route_nodes)
        if len(route_pts) < 2:
            raise ValueError("La ruta no tiene coordenadas válidas para graficar.")

        extent = self._route_extent(route_pts)
        side_in = max(self.figsize[0], 2000.0 / self.dpi)
        fig = plt.figure(figsize=(side_in, side_in), facecolor="white")
        ax = fig.add_axes((0.02, 0.02, 0.96, 0.92))

        try:
            self._configure_axes(ax, extent)
            if self._draw_basemap(ax):
                self._collect_labels(graph, extent)
            else:
                self._draw_network(ax, graph, extent)

            self._draw_route(ax, route_pts)
            self._draw_direction_arrows(ax, route_pts)

            origin = self._node_xy(graph, getattr(result, "origin_node", None))
            dest = self._node_xy(graph, getattr(result, "dest_node", None))
            reserved = self._draw_endpoints(ax, origin, dest)
            self._draw_scale_bar(ax, extent)
            self._draw_north_arrow(ax)
            self._draw_title(ax, result)
            self._draw_attribution(ax)

            if self.labels:
                self._draw_labels(ax, graph, extent, reserved)

            fig.savefig(out_path, dpi=self.dpi, facecolor=fig.get_facecolor())
        finally:
            plt.close(fig)

        if show:
            self._open_file(out_path)
        return out_path

    def plot(
        self,
        result: Any,
        out_path: str | Path = "route.png",
        show: bool = False,
        dpi: int | None = None,
        figsize: tuple[float, float] | None = None,
    ) -> Path:
        """Alias compatible con la API anterior de ``RoutePlotter``."""
        if dpi is not None:
            self.dpi = int(dpi)
        if figsize is not None:
            self.figsize = figsize
        return self.render(result, out_path=out_path, show=show)

    # ------------------------------------------------------------------
    # Proyección
    # ------------------------------------------------------------------
    def _setup_projection(self, graph: nx.MultiDiGraph, route_nodes: list[Any]) -> None:
        graph_crs = graph.graph.get("crs")
        self._crs = graph_crs
        lats = []
        for node in route_nodes:
            lon, lat = self._node_lonlat(graph, node)
            if lon is not None and lat is not None:
                lats.append(lat)
        self._lat0 = sum(lats) / len(lats) if lats else 0.0
        cos_lat = max(math.cos(math.radians(self._lat0)), 1e-6)
        self._scale = 1.0 / cos_lat
        self._transformer = None
        if graph_crs is not None and not self._is_geographic_crs(graph_crs):
            try:
                from pyproj import Transformer

                self._transformer = Transformer.from_crs(graph_crs, "EPSG:4326", always_xy=True)
            except Exception as exc:  # pragma: no cover - depende de pyproj
                self.warnings.append(f"No se pudo preparar la reproyección: {exc}")

    @staticmethod
    def _is_geographic_crs(crs: Any) -> bool:
        text = str(crs).lower()
        return any(token in text for token in ("4326", "wgs84", "wgs 84", "latlon", "geographic"))

    @staticmethod
    def _project(lon: float, lat: float) -> tuple[float, float]:
        """Proyección Web Mercator (EPSG:3857), métrica y conforme."""
        lat = max(-MAX_MERCATOR_LAT, min(MAX_MERCATOR_LAT, lat))
        x = MERCATOR_RADIUS_M * math.radians(lon)
        y = MERCATOR_RADIUS_M * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
        return x, y

    def _ground_to_projected(self, meters: float) -> float:
        return meters * self._scale

    def _node_lonlat(self, graph: nx.MultiDiGraph, node: Any) -> tuple[float | None, float | None]:
        if node is None or node not in graph.nodes:
            return None, None
        data = graph.nodes[node]
        lon = data.get("lon")
        lat = data.get("lat")
        if lon is not None and lat is not None:
            return float(lon), float(lat)
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            return None, None
        if self._is_geographic_crs(self._crs):
            return float(x), float(y)
        if self._transformer is not None:
            lon_t, lat_t = self._transformer.transform(float(x), float(y))
            return float(lon_t), float(lat_t)
        return None, None

    def _node_xy(self, graph: nx.MultiDiGraph, node: Any) -> tuple[float, float] | None:
        lon, lat = self._node_lonlat(graph, node)
        if lon is None or lat is None:
            return None
        return self._project(lon, lat)

    # ------------------------------------------------------------------
    # Geometrías
    # ------------------------------------------------------------------
    def _edge_lonlat(
        self,
        graph: nx.MultiDiGraph,
        u: Any,
        v: Any,
        data: dict[str, Any],
    ) -> list[tuple[float, float]]:
        """Devuelve la geometría de la arista en WGS84, orientada de ``u`` a ``v``."""
        pts: list[tuple[float, float]] = []
        geom = data.get("geometry")
        if geom is not None and hasattr(geom, "coords"):
            try:
                raw = [(float(x), float(y)) for x, y in geom.coords]
            except Exception:
                raw = []
            if len(raw) >= 2:
                if not self._is_geographic_crs(self._crs) and self._transformer is not None:
                    xs, ys = self._transformer.transform([p[0] for p in raw], [p[1] for p in raw])
                    raw = list(zip(xs, ys, strict=False))
                pts = raw

        if len(pts) < 2:
            u_lon, u_lat = self._node_lonlat(graph, u)
            v_lon, v_lat = self._node_lonlat(graph, v)
            if None in (u_lon, u_lat, v_lon, v_lat):
                return []
            return [(float(u_lon), float(u_lat)), (float(v_lon), float(v_lat))]

        u_lon, u_lat = self._node_lonlat(graph, u)
        if u_lon is not None and u_lat is not None:
            first_gap = abs(pts[0][0] - u_lon) + abs(pts[0][1] - u_lat)
            last_gap = abs(pts[-1][0] - u_lon) + abs(pts[-1][1] - u_lat)
            if last_gap < first_gap:
                pts.reverse()
        return pts

    def _route_polyline(
        self,
        graph: nx.MultiDiGraph,
        route_nodes: list[Any],
    ) -> list[tuple[float, float]]:
        """Une las geometrías reales de las aristas de la ruta."""
        points: list[tuple[float, float]] = []
        current_name: str | None = None
        current_points: list[tuple[float, float]] = []

        def flush(name: str | None, group: list[tuple[float, float]]) -> None:
            if not name or len(group) < 2:
                return
            length = self._polyline_length(group)
            existing = self._route_name_candidates.get(name)
            if existing is None or length > existing[0]:
                self._route_name_candidates[name] = (length, list(group))

        for u, v in zip(route_nodes, route_nodes[1:], strict=False):
            edges = graph.get_edge_data(u, v) or {}
            data = self._pick_edge(edges)
            if not data:
                u_xy = self._node_xy(graph, u)
                v_xy = self._node_xy(graph, v)
                if u_xy is None or v_xy is None:
                    continue
                coords = [u_xy, v_xy]
                name = None
            else:
                lonlat = self._edge_lonlat(graph, u, v, data)
                coords = [self._project(lon, lat) for lon, lat in lonlat]
                name = self._edge_name(data)
            if not coords:
                continue
            if points and self._same_point(points[-1], coords[0]):
                points.extend(coords[1:])
            else:
                points.extend(coords)
            if name != current_name:
                flush(current_name, current_points)
                current_name = name
                current_points = list(coords)
            elif name is not None:
                if current_points and self._same_point(current_points[-1], coords[0]):
                    current_points.extend(coords[1:])
                else:
                    current_points.extend(coords)
        flush(current_name, current_points)
        return points

    @staticmethod
    def _pick_edge(edges: dict[Any, dict[str, Any]]) -> dict[str, Any] | None:
        if not edges:
            return None
        candidates = []
        for data in edges.values():
            geometry = data.get("geometry")
            if geometry is not None and hasattr(geometry, "coords"):
                candidates.append(data)
        if candidates:
            return max(candidates, key=lambda data: len(data["geometry"].coords))
        return next(iter(edges.values()), None)

    @staticmethod
    def _edge_name(data: dict[str, Any]) -> str | None:
        name = data.get("name")
        if isinstance(name, (list, tuple)):
            name = name[0] if name else None
        if name is None:
            return None
        text = str(name).strip()
        return text or None

    @staticmethod
    def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) < 0.5 and abs(a[1] - b[1]) < 0.5

    @staticmethod
    def _polyline_length(points: list[tuple[float, float]]) -> float:
        return sum(
            math.hypot(x2 - x1, y2 - y1)
            for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False)
        )

    def _route_extent(
        self, route_pts: list[tuple[float, float]]
    ) -> tuple[float, float, float, float]:
        xs = [p[0] for p in route_pts]
        ys = [p[1] for p in route_pts]
        pad_m = self.margin_m if self.margin_m > 0.0 else 20.0
        pad = self._ground_to_projected(pad_m)
        return (min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad)

    # ------------------------------------------------------------------
    # Dibujo de la red
    # ------------------------------------------------------------------
    def _configure_axes(self, ax: Any, extent: tuple[float, float, float, float]) -> None:
        xmin, xmax, ymin, ymax = extent
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")
        ax.set_facecolor("white")

    def _draw_network(
        self,
        ax: Any,
        graph: nx.MultiDiGraph,
        extent: tuple[float, float, float, float],
    ) -> None:
        xmin, xmax, ymin, ymax = extent
        groups: dict[tuple[float, str, Any], list[list[tuple[float, float]]]] = {}
        seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()

        for u, v, data in graph.edges(data=True):
            lonlat = self._edge_lonlat(graph, u, v, data)
            if len(lonlat) < 2:
                continue
            a = (round(lonlat[0][0], 5), round(lonlat[0][1], 5))
            b = (round(lonlat[-1][0], 5), round(lonlat[-1][1], 5))
            key = (a, b) if a <= b else (b, a)
            if key in seen:
                continue
            seen.add(key)

            projected = [self._project(lon, lat) for lon, lat in lonlat]
            xs = [p[0] for p in projected]
            ys = [p[1] for p in projected]
            if max(xs) < xmin or min(xs) > xmax or max(ys) < ymin or min(ys) > ymax:
                continue

            style = HIGHWAY_STYLES.get(str(data.get("highway", "")).lower(), DEFAULT_STYLE)
            groups.setdefault(style, []).append(projected)

            name = self._edge_name(data)
            if name:
                length = self._polyline_length(projected)
                current = self._label_candidates.get(name)
                if current is None or length > current[0]:
                    self._label_candidates[name] = (length, projected)

        for (linewidth, color, linestyle), segments in sorted(
            groups.items(), key=lambda item: item[0][0]
        ):
            collection = LineCollection(
                segments,
                colors=color,
                linewidths=linewidth,
                linestyles=linestyle,
                capstyle="round",
                joinstyle="round",
                zorder=1.0 + linewidth * 0.1,
            )
            ax.add_collection(collection)

    def _collect_labels(
        self,
        graph: nx.MultiDiGraph,
        extent: tuple[float, float, float, float],
    ) -> None:
        """Recolecta nombres cuando el fondo es un basemap (sin dibujar la red)."""
        xmin, xmax, ymin, ymax = extent
        for u, v, data in graph.edges(data=True):
            name = self._edge_name(data)
            if not name:
                continue
            lonlat = self._edge_lonlat(graph, u, v, data)
            if len(lonlat) < 2:
                continue
            projected = [self._project(lon, lat) for lon, lat in lonlat]
            xs = [p[0] for p in projected]
            ys = [p[1] for p in projected]
            if max(xs) < xmin or min(xs) > xmax or max(ys) < ymin or min(ys) > ymax:
                continue
            length = self._polyline_length(projected)
            current = self._label_candidates.get(name)
            if current is None or length > current[0]:
                self._label_candidates[name] = (length, projected)

    # ------------------------------------------------------------------
    # Dibujo de la ruta
    # ------------------------------------------------------------------
    def _draw_route(self, ax: Any, points: list[tuple[float, float]]) -> None:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(
            xs,
            ys,
            color="white",
            linewidth=ROUTE_HALO_LINEWIDTH,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=5,
        )
        ax.plot(
            xs,
            ys,
            color=ROUTE_COLOR,
            linewidth=ROUTE_LINEWIDTH,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=6,
        )

    def _draw_direction_arrows(self, ax: Any, points: list[tuple[float, float]]) -> None:
        cumulative = [0.0]
        for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
            cumulative.append(cumulative[-1] + math.hypot(x2 - x1, y2 - y1))
        total = cumulative[-1]
        if total <= 0.0:
            return
        spacing = max(total / 8.0, self._ground_to_projected(70.0))
        positions = [spacing * (index + 0.5) for index in range(int(total // spacing))]
        arrow_len = self._ground_to_projected(8.0)

        for distance in positions:
            margin = self._ground_to_projected(25.0)
            if distance < margin or distance > total - margin:
                continue
            segment = self._point_at(points, cumulative, distance)
            if segment is None:
                continue
            (x, y), (dx, dy) = segment
            norm = math.hypot(dx, dy)
            if norm == 0.0:
                continue
            ux, uy = dx / norm, dy / norm
            arrow = FancyArrowPatch(
                (x - ux * arrow_len, y - uy * arrow_len),
                (x + ux * arrow_len, y + uy * arrow_len),
                arrowstyle="-|>",
                mutation_scale=13,
                linewidth=1.0,
                facecolor="white",
                edgecolor="#8b0000",
                zorder=7,
            )
            ax.add_patch(arrow)

    def _point_at(
        self,
        points: list[tuple[float, float]],
        cumulative: list[float],
        distance: float,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        for index in range(len(cumulative) - 1):
            if cumulative[index] <= distance <= cumulative[index + 1]:
                (x1, y1), (x2, y2) = points[index], points[index + 1]
                span = cumulative[index + 1] - cumulative[index]
                if span <= 0.0:
                    return None
                ratio = (distance - cumulative[index]) / span
                x = x1 + (x2 - x1) * ratio
                y = y1 + (y2 - y1) * ratio
                return (x, y), (x2 - x1, y2 - y1)
        return None

    # ------------------------------------------------------------------
    # Etiquetas
    # ------------------------------------------------------------------
    def _draw_labels(
        self,
        ax: Any,
        graph: nx.MultiDiGraph,
        extent: tuple[float, float, float, float],
        reserved: list[tuple[float, float, float, float]] | None = None,
    ) -> None:
        xmin, xmax, ymin, ymax = extent
        data_width = xmax - xmin
        pt_to_m = data_width / (self.figsize[0] * 72.0 * 0.96)
        boxes: list[tuple[float, float, float, float]] = list(reserved or [])
        placed: set[str] = set()

        route_names = set(self._route_name_candidates)
        ordered: list[tuple[str, list[tuple[float, float]], bool]] = []
        for name, (_, pts) in sorted(
            self._route_name_candidates.items(), key=lambda item: item[1][0], reverse=True
        ):
            ordered.append((name, pts, True))
        background = [
            (name, pts)
            for name, (_, pts) in self._label_candidates.items()
            if name not in route_names
        ]
        background.sort(key=lambda item: self._polyline_length(item[1]), reverse=True)
        for name, pts in background[:MAX_BACKGROUND_LABELS]:
            ordered.append((name, pts, False))

        for name, pts, is_route in ordered:
            if name in placed:
                continue
            fontsize = 9.0 if is_route else 6.8
            width = max(len(name) * fontsize * 0.62 * pt_to_m, 20.0)
            height = fontsize * 1.7 * pt_to_m
            fractions = (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8) if is_route else (0.5, 0.3, 0.7)
            offsets = (0.0, 9.0, -9.0, 18.0, -18.0, 27.0, -27.0, 36.0, -36.0)
            if not is_route:
                offsets = (0.0,)
            fallback: tuple[float, float, float, float, float, float] | None = None
            placed_here = False
            for fraction in fractions:
                position = self._label_position(pts, fraction)
                if position is None:
                    continue
                base_x, base_y, angle = position
                angle_rad = math.radians(angle)
                for offset_m in offsets:
                    shift = self._ground_to_projected(offset_m)
                    x = base_x - math.sin(angle_rad) * shift
                    y = base_y + math.cos(angle_rad) * shift
                    if not (xmin <= x <= xmax and ymin <= y <= ymax):
                        continue
                    box = self._label_box(x, y, width, height, angle_rad)
                    if any(self._boxes_overlap(box, other) for other in boxes):
                        if fallback is None and abs(offset_m) <= 18.0:
                            fallback = (x, y, angle, base_x, base_y, offset_m)
                        continue
                    boxes.append(box)
                    placed.add(name)
                    self._place_label_text(
                        ax,
                        name,
                        x,
                        y,
                        angle,
                        fontsize,
                        is_route,
                        (base_x, base_y) if offset_m else None,
                    )
                    placed_here = True
                    break
                if placed_here:
                    break
            if not placed_here and is_route and fallback is not None:
                x, y, angle, base_x, base_y, offset_m = fallback
                boxes.append(self._label_box(x, y, width, height, math.radians(angle)))
                placed.add(name)
                self._place_label_text(
                    ax,
                    name,
                    x,
                    y,
                    angle,
                    fontsize,
                    True,
                    (base_x, base_y) if offset_m else None,
                )

    def _label_box(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        angle_rad: float,
    ) -> tuple[float, float, float, float]:
        half_x = (width / 2.0) * abs(math.cos(angle_rad)) + (height / 2.0) * abs(
            math.sin(angle_rad)
        )
        half_y = (width / 2.0) * abs(math.sin(angle_rad)) + (height / 2.0) * abs(
            math.cos(angle_rad)
        )
        pad = self._ground_to_projected(3.0)
        return (x - half_x - pad, y - half_y - pad, x + half_x + pad, y + half_y + pad)

    def _place_label_text(
        self,
        ax: Any,
        name: str,
        x: float,
        y: float,
        angle: float,
        fontsize: float,
        is_route: bool,
        leader_from: tuple[float, float] | None,
    ) -> None:
        if leader_from is not None:
            ax.plot(
                [leader_from[0], x],
                [leader_from[1], y],
                color="#888888",
                linewidth=0.6,
                zorder=3.5,
                solid_capstyle="round",
            )
        ax.text(
            x,
            y,
            name,
            fontsize=fontsize,
            rotation=angle,
            rotation_mode="anchor",
            ha="center",
            va="center",
            color="#5a0000" if is_route else "#555555",
            fontweight="bold" if is_route else "normal",
            zorder=9 if is_route else 4,
            path_effects=[path_effects.withStroke(linewidth=2.6, foreground="white")],
        )

    @staticmethod
    def _boxes_overlap(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> bool:
        return not (
            first[2] < second[0]
            or second[2] < first[0]
            or first[3] < second[1]
            or second[3] < first[1]
        )

    def _label_position(
        self, points: list[tuple[float, float]], fraction: float = 0.5
    ) -> tuple[float, float, float] | None:
        if len(points) < 2:
            return None
        cumulative = [0.0]
        for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
            cumulative.append(cumulative[-1] + math.hypot(x2 - x1, y2 - y1))
        total = cumulative[-1]
        if total <= 0.0:
            return None
        target = total * min(max(fraction, 0.0), 1.0)
        for index in range(len(cumulative) - 1):
            if cumulative[index] <= target <= cumulative[index + 1]:
                (x1, y1), (x2, y2) = points[index], points[index + 1]
                span = cumulative[index + 1] - cumulative[index]
                ratio = 0.0 if span <= 0.0 else (target - cumulative[index]) / span
                x = x1 + (x2 - x1) * ratio
                y = y1 + (y2 - y1) * ratio
                angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
                while angle > 90.0:
                    angle -= 180.0
                while angle < -90.0:
                    angle += 180.0
                return x, y, angle
        return None

    # ------------------------------------------------------------------
    # Origen, destino y decoraciones
    # ------------------------------------------------------------------
    def _draw_endpoints(
        self,
        ax: Any,
        origin: tuple[float, float] | None,
        dest: tuple[float, float] | None,
    ) -> list[tuple[float, float, float, float]]:
        boxes: list[tuple[float, float, float, float]] = []
        halo = [path_effects.withStroke(linewidth=3.0, foreground="white")]
        for position, label, color, marker, offset in (
            (origin, "Origen", "#1a9850", "o", (14, 14)),
            (dest, "Destino", "#d73027", "s", (14, -18)),
        ):
            if position is None:
                continue
            x, y = position
            ax.plot(
                x,
                y,
                marker=marker,
                markersize=13,
                markerfacecolor=color,
                markeredgecolor="white",
                markeredgewidth=2.0,
                zorder=11,
                linestyle="none",
            )
            ax.annotate(
                label,
                xy=(x, y),
                xytext=offset,
                textcoords="offset points",
                fontsize=11,
                fontweight="bold",
                color=color,
                zorder=12,
                path_effects=halo,
            )
            pad = self._ground_to_projected(25.0)
            boxes.append((x - pad, y - pad, x + pad, y + pad))
        return boxes

    def _draw_scale_bar(self, ax: Any, extent: tuple[float, float, float, float]) -> None:
        xmin, xmax, ymin, ymax = extent
        width = xmax - xmin
        height = ymax - ymin
        target_projected = width * 0.22
        target_ground = target_projected / self._scale
        chosen = NICE_SCALE_METERS[0]
        for value in NICE_SCALE_METERS:
            if value <= target_ground:
                chosen = value
        length = chosen * self._scale
        x0 = xmin + width * 0.04
        y0 = ymin + height * 0.05
        ax.plot(
            [x0, x0 + length],
            [y0, y0],
            color="#222222",
            linewidth=3.0,
            solid_capstyle="butt",
            zorder=10,
        )
        tick = height * 0.012
        for xpos in (x0, x0 + length):
            ax.plot([xpos, xpos], [y0 - tick, y0 + tick], color="#222222", linewidth=1.2, zorder=10)
        ax.text(
            x0 + length / 2.0,
            y0 + tick * 1.6,
            f"{chosen} m",
            fontsize=7.5,
            ha="center",
            va="bottom",
            color="#222222",
            zorder=10,
            path_effects=[path_effects.withStroke(linewidth=2.5, foreground="white")],
        )

    def _draw_north_arrow(self, ax: Any) -> None:
        ax.annotate(
            "",
            xy=(0.955, 0.955),
            xytext=(0.955, 0.885),
            xycoords="axes fraction",
            arrowprops=dict(arrowstyle="-|>", color="#222222", linewidth=1.6),
            zorder=10,
        )
        ax.text(
            0.955,
            0.965,
            "N",
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
            color="#222222",
            zorder=10,
            path_effects=[path_effects.withStroke(linewidth=2.5, foreground="white")],
        )

    def _draw_title(self, ax: Any, result: Any) -> None:
        distance_km = getattr(result, "distance_km", None)
        duration_min = getattr(result, "duration_min", None)
        profile = getattr(result, "profile", None)
        parts = []
        if distance_km is not None:
            parts.append(f"Distancia: {distance_km:.2f} km")
        if duration_min is not None:
            parts.append(f"Tiempo estimado: {duration_min:.1f} min")
        if profile:
            parts.append(f"Perfil: {profile}")
        if parts:
            ax.set_title("  |  ".join(parts), fontsize=13, fontweight="bold", pad=12)

    def _draw_attribution(self, ax: Any) -> None:
        ax.text(
            0.995,
            0.008,
            "© OpenStreetMap contributors",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=7.5,
            color="#555555",
            zorder=10,
            path_effects=[path_effects.withStroke(linewidth=2.5, foreground="white")],
        )

    # ------------------------------------------------------------------
    # Basemap opcional
    # ------------------------------------------------------------------
    def _draw_basemap(self, ax: Any) -> bool:
        if not self.basemap or str(self.basemap).lower() != "osm":
            return False
        try:
            import contextily as ctx
        except ImportError:
            self.warnings.append(
                "El basemap OSM requiere contextily (pip install contextily); "
                "se dibuja la red vial del grafo."
            )
            return False
        try:
            source = ctx.providers.OpenStreetMap.Mapnik
            ctx.add_basemap(ax, crs="EPSG:3857", source=source, attribution=False, zoom="auto")
            return True
        except Exception as exc:
            self.warnings.append(
                f"No se pudieron descargar los tiles del basemap ({exc}); "
                "se dibuja la red vial del grafo."
            )
            return False

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    @staticmethod
    def _open_file(path: Path) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass


# Nombre público anterior; se mantiene para no romper imports existentes.
RoutePlotter = RouteRenderer

__all__ = ["RouteRenderer", "RoutePlotter"]
