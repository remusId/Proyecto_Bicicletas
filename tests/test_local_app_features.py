"""Pruebas locales para la búsqueda, la vista y los diagnósticos."""

from dataclasses import replace
from unittest.mock import Mock

import networkx as nx
import pytest

from app.config import Settings
from app.domain.exceptions import ProviderUnavailableError
from app.domain.models import Coordinate
from app.providers.overpass_provider import OverpassProvider
from app.routing.profile import profile_from_name
from app.services.cache import GraphCache
from app.services.diagnostics import explain_no_route
from app.services.geocoder import TTL_S, NominatimGeocoder
from app.services.ui_state import MapView, ViewStore


def test_geocoder_parses_reuses_disk_cache_and_expires(tmp_path, monkeypatch):
    clock = Mock(return_value=1000.0)
    monkeypatch.setattr("app.services.geocoder.time.time", clock)
    response = Mock(status_code=200)
    response.json.return_value = [{"display_name": "Plaza Norte", "lat": "-12", "lon": "-77"}]
    get = Mock(return_value=response)
    monkeypatch.setattr("app.services.geocoder.requests.get", get)
    path = tmp_path / "geocode.json"
    places = NominatimGeocoder("Prueba/1", path).search("Plaza Norte")
    assert places[0].coordinate == Coordinate(-12, -77)
    assert NominatimGeocoder("Prueba/1", path).search(" plaza  norte ") == places
    assert get.call_count == 1
    assert get.call_args.kwargs["headers"]["User-Agent"] == "Prueba/1"
    assert get.call_args.kwargs["params"]["format"] == "jsonv2"
    clock.return_value += TTL_S
    assert NominatimGeocoder("Prueba/1", path).search("Plaza Norte") == places
    assert get.call_count == 2


def test_geocoder_429_is_actionable_and_throttles_next_attempt(tmp_path, monkeypatch):
    get = Mock(return_value=Mock(status_code=429))
    monkeypatch.setattr("app.services.geocoder.requests.get", get)
    sleep = Mock()
    monkeypatch.setattr("app.services.geocoder.time.sleep", sleep)
    geocoder = NominatimGeocoder("Prueba/1", tmp_path / "geocode.json")
    for query in ("Lima", "Madrid"):
        with pytest.raises(ProviderUnavailableError, match="HTTP 429.*usa coordenadas"):
            geocoder.search(query)
    assert get.call_count == 2
    assert 0 < sleep.call_args.args[0] <= 1


@pytest.mark.network
def test_nominatim_plaza_norte_lima(tmp_path):
    places = NominatimGeocoder(Settings.from_env().user_agent, tmp_path / "geocode.json").search(
        "Plaza Norte, Lima"
    )
    assert places[0].coordinate.distance_to(Coordinate(-12.0063, -77.0588)) < 2000


def test_view_persists_and_handles_invalid_data(tmp_path, monkeypatch):
    target = tmp_path / "ui_state.json"
    monkeypatch.setenv("APP_UI_STATE", str(target))
    madrid = MapView(Coordinate(40.4168, -3.7038), 14)
    lima = MapView(Coordinate(-12.01, -77.05), 16)
    assert ViewStore().load(madrid) == madrid
    ViewStore().save(lima)
    assert ViewStore().load(madrid) == lima
    target.write_bytes(b'{"lat": NaN, "lon": -77, "zoom": 16}')
    assert ViewStore().load(madrid) == madrid
    target.write_bytes(b"\xff")
    assert ViewStore().load(madrid) == madrid


def test_overpass_failover_is_sequential(tmp_path, monkeypatch, overpass_payload):
    urls = ("https://first.invalid/api", "https://second.invalid/api")
    monkeypatch.setenv("APP_OVERPASS_URLS", ", ".join(urls))
    settings = replace(Settings.from_env(), overpass_retries=2)
    provider = OverpassProvider.from_settings(GraphCache(tmp_path), settings)
    ok = Mock(status_code=200)
    ok.json.return_value = overpass_payload
    failure = Mock(status_code=502, headers={})
    post = Mock(side_effect=[failure, failure, ok])
    monkeypatch.setattr(provider._session, "post", post)
    monkeypatch.setattr("app.providers.overpass_provider.time.sleep", Mock())
    assert provider._request("consulta") == overpass_payload
    assert [call.args[0] for call in post.call_args_list] == [urls[0], urls[0], urls[1]]
    post.side_effect = None
    post.return_value = failure
    with pytest.raises(
        ProviderUnavailableError, match=r"tras 4 intentos.*first\.invalid.*second\.invalid"
    ):
        provider._request("consulta")


def test_diagnostic_reports_component_sizes_and_closest_points():
    graph = nx.MultiDiGraph()
    for node, lon in enumerate((0, 0.001, 0.00108, 0.002)):
        graph.add_node(node, lat=0, lon=lon)
    graph.add_edge(0, 1, highway="residential", length=110)
    graph.add_edge(2, 3, highway="residential", length=100)
    graph.add_edge(1, 2, highway="residential", length=9, bicycle="no")
    message = explain_no_route(graph, profile_from_name("bike"), 0, 3)
    assert "2 y 2 nodos, 0 aristas" in message
    assert "9 m" in message
    assert "0.000000,0.001000 y 0.000000,0.001080" in message


def test_diagnostic_distinguishes_direction_isolated_nodes_and_empty_graph():
    graph = nx.MultiDiGraph()
    graph.add_edge(1, 2, highway="residential", length=100)
    graph.add_node(3)
    profile = profile_from_name("bike")
    assert "sentido solicitado" in explain_no_route(graph, profile, 2, 1)
    assert "sin aristas transitables" in explain_no_route(graph, profile, 1, 3)
    assert "grafo está vacío" in explain_no_route(nx.MultiDiGraph(), profile, 1, 3)


def test_alternative_accesses_respect_direction_and_bicycle_restrictions():
    graph = nx.MultiDiGraph()
    for node, lon in enumerate((0, 0.01, 0.009, 0.001, 0.002, 0.008)):
        graph.add_node(node, lat=0, lon=lon)
    for source, target in ((0, 2), (3, 1), (1, 4), (5, 0)):
        graph.add_edge(source, target, highway="residential", length=100)
    graph.add_edge(0, 1, highway="residential", bicycle="no", length=100)
    message = explain_no_route(
        graph,
        profile_from_name("bike"),
        0,
        1,
        requested_points=(Coordinate(0, 0.0019), Coordinate(0, 0.0081)),
    )
    assert "Origen alternativo: 0.0,0.001" in message
    assert "Destino alternativo: 0.0,0.009" in message
    assert "cambiando solo uno" in message
