"""Descarga manual de un grafo y lo guarda en la caché de la aplicación.

La clave de caché depende de la bbox (origen, destino y margen), del backend y
del perfil. Para que la UI o la CLI reutilicen el grafo sin volver a descargar,
usa exactamente el mismo origen, destino, margen y perfil.

Ejemplos
--------
Descarga directa con Overpass:

    python scripts/descargar_grafo.py \
        --origin 40.4168,-3.7038 --dest 40.4210,-3.6990 --margin-km 0.25

Usar un JSON exportado de Overpass Turbo (Export > Data > raw data):

    python scripts/descargar_grafo.py \
        --origin 40.4168,-3.7038 --dest 40.4210,-3.6990 \
        --json datos_overpass.json

Usar un XML de OSM (Overpass Turbo > Export > Data > raw OSM data):

    python scripts/descargar_grafo.py \
        --origin 40.4168,-3.7038 --dest 40.4210,-3.6990 \
        --xml datos.osm
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import networkx as nx
import osmnx as ox

from app.config import Settings
from app.domain.models import BoundingBox, Coordinate
from app.providers.factory import GraphProviderFactory
from app.providers.osmnx_provider import OsmnxProvider
from app.providers.overpass_provider import parse_overpass_payload
from app.services.cache import GraphCache


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descarga un grafo de OpenStreetMap y lo guarda en la caché.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--origin", required=True, help="Origen LAT,LON")
    parser.add_argument("--dest", required=True, help="Destino LAT,LON")
    parser.add_argument(
        "--provider",
        choices=["overpass", "osmnx"],
        default="overpass",
        help="Backend de descarga si no se usa --json/--xml",
    )
    parser.add_argument(
        "--profile",
        choices=["bike", "shortest"],
        default="bike",
        help="Perfil con el que se guardará la entrada de caché",
    )
    parser.add_argument(
        "--profiles",
        default=None,
        help="Perfiles separados por coma para guardar la misma descarga (bike,shortest)",
    )
    parser.add_argument(
        "--margin-km",
        type=float,
        default=1.0,
        help="Margen alrededor de los puntos",
    )
    parser.add_argument(
        "--cache-dir",
        default=".cache/graphs",
        help="Directorio de la caché de la aplicación",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="JSON exportado de Overpass (se guarda como backend overpass)",
    )
    parser.add_argument(
        "--xml",
        type=Path,
        help="XML de OSM (se guarda como backend osmnx)",
    )
    parser.add_argument(
        "--overpass-url",
        default="https://overpass-api.de/api/interpreter",
        help="Endpoint de Overpass para la descarga directa",
    )
    parser.add_argument(
        "--user-agent",
        default="ProyectoFinalPOO-Manual/1.0 (configura un contacto identificable)",
        help="User-Agent identificable",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Permite áreas mayores que el límite de la app (25 km²)",
    )
    return parser


def _parse_profiles(args: argparse.Namespace) -> list[str]:
    raw = args.profiles if args.profiles else args.profile
    profiles = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = [item for item in profiles if item not in {"bike", "shortest"}]
    if not profiles or invalid:
        raise SystemExit("Perfiles no válidos. Usa 'bike' y/o 'shortest' separados por coma.")
    return list(dict.fromkeys(profiles))


def _load_from_json(path: Path) -> nx.MultiDiGraph:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return parse_overpass_payload(payload)


def _load_from_xml(path: Path) -> nx.MultiDiGraph:
    graph = ox.graph_from_xml(path, simplify=True, retain_all=False)
    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise ValueError("El XML no contiene una red válida.")
    return OsmnxProvider._project_and_keep_latlon(graph)


def _load_from_provider(
    provider_name: str,
    bbox: BoundingBox,
    profile: str,
    cache: GraphCache,
    settings: Settings,
) -> nx.MultiDiGraph:
    provider = GraphProviderFactory.create(provider_name, cache, settings)
    return provider.load_graph(bbox, profile=profile)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    origin = Coordinate.from_string(args.origin)
    dest = Coordinate.from_string(args.dest)
    bbox = BoundingBox.from_points(origin, dest, margin_m=args.margin_km * 1000.0)

    if bbox.area_km2 > 25.0 and not args.force:
        print(
            f"El área ({bbox.area_km2:.2f} km²) supera el límite de 25 km². "
            "Usa --force o descarga un extracto de Geofabrik.",
            file=sys.stderr,
        )
        return 1

    profiles = _parse_profiles(args)
    settings = Settings(
        provider=args.provider,
        profile=profiles[0],
        margin_m=args.margin_km * 1000.0,
        cache_dir=Path(args.cache_dir),
        use_cache=True,
        overpass_url=args.overpass_url,
        user_agent=args.user_agent,
    )
    cache = GraphCache(settings.cache_dir, enabled=True)

    if args.json is not None and args.xml is not None:
        print("Usa solo uno de --json o --xml.", file=sys.stderr)
        return 1

    if args.json is not None:
        backend = "overpass"
        graph = _load_from_json(args.json)
        extra = ""
    elif args.xml is not None:
        backend = "osmnx"
        graph = _load_from_xml(args.xml)
        extra = settings.network_type
    else:
        backend = args.provider
        graph = _load_from_provider(backend, bbox, profiles[0], cache, settings)
        extra = settings.network_type if backend == "osmnx" else ""

    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        print("El grafo está vacío: no hay red utilizable en el área.", file=sys.stderr)
        return 1

    graph.graph["download_bbox"] = bbox.to_osmnx_tuple()
    keys = [cache.key(bbox, backend, profile, extra=extra) for profile in profiles]
    for key in keys:
        cache.save(key, graph)

    print(f"Área:            {bbox.area_km2:.2f} km²")
    print(f"Backend:         {backend}")
    print(f"Perfiles:        {', '.join(profiles)}")
    print(f"Nodos:           {graph.number_of_nodes()}")
    print(f"Aristas:         {graph.number_of_edges()}")
    for key in keys:
        print(f"Clave de caché:  {key}")
        print(f"Guardado en:     {cache.directory / f'{key}.pkl'}")
    print()
    print("Para reutilizarlo, usa el mismo origen, destino, margen y perfil en la UI o en la CLI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
