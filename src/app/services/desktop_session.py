"""Control de cierre compartido por el lanzador y la interfaz de escritorio."""

from collections.abc import Callable

shutdown: Callable[[], None] | None = None
