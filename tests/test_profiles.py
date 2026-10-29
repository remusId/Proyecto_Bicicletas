"""Pruebas del perfil ciclista, exclusiones y admisibilidad."""

from __future__ import annotations

import math

import networkx as nx
import pytest

from app.routing.astar import AStarPathFinder
from app.routing.profile import BikeFriendlyProfile, ShortestProfile


def _edge(highway: str, length: float = 100.0, **extra) -> dict:
    return {"highway": highway, "length": length, **extra}


def test_multiplier_order_for_bike_profile() -> None:
    profile = BikeFriendlyProfile()
    cycleway = profile.edge_cost(_edge("cycleway"))
    residential = profile.edge_cost(_edge("residential"))
    living_street = profile.edge_cost(_edge("living_street"))
    tertiary = profile.edge_cost(_edge("tertiary"))
    secondary = profile.edge_cost(_edge("secondary"))
    primary = profile.edge_cost(_edge("primary"))
    assert cycleway < residential
    assert cycleway < living_street
    assert residential < tertiary < secondary < primary
    assert cycleway == pytest.approx(100.0)
    assert profile.heuristic_scale() >= 1.0


def test_forbidden_roads_are_excluded() -> None:
    for profile in (ShortestProfile(), BikeFriendlyProfile()):
        assert math.isinf(profile.edge_cost(_edge("motorway")))
        assert math.isinf(profile.edge_cost(_edge("trunk")))
        assert math.isinf(profile.edge_cost(_edge("steps")))
        assert math.isinf(profile.edge_cost(_edge("residential", bicycle="no")))
        assert math.isinf(profile.edge_cost(_edge("residential", access="private")))


def test_bicycle_yes_overrides_private_access() -> None:
    profile = BikeFriendlyProfile()
    cost = profile.edge_cost(_edge("residential", access="private", bicycle="yes"))
    assert math.isfinite(cost)
    assert cost == pytest.approx(108.0)


def test_shortest_profile_uses_length_only() -> None:
    profile = ShortestProfile()
    assert profile.edge_cost(_edge("primary", length=250.0)) == pytest.approx(250.0)
    assert profile.heuristic_scale() == 1.0


def test_custom_multipliers_must_keep_heuristic_admissible() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        BikeFriendlyProfile(multipliers={"residential": 0.9})
    profile = BikeFriendlyProfile(multipliers={"residential": 2.0})
    assert profile.edge_cost(_edge("residential")) == pytest.approx(200.0)
    assert profile.heuristic_scale() >= 1.0

    all_double = {key: 2.0 for key in BikeFriendlyProfile.DEFAULT_MULTIPLIERS}
    doubled = BikeFriendlyProfile(multipliers=all_double)
    assert doubled.heuristic_scale() == pytest.approx(2.0)
    assert doubled.edge_cost(_edge("cycleway", bicycle="yes")) == pytest.approx(200.0)


def test_astar_avoids_steps_even_if_shorter() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node(1, lat=40.0, lon=-3.0, x=-3.0, y=40.0)
    graph.add_node(2, lat=40.0, lon=-2.999, x=-2.999, y=40.0)
    graph.add_node(3, lat=40.0, lon=-2.998, x=-2.998, y=40.0)
    graph.add_edge(1, 2, key=0, length=50.0, highway="steps")
    graph.add_edge(1, 3, key=0, length=150.0, highway="residential")
    graph.add_edge(3, 2, key=0, length=150.0, highway="residential")
    result = AStarPathFinder(graph, BikeFriendlyProfile()).find_path(1, 2)
    assert result.nodes == (1, 3, 2)
    assert result.distance_m == pytest.approx(300.0)
