"""Contratos y resultado de los algoritmos de búsqueda de caminos."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import networkx as nx

from app.domain.models import NodeId
from app.routing.profile import CostProfile


@dataclass(frozen=True, slots=True)
class PathSearchResult:
    """Resultado de una búsqueda: camino, coste, distancia y métricas."""

    nodes: tuple[NodeId, ...]
    cost: float
    distance_m: float
    nodes_expanded: int
    elapsed_s: float
    algorithm: str


class PathFinder(ABC):
    """Estrategia abstracta de búsqueda de caminos."""

    def __init__(
        self,
        graph: nx.MultiDiGraph | None = None,
        profile: CostProfile | None = None,
    ) -> None:
        self._graph = graph
        self._profile = profile

    @property
    def graph(self) -> nx.MultiDiGraph:
        """Grafo vinculado a la búsqueda."""
        if self._graph is None:
            raise RuntimeError("El buscador no tiene un grafo vinculado.")
        return self._graph

    @property
    def profile(self) -> CostProfile:
        """Perfil de coste vinculado a la búsqueda."""
        if self._profile is None:
            raise RuntimeError("El buscador no tiene un perfil vinculado.")
        return self._profile

    def bind(
        self,
        graph: nx.MultiDiGraph,
        profile: CostProfile,
    ) -> PathFinder:
        """Vincula grafo y perfil, y devuelve la misma estrategia."""
        self._graph = graph
        self._profile = profile
        return self

    @abstractmethod
    def find_path(self, origin: NodeId, dest: NodeId) -> PathSearchResult:
        """Busca el camino de coste mínimo entre dos nodos."""
