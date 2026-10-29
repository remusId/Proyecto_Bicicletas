"""Prueba de integración real, omitida por defecto."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.domain.models import Coordinate
from app.providers.factory import GraphProviderFactory
from app.routing.factory import PathFinderFactory
from app.routing.profile import profile_from_name
from app.services.cache import GraphCache
from app.services.planner import RoutePlanner


@pytest.mark.network
def test_real_short_route_with_overpass() -> None:
    """Calcula una ruta corta real contra la API pública de Overpass."""
    settings = Settings(
        provider="overpass",
        profile="bike",
        algorithm="astar",
        margin_m=250.0,
        max_area_km2=2.0,
        overpass_timeout_s=60.0,
        overpass_retries=3,
        cache_dir=Path(".cache/network-test"),
        use_cache=False,
        user_agent="ProyectoFinalPOO-Test/1.0 (test@example.invalid)",
    )
    cache = GraphCache(settings.cache_dir, enabled=False)
    provider = GraphProviderFactory.create(settings.provider, cache, settings)
    planner = RoutePlanner(
        provider,
        profile_from_name(settings.profile),
        PathFinderFactory.create(settings.algorithm),
        settings,
    )
    result = planner.plan(
        Coordinate(40.4168, -3.7038),
        Coordinate(40.4210, -3.6990),
    )
    assert result.distance_m > 0.0
    assert result.duration_s > 0.0
    assert result.backend == "overpass"
    assert result.nodes_expanded > 0
    assert len(result.geometry) == len(result.nodes)
