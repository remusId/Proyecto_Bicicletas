"""Pruebas del proveedor OSMnx sin red."""

from __future__ import annotations

import osmnx as ox
import pytest

from app.domain.exceptions import ProviderUnavailableError
from app.domain.models import BoundingBox, Coordinate
from app.providers.osmnx_provider import OsmnxProvider
from app.services.cache import GraphCache


def test_osmnx_nearest_node_uses_projected_graph(synthetic_graph, tmp_path) -> None:
    projected = ox.project_graph(synthetic_graph)
    for node, data in synthetic_graph.nodes(data=True):
        projected.nodes[node]["lat"] = data["lat"]
        projected.nodes[node]["lon"] = data["lon"]

    provider = OsmnxProvider(
        GraphCache(tmp_path, enabled=False),
        user_agent="test/1.0 (test@example.invalid)",
    )
    node, distance_m = provider.nearest_node(projected, Coordinate(40.0001, -3.0001))
    assert node == 0
    assert 0.0 <= distance_m < 50.0


def test_osmnx_retries_502_and_projects(synthetic_graph, tmp_path, monkeypatch) -> None:
    provider = OsmnxProvider(
        GraphCache(tmp_path, enabled=False),
        user_agent="test/1.0 (test@example.invalid)",
        retries=3,
        backoff_base_s=0.0,
    )
    calls: list[int] = []

    def fake_graph_from_bbox(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("502 Bad Gateway")
        return synthetic_graph

    monkeypatch.setattr(ox, "graph_from_bbox", fake_graph_from_bbox)
    bbox = BoundingBox.from_points(
        Coordinate(40.0, -3.0), Coordinate(40.004, -2.996), margin_m=100.0
    )
    graph = provider.load_graph(bbox)
    assert len(calls) == 3
    assert graph.nodes[0]["lat"] == pytest.approx(40.0)


def test_osmnx_retry_exhaustion_is_clear(synthetic_graph, tmp_path, monkeypatch) -> None:
    provider = OsmnxProvider(
        GraphCache(tmp_path, enabled=False),
        user_agent="test/1.0 (test@example.invalid)",
        retries=3,
        backoff_base_s=0.0,
    )
    calls: list[int] = []

    def fake_graph_from_bbox(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("504 Gateway Timeout")

    monkeypatch.setattr(ox, "graph_from_bbox", fake_graph_from_bbox)
    bbox = BoundingBox.from_points(
        Coordinate(40.0, -3.0), Coordinate(40.004, -2.996), margin_m=100.0
    )
    with pytest.raises(ProviderUnavailableError, match="tras 3 intento"):
        provider.load_graph(bbox)
    assert len(calls) == 3
