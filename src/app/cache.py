"""Acceso directo a la caché de grafos.

La implementación vive en ``app.services.cache`` para mantener la separación
entre dominio, servicios y proveedores. Este módulo conserva el punto de
entrada ``app.cache`` indicado en la estructura del proyecto.
"""

from app.services.cache import GraphCache

__all__ = ["GraphCache"]
