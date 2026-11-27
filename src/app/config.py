"""Configuración validada de la aplicación."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.domain.exceptions import AreaTooLargeError
from app.domain.models import BoundingBox, Coordinate

DEFAULT_USER_AGENT = "RutasCiclistas/0.1 (configura OSM_USER_AGENT con un contacto identificable)"
OVERPASS_MIRRORS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.nextgis.com/api/interpreter",
)
_MAX_LOCAL_AREA_KM2 = 2500
_MAX_LOCAL_SPAN_KM = 250


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
    default_center: Coordinate = field(
        default_factory=lambda: Coordinate(lat=-12.0464, lon=-77.0428)
    )
    map_zoom: int = 14
    overpass_urls: tuple[str, ...] = ()
    overpass_deadline_s: float = 90.0

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
        if not math.isfinite(self.overpass_deadline_s) or self.overpass_deadline_s <= 0:
            raise ValueError("El plazo total de Overpass debe ser finito y mayor que cero.")
        if not 1 <= self.overpass_retries <= 3:
            raise ValueError("Overpass admite entre 1 y 3 intentos.")
        if not self.user_agent.strip():
            raise ValueError("El User-Agent debe ser identificable y no vacío.")
        if self.map_zoom < 1:
            raise ValueError("El zoom del mapa debe ser positivo.")
        object.__setattr__(self, "cache_dir", Path(self.cache_dir))

    def with_area_for(self, origin: Coordinate, dest: Coordinate) -> Settings:
        """Ajusta el área de descarga para una solicitud de alcance local."""
        bbox = BoundingBox.from_points(origin, dest, self.margin_m)
        area = bbox.area_km2
        span = max(bbox.width_m, bbox.height_m) / 1000
        if area > _MAX_LOCAL_AREA_KM2 or span > _MAX_LOCAL_SPAN_KM:
            area_label = f"{area:,.0f}".replace(",", " ")
            raise AreaTooLargeError(
                f"Esta ruta requiere descargar {area_label} km² de mapa "
                f"y el área mide {span:.0f} km de lado mayor. "
                f"La app admite descargas locales de hasta {_MAX_LOCAL_AREA_KM2} km² "
                f"y {_MAX_LOCAL_SPAN_KM} km por lado. "
                "Acerca los puntos o calcula el recorrido por tramos."
            )
        if area <= self.max_area_km2:
            return self
        return replace(self, max_area_km2=area)

    @classmethod
    def from_env(cls) -> Settings:
        """Crea la configuración leyendo variables de entorno opcionales."""
        defaults = cls()
        provider = os.getenv("APP_PROVIDER", defaults.provider)
        profile = os.getenv("APP_PROFILE", defaults.profile)
        algorithm = os.getenv("APP_ALGORITHM", defaults.algorithm)
        max_snap_raw = os.getenv("APP_MAX_SNAP_M")
        max_snap_m = defaults.max_snap_m if max_snap_raw is None else float(max_snap_raw)
        single_url = os.getenv("OVERPASS_URL")
        raw_urls = os.getenv("APP_OVERPASS_URLS")
        urls = tuple(url.strip() for url in raw_urls.split(",") if url.strip()) if raw_urls else ()
        if not urls:
            urls = (single_url,) if single_url else (defaults.overpass_url, *OVERPASS_MIRRORS)
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
            overpass_url=urls[0],
            overpass_urls=urls,
            overpass_deadline_s=_env_float("APP_OVERPASS_DEADLINE_S", defaults.overpass_deadline_s),
            overpass_timeout_s=_env_float("OVERPASS_TIMEOUT_S", defaults.overpass_timeout_s),
            overpass_retries=_env_int("OVERPASS_RETRIES", defaults.overpass_retries),
            user_agent=os.getenv("OSM_USER_AGENT", defaults.user_agent),
            default_center=Coordinate(
                lat=_env_float("APP_DEFAULT_LAT", defaults.default_center.lat),
                lon=_env_float("APP_DEFAULT_LON", defaults.default_center.lon),
            ),
            map_zoom=_env_int("APP_MAP_ZOOM", defaults.map_zoom),
        )
