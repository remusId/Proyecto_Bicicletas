"""Proveedor de grafos basado en OSMnx."""

from __future__ import annotations

import time
from typing import Any

import networkx as nx
import osmnx as ox
from pyproj import Transformer

from app.domain.exceptions import ProviderUnavailableError, SnapDistanceError
from app.domain.models import BoundingBox, Coordinate, NodeId
from app.providers.base import GraphProvider
from app.routing.geo import node_coordinate
from app.services.cache import GraphCache


class OsmnxProvider(GraphProvider):
    """Descarga la red ciclable con ``osmnx.graph_from_bbox``."""

    def __init__(
        self,
        cache: GraphCache | None = None,
        *,
        network_type: str = "bike",
        use_cache: bool = True,
        user_agent: str,
        requests_timeout_s: float = 60.0,
        retries: int = 3,
        backoff_base_s: float = 1.0,
    ) -> None:
        super().__init__(cache)
        if not user_agent.strip():
            raise ValueError("El User-Agent no puede estar vacío.")
        if network_type != "bike":
            raise ValueError("Este proyecto usa network_type='bike'.")
        if not 1 <= retries <= 3:
            raise ValueError("OSMnx admite entre 1 y 3 intentos.")
        if requests_timeout_s <= 0.0:
            raise ValueError("El timeout debe ser mayor que cero.")
        if backoff_base_s < 0.0:
            raise ValueError("El backoff no puede ser negativo.")
        self._network_type = network_type
        self._use_cache = bool(use_cache)
        self._user_agent = user_agent
        self._requests_timeout_s = requests_timeout_s
        self._retries = retries
        self._backoff_base_s = backoff_base_s

    @property
    def name(self) -> str:
        """Identificador del backend."""
        return "osmnx"

    def load_graph(
        self,
        bbox: BoundingBox,
        profile: str = "bike",
    ) -> nx.MultiDiGraph:
        """Descarga y proyecta la red ciclable de la caja indicada."""
        key = None
        if self._cache is not None:
            key = self._cache.key(bbox, self.name, profile, extra=self._network_type)
            cached = self._cache.load(key)
            if cached is not None:
                return cached

        cache_enabled = self._use_cache and (self._cache is None or self._cache.enabled)
        ox.settings.use_cache = cache_enabled
        ox.settings.http_user_agent = self._user_agent
        ox.settings.requests_timeout = self._requests_timeout_s
        if self._cache is not None and cache_enabled:
            ox.settings.cache_folder = str(self._cache.directory / "osmnx")

        try:
            graph = self._download_graph(bbox)
            if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
                raise ProviderUnavailableError(
                    "OSMnx no encontró una red ciclable en el área seleccionada. "
                    "Prueba a ampliar el margen o mover los puntos."
                )
            graph = self._project_and_keep_latlon(graph)
        except ProviderUnavailableError:
            raise
        except Exception as exc:  # OSMnx puede lanzar errores de red o de datos.
            raise ProviderUnavailableError(
                "No se pudo descargar la red ciclable con OSMnx. "
                "Comprueba tu conexión o inténtalo de nuevo más tarde."
            ) from exc

        if self._cache is not None and key is not None:
            self._cache.save(key, graph)
        return graph

    def nearest_node(
        self,
        graph: nx.MultiDiGraph,
        coordinate: Coordinate,
    ) -> tuple[NodeId, float]:
        """Usa ``osmnx.nearest_nodes`` sobre el grafo proyectado."""
        if graph.number_of_nodes() == 0:
            raise SnapDistanceError("El grafo no contiene nodos para hacer el snap.")
        try:
            crs = graph.graph.get("crs")
            if crs is None:
                raise ValueError("El grafo no tiene CRS.")
            transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            x, y = transformer.transform(coordinate.lon, coordinate.lat)
            node, _ = ox.nearest_nodes(graph, X=x, Y=y, return_dist=True)
            try:
                node_id = int(node)
            except (TypeError, ValueError):
                node_id = node
            snap_distance = coordinate.distance_to(node_coordinate(graph, node_id))
        except SnapDistanceError:
            raise
        except Exception as exc:
            raise SnapDistanceError(
                "No se pudo ajustar el punto a la red ciclable con OSMnx."
            ) from exc
        return node_id, snap_distance

    def _download_graph(self, bbox: BoundingBox) -> nx.MultiDiGraph:
        last_error: Exception | None = None
        attempts_made = 0
        for attempt in range(1, self._retries + 1):
            attempts_made = attempt
            try:
                return ox.graph_from_bbox(
                    bbox.to_osmnx_tuple(),
                    network_type=self._network_type,
                    simplify=True,
                    retain_all=False,
                )
            except Exception as exc:
                last_error = exc
                if attempt >= self._retries or not self._is_retryable(exc):
                    break
                time.sleep(self._backoff_base_s * (2 ** (attempt - 1)))
        if last_error is not None:
            raise ProviderUnavailableError(
                f"OSMnx/Overpass no está disponible tras {attempts_made} intento(s). "
                "Espera un poco y vuelve a intentarlo."
            ) from last_error
        raise ProviderUnavailableError("OSMnx no devolvió ningún grafo.")

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
            "429",
            "500",
            "502",
            "503",
            "504",
            "timeout",
            "timed out",
            "capacity",
            "gateway",
            "too many requests",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _project_and_keep_latlon(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        """Proyecta a UTM y conserva lat/lon para la heurística y el mapa."""
        latlon: dict[Any, tuple[float, float]] = {}
        for node, data in graph.nodes(data=True):
            latlon[node] = (float(data["y"]), float(data["x"]))
        projected = ox.project_graph(graph)
        for node, (lat, lon) in latlon.items():
            projected.nodes[node]["lat"] = lat
            projected.nodes[node]["lon"] = lon
        return projected
