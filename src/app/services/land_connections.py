"""Comprobación geográfica previa a la descarga de la red ciclista."""

from __future__ import annotations

import gzip
import json
from functools import cache
from importlib.resources import files

from networkx.utils import UnionFind
from shapely import LineString, Point, STRtree, get_parts, make_valid
from shapely.affinity import translate
from shapely.geometry import shape

from app.domain.exceptions import NoRouteFoundError
from app.domain.models import Coordinate

# La costa generalizada puede separar puntos cercanos unidos por puentes o túneles.
_COASTAL_GAP_DEGREES = 0.38
_COAST_TOLERANCE_DEGREES = 0.10
# Franja sin conexión vial entre Panamá y Colombia. Los puntos de la franja
# quedan sin clasificar y se resuelven con la red local.
_DARIEN_GAP = LineString([(-78.5, 9.7), (-77.5, 8.7), (-77.9, 7.0)]).buffer(0.30)


@cache
def _land_index() -> tuple[STRtree, tuple[int, ...]]:
    data = files(__package__).joinpath("natural_earth_land.geojson.gz").read_bytes()
    land = json.loads(gzip.decompress(data))
    polygons = []
    for feature in land["features"]:
        geometry = make_valid(shape(feature["geometry"]))
        if geometry.intersects(_DARIEN_GAP):
            geometry = geometry.difference(_DARIEN_GAP)
        polygons.extend(part for part in get_parts(geometry) if part.geom_type == "Polygon")

    ids = list(range(len(polygons)))
    for index, polygon in enumerate(polygons.copy()):
        west, _, east, _ = polygon.bounds
        # Las copias permiten unir y consultar los dos lados del antimeridiano.
        if west <= -180 + _COASTAL_GAP_DEGREES:
            polygons.append(translate(polygon, xoff=360))
            ids.append(index)
        if east >= 180 - _COASTAL_GAP_DEGREES:
            polygons.append(translate(polygon, xoff=-360))
            ids.append(index)

    tree = STRtree(polygons)
    groups = UnionFind(ids)
    for left, right in tree.query(
        polygons, predicate="dwithin", distance=_COASTAL_GAP_DEGREES
    ).T:
        if left < right:
            groups.union(ids[left], ids[right])
    return tree, tuple(groups[index] for index in ids)


def _land_group(coordinate: Coordinate) -> int | None:
    tree, groups = _land_index()
    point = Point(coordinate.lon, coordinate.lat)
    if _DARIEN_GAP.covers(point):
        return None
    candidates = {
        groups[index]
        for index in tree.query(point, predicate="dwithin", distance=_COAST_TOLERANCE_DEGREES)
    }
    return next(iter(candidates)) if len(candidates) == 1 else None


def check_land_route(origin: Coordinate, dest: Coordinate) -> None:
    """Avisa cuando ambas coordenadas caen en zonas terrestres desconectadas."""
    start = _land_group(origin)
    end = _land_group(dest)
    if start is None or end is None or start == end:
        return

    americas = {_land_group(Coordinate(39, -100)), _land_group(Coordinate(-12, -77))}
    if {start, end} == americas:
        reason = "No hay una conexión vial entre Panamá y Colombia a través del Darién."
    else:
        reason = "Los puntos están en zonas terrestres separadas por agua."
    raise NoRouteFoundError(f"No existe una ruta por tierra entre el origen y el destino. {reason}")
