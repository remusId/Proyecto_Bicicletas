"""Orquestador del flujo completo de planificación."""

from __future__ import annotations

import math

import networkx as nx

from app.config import Settings
from app.domain.exceptions import (
    AreaTooLargeError,
    NoRouteFoundError,
    ProviderUnavailableError,
    SnapDistanceError,
)
from app.domain.models import BoundingBox, Coordinate, NodeId, RouteResult
from app.providers.base import GraphProvider
from app.routing.base import PathFinder
from app.routing.geo import node_coordinate
from app.routing.profile import CostProfile


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

    def plan(self, origin: Coordinate, dest: Coordinate) -> RouteResult:
        """Calcula la ruta entre dos coordenadas."""
        bbox = BoundingBox.from_points(origin, dest, margin_m=self._settings.margin_m)
        if bbox.area_km2 > self._settings.max_area_km2:
            raise AreaTooLargeError(
                f"El área de descarga ({bbox.area_km2:.2f} km²) supera el límite "
                f"configurado ({self._settings.max_area_km2:.2f} km²). "
                "Acerca los puntos o reduce el margen."
            )

        graph = self._provider.load_graph(bbox, profile=self._profile.name)
        if graph.number_of_nodes() == 0:
            raise ProviderUnavailableError(
                "La red descargada está vacía. No hay cobertura ciclable en el área."
            )

        origin_node, origin_snap = self._snap(graph, origin, arriving=False)
        dest_node, dest_snap = self._snap(graph, dest, arriving=True)
        warnings = self._snap_warnings(origin_snap, dest_snap)
        self._check_max_snap(origin_snap, dest_snap)

        search = self._pathfinder.bind(graph, self._profile).find_path(origin_node, dest_node)
        if not math.isfinite(search.cost) or not math.isfinite(search.distance_m):
            raise NoRouteFoundError("La ruta calculada no tiene una distancia válida.")

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
