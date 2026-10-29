"""Dijkstra de validación: reutiliza el motor de A* con heurística nula."""

from __future__ import annotations

from app.domain.models import Coordinate, NodeId
from app.routing.astar import AStarPathFinder


class DijkstraPathFinder(AStarPathFinder):
    """Dijkstra implementado con la misma cola de prioridad que A*."""

    @property
    def algorithm(self) -> str:
        """Nombre del algoritmo."""
        return "Dijkstra"

    def _heuristic(self, node: NodeId, destination: Coordinate, scale: float) -> float:
        return 0.0
