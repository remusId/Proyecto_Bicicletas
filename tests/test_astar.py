"""Pruebas de A*, Dijkstra y admisibilidad."""

from __future__ import annotations

import random

import networkx as nx
import pytest

from app.domain.exceptions import NoRouteFoundError
from app.routing.astar import AStarPathFinder
from app.routing.base import PathFinder
from app.routing.dijkstra import DijkstraPathFinder
from app.routing.geo import heuristic_m, node_coordinate
from app.routing.profile import BikeFriendlyProfile, CostProfile, ShortestProfile


def test_abstract_classes_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        CostProfile()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        PathFinder()  # type: ignore[abstract]


def test_astar_matches_networkx_dijkstra_on_twenty_pairs(synthetic_graph) -> None:
    rng = random.Random(2026)
    profile = ShortestProfile()
    finder = AStarPathFinder(synthetic_graph, profile)
    nodes = list(synthetic_graph.nodes)
    pairs = [tuple(rng.sample(nodes, 2)) for _ in range(25)]

    for origin, dest in pairs:
        result = finder.find_path(origin, dest)
        expected = nx.shortest_path_length(synthetic_graph, origin, dest, weight="length")
        assert result.cost == pytest.approx(expected, rel=1e-9, abs=1e-9)
        assert result.distance_m == pytest.approx(expected, rel=1e-9, abs=1e-9)
        assert result.nodes[0] == origin
        assert result.nodes[-1] == dest
        assert result.nodes_expanded > 0
        assert result.elapsed_s >= 0.0


def test_astar_and_dijkstra_agree_for_both_profiles(synthetic_graph) -> None:
    rng = random.Random(7)
    nodes = list(synthetic_graph.nodes)
    for profile in (ShortestProfile(), BikeFriendlyProfile()):
        astar = AStarPathFinder(synthetic_graph, profile)
        dijkstra = DijkstraPathFinder(synthetic_graph, profile)
        for _ in range(20):
            origin, dest = rng.sample(nodes, 2)
            a = astar.find_path(origin, dest)
            d = dijkstra.find_path(origin, dest)
            assert a.cost == pytest.approx(d.cost, rel=1e-9, abs=1e-9)
            assert a.distance_m == pytest.approx(d.distance_m, rel=1e-9, abs=1e-9)


def test_heuristic_never_overestimates(synthetic_graph) -> None:
    dest = 24
    destination = node_coordinate(synthetic_graph, dest)
    distances = nx.single_source_dijkstra_path_length(
        synthetic_graph.reverse(copy=False), dest, weight="length"
    )
    for profile in (ShortestProfile(), BikeFriendlyProfile()):
        scale = profile.heuristic_scale()
        for node, true_distance in distances.items():
            estimate = heuristic_m(synthetic_graph, node, destination, scale)
            assert estimate <= true_distance + 1e-6


def test_heuristic_is_consistent_on_edges(synthetic_graph) -> None:
    dest = 12
    destination = node_coordinate(synthetic_graph, dest)
    for profile in (ShortestProfile(), BikeFriendlyProfile()):
        scale = profile.heuristic_scale()
        for source, target, data in synthetic_graph.edges(data=True):
            cost = profile.edge_cost(data)
            if cost == float("inf"):
                continue
            left = heuristic_m(synthetic_graph, source, destination, scale)
            right = cost + heuristic_m(synthetic_graph, target, destination, scale)
            assert left <= right + 1e-6


def test_no_route_raises_clear_error() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=-3.0, y=40.0, lat=40.0, lon=-3.0)
    graph.add_node(2, x=-3.0, y=40.001, lat=40.001, lon=-3.0)
    graph.add_node(3, x=-3.0, y=40.002, lat=40.002, lon=-3.0)
    graph.add_edge(1, 2, key=0, length=100.0, highway="residential")
    finder = AStarPathFinder(graph, ShortestProfile())
    with pytest.raises(NoRouteFoundError):
        finder.find_path(1, 3)


def test_origin_equals_destination(synthetic_graph) -> None:
    result = AStarPathFinder(synthetic_graph, ShortestProfile()).find_path(0, 0)
    assert result.nodes == (0,)
    assert result.cost == 0.0
    assert result.distance_m == 0.0
