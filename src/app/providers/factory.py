"""Fábrica de proveedores concretos."""

from __future__ import annotations

from app.config import Settings
from app.providers.base import GraphProvider
from app.providers.osmnx_provider import OsmnxProvider
from app.providers.overpass_provider import OverpassProvider
from app.services.cache import GraphCache


class GraphProviderFactory:
    """Crea el proveedor solicitado sin filtrar la clase concreta a la UI."""

    @classmethod
    def create(
        cls,
        name: str,
        cache: GraphCache,
        settings: Settings,
    ) -> GraphProvider:
        """Devuelve el proveedor configurado."""
        normalized = name.strip().lower()
        if normalized == "osmnx":
            return OsmnxProvider(
                cache,
                network_type=settings.network_type,
                use_cache=settings.use_cache,
                user_agent=settings.user_agent,
                requests_timeout_s=settings.overpass_timeout_s,
                retries=settings.overpass_retries,
            )
        if normalized == "overpass":
            return OverpassProvider(
                cache,
                overpass_url=settings.overpass_url,
                timeout_s=settings.overpass_timeout_s,
                retries=settings.overpass_retries,
                user_agent=settings.user_agent,
            )
        raise ValueError("Proveedor no soportado. Usa 'osmnx' o 'overpass'.")
