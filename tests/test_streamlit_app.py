"""Prueba de arranque de la app Streamlit sin navegador."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from streamlit.testing.v1 import AppTest

from app.domain.models import BoundingBox, Coordinate, RouteResult
from app.services.planner import RoutePlanner
from app.services.ui_state import MapView, ViewStore

APP_PATH = Path(__file__).parents[1] / "src" / "app" / "ui" / "streamlit_app.py"


def test_streamlit_app_starts_without_exceptions() -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not app.exception
    assert len(app.title) == 1
    assert len(app.radio) == 1
    assert {button.label for button in app.button} == {
        "Fijar origen",
        "Buscar",
        "Calcular ruta",
        "Limpiar puntos",
    }


def test_streamlit_keeps_coordinate_view_in_new_session(tmp_path, monkeypatch) -> None:
    path = tmp_path / "view.json"
    monkeypatch.setenv("APP_UI_STATE", str(path))
    app = AppTest.from_file(APP_PATH, default_timeout=60).run()
    app.text_input[0].set_value("-12.019720,-77.048610")
    next(button for button in app.button if button.label == "Fijar origen").click().run()
    assert not app.exception
    expected = MapView(Coordinate(-12.019720, -77.048610), 16)
    assert ViewStore(path).load(MapView(Coordinate(0, 0), 14)) == expected
    fresh = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not fresh.exception
    assert fresh.session_state["map_view"] == expected


def test_coordinate_form_keeps_origin_and_destination_independent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_UI_STATE", str(tmp_path / "view.json"))
    monkeypatch.setattr(RoutePlanner, "prefetch", lambda *_: None)
    app = AppTest.from_file(APP_PATH, default_timeout=60).run()
    app.text_input[0].set_value("40.4168,-3.7038")
    next(button for button in app.button if button.label == "Fijar origen").click().run()
    app.radio[0].set_value("Destino").run()
    assert app.text_input[0].value == ""

    app.text_input[0].set_value("40.47,-3.65")
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
    assert app.text_input[0].value == "40.47,-3.65"
    next(button for button in app.button if button.label == "Limpiar puntos").click().run()
    assert app.text_input[0].value == ""
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
