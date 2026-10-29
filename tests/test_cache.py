"""Pruebas de la caché en disco."""

from __future__ import annotations

import networkx as nx

from app.domain.models import BoundingBox, Coordinate
from app.services.cache import GraphCache


def _graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=-3.7, y=40.4, lat=40.4, lon=-3.7)
    graph.add_node(2, x=-3.6, y=40.4, lat=40.4, lon=-3.6)
    graph.add_edge(1, 2, length=100.0, highway="residential")
    return graph


def test_cache_roundtrip_and_key_components(tmp_path) -> None:
    cache = GraphCache(tmp_path / "cache", enabled=True)
    bbox = BoundingBox.from_points(Coordinate(40.4, -3.7), Coordinate(40.4, -3.6), margin_m=100.0)
    key_osmnx = cache.key(bbox, "osmnx", "bike")
    key_overpass = cache.key(bbox, "overpass", "bike")
    key_shortest = cache.key(bbox, "osmnx", "shortest")
    assert len({key_osmnx, key_overpass, key_shortest}) == 3

    cache.save(key_osmnx, _graph())
    loaded = cache.load(key_osmnx)
    assert loaded is not None
    assert loaded.number_of_nodes() == 2
    assert loaded[1][2][0]["length"] == 100.0
    assert cache.load(key_overpass) is None


def test_disabled_cache_does_not_write(tmp_path) -> None:
    cache = GraphCache(tmp_path / "cache", enabled=False)
    bbox = BoundingBox.from_points(Coordinate(40.4, -3.7), Coordinate(40.4, -3.6), margin_m=100.0)
    key = cache.key(bbox, "osmnx", "bike")
    cache.save(key, _graph())
    assert cache.load(key) is None
    assert not cache.directory.exists()
