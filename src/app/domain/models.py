"""Dominio del proyecto: coordenadas, cajas geográficas y resultados."""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, degrees, isfinite, radians, sin, sqrt
from typing import Any

EARTH_RADIUS_M = 6_371_008.8
NodeId = int | str


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Devuelve la distancia haversine entre dos puntos en metros."""
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * asin(sqrt(min(1.0, max(0.0, a))))


@dataclass(frozen=True, slots=True)
class Coordinate:
    """Punto geográfico validado en grados WGS84."""

    lat: float
    lon: float

    def __post_init__(self) -> None:
        try:
            lat = float(self.lat)
            lon = float(self.lon)
        except (TypeError, ValueError) as exc:
            raise ValueError("La latitud y la longitud deben ser numéricas.") from exc
        if not isfinite(lat) or not isfinite(lon):
            raise ValueError("La latitud y la longitud deben ser finitas.")
        if not -90.0 <= lat <= 90.0:
            raise ValueError("La latitud debe estar entre -90 y 90.")
        if not -180.0 <= lon <= 180.0:
            raise ValueError("La longitud debe estar entre -180 y 180.")
        object.__setattr__(self, "lat", lat)
        object.__setattr__(self, "lon", lon)

    @classmethod
    def from_string(cls, value: str) -> Coordinate:
        """Convierte ``"lat,lon"`` en una coordenada validada."""
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 2:
            raise ValueError("El formato debe ser LAT,LON (por ejemplo 40.4168,-3.7038).")
        try:
            return cls(float(parts[0]), float(parts[1]))
        except ValueError as exc:
            raise ValueError("Las coordenadas deben ser números separados por una coma.") from exc

    def as_tuple(self) -> tuple[float, float]:
        """Devuelve ``(lat, lon)``."""
        return (self.lat, self.lon)

    def distance_to(self, other: Coordinate) -> float:
        """Distancia haversine a otro punto, en metros."""
        return haversine_m(self.lat, self.lon, other.lat, other.lon)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Caja geográfica con límites sur, oeste, norte y este."""

    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        values = (self.south, self.west, self.north, self.east)
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("Los límites de la caja deben ser finitos.")
        if not -90.0 <= self.south < self.north <= 90.0:
            raise ValueError("La caja debe cumplir -90 <= sur < norte <= 90.")
        if not -180.0 <= self.west < self.east <= 180.0:
            raise ValueError("La caja debe cumplir -180 <= oeste < este <= 180.")

    @classmethod
    def from_points(
        cls,
        first: Coordinate,
        second: Coordinate,
        margin_m: float = 1000.0,
    ) -> BoundingBox:
        """Crea una caja que contiene ambos puntos más un margen en metros."""
        if not isfinite(margin_m) or margin_m < 0.0:
            raise ValueError("El margen debe ser un número no negativo.")

        min_lat = min(first.lat, second.lat)
        max_lat = max(first.lat, second.lat)
        min_lon = min(first.lon, second.lon)
        max_lon = max(first.lon, second.lon)

        mid_lat = radians((min_lat + max_lat) / 2.0)
        lat_pad = degrees(margin_m / EARTH_RADIUS_M)
        lon_pad = degrees(margin_m / (EARTH_RADIUS_M * max(cos(mid_lat), 1e-6)))

        south = max(-90.0, min_lat - lat_pad)
        north = min(90.0, max_lat + lat_pad)
        west = min_lon - lon_pad
        east = max_lon + lon_pad
        if west < -180.0 or east > 180.0:
            raise ValueError("El área cruza el meridiano 180; elige puntos más cercanos.")
        return cls(south=south, west=west, north=north, east=east)

    @property
    def width_m(self) -> float:
        """Ancho aproximado de la caja en metros."""
        mid_lat = (self.south + self.north) / 2.0
        return haversine_m(mid_lat, self.west, mid_lat, self.east)

    @property
    def height_m(self) -> float:
        """Alto aproximado de la caja en metros."""
        mid_lon = (self.west + self.east) / 2.0
        return haversine_m(self.south, mid_lon, self.north, mid_lon)

    @property
    def area_m2(self) -> float:
        """Área aproximada de la caja en metros cuadrados."""
        return self.width_m * self.height_m

    @property
    def area_km2(self) -> float:
        """Área aproximada de la caja en kilómetros cuadrados."""
        return self.area_m2 / 1_000_000.0

    @property
    def center(self) -> Coordinate:
        """Centro geográfico de la caja."""
        return Coordinate(
            lat=(self.south + self.north) / 2.0,
            lon=(self.west + self.east) / 2.0,
        )

    def to_osmnx_tuple(self) -> tuple[float, float, float, float]:
        """Devuelve ``(oeste, sur, este, norte)`` para OSMnx/Overpass."""
        return (self.west, self.south, self.east, self.north)

    def cache_token(self, precision: int = 5) -> str:
        """Token estable de la caja redondeada para la caché."""
        return (
            f"{self.south:.{precision}f}_{self.west:.{precision}f}_"
            f"{self.north:.{precision}f}_{self.east:.{precision}f}"
        )


@dataclass(frozen=True, slots=True)
class RouteResult:
    """Resultado inmutable de una planificación de ruta."""

    nodes: tuple[NodeId, ...]
    distance_m: float
    duration_s: float
    nodes_expanded: int
    backend: str
    profile: str
    algorithm: str
    snap_origin_m: float
    snap_dest_m: float
    geometry: tuple[Coordinate, ...] = ()
    warnings: tuple[str, ...] = ()
    bbox: BoundingBox | None = None
    weighted_cost: float | None = None
    compute_time_s: float = 0.0
    graph: Any = None
    origin_node: NodeId | None = None
    dest_node: NodeId | None = None

    def __post_init__(self) -> None:
        if self.distance_m < 0.0 or self.duration_s < 0.0:
            raise ValueError("La distancia y la duración no pueden ser negativas.")
        if self.nodes_expanded < 0:
            raise ValueError("El número de nodos expandidos no puede ser negativo.")
        if self.compute_time_s < 0.0:
            raise ValueError("El tiempo de cómputo no puede ser negativo.")

    @property
    def distance_km(self) -> float:
        """Distancia total en kilómetros."""
        return self.distance_m / 1000.0

    @property
    def duration_min(self) -> float:
        """Duración estimada en minutos."""
        return self.duration_s / 60.0

    @property
    def duration_h(self) -> float:
        """Duración estimada en horas."""
        return self.duration_s / 3600.0

    def as_summary(self) -> dict[str, Any]:
        """Resumen serializable para CLI y UI."""
        return {
            "nodes": list(self.nodes),
            "distance_km": round(self.distance_km, 3),
            "duration_min": round(self.duration_min, 1),
            "nodes_expanded": self.nodes_expanded,
            "backend": self.backend,
            "profile": self.profile,
            "algorithm": self.algorithm,
            "snap_origin_m": round(self.snap_origin_m, 1),
            "snap_dest_m": round(self.snap_dest_m, 1),
            "compute_time_s": round(self.compute_time_s, 4),
            "warnings": list(self.warnings),
        }
