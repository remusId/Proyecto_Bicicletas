"""Prueba de arranque de la app Streamlit sin navegador."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.domain.models import BoundingBox, Coordinate, RouteResult
from app.providers.overpass_provider import OverpassProvider
from app.services import desktop_session
from app.services.planner import RoutePlanner
from app.services.ui_state import MapView

APP_PATH = Path(__file__).parents[1] / "src" / "app" / "ui" / "streamlit_app.py"


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_CACHE_DIR", str(tmp_path / "graphs"))
    monkeypatch.setenv("APP_GEOCODE_CACHE", str(tmp_path / "geocode.json"))


def test_streamlit_app_starts_without_exceptions() -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not app.exception
    assert len(app.title) == 1
    assert len(app.radio) == 1
    assert {button.label for button in app.button} == {
        "Fijar origen",
        "Fijar destino",
        "Buscar",
        "Calcular ruta",
        "Limpiar puntos",
        "Limpiar caché",
    }
    assert not app.sidebar.selectbox
    assert {widget.label: widget.value for widget in app.selectbox} == {
        "Backend de datos": "overpass",
        "Perfil": "bike",
        "Algoritmo": "astar",
    }
    assert {widget.label: widget.value for widget in app.number_input} == {
        "Velocidad media (km/h)": 15.0,
        "Margen del bbox (km)": 1.0,
    }
    assert "proyecto academico" not in str(app.caption)


def test_streamlit_starts_in_lima_and_keeps_view_only_in_session(tmp_path, monkeypatch) -> None:
    path = tmp_path / "ui_state.json"
    previous_view = '{"lat": 46.6, "lon": 1.8, "zoom": 5}'
    path.write_text(previous_view, encoding="utf-8")
    monkeypatch.setenv("APP_UI_STATE", str(path))
    default_view = MapView(Coordinate(-12.0464, -77.0428), 14)
    app = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert app.session_state["map_view"] == default_view
    app.text_input[0].set_value("-12.019720,-77.048610")
    next(button for button in app.button if button.label == "Fijar origen").click().run()
    assert not app.exception
    expected = MapView(Coordinate(-12.019720, -77.048610), 16)
    assert app.run().session_state["map_view"] == expected
    fresh = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not fresh.exception
    assert fresh.session_state["map_view"] == default_view
    assert path.read_text(encoding="utf-8") == previous_view


def test_desktop_exit_calls_launcher_shutdown(monkeypatch) -> None:
    shutdown = Mock()
    register = Mock()
    monkeypatch.setattr(desktop_session, "shutdown", shutdown)
    monkeypatch.setattr(st.components.v2, "component", register)
    app = AppTest.from_file(APP_PATH, default_timeout=10).run()
    next(button for button in app.button if button.label == "Salir de la aplicación").click().run()
    assert not app.exception
    shutdown.assert_called_once_with()
    register.return_value.assert_called_once_with()
    assert "Aplicación cerrada" in register.call_args.kwargs["js"]


@pytest.mark.parametrize(
    ("origin", "dest"),
    [
        (
            Coordinate(8.754794702435618, -78.35449218750001),
            Coordinate(46.800059446787316, -99.140625),
        ),
        (Coordinate(39, -105), Coordinate(39, -101)),
    ],
)
def test_oversized_route_shows_download_limit_before_prefetch(origin, dest) -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=10).run()
    app.session_state["origin"] = origin
    app.session_state["dest"] = dest
    app.run()

    assert not app.exception
    assert app.session_state.get("prefetch") is None
    assert "Esta ruta requiere descargar" in app.error[0].value
    assert "calcula el recorrido por tramos" in app.error[0].value


def test_coordinate_form_keeps_origin_and_destination_independent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_UI_STATE", str(tmp_path / "view.json"))
    monkeypatch.setattr(RoutePlanner, "prefetch", lambda *_: None)
    app = AppTest.from_file(APP_PATH, default_timeout=60).run()
    app.text_input[0].set_value("40.4168,-3.7038")
    next(button for button in app.button if button.label == "Fijar origen").click().run()
    app.radio[0].set_value("Destino").run()
    assert app.text_input[1].value == ""

    app.text_input[1].set_value("40.47,-3.65")
    next(button for button in app.button if button.label == "Fijar destino").click().run()
    app.radio[0].set_value("Origen").run()
    assert app.text_input[0].value == "40.4168,-3.7038"
    assert app.session_state["origin"] == Coordinate(40.4168, -3.7038)
    assert app.session_state["dest"] == Coordinate(40.47, -3.65)
    _, planner, future = app.session_state["prefetch"]
    future.result()
    required_area = BoundingBox.from_points(
        app.session_state["origin"], app.session_state["dest"], planner.settings.margin_m
    ).area_km2
    assert required_area > 25
    assert planner.settings.max_area_km2 == required_area
    assert not next(button for button in app.button if button.label == "Calcular ruta").disabled

    app.radio[0].set_value("Destino").run()
    assert app.text_input[1].value == "40.47,-3.65"
    next(button for button in app.button if button.label == "Limpiar puntos").click().run()
    assert app.text_input[0].value == ""
    assert app.text_input[1].value == ""
    assert app.session_state["origin"] is None
    assert app.session_state["dest"] is None


def test_zoom_persists_without_changing_folium_initial_view(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_UI_STATE", str(tmp_path / "view.json"))
    rendered = []
    zoom_event = {"center": {"lat": -12.02, "lng": -77.05}, "zoom": 17}

    def map_component(map_obj, **kwargs):
        rendered.append((map_obj.location, map_obj.options["zoom"], kwargs["key"]))
        return zoom_event

    monkeypatch.setattr("streamlit_folium.st_folium", map_component)
    app = AppTest.from_file(APP_PATH, default_timeout=60).run()
    app.run()
    assert not app.exception
    assert rendered[0] == rendered[1]
    assert app.session_state["map_view"] == MapView(Coordinate(-12.02, -77.05), 17)


def test_calculate_waits_without_blocking_web_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_UI_STATE", str(tmp_path / "view.json"))
    release = Event()
    monkeypatch.setattr(RoutePlanner, "prefetch", lambda *_: release.wait(timeout=20))
    result = RouteResult((1, 2), 100, 30, 2, "overpass", "bike", "astar", 0, 0)
    monkeypatch.setattr(RoutePlanner, "plan_with_alternatives", lambda *_: result)
    app = AppTest.from_file(APP_PATH, default_timeout=10).run()
    app.session_state["origin"] = Coordinate(40.4168, -3.7038)
    app.session_state["dest"] = Coordinate(40.421, -3.699)
    try:
        app.run()
        _, _, future = app.session_state["prefetch"]
        next(button for button in app.button if button.label == "Calcular ruta").click().run()
        assert not app.exception
        assert not future.done()
        assert app.session_state["prefetch"][2] is future
        assert app.session_state["pending_calculation"]
    finally:
        release.set()
    future.result(timeout=5)
    app.run()
    assert not app.exception
    assert app.session_state["route_result"] == result


def test_shows_terrestrial_route_error_for_lima_to_france(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_UI_STATE", str(tmp_path / "view.json"))

    def unexpected_download(*args, **kwargs):
        pytest.fail("Una ruta transatlántica no debe consultar a Overpass.")

    monkeypatch.setattr(OverpassProvider, "load_graph", unexpected_download)
    app = AppTest.from_file(APP_PATH, default_timeout=10).run()
    app.session_state["origin"] = Coordinate(-12.0464, -77.0428)
    app.session_state["dest"] = Coordinate(46.6034, 1.8883)
    app.run()

    assert not app.exception
    assert [error.value for error in app.error] == [
        "No existe una ruta por tierra entre el origen y el destino. "
        "Los puntos están en zonas terrestres separadas por agua."
    ]


def test_wrapped_map_click_shows_pacific_route_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_UI_STATE", str(tmp_path / "view.json"))
    map_output = {}
    monkeypatch.setattr("streamlit_folium.st_folium", lambda *args, **kwargs: map_output)

    app = AppTest.from_file(APP_PATH, default_timeout=10).run()
    app.session_state["origin"] = Coordinate(34, -118)
    app.radio[0].set_value("Destino").run()
    map_output["last_clicked"] = {"lat": -37, "lng": -185}
    map_output["center"] = map_output["last_clicked"]
    map_output["zoom"] = 5
    app.run()

    assert not app.exception
    assert app.session_state["dest"] == Coordinate(-37, 175)
    assert app.session_state["map_view"] == MapView(Coordinate(-37, 175), 5)
    assert app.session_state.get("prefetch") is None
    assert [error.value for error in app.error] == [
        "No existe una ruta por tierra entre el origen y el destino. "
        "Los puntos están en zonas terrestres separadas por agua."
    ]


def test_invalid_map_click_shows_warning(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_UI_STATE", str(tmp_path / "view.json"))
    monkeypatch.setattr(
        "streamlit_folium.st_folium",
        lambda *args, **kwargs: {"last_clicked": {"lat": 91, "lng": 20}},
    )
    app = AppTest.from_file(APP_PATH, default_timeout=10).run()

    assert not app.exception
    assert app.session_state["origin"] is None
    assert [warning.value for warning in app.warning] == [
        "No se pudo seleccionar ese punto. Haz clic de nuevo en el mapa."
    ]
