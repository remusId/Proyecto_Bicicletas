"""Excepciones propias del dominio de routing."""

from __future__ import annotations


class RoutingError(Exception):
    """Error base de la aplicación de rutas."""

    diagnostic: str | None = None


class NoRouteFoundError(RoutingError):
    """No existe un camino entre el origen y el destino."""


class AreaTooLargeError(RoutingError):
    """El área solicitada supera el límite configurado."""


class ProviderUnavailableError(RoutingError):
    """El proveedor de datos no está disponible o devolvió datos inválidos."""


class EmptyGraphError(ProviderUnavailableError):
    """La descarga no contiene red vial utilizable."""

    diagnostic = "El grafo está vacío. Amplía el margen o elige otra zona."


class SnapDistanceError(RoutingError):
    """Un punto está demasiado lejos de la red ciclable."""
