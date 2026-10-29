"""Pruebas del dominio y de la configuración."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.exceptions import (
    AreaTooLargeError,
    NoRouteFoundError,
    ProviderUnavailableError,
    RoutingError,
    SnapDistanceError,
)
from app.domain.models import BoundingBox, Coordinate, RouteResult


def test_coordinate_validates_ranges() -> None:
    assert Coordinate(40.4, -3.7).as_tuple() == (40.4, -3.7)
    with pytest.raises(ValueError):
        Coordinate(91.0, 0.0)
    with pytest.raises(ValueError):
        Coordinate(0.0, 181.0)
    with pytest.raises(ValueError):
        Coordinate.from_string("40.4")


def test_coordinate_from_string() -> None:
    coordinate = Coordinate.from_string(" 40.4168 , -3.7038 ")
    assert coordinate == Coordinate(40.4168, -3.7038)
    with pytest.raises(ValueError):
        Coordinate.from_string("a,b")


def test_bounding_box_contains_margin_and_has_area() -> None:
    origin = Coordinate(40.4168, -3.7038)
    dest = Coordinate(40.4268, -3.6938)
    bbox = BoundingBox.from_points(origin, dest, margin_m=500.0)
    assert bbox.south < origin.lat < bbox.north
    assert bbox.west < origin.lon < bbox.east
    assert bbox.area_km2 > 0.0
    assert bbox.to_osmnx_tuple() == (bbox.west, bbox.south, bbox.east, bbox.north)
    assert bbox.cache_token() == bbox.cache_token()
    with pytest.raises(ValueError):
        BoundingBox.from_points(origin, dest, margin_m=-1.0)


def test_route_result_properties() -> None:
    result = RouteResult(
        nodes=(1, 2, 3),
        distance_m=1500.0,
        duration_s=360.0,
        nodes_expanded=4,
        backend="fake",
        profile="bike",
        algorithm="A*",
        snap_origin_m=10.0,
        snap_dest_m=20.0,
    )
    assert result.distance_km == 1.5
    assert result.duration_min == 6.0
    assert result.as_summary()["backend"] == "fake"
    with pytest.raises(ValueError):
        RouteResult(
            nodes=(),
            distance_m=-1.0,
            duration_s=0.0,
            nodes_expanded=0,
            backend="fake",
            profile="bike",
            algorithm="A*",
            snap_origin_m=0.0,
            snap_dest_m=0.0,
        )


def test_exception_hierarchy() -> None:
    for error_type in (
        NoRouteFoundError,
        AreaTooLargeError,
        ProviderUnavailableError,
        SnapDistanceError,
    ):
        assert issubclass(error_type, RoutingError)


def test_settings_validation() -> None:
    settings = Settings()
    assert settings.provider == "osmnx"
    with pytest.raises(ValueError):
        Settings(provider="otro")
    with pytest.raises(ValueError):
        Settings(overpass_retries=4)
    with pytest.raises(ValueError):
        Settings(bike_speed_kmh=0.0)
