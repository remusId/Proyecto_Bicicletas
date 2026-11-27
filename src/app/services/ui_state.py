"""Estado de la vista del mapa y escritura atómica de archivos JSON."""

import json
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
