"""Explica fallos a partir de la red transitable y los nodos ajustados."""

import math
from collections.abc import Iterator

import networkx as nx
from scipy.spatial import cKDTree

from app.domain.models import Coordinate, NodeId
from app.routing.geo import node_coordinate
from app.routing.profile import CostProfile


def _transitable_graph(graph: nx.MultiDiGraph, profile: CostProfile) -> nx.DiGraph:
    return nx.DiGraph(
        (source, target)
        for source, target, edge in graph.edges(data=True)
        if math.isfinite(profile.edge_cost(edge))
    )


def retry_pairs(
    graph: nx.MultiDiGraph,
    profile: CostProfile,
    origin: NodeId,
    dest: NodeId,
    requested_origin: Coordinate,
    requested_dest: Coordinate,
) -> Iterator[tuple[NodeId, NodeId]]:
    """Propone primero un cambio de extremo y después dos extremos conectados."""
    usable = _transitable_graph(graph, profile)
    points = {}
    for node in usable:
        try:
            points[node] = node_coordinate(graph, node)
        except (TypeError, ValueError):
            continue

    def nearest(nodes: set[NodeId], point: Coordinate) -> NodeId | None:
        return min(
            points.keys() & nodes, key=lambda node: point.distance_to(points[node]), default=None
        )

    def displacement(pair: tuple[NodeId, NodeId]) -> float:
        start, end = pair
        return requested_origin.distance_to(points[start]) + requested_dest.distance_to(points[end])

    single_changes = []
    if dest in points:
        start = nearest(nx.ancestors(usable, dest) - {origin}, requested_origin)
        if start is not None:
            single_changes.append((start, dest))
    if origin in points:
        end = nearest(nx.descendants(usable, origin) - {dest}, requested_dest)
        if end is not None:
            single_changes.append((origin, end))
    yield from sorted(single_changes, key=displacement)

    double_changes = []
    for component in nx.weakly_connected_components(usable):
        start = nearest(
            {
                node
                for node in component
                if node != origin and any(end not in {node, dest} for end in usable[node])
            },
            requested_origin,
        )
        if start is not None:
            end = nearest(nx.descendants(usable, start) - {dest}, requested_dest)
            if end is not None:
                double_changes.append((start, end))
    yield from sorted(double_changes, key=displacement)


def explain_no_route(
    graph: nx.MultiDiGraph,
    profile: CostProfile,
    origin: NodeId,
    dest: NodeId,
    *,
    requested_points: tuple[Coordinate, Coordinate] | None = None,
) -> str | None:
    """Inspecciona la conectividad sin modificar el grafo ni la ruta."""
    if not graph:
        return "El grafo está vacío. Amplía el margen o elige otra zona."
    usable = _transitable_graph(graph, profile)
    if origin not in usable or dest not in usable:
        return (
            "Un punto se ajustó a un nodo sin aristas transitables para el perfil. "
            "Mueve ese punto a una calle que admita bicicletas."
        )
    components = usable.to_undirected(as_view=True)
    start_nodes = nx.node_connected_component(components, origin)
    if dest not in start_nodes:
        end_nodes = nx.node_connected_component(components, dest)
        origin_points = _coordinates(graph, start_nodes)
        dest_points = _coordinates(graph, end_nodes)
        detail = (
            f"Los puntos están en componentes ciclables distintas ({len(start_nodes):,} y "
            f"{len(end_nodes):,} nodos, 0 aristas transitables entre ambas). "
        )
        if origin_points and dest_points:
            distances, indices = cKDTree([_sphere(point) for point in dest_points]).query(
                [_sphere(point) for point in origin_points]
            )
            nearest = int(distances.argmin())
            first, second = origin_points[nearest], dest_points[int(indices[nearest])]
            detail += (
                f"Distancia mínima ≈ {first.distance_to(second):.0f} m. "
                f"Puntos más cercanos: {first.lat:.6f},{first.lon:.6f} y "
                f"{second.lat:.6f},{second.lon:.6f}. "
            )
        detail += (
            "La separación es en línea recta y no confirma que se pueda cruzar. "
            "Puedes ampliar el margen para buscar conexiones fuera del recorte."
        )
    elif not nx.has_path(usable, origin, dest):
        detail = (
            "Los puntos están en la misma componente, pero no hay camino en el sentido solicitado."
        )
    else:
        return None

    if requested_points is None:
        return detail

    requested_origin, requested_dest = requested_points
    alternatives = (
        ("Origen alternativo", requested_origin, nx.ancestors(usable, dest)),
        ("Destino alternativo", requested_dest, nx.descendants(usable, origin)),
    )
    for label, requested, nodes in alternatives:
        point = min(_coordinates(graph, nodes), key=requested.distance_to, default=None)
        if point is not None:
            detail += (
                f"\n{label}: {point.lat},{point.lon} "
                f"(a {requested.distance_to(point):.0f} m en línea recta del punto pedido)."
            )
    if "\n" in detail:
        detail += (
            "\nPrueba cambiando solo uno de los puntos. Comprueba por separado cómo llegar "
            "al punto alternativo."
        )
    return detail


def _coordinates(graph: nx.MultiDiGraph, nodes: set[NodeId]) -> list[Coordinate]:
    points = []
    for node in nodes:
        try:
            points.append(node_coordinate(graph, node))
        except (TypeError, ValueError):
            continue
    return points


def _sphere(point: Coordinate) -> tuple[float, float, float]:
    lat, lon = math.radians(point.lat), math.radians(point.lon)
    return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)
