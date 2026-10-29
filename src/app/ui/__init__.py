"""Interfaces de usuario."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.ui.cli import CliApp
from app.ui.map_renderer import MapRenderer

if TYPE_CHECKING:
    from app.ui.streamlit_app import StreamlitApp

__all__ = ["CliApp", "MapRenderer", "StreamlitApp"]


def __getattr__(name: str) -> Any:
    """Carga Streamlit solo cuando se solicita explícitamente."""
    if name == "StreamlitApp":
        from app.ui.streamlit_app import StreamlitApp

        return StreamlitApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
