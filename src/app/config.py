"""Configuración validada de la aplicación."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.models import Coordinate

DEFAULT_USER_AGENT = (
    "ProyectoFinalPOO/0.1 (proyecto académico; "
    "configura OSM_USER_AGENT con un contacto identificable)"
)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Parámetros de ejecución de la aplicación."""

    provider: str = "osmnx"
    profile: str = "bike"
    algorithm: str = "astar"
    margin_m: float = 1000.0
    max_area_km2: float = 25.0
    snap_warning_m: float = 200.0
    max_snap_m: float | None = None
    bike_speed_kmh: float = 15.0
    cache_dir: Path = Path(".cache/graphs")
    use_cache: bool = True
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout_s: float = 60.0
    overpass_retries: int = 3
    user_agent: str = DEFAULT_USER_AGENT
    network_type: str = "bike"
    default_center: Coordinate = field(default_factory=lambda: Coordinate(lat=40.4168, lon=-3.7038))
    map_zoom: int = 14

    def __post_init__(self) -> None:
        if self.provider not in {"osmnx", "overpass"}:
            raise ValueError("El proveedor debe ser 'osmnx' o 'overpass'.")
        if self.profile not in {"bike", "shortest"}:
            raise ValueError("El perfil debe ser 'bike' o 'shortest'.")
        if self.algorithm not in {"astar", "dijkstra"}:
            raise ValueError("El algoritmo debe ser 'astar' o 'dijkstra'.")
        if self.margin_m < 0.0:
            raise ValueError("El margen no puede ser negativo.")
        if self.max_area_km2 <= 0.0:
            raise ValueError("El área máxima debe ser mayor que cero.")
        if self.snap_warning_m < 0.0:
            raise ValueError("El umbral de aviso de snap no puede ser negativo.")
        if self.max_snap_m is not None and self.max_snap_m <= 0.0:
            raise ValueError("El snap máximo debe ser mayor que cero.")
        if self.bike_speed_kmh <= 0.0:
            raise ValueError("La velocidad media debe ser mayor que cero.")
        if self.overpass_timeout_s <= 0.0:
            raise ValueError("El timeout de Overpass debe ser mayor que cero.")
        if not 1 <= self.overpass_retries <= 3:
            raise ValueError("Overpass admite entre 1 y 3 intentos.")
        if not self.user_agent.strip():
            raise ValueError("El User-Agent debe ser identificable y no vacío.")
        if self.map_zoom < 1:
            raise ValueError("El zoom del mapa debe ser positivo.")
        object.__setattr__(self, "cache_dir", Path(self.cache_dir))

    @classmethod
    def from_env(cls) -> Settings:
        """Crea la configuración leyendo variables de entorno opcionales."""
        defaults = cls()
        provider = os.getenv("APP_PROVIDER", defaults.provider)
        profile = os.getenv("APP_PROFILE", defaults.profile)
        algorithm = os.getenv("APP_ALGORITHM", defaults.algorithm)
        max_snap_raw = os.getenv("APP_MAX_SNAP_M")
        max_snap_m = defaults.max_snap_m if max_snap_raw is None else float(max_snap_raw)
        return cls(
            provider=provider,
            profile=profile,
            algorithm=algorithm,
            margin_m=_env_float("APP_MARGIN_M", defaults.margin_m),
            max_area_km2=_env_float("APP_MAX_AREA_KM2", defaults.max_area_km2),
            snap_warning_m=_env_float("APP_SNAP_WARNING_M", defaults.snap_warning_m),
            max_snap_m=max_snap_m,
            bike_speed_kmh=_env_float("APP_BIKE_SPEED_KMH", defaults.bike_speed_kmh),
            cache_dir=Path(os.getenv("APP_CACHE_DIR", str(defaults.cache_dir))),
            use_cache=_env_bool("APP_USE_CACHE", defaults.use_cache),
            overpass_url=os.getenv("OVERPASS_URL", defaults.overpass_url),
            overpass_timeout_s=_env_float("OVERPASS_TIMEOUT_S", defaults.overpass_timeout_s),
            overpass_retries=_env_int("OVERPASS_RETRIES", defaults.overpass_retries),
            user_agent=os.getenv("OSM_USER_AGENT", defaults.user_agent),
            default_center=Coordinate(
                lat=_env_float("APP_DEFAULT_LAT", defaults.default_center.lat),
                lon=_env_float("APP_DEFAULT_LON", defaults.default_center.lon),
            ),
            map_zoom=_env_int("APP_MAP_ZOOM", defaults.map_zoom),
        )
