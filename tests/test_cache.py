"""Pruebas de la caché en disco."""

from __future__ import annotations

import os
import time

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


def test_prune_expires_and_limits_only_cache_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.cache.GRAPH_CACHE_LIMIT_BYTES", 12)
    cache = GraphCache(tmp_path)
    osmnx = tmp_path / "osmnx"
    osmnx.mkdir()
    expired = osmnx / ("a" * 40 + ".json")
    older = osmnx / ("b" * 40 + ".json")
    recent = osmnx / ("c" * 40 + ".json")
    unrelated = osmnx / "mis-datos.json"
    now = time.time()
    for path, seconds_ago in ((expired, 20 * 86400), (older, 60), (recent, 0), (unrelated, 0)):
        path.write_bytes(b"12345678")
        os.utime(path, (now - seconds_ago, now - seconds_ago))

    assert cache.prune() == 2
    assert recent.exists()
    assert unrelated.exists()
    assert cache.clear() == 1
    assert not recent.exists()
    assert unrelated.exists()
