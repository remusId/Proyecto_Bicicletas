"""Prueba de arranque de la app Streamlit sin navegador."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parents[1] / "src" / "app" / "ui" / "streamlit_app.py"


def test_streamlit_app_starts_without_exceptions() -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not app.exception
    assert len(app.title) == 1
    assert len(app.radio) == 1
    assert len(app.button) == 2
