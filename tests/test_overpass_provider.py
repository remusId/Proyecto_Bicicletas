"""Pruebas del parser y del proveedor Overpass sin red."""

from __future__ import annotations

import pytest
import requests

from app.domain.exceptions import ProviderUnavailableError
from app.domain.models import BoundingBox, Coordinate
from app.providers.overpass_provider import OverpassProvider, parse_overpass_payload
from app.services.cache import GraphCache


class FakeResponse:
    """Respuesta HTTP mínima para simular Overpass."""

    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


def _provider(tmp_path, **kwargs) -> OverpassProvider:
    return OverpassProvider(
        GraphCache(tmp_path / "cache", enabled=False),
        user_agent="ProyectoFinalPOO-Test/1.0 (test@example.invalid)",
        **kwargs,
    )


def test_parser_produces_osmnx_like_attributes(overpass_payload) -> None:
    graph = parse_overpass_payload(overpass_payload)
    assert graph.number_of_nodes() == 8
    assert graph.graph["crs"] == "epsg:4326"
    assert graph.graph["created_with"] == "OverpassProvider"
    assert graph.graph["simplified"] is False

    node = graph.nodes[1]
    for key in ("x", "y", "lat", "lon", "street_count"):
        assert key in node
    assert node["x"] == pytest.approx(-3.7040)
    assert node["y"] == pytest.approx(40.4160)

    data = graph[1][2][next(iter(graph[1][2]))]
    for key in (
        "length",
        "highway",
        "oneway",
        "reversed",
        "osmid",
        "name",
        "geometry",
        "bicycle",
        "oneway:bicycle",
    ):
        assert key in data
    assert data["length"] > 0.0
    assert data["highway"] == "residential"
    assert data["osmid"] == 100
    assert data["reversed"] is False


def test_parser_respects_oneway_and_oneway_bicycle(overpass_payload) -> None:
    graph = parse_overpass_payload(overpass_payload)
    assert graph.has_edge(1, 2)
    assert not graph.has_edge(2, 1)

    assert graph.has_edge(3, 4)
    assert graph.has_edge(4, 3)

    assert graph.has_edge(6, 5)
    assert not graph.has_edge(5, 6)

    assert graph.has_edge(7, 8)
    assert graph.has_edge(8, 7)
    reverse_data = graph[8][7][next(iter(graph[8][7]))]
    assert reverse_data["reversed"] is True


def test_parser_keeps_prohibited_roads_for_profile_filtering(overpass_payload) -> None:
    graph = parse_overpass_payload(overpass_payload)
    motorway = graph[2][4][next(iter(graph[2][4]))]
    steps = graph[6][7][next(iter(graph[6][7]))]
    assert motorway["highway"] == "motorway"
    assert steps["highway"] == "steps"
    assert steps["bicycle"] == "no"


def test_parser_skips_missing_nodes() -> None:
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 40.0, "lon": -3.0},
            {"type": "node", "id": 2, "lat": 40.001, "lon": -3.0},
            {
                "type": "way",
                "id": 10,
                "nodes": [1, 2, 99],
                "tags": {"highway": "residential"},
            },
        ]
    }
    graph = parse_overpass_payload(payload)
    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 2


def test_overpass_nearest_node_in_meters(overpass_payload, tmp_path) -> None:
    graph = parse_overpass_payload(overpass_payload)
    provider = _provider(tmp_path)
    node, distance_m = provider.nearest_node(graph, Coordinate(40.41601, -3.70401))
    assert node == 1
    assert 0.0 < distance_m < 5.0


def test_overpass_retries_429_and_respects_retry_after(
    tmp_path, monkeypatch, overpass_payload
) -> None:
    provider = _provider(tmp_path, retries=3, backoff_base_s=1.0)
    responses = [
        FakeResponse(429, headers={"Retry-After": "0"}),
        FakeResponse(429, headers={"Retry-After": "0"}),
        FakeResponse(200, overpass_payload),
    ]
    calls: list[object] = []

    def fake_post(url, data, timeout):
        calls.append((url, data, timeout))
        return responses.pop(0)

    sleeps: list[float] = []
    monkeypatch.setattr(provider._session, "post", fake_post)
    monkeypatch.setattr("app.providers.overpass_provider.time.sleep", sleeps.append)

    payload = provider._request("consulta")
    assert payload["elements"]
    assert len(calls) == 3
    assert sleeps == [0.0, 0.0]


def test_overpass_retries_exhausted_raises_clear_error(tmp_path, monkeypatch) -> None:
    provider = _provider(tmp_path, retries=3, backoff_base_s=1.0)
    calls: list[object] = []

    def fake_post(url, data, timeout):
        calls.append(url)
        return FakeResponse(504)

    monkeypatch.setattr(provider._session, "post", fake_post)
    monkeypatch.setattr("app.providers.overpass_provider.time.sleep", lambda _: None)

    with pytest.raises(ProviderUnavailableError, match="tras 3 intentos"):
        provider._request("consulta")
    assert len(calls) == 3


def test_overpass_retries_timeout(tmp_path, monkeypatch) -> None:
    provider = _provider(tmp_path, retries=3)
    calls: list[object] = []

    def fake_post(url, data, timeout):
        calls.append(url)
        raise requests.Timeout("sin respuesta")

    monkeypatch.setattr(provider._session, "post", fake_post)
    monkeypatch.setattr("app.providers.overpass_provider.time.sleep", lambda _: None)

    with pytest.raises(ProviderUnavailableError, match="timeout"):
        provider._request("consulta")
    assert len(calls) == 3


def test_overpass_query_and_user_agent(tmp_path) -> None:
    provider = _provider(tmp_path)
    bbox = BoundingBox.from_points(Coordinate(40.4, -3.7), Coordinate(40.41, -3.69), margin_m=100.0)
    query = provider._build_query(bbox)
    assert 'way["highway"' in query
    assert f"({bbox.south},{bbox.west},{bbox.north},{bbox.east})" in query
    assert provider.user_agent.startswith("ProyectoFinalPOO-Test/")


def test_overpass_load_graph_and_cache(tmp_path, monkeypatch, overpass_payload) -> None:
    cache = GraphCache(tmp_path / "cache", enabled=True)
    provider = OverpassProvider(
        cache,
        user_agent="ProyectoFinalPOO-Test/1.0 (test@example.invalid)",
    )
    calls: list[str] = []

    def fake_request(query: str) -> dict:
        calls.append(query)
        return overpass_payload

    monkeypatch.setattr(provider, "_request", fake_request)
    bbox = BoundingBox.from_points(
        Coordinate(40.416, -3.704), Coordinate(40.42, -3.698), margin_m=100.0
    )
    first = provider.load_graph(bbox, profile="bike")
    second = provider.load_graph(bbox, profile="bike")
    assert first.number_of_edges() > 0
    assert second.number_of_edges() == first.number_of_edges()
    assert len(calls) == 1


def test_overpass_empty_response_is_reported(tmp_path, monkeypatch) -> None:
    provider = _provider(tmp_path)
    monkeypatch.setattr(provider, "_request", lambda query: {"elements": []})
    bbox = BoundingBox.from_points(Coordinate(40.4, -3.7), Coordinate(40.41, -3.69), margin_m=100.0)
    with pytest.raises(ProviderUnavailableError, match="no encontró"):
        provider.load_graph(bbox)
