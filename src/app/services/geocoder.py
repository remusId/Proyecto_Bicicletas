"""Búsquedas explícitas y cacheadas con Nominatim."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import requests

from app.domain.exceptions import ProviderUnavailableError
from app.domain.models import Coordinate
from app.services.ui_state import write_json

TTL_S = 7 * 24 * 3600
MAX_ENTRIES = 250


@contextmanager
def _local_lock(path: Path):
    """Serializa la CLI y las sesiones web que comparten la caché."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
            yield


@dataclass(frozen=True)
class Place:
    name: str
    coordinate: Coordinate

    @property
    def latlon(self) -> str:
        return f"{self.coordinate.lat},{self.coordinate.lon}"


class NominatimGeocoder:
    def __init__(self, user_agent: str, cache_path: Path | None = None) -> None:
        if not user_agent.strip():
            raise ValueError("Configura un User-Agent identificable para Nominatim.")
        self._user_agent = user_agent
        self._path = cache_path or Path(os.getenv("APP_GEOCODE_CACHE", ".cache/geocode.json"))
        self._url = os.getenv("APP_NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")

    def search(self, query: str) -> tuple[Place, ...]:
        query = " ".join(query.split())
        if not query:
            raise ValueError("Escribe un nombre de lugar para buscar.")
        key = f"{self._url} {query.casefold()}"
        try:
            with _local_lock(self._path.with_suffix(".lock")):
                data = self._read()
                entries = data.get("entries", {})
                if not isinstance(entries, dict):
                    entries = {}
                now = time.time()
                for name, record in list(entries.items()):
                    try:
                        if 0 <= now - float(record["at"]) < TTL_S:
                            continue
                    except (ValueError, TypeError, KeyError):
                        pass
                    del entries[name]
                if key in entries:
                    try:
                        return self._parse(entries[key]["results"])
                    except (ValueError, TypeError, KeyError):
                        pass
                last = data.get("last")
                if isinstance(last, (int, float)) and 0 <= now - last < 1:
                    time.sleep(1 - (now - last))
                data = {"last": time.time(), "entries": entries}
                write_json(self._path, data)
                payload = self._request(query)
                results = self._parse(payload)
                entries[key] = {"at": time.time(), "results": payload}
                if len(entries) > MAX_ENTRIES:
                    oldest = min(entries, key=lambda name: float(entries[name]["at"]))
                    del entries[oldest]
                write_json(self._path, data)
                return results
        except OSError as exc:
            raise ProviderUnavailableError(
                "No se pudo acceder a la caché de búsqueda local."
            ) from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise ProviderUnavailableError("Nominatim devolvió resultados inválidos.") from exc

    def clear_cache(self) -> None:
        """Borra las búsquedas guardadas y conserva el límite de frecuencia."""
        with _local_lock(self._path.with_suffix(".lock")):
            data = self._read()
            if data:
                write_json(self._path, {"last": data.get("last"), "entries": {}})

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _request(self, query: str) -> object:
        try:
            response = requests.get(
                self._url,
                params={"q": query, "format": "jsonv2", "limit": 5, "accept-language": "es"},
                headers={"User-Agent": self._user_agent},
                timeout=8,
            )
        except requests.RequestException as exc:
            raise ProviderUnavailableError(
                "No se pudo conectar con Nominatim. Revisa tu conexión o usa coordenadas."
            ) from exc
        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"Nominatim respondió con HTTP {response.status_code}. "
                "Intenta en unos minutos o usa coordenadas."
            )
        return response.json()

    @staticmethod
    def _parse(payload: object) -> tuple[Place, ...]:
        if not isinstance(payload, list):
            raise ValueError("Se esperaba una lista de resultados.")
        return tuple(
            Place(str(row["display_name"]), Coordinate(row["lat"], row["lon"]))
            for row in payload[:5]
        )
