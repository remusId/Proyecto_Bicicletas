"""Pruebas de fábricas y de la capa de presentación."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.models import Coordinate, RouteResult
from app.providers.base import GraphProvider
from app.providers.factory import GraphProviderFactory
from app.providers.osmnx_provider import OsmnxProvider
from app.providers.overpass_provider import OverpassProvider
from app.routing.astar import AStarPathFinder
from app.routing.dijkstra import DijkstraPathFinder
from app.routing.factory import PathFinderFactory
from app.routing.profile import BikeFriendlyProfile, ShortestProfile, profile_from_name
from app.services.cache import GraphCache
from app.ui.map_renderer import MapRenderer


def test_graph_provider_abstract_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        GraphProvider()  # type: ignore[abstract]


def test_provider_factory(tmp_path) -> None:
    settings = Settings()
    cache = GraphCache(tmp_path / "cache", enabled=False)
    osmnx = GraphProviderFactory.create("osmnx", cache, settings)
    overpass = GraphProviderFactory.create("overpass", cache, settings)
    assert isinstance(osmnx, OsmnxProvider)
    assert isinstance(overpass, OverpassProvider)
    with pytest.raises(ValueError):
        GraphProviderFactory.create("otro", cache, settings)


def test_pathfinder_and_profile_factories() -> None:
    assert isinstance(PathFinderFactory.create("astar"), AStarPathFinder)
    assert isinstance(PathFinderFactory.create("dijkstra"), DijkstraPathFinder)
    assert isinstance(profile_from_name("bike"), BikeFriendlyProfile)
    assert isinstance(profile_from_name("shortest"), ShortestProfile)
    with pytest.raises(ValueError):
        PathFinderFactory.create("otro")
    with pytest.raises(ValueError):
        profile_from_name("otro")


def test_map_renderer_draws_route_and_attribution() -> None:
    origin = Coordinate(40.0, -3.0)
    dest = Coordinate(40.001, -3.001)
    result = RouteResult(
        nodes=(1, 2),
        distance_m=150.0,
        duration_s=36.0,
        nodes_expanded=2,
        backend="fake",
        profile="bike",
        algorithm="A*",
        snap_origin_m=1.0,
        snap_dest_m=1.0,
        geometry=(origin, dest),
    )
    fmap = MapRenderer().render(origin, dest, result)
    html = fmap.get_root().render()
    assert "OpenStreetMap contributors" in html
    assert "Ruta ciclista" in html
    assert "Origen" in html
    assert "Destino" in html
