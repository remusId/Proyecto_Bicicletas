"""Proveedor directo de Overpass API, sin OSMnx para la descarga."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import networkx as nx
import requests
from scipy.spatial import cKDTree
from shapely.geometry import LineString

from app.domain.exceptions import ProviderUnavailableError, SnapDistanceError
from app.domain.models import (
    EARTH_RADIUS_M,
    BoundingBox,
    Coordinate,
    NodeId,
    haversine_m,
)
from app.providers.base import GraphProvider
from app.services.cache import GraphCache

_RELEVANT_HIGHWAYS = (
    "motorway|motorway_link|trunk|trunk_link|primary|primary_link|"
    "secondary|secondary_link|tertiary|tertiary_link|unclassified|"
    "residential|living_street|service|track|path|footway|pedestrian|"
    "steps|cycleway|bridleway|road|construction|proposed|raceway|"
    "bus_guideway|corridor|elevator|escalator|platform"
)
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _tag_text(value: Any) -> str:
    """Normaliza una etiqueta OSM."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value).strip().lower()


def _node_coordinate(data: Mapping[str, Any]) -> Coordinate:
    """Extrae una coordenada de los atributos de un nodo."""
    if "lat" in data and "lon" in data:
        return Coordinate(lat=float(data["lat"]), lon=float(data["lon"]))
    return Coordinate(lat=float(data["y"]), lon=float(data["x"]))


def _way_directions(tags: Mapping[str, Any]) -> tuple[bool, bool]:
    """Devuelve ``(forward, backward)`` respetando oneway y oneway:bicycle."""
    oneway = _tag_text(tags.get("oneway"))
    bicycle_oneway = _tag_text(tags.get("oneway:bicycle"))
    if bicycle_oneway in {"no", "false", "0"}:
        return True, True
    if oneway == "-1":
        return False, True
    if oneway in {"yes", "true", "1"}:
        return True, False
    return True, True


def parse_overpass_payload(payload: Mapping[str, Any]) -> nx.MultiDiGraph:
    """Convierte una respuesta Overpass JSON en un ``MultiDiGraph`` tipo OSMnx."""
    elements = payload.get("elements", [])
    if not isinstance(elements, list):
        raise ValueError("La respuesta de Overpass no contiene una lista de elementos.")

    nodes: dict[int, dict[str, Any]] = {}
    for element in elements:
        if element.get("type") != "node":
            continue
        try:
            node_id = int(element["id"])
            lat = float(element["lat"])
            lon = float(element["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        nodes[node_id] = {
            "x": lon,
            "y": lat,
            "lat": lat,
            "lon": lon,
            "street_count": 0,
        }

    graph = nx.MultiDiGraph()
    for node_id, data in nodes.items():
        graph.add_node(node_id, **data)

    incident_ways: dict[int, set[int]] = {node_id: set() for node_id in nodes}
    for element in elements:
        if element.get("type") != "way":
            continue
        way_id = int(element.get("id", 0))
        way_nodes = [int(node) for node in element.get("nodes", [])]
        if len(way_nodes) < 2:
            continue
        tags: Mapping[str, Any] = element.get("tags") or {}
        highway = _tag_text(tags.get("highway"))
        if not highway:
            continue
        forward, backward = _way_directions(tags)
        for node in way_nodes:
            if node in incident_ways:
                incident_ways[node].add(way_id)

        for index, (source, target) in enumerate(zip(way_nodes, way_nodes[1:], strict=False)):
            if source not in nodes or target not in nodes:
                continue
            start = _node_coordinate(nodes[source])
            end = _node_coordinate(nodes[target])
            length = haversine_m(start.lat, start.lon, end.lat, end.lon)
            geometry = LineString([(start.lon, start.lat), (end.lon, end.lat)])
            data: dict[str, Any] = {
                "osmid": way_id,
                "name": tags.get("name"),
                "highway": highway,
                "oneway": not (forward and backward),
                "reversed": False,
                "length": length,
                "geometry": geometry,
                "maxspeed": tags.get("maxspeed"),
                "lanes": tags.get("lanes"),
                "ref": tags.get("ref"),
                "bridge": tags.get("bridge"),
                "tunnel": tags.get("tunnel"),
                "access": tags.get("access"),
                "service": tags.get("service"),
                "width": tags.get("width"),
                "est_width": tags.get("est_width"),
                "junction": tags.get("junction"),
                "area": tags.get("area"),
                "bicycle": tags.get("bicycle"),
                "oneway:bicycle": tags.get("oneway:bicycle"),
                "cycleway": tags.get("cycleway"),
                "surface": tags.get("surface"),
            }
            if forward:
                graph.add_edge(source, target, key=f"{way_id}:{index}:f", **data)
            if backward:
                reverse_data = dict(data)
                reverse_data["reversed"] = True
                graph.add_edge(target, source, key=f"{way_id}:{index}:r", **reverse_data)

    for node_id, ways in incident_ways.items():
        if node_id in graph:
            graph.nodes[node_id]["street_count"] = len(ways)

    graph.graph.update(
        {
            "crs": "epsg:4326",
            "created_date": datetime.now(UTC).isoformat(),
            "created_with": "OverpassProvider",
            "simplified": False,
            "bbox": _payload_bbox(nodes),
        }
    )
    return graph


def _payload_bbox(nodes: Mapping[int, Mapping[str, Any]]) -> list[float]:
    """Calcula ``[oeste, sur, este, norte]`` a partir de los nodos."""
    if not nodes:
        return [0.0, 0.0, 0.0, 0.0]
    lons = [float(data["lon"]) for data in nodes.values()]
    lats = [float(data["lat"]) for data in nodes.values()]
    return [min(lons), min(lats), max(lons), max(lats)]


class OverpassProvider(GraphProvider):
    """Descarga ways de Overpass y construye un grafo compatible con OSMnx."""

    def __init__(
        self,
        cache: GraphCache | None = None,
        *,
        overpass_url: str = "https://overpass-api.de/api/interpreter",
        timeout_s: float = 60.0,
        retries: int = 3,
        user_agent: str,
        backoff_base_s: float = 1.0,
    ) -> None:
        super().__init__(cache)
        if not overpass_url.strip():
            raise ValueError("La URL de Overpass no puede estar vacía.")
        if timeout_s <= 0.0:
            raise ValueError("El timeout debe ser mayor que cero.")
        if not 1 <= retries <= 3:
            raise ValueError("Overpass admite entre 1 y 3 intentos.")
        if not user_agent.strip():
            raise ValueError("El User-Agent no puede estar vacío.")
        if backoff_base_s < 0.0:
            raise ValueError("El backoff no puede ser negativo.")
        self._url = overpass_url
        self._timeout_s = timeout_s
        self._retries = retries
        self._backoff_base_s = backoff_base_s
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    @property
    def name(self) -> str:
        """Identificador del backend."""
        return "overpass"

    @property
    def user_agent(self) -> str:
        """User-Agent configurado para las peticiones."""
        return str(self._session.headers.get("User-Agent", ""))

    def load_graph(
        self,
        bbox: BoundingBox,
        profile: str = "bike",
    ) -> nx.MultiDiGraph:
        """Descarga el área y devuelve un grafo con atributos tipo OSMnx."""
        key = None
        if self._cache is not None:
            key = self._cache.key(bbox, self.name, profile)
            cached = self._cache.load(key)
            if cached is not None:
                return cached

        try:
            payload = self._request(self._build_query(bbox))
            graph = parse_overpass_payload(payload)
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                "Overpass devolvió datos que no se pudieron interpretar."
            ) from exc

        if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
            raise ProviderUnavailableError(
                "Overpass no encontró una red ciclable en el área seleccionada. "
                "Prueba a ampliar el margen o mover los puntos."
            )
        graph.graph["download_bbox"] = bbox.to_osmnx_tuple()
        if self._cache is not None and key is not None:
            self._cache.save(key, graph)
        return graph

    def nearest_node(
        self,
        graph: nx.MultiDiGraph,
        coordinate: Coordinate,
    ) -> tuple[NodeId, float]:
        """Snap con KD-tree en una proyección local en metros."""
        if graph.number_of_nodes() == 0:
            raise SnapDistanceError("El grafo no contiene nodos para hacer el snap.")
        nodes: list[tuple[NodeId, Coordinate]] = []
        lat0 = math.radians(coordinate.lat)
        cos_lat0 = math.cos(lat0)
        points: list[tuple[float, float]] = []
        for node, data in graph.nodes(data=True):
            try:
                node_coord = _node_coordinate(data)
            except (KeyError, TypeError, ValueError):
                continue
            x = math.radians(node_coord.lon - coordinate.lon) * cos_lat0 * EARTH_RADIUS_M
            y = math.radians(node_coord.lat - coordinate.lat) * EARTH_RADIUS_M
            nodes.append((node, node_coord))
            points.append((x, y))
        if not points:
            raise SnapDistanceError("El grafo no tiene nodos con coordenadas válidas.")

        tree = cKDTree(points)
        _, index = tree.query((0.0, 0.0), k=1)
        node_id, node_coord = nodes[int(index)]
        return node_id, coordinate.distance_to(node_coord)

    def _build_query(self, bbox: BoundingBox) -> str:
        south, west, north, east = (
            bbox.south,
            bbox.west,
            bbox.north,
            bbox.east,
        )
        return (
            f"[out:json][timeout:{max(1, int(self._timeout_s))}];\n"
            f'way["highway"~"^({_RELEVANT_HIGHWAYS})$"]({south},{west},{north},{east});\n'
            "out body;\n"
            ">;\n"
            "out skel qt;"
        )

    def _request(self, query: str) -> dict[str, Any]:
        last_error = "sin respuesta"
        for attempt in range(1, self._retries + 1):
            try:
                response = self._session.post(
                    self._url,
                    data={"data": query},
                    timeout=self._timeout_s,
                )
            except requests.Timeout:
                last_error = "timeout"
                if attempt < self._retries:
                    time.sleep(self._backoff_base_s * (2 ** (attempt - 1)))
                continue
            except requests.RequestException:
                last_error = "error de conexión"
                if attempt < self._retries:
                    time.sleep(self._backoff_base_s * (2 ** (attempt - 1)))
                continue

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise ProviderUnavailableError(
                        "Overpass devolvió una respuesta que no es JSON válido."
                    ) from exc
                if not isinstance(payload, dict):
                    raise ProviderUnavailableError(
                        "Overpass devolvió una respuesta con formato inesperado."
                    )
                return payload

            last_error = f"HTTP {response.status_code}"
            if response.status_code not in _RETRYABLE_STATUS:
                raise ProviderUnavailableError(
                    f"Overpass respondió con {last_error}. Revisa los parámetros de la consulta."
                )
            if attempt < self._retries:
                retry_after = response.headers.get("Retry-After")
                delay = self._retry_delay(attempt, retry_after)
                time.sleep(delay)

        raise ProviderUnavailableError(
            f"Overpass no está disponible tras {self._retries} intentos ({last_error}). "
            "Espera un poco y vuelve a intentarlo."
        )

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return self._backoff_base_s * (2 ** (attempt - 1))


__all__ = ["OverpassProvider", "parse_overpass_payload"]
