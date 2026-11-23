"""Orquestador del flujo completo de planificación."""

from __future__ import annotations

import math

import networkx as nx

from app.config import Settings
from app.domain.exceptions import (
    AreaTooLargeError,
    EmptyGraphError,
    NoRouteFoundError,
    SnapDistanceError,
)
from app.domain.models import BoundingBox, Coordinate, NodeId, RouteResult
from app.providers.base import GraphProvider
from app.routing.base import PathFinder
from app.routing.geo import node_coordinate
from app.routing.profile import CostProfile
from app.services.diagnostics import explain_no_route, retry_pairs


class RoutePlanner:
    """Compone proveedor, perfil y buscador para obtener una ``RouteResult``."""

    def __init__(
        self,
        provider: GraphProvider,
        profile: CostProfile,
        pathfinder: PathFinder,
        settings: Settings,
    ) -> None:
        self._provider = provider
        self._profile = profile
        self._pathfinder = pathfinder
        self._settings = settings
        self._prepared: tuple[BoundingBox, nx.MultiDiGraph] | None = None

    @property
    def provider(self) -> GraphProvider:
        """Proveedor inyectado."""
        return self._provider

    @property
    def profile(self) -> CostProfile:
        """Perfil inyectado."""
        return self._profile

    @property
    def pathfinder(self) -> PathFinder:
        """Buscador inyectado."""
        return self._pathfinder

    @property
    def settings(self) -> Settings:
        """Configuración inyectada."""
        return self._settings

    def _bbox(self, origin: Coordinate, dest: Coordinate) -> BoundingBox:
        bbox = BoundingBox.from_points(origin, dest, margin_m=self._settings.margin_m)
        if bbox.area_km2 > self._settings.max_area_km2:
            raise AreaTooLargeError(
                f"El área de descarga ({bbox.area_km2:.2f} km²) supera el límite "
                f"configurado ({self._settings.max_area_km2:.2f} km²). "
                "Acerca los puntos o reduce el margen."
            )
        return bbox

    def prefetch(self, origin: Coordinate, dest: Coordinate) -> None:
        """Carga la red para la siguiente llamada a plan con el mismo recorte."""
        bbox = self._bbox(origin, dest)
        self._prepared = bbox, self._provider.load_graph(bbox, profile=self._profile.name)

    def plan(self, origin: Coordinate, dest: Coordinate) -> RouteResult:
        """Calcula la ruta entre dos coordenadas."""
        return self._plan(origin, dest, retry=False)

    def plan_with_alternatives(self, origin: Coordinate, dest: Coordinate) -> RouteResult:
        """Intenta la ruta pedida y reintenta con extremos conectados si falla."""
        return self._plan(origin, dest, retry=True)

    def _plan(self, origin: Coordinate, dest: Coordinate, *, retry: bool) -> RouteResult:
        bbox = self._bbox(origin, dest)
        prepared = self._prepared
        if prepared is not None and prepared[0] == bbox:
            graph = prepared[1]
        else:
            graph = self._provider.load_graph(bbox, profile=self._profile.name)

        if graph.number_of_nodes() == 0:
            raise EmptyGraphError(
                "La red descargada está vacía. No hay cobertura ciclable en el área."
            )

        origin_node, origin_snap = self._snap(graph, origin, arriving=False)
        dest_node, dest_snap = self._snap(graph, dest, arriving=True)
        self._check_max_snap(origin_snap, dest_snap)

        finder = self._pathfinder.bind(graph, self._profile)
        alternative_origin = alternative_dest = None
        try:
            search = finder.find_path(origin_node, dest_node)
        except NoRouteFoundError as exc:
            pairs = retry_pairs(graph, self._profile, origin_node, dest_node, origin, dest)
            for start, end in pairs if retry else ():
                start_point = node_coordinate(graph, start) if start != origin_node else None
                end_point = node_coordinate(graph, end) if end != dest_node else None
                start_snap = origin_snap if start_point is None else origin.distance_to(start_point)
                end_snap = dest_snap if end_point is None else dest.distance_to(end_point)
                try:
                    self._check_max_snap(start_snap, end_snap)
                    search = finder.find_path(start, end)
                except (NoRouteFoundError, SnapDistanceError):
                    continue
                if not math.isfinite(search.cost) or not math.isfinite(search.distance_m):
                    continue
                alternative_origin, alternative_dest = start_point, end_point
                origin_node, dest_node = start, end
                origin_snap, dest_snap = start_snap, end_snap
                break
            else:
                exc.diagnostic = explain_no_route(
                    graph,
                    self._profile,
                    origin_node,
                    dest_node,
                    requested_points=(origin, dest) if not retry else None,
                )
                if retry:
                    exc.diagnostic = (
                        f"{exc.diagnostic or ''}\n"
                        "No se encontró una alternativa que cumpla la configuración actual."
                    ).strip()
                raise
        if not math.isfinite(search.cost) or not math.isfinite(search.distance_m):
            raise NoRouteFoundError("La ruta calculada no tiene una distancia válida.")

        warnings = self._snap_warnings(
            origin_snap if alternative_origin is None else 0.0,
            dest_snap if alternative_dest is None else 0.0,
        )
        for label, point, distance in (
            ("Origen", alternative_origin, origin_snap),
            ("Destino", alternative_dest, dest_snap),
        ):
            if point is not None:
                warnings.append(
                    f"{label} alternativo aplicado: {point.lat},{point.lon} "
                    f"({distance:.0f} m en línea recta del punto pedido). "
                    "El tramo hasta el punto pedido queda fuera de la ruta."
                )
        speed_m_s = self._settings.bike_speed_kmh * 1000.0 / 3600.0
        duration_s = search.distance_m / speed_m_s
        geometry = tuple(node_coordinate(graph, node) for node in search.nodes)
        return RouteResult(
            nodes=search.nodes,
            distance_m=search.distance_m,
            duration_s=duration_s,
            nodes_expanded=search.nodes_expanded,
            backend=self._provider.name,
            profile=self._profile.name,
            algorithm=search.algorithm,
            snap_origin_m=origin_snap,
            snap_dest_m=dest_snap,
            geometry=geometry,
            warnings=tuple(warnings),
            bbox=bbox,
            weighted_cost=search.cost,
            compute_time_s=search.elapsed_s,
            graph=graph,
            origin_node=origin_node,
            dest_node=dest_node,
            alternative_origin=alternative_origin,
            alternative_dest=alternative_dest,
        )

    def _snap(
        self,
        graph: nx.MultiDiGraph,
        coordinate: Coordinate,
        *,
        arriving: bool,
    ) -> tuple[NodeId, float]:
        """Ajusta la coordenada al nodo más cercano que el perfil puede usar.

        Se descartan los nodos sin ninguna arista transitable, de modo que un
        punto dentro de un recinto (pasillos, escaleras, aparcamientos) no
        bloquee la búsqueda con un nodo aislado para el perfil activo.
        """
        usable = self._usable_nodes(graph, arriving=arriving)
        if not usable:
            return self._provider.nearest_node(graph, coordinate)
        return self._provider.nearest_node(graph.subgraph(usable), coordinate)

    def _usable_nodes(self, graph: nx.MultiDiGraph, *, arriving: bool) -> set[NodeId]:
        """Nodos con al menos una arista transitable de entrada o de salida."""
        usable: set[NodeId] = set()
        for source, target, data in graph.edges(data=True):
            if not math.isfinite(self._profile.edge_cost(data)):
                continue
            usable.add(target if arriving else source)
        return usable

    def _snap_warnings(self, origin_snap: float, dest_snap: float) -> list[str]:
        warnings: list[str] = []
        if origin_snap > self._settings.snap_warning_m:
            warnings.append(f"El origen se ha ajustado {origin_snap:.0f} m al nodo más cercano.")
        if dest_snap > self._settings.snap_warning_m:
            warnings.append(f"El destino se ha ajustado {dest_snap:.0f} m al nodo más cercano.")
        return warnings

    def _check_max_snap(self, origin_snap: float, dest_snap: float) -> None:
        maximum = self._settings.max_snap_m
        if maximum is None:
            return
        if origin_snap > maximum:
            raise SnapDistanceError(
                f"El origen está a {origin_snap:.0f} m de la red, por encima del "
                f"máximo permitido ({maximum:.0f} m)."
            )
        if dest_snap > maximum:
            raise SnapDistanceError(
                f"El destino está a {dest_snap:.0f} m de la red, por encima del "
                f"máximo permitido ({maximum:.0f} m)."
            )
