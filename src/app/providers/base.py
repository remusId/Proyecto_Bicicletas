"""Contrato abstracto de los proveedores de grafos."""

from __future__ import annotations

from abc import ABC, abstractmethod

import networkx as nx

from app.domain.models import BoundingBox, Coordinate, NodeId
from app.services.cache import GraphCache


class GraphProvider(ABC):
    """Fuente intercambiable de grafos ciclables."""

    def __init__(self, cache: GraphCache | None = None) -> None:
        self._cache = cache

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador corto del backend."""

    @property
    def cache(self) -> GraphCache | None:
        """Caché asociada al proveedor, si existe."""
        return self._cache

    @abstractmethod
    def load_graph(
        self,
        bbox: BoundingBox,
        profile: str = "bike",
    ) -> nx.MultiDiGraph:
        """Descarga o recupera un grafo para la caja y el perfil indicados."""

    @abstractmethod
    def nearest_node(
        self,
        graph: nx.MultiDiGraph,
        coordinate: Coordinate,
    ) -> tuple[NodeId, float]:
        """Ajusta una coordenada al nodo más cercano y devuelve su distancia en metros."""
