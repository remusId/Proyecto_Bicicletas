"""Persistencia local de la vista del mapa."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.domain.models import Coordinate


def write_json(path: Path, data: object) -> None:
    """Publica un JSON completo incluso si dos sesiones guardan a la vez."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        staged = Path(temporary.name)
        try:
            json.dump(data, temporary, ensure_ascii=False, allow_nan=False)
            temporary.close()
            staged.replace(path)
        finally:
            temporary.close()
            staged.unlink(missing_ok=True)


@dataclass(frozen=True)
class MapView:
    center: Coordinate
    zoom: int

    def __post_init__(self) -> None:
        if type(self.zoom) is not int or not 1 <= self.zoom <= 19:
            raise ValueError("El zoom debe ser un entero entre 1 y 19.")


class ViewStore:
    def __init__(self, path: Path | None = None) -> None:
        local = os.getenv("LOCALAPPDATA")
        default = (
            Path(local) / "RutasCiclistas" if local else Path.home() / ".config/rutas-ciclistas"
        )
        self.path = path or Path(os.getenv("APP_UI_STATE", str(default / "ui_state.json")))

    def load(self, fallback: MapView) -> MapView:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return MapView(Coordinate(data["lat"], data["lon"]), data["zoom"])
        except (OSError, ValueError, TypeError, KeyError):
            return fallback

    def save(self, view: MapView) -> None:
        write_json(self.path, {"lat": view.center.lat, "lon": view.center.lon, "zoom": view.zoom})
