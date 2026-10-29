"""Utilidades geográficas compartidas por los algoritmos de routing."""

from __future__ import annotations

import math
from typing import Any

import networkx as nx

from app.domain.models import Coordinate, NodeId, haversine_m


def node_coordinate(graph: nx.MultiDiGraph, node: NodeId) -> Coordinate:
    """Obtiene la coordenada WGS84 de un nodo del grafo."""
    data: dict[str, Any] = graph.nodes[node]
    if "lat" in data and "lon" in data:
        return Coordinate(lat=float(data["lat"]), lon=float(data["lon"]))
    if "y" in data and "x" in data:
        return Coordinate(lat=float(data["y"]), lon=float(data["x"]))
    raise ValueError(f"El nodo {node!r} no tiene coordenadas.")


def edge_length_m(edge_data: dict[str, Any], source: Coordinate, target: Coordinate) -> float:
    """Longitud física de una arista, en metros."""
    raw = edge_data.get("length")
    if raw is not None:
        try:
            length = float(raw)
        except (TypeError, ValueError):
            length = math.nan
        if math.isfinite(length) and length >= 0.0:
            return length
    return haversine_m(source.lat, source.lon, target.lat, target.lon)


def heuristic_m(
    graph: nx.MultiDiGraph,
    node: NodeId,
    destination: Coordinate,
    scale: float,
) -> float:
    """Heurística haversine escalada al coste del perfil."""
    return node_coordinate(graph, node).distance_to(destination) * scale


__all__ = ["edge_length_m", "haversine_m", "heuristic_m", "node_coordinate"]
