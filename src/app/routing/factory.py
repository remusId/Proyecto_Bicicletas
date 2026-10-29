"""Fábrica de estrategias de búsqueda."""

from __future__ import annotations

from app.routing.astar import AStarPathFinder
from app.routing.base import PathFinder
from app.routing.dijkstra import DijkstraPathFinder


class PathFinderFactory:
    """Crea el algoritmo solicitado sin exponer clases concretas a la UI."""

    @classmethod
    def create(cls, name: str) -> PathFinder:
        """Devuelve el buscador configurado."""
        normalized = name.strip().lower()
        if normalized in {"astar", "a*"}:
            return AStarPathFinder()
        if normalized == "dijkstra":
            return DijkstraPathFinder()
        raise ValueError("Algoritmo no soportado. Usa 'astar' o 'dijkstra'.")
