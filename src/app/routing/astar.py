"""A* propio con heapq y heurística haversine."""

from __future__ import annotations

import heapq
import itertools
import math
import time
from collections.abc import Iterator
from typing import Any

from app.domain.exceptions import NoRouteFoundError
from app.domain.models import Coordinate, NodeId
from app.routing.base import PathFinder, PathSearchResult
from app.routing.geo import edge_length_m, heuristic_m, node_coordinate


class AStarPathFinder(PathFinder):
    """A* sobre ``MultiDiGraph`` con coste definido por un ``CostProfile``."""

    @property
    def algorithm(self) -> str:
        """Nombre del algoritmo."""
        return "A*"

    def find_path(self, origin: NodeId, dest: NodeId) -> PathSearchResult:
        """Calcula el camino de coste mínimo entre origen y destino."""
        graph = self.graph
        profile = self.profile
        if origin not in graph:
            raise NoRouteFoundError("El nodo de origen no existe en la red descargada.")
        if dest not in graph:
            raise NoRouteFoundError("El nodo de destino no existe en la red descargada.")

        started = time.perf_counter()
        if origin == dest:
            return PathSearchResult(
                nodes=(origin,),
                cost=0.0,
                distance_m=0.0,
                nodes_expanded=1,
                elapsed_s=time.perf_counter() - started,
                algorithm=self.algorithm,
            )

        destination = node_coordinate(graph, dest)
        scale = profile.heuristic_scale()
        if not math.isfinite(scale) or scale < 0.0:
            raise ValueError("La escala de la heurística debe ser finita y no negativa.")

        counter = itertools.count()
        g_score: dict[NodeId, float] = {origin: 0.0}
        came_from: dict[NodeId, tuple[NodeId, dict[str, Any]]] = {}
        closed: set[NodeId] = set()
        open_heap: list[tuple[float, int, NodeId]] = [
            (self._heuristic(origin, destination, scale), next(counter), origin)
        ]
        expanded = 0

        while open_heap:
            _, _, current = heapq.heappop(open_heap)
            if current in closed:
                continue
            closed.add(current)
            expanded += 1
            if current == dest:
                break

            for neighbor, edge_data in self._out_edges(current):
                edge_cost = profile.edge_cost(edge_data)
                if not math.isfinite(edge_cost) or edge_cost < 0.0:
                    continue
                tentative = g_score[current] + edge_cost
                if tentative < g_score.get(neighbor, math.inf):
                    g_score[neighbor] = tentative
                    came_from[neighbor] = (current, edge_data)
                    priority = tentative + self._heuristic(neighbor, destination, scale)
                    heapq.heappush(open_heap, (priority, next(counter), neighbor))

        if dest not in g_score:
            raise NoRouteFoundError(
                "No hay una ruta ciclable entre el origen y el destino con el perfil elegido."
            )

        nodes, distance_m = self._reconstruct(origin, dest, came_from)
        return PathSearchResult(
            nodes=nodes,
            cost=g_score[dest],
            distance_m=distance_m,
            nodes_expanded=expanded,
            elapsed_s=time.perf_counter() - started,
            algorithm=self.algorithm,
        )

    def _heuristic(self, node: NodeId, destination: Coordinate, scale: float) -> float:
        return heuristic_m(self.graph, node, destination, scale)

    def _out_edges(self, node: NodeId) -> Iterator[tuple[NodeId, dict[str, Any]]]:
        graph = self.graph
        if graph.is_multigraph():
            for _, neighbor, _, data in graph.out_edges(node, data=True, keys=True):
                yield neighbor, data
        else:
            for _, neighbor, data in graph.out_edges(node, data=True):
                yield neighbor, data

    def _reconstruct(
        self,
        origin: NodeId,
        dest: NodeId,
        came_from: dict[NodeId, tuple[NodeId, dict[str, Any]]],
    ) -> tuple[tuple[NodeId, ...], float]:
        path: list[NodeId] = [dest]
        distance_m = 0.0
        current = dest
        while current != origin:
            previous, edge_data = came_from[current]
            distance_m += edge_length_m(
                edge_data,
                node_coordinate(self.graph, previous),
                node_coordinate(self.graph, current),
            )
            path.append(previous)
            current = previous
        path.reverse()
        return tuple(path), distance_m
