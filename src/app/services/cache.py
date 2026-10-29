"""Caché en disco de grafos descargados."""

from __future__ import annotations

import hashlib
import os
import pickle
import re
import tempfile
from pathlib import Path

import networkx as nx

from app.domain.models import BoundingBox


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
        if not path.exists():
            return None
        try:
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

    def clear(self) -> None:
        """Elimina los grafos almacenados."""
        if not self._directory.exists():
            return
        for path in self._directory.glob("*.pkl"):
            path.unlink(missing_ok=True)

    def _path_for(self, key: str) -> Path:
        return self._directory / f"{key}.pkl"
