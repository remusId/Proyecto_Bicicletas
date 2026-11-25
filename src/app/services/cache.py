"""Caché en disco de grafos descargados."""

from __future__ import annotations

import hashlib
import os
import pickle
import re
import stat
import tempfile
import time
from contextlib import suppress
from pathlib import Path

import networkx as nx

from app.domain.models import BoundingBox

GRAPH_TTL_S = 14 * 24 * 3600
GRAPH_CACHE_LIMIT_BYTES = 150 * 1024**2
_GRAPH_NAME = re.compile(r"(?:osmnx|overpass)_[\w.-]+_.+_[a-f0-9]{12}\.pkl")
_OSMNX_NAME = re.compile(r"[a-f0-9]{40}\.json")


class GraphCache:
    """Caché de grafos por bbox redondeada, backend y perfil."""

    def __init__(self, directory: Path, enabled: bool = True) -> None:
        self._directory = Path(directory)
        self._enabled = bool(enabled)
        if self._enabled:
            self._directory.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        """Directorio donde se guardan los grafos."""
        return self._directory

    @property
    def enabled(self) -> bool:
        """Indica si la caché está activa."""
        return self._enabled

    def key(
        self,
        bbox: BoundingBox,
        backend: str,
        profile: str,
        extra: str = "",
    ) -> str:
        """Construye una clave estable para la bbox, backend y perfil."""
        raw = f"{bbox.cache_token()}|{backend}|{profile}|{extra}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        safe_backend = re.sub(r"[^A-Za-z0-9_.-]", "_", backend)
        safe_profile = re.sub(r"[^A-Za-z0-9_.-]", "_", profile)
        return f"{safe_backend}_{safe_profile}_{bbox.cache_token()}_{digest}"

    def load(self, key: str) -> nx.MultiDiGraph | None:
        """Carga un grafo de la caché o devuelve ``None``."""
        if not self._enabled:
            return None
        path = self._path_for(key)
        try:
            if path.stat().st_mtime <= time.time() - GRAPH_TTL_S:
                path.unlink(missing_ok=True)
                return None
            with path.open("rb") as handle:
                graph = pickle.load(handle)  # noqa: S301 - caché local propia
        except (OSError, EOFError, pickle.PickleError, AttributeError, ImportError):
            return None
        if not isinstance(graph, nx.MultiDiGraph):
            return None
        return graph

    def save(self, key: str, graph: nx.MultiDiGraph) -> None:
        """Guarda un grafo de forma atómica."""
        if not self._enabled:
            return
        if not isinstance(graph, nx.MultiDiGraph):
            raise ValueError("Solo se pueden cachear objetos MultiDiGraph.")
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path_for(key)
        fd, temp_name = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=self._directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                pickle.dump(graph, handle, protocol=pickle.HIGHEST_PROTOCOL)
            Path(temp_name).replace(path)
        finally:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
        self.prune()

    def clear(self) -> int:
        """Elimina los grafos y descargas de OSMnx reconocidos."""
        return self._prune(max_bytes=0, cutoff=float("inf"))

    def prune(self) -> int:
        """Elimina archivos vencidos y luego los más antiguos hasta respetar la cuota."""
        return self._prune(GRAPH_CACHE_LIMIT_BYTES, time.time() - GRAPH_TTL_S)

    def _prune(self, max_bytes: int, cutoff: float) -> int:
        try:
            if not _cache_folder(self._directory):
                return 0
        except OSError:
            return 0
        entries = []
        for folder, pattern in (
            (self._directory, _GRAPH_NAME),
            (self._directory / "osmnx", _OSMNX_NAME),
        ):
            with suppress(OSError):
                if not _cache_folder(folder):
                    continue
                for path in folder.iterdir():
                    if pattern.fullmatch(path.name):
                        with suppress(OSError):
                            info = path.lstat()
                            if stat.S_ISREG(info.st_mode):
                                entries.append((info.st_mtime, info.st_size, path))
        total = sum(size for _, size, _ in entries)
        removed = 0
        for age, size, path in sorted(entries):
            if age > cutoff and total <= max_bytes:
                break
            with suppress(OSError):
                current = path.lstat()
                if current.st_mtime == age and current.st_size == size:
                    path.unlink()
                    total -= size
                    removed += 1
        return removed

    def _path_for(self, key: str) -> Path:
        return self._directory / f"{key}.pkl"


def _cache_folder(path: Path) -> bool:
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISDIR(info.st_mode) and not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
