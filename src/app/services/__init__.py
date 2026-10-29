"""Servicios de aplicación."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.cache import GraphCache

if TYPE_CHECKING:
    from app.services.planner import RoutePlanner

__all__ = ["GraphCache", "RoutePlanner"]


def __getattr__(name: str) -> Any:
    """Carga el planificador solo cuando se solicita explícitamente."""
    if name == "RoutePlanner":
        from app.services.planner import RoutePlanner

        return RoutePlanner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
