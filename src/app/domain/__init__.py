"""Modelos y excepciones del dominio."""

from app.domain.exceptions import (
    AreaTooLargeError,
    NoRouteFoundError,
    ProviderUnavailableError,
    RoutingError,
    SnapDistanceError,
)
from app.domain.models import (
    EARTH_RADIUS_M,
    BoundingBox,
    Coordinate,
    NodeId,
    RouteResult,
    haversine_m,
)

__all__ = [
    "EARTH_RADIUS_M",
    "AreaTooLargeError",
    "BoundingBox",
    "Coordinate",
    "NoRouteFoundError",
    "NodeId",
    "ProviderUnavailableError",
    "RouteResult",
    "RoutingError",
    "SnapDistanceError",
    "haversine_m",
]
