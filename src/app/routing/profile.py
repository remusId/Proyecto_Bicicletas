"""Perfiles de coste para el routing ciclista."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any


def _tag_text(value: Any) -> str:
    """Normaliza un valor de etiqueta OSM, incluidas listas de valores."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value).strip().lower()


def _edge_length(edge_data: Mapping[str, Any]) -> float:
    """Longitud de la arista en metros, o infinito si falta."""
    raw = edge_data.get("length")
    try:
        length = float(raw)
    except (TypeError, ValueError):
        return math.inf
    if not math.isfinite(length) or length < 0.0:
        return math.inf
    return length


class CostProfile(ABC):
    """Perfil abstracto que traduce atributos OSM a un coste en metros."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador del perfil."""

    @abstractmethod
    def edge_cost(self, edge_data: Mapping[str, Any]) -> float:
        """Coste de una arista; ``inf`` significa no transitable."""

    @abstractmethod
    def heuristic_scale(self) -> float:
        """Multiplicador mínimo del perfil para una heurística admisible."""


class ShortestProfile(CostProfile):
    """Ruta más corta: coste igual a la longitud, con vías prohibidas excluidas."""

    DEFAULT_EXCLUDED_HIGHWAYS = frozenset(
        {
            "motorway",
            "motorway_link",
            "trunk",
            "trunk_link",
            "steps",
            "construction",
            "proposed",
            "raceway",
            "bus_guideway",
            "corridor",
            "elevator",
            "escalator",
            "platform",
        }
    )

    def __init__(self, excluded_highways: Iterable[str] | None = None) -> None:
        excluded = (
            self.DEFAULT_EXCLUDED_HIGHWAYS if excluded_highways is None else excluded_highways
        )
        self._excluded = frozenset(_tag_text(item) for item in excluded)

    @property
    def name(self) -> str:
        """Identificador del perfil."""
        return "shortest"

    def edge_cost(self, edge_data: Mapping[str, Any]) -> float:
        """Devuelve la longitud si la vía es ciclable."""
        if self._forbidden(edge_data):
            return math.inf
        return _edge_length(edge_data)

    def heuristic_scale(self) -> float:
        """La heurística haversine no se escala en el modo más corto."""
        return 1.0

    def _forbidden(self, edge_data: Mapping[str, Any]) -> bool:
        highway = _tag_text(edge_data.get("highway"))
        bicycle = _tag_text(edge_data.get("bicycle"))
        access = _tag_text(edge_data.get("access"))
        if highway in self._excluded:
            return True
        if bicycle == "no":
            return True
        return access in {"no", "private"} and bicycle != "yes"


class BikeFriendlyProfile(CostProfile):
    """Perfil ciclista con multiplicadores por tipo de vía."""

    DEFAULT_MULTIPLIERS: Mapping[str, float] = MappingProxyType(
        {
            "cycleway": 1.00,
            "living_street": 1.05,
            "residential": 1.08,
            "unclassified": 1.10,
            "service": 1.12,
            "track": 1.15,
            "path": 1.20,
            "pedestrian": 1.25,
            "tertiary": 1.20,
            "tertiary_link": 1.20,
            "secondary": 1.35,
            "secondary_link": 1.35,
            "primary": 1.55,
            "primary_link": 1.55,
            "road": 1.30,
            "_default": 1.30,
        }
    )
    DEFAULT_EXCLUDED_HIGHWAYS = ShortestProfile.DEFAULT_EXCLUDED_HIGHWAYS

    def __init__(
        self,
        multipliers: Mapping[str, float] | None = None,
        excluded_highways: Iterable[str] | None = None,
    ) -> None:
        merged = dict(self.DEFAULT_MULTIPLIERS)
        if multipliers is not None:
            merged.update({_tag_text(key): float(value) for key, value in multipliers.items()})
        for key, value in merged.items():
            if not math.isfinite(value) or value < 1.0:
                raise ValueError(
                    f"El multiplicador de '{key}' debe ser >= 1 para mantener "
                    "la heurística admisible."
                )
        excluded = (
            self.DEFAULT_EXCLUDED_HIGHWAYS if excluded_highways is None else excluded_highways
        )
        self._multipliers = merged
        self._excluded = frozenset(_tag_text(item) for item in excluded)

    @property
    def name(self) -> str:
        """Identificador del perfil."""
        return "bike"

    @property
    def multipliers(self) -> Mapping[str, float]:
        """Copia de solo lectura de los multiplicadores activos."""
        return MappingProxyType(self._multipliers)

    def edge_cost(self, edge_data: Mapping[str, Any]) -> float:
        """Aplica el multiplicador del tipo de vía a la longitud."""
        if self._forbidden(edge_data):
            return math.inf
        length = _edge_length(edge_data)
        if not math.isfinite(length):
            return math.inf
        highway = _tag_text(edge_data.get("highway"))
        multiplier = self._multipliers.get(highway, self._multipliers["_default"])
        return length * multiplier

    def heuristic_scale(self) -> float:
        """Mínimo multiplicador finito; nunca menor que 1."""
        finite = [value for value in self._multipliers.values() if math.isfinite(value)]
        return max(1.0, min(finite))

    def _forbidden(self, edge_data: Mapping[str, Any]) -> bool:
        highway = _tag_text(edge_data.get("highway"))
        bicycle = _tag_text(edge_data.get("bicycle"))
        access = _tag_text(edge_data.get("access"))
        if highway in self._excluded:
            return True
        if bicycle == "no":
            return True
        return access in {"no", "private"} and bicycle != "yes"


def profile_from_name(name: str) -> CostProfile:
    """Crea el perfil solicitado por nombre."""
    normalized = name.strip().lower()
    if normalized in {"bike", "ciclable", "bici"}:
        return BikeFriendlyProfile()
    if normalized in {"shortest", "short", "corta", "corto"}:
        return ShortestProfile()
    raise ValueError("Perfil no soportado. Usa 'bike' o 'shortest'.")


__all__ = [
    "BikeFriendlyProfile",
    "CostProfile",
    "ShortestProfile",
    "profile_from_name",
]
