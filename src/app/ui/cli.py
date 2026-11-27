"""Interfaz de línea de comandos."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.domain.exceptions import RoutingError
from app.domain.models import Coordinate, RouteResult
from app.providers.factory import GraphProviderFactory
from app.routing.factory import PathFinderFactory
from app.routing.profile import profile_from_name
from app.services.cache import GraphCache
from app.services.geocoder import NominatimGeocoder
from app.services.land_connections import check_land_route
from app.services.planner import RoutePlanner
from app.visualization.plotter import RoutePlotter


class CliApp:
    """CLI mínima que delega el cálculo en ``RoutePlanner``."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings.from_env()

    def run(self, argv: Sequence[str] | None = None) -> int:
        """Ejecuta la CLI y devuelve un código de salida."""
        parser = self._build_parser()
        args = parser.parse_args(argv)
        try:
            settings = replace(
                self._settings,
                provider=args.provider,
                profile=args.profile,
                algorithm=args.algorithm,
                margin_m=args.margin_km * 1000.0,
                max_area_km2=(
                    self._settings.max_area_km2 if args.max_area_km2 is None else args.max_area_km2
                ),
                bike_speed_kmh=args.speed_kmh,
                cache_dir=Path(args.cache_dir),
                use_cache=not args.no_cache,
                user_agent=args.user_agent,
            )
            geocoder = NominatimGeocoder(settings.user_agent)
            if args.geocode is not None:
                if any((args.origin, args.dest, args.origin_place, args.dest_place)):
                    raise ValueError("--geocode se usa sin argumentos de origen y destino.")
                places = geocoder.search(args.geocode)
                if not places:
                    raise ValueError("No se encontraron lugares. Añade la ciudad o el distrito.")
                for place in places:
                    print(f"{place.name} ({place.latlon})")
                print("Datos: © OpenStreetMap contributors")
                print(places[0].latlon)
                return 0
            if not (args.origin or args.origin_place) or not (args.dest or args.dest_place):
                raise ValueError("Indica un origen y un destino por coordenadas o nombre.")
            origin = self._coordinate(args.origin, args.origin_place, geocoder)
            dest = self._coordinate(args.dest, args.dest_place, geocoder)
            check_land_route(origin, dest)
            if args.max_area_km2 is None and os.getenv("APP_MAX_AREA_KM2") is None:
                expanded = settings.with_area_for(origin, dest)
                if expanded is not settings:
                    print(
                        f"Área ajustada automáticamente a {expanded.max_area_km2:.1f} km².",
                        file=sys.stderr,
                    )
                settings = expanded
            cache = GraphCache(settings.cache_dir, enabled=settings.use_cache)
            provider = GraphProviderFactory.create(settings.provider, cache, settings)
            profile = profile_from_name(settings.profile)
            pathfinder = PathFinderFactory.create(settings.algorithm)
            planner = RoutePlanner(provider, profile, pathfinder, settings)
            self._progress(0, "Preparando red ciclista (caché o descarga)…")
            planner.prefetch(origin, dest)
            self._progress(1, "Red lista. Calculando ruta…")
            result = planner.plan_with_alternatives(origin, dest)
        except (RoutingError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            if isinstance(exc, RoutingError) and exc.diagnostic:
                print(f"Diagnóstico\n{exc.diagnostic}", file=sys.stderr)
            return 1
        except Exception:
            print(
                "Error: no se pudo calcular la ruta. Revisa la conexión, el área "
                "o la configuración.",
                file=sys.stderr,
            )
            return 1

        if not args.no_summary:
            self._print_result(result)
            self._print_instructions(result)
        elif result.alternative_origin is not None or result.alternative_dest is not None:
            for warning in result.warnings:
                print(f"Aviso: {warning}", file=sys.stderr)
        # Generar visualización si está activada
        if getattr(args, "plot", True):
            self._progress(2, "Ruta calculada. Generando el mapa…")
            try:
                plotter = RoutePlotter(
                    margin_m=args.margin_m,
                    dpi=args.dpi,
                    labels=not args.no_labels,
                    basemap=None if args.basemap == "none" else args.basemap,
                )
                out_path = getattr(args, "plot_out", "route.png") or "route.png"
                no_show = getattr(args, "no_show", False)
                plotter.render(result, out_path=out_path, show=not no_show)
                for note in plotter.warnings:
                    print(f"Aviso: {note}", file=sys.stderr)
            except Exception as exc:
                print(f"Aviso: no se pudo generar la imagen: {exc}", file=sys.stderr)
                return 0
            self._progress(3, "Ruta y mapa listos.")
        else:
            self._progress(3, "Ruta calculada.")
        return 0

    @staticmethod
    def _progress(completed: int, message: str) -> None:
        bar = "#" * (completed * 4) + "-" * ((3 - completed) * 4)
        print(f"[{bar}] {message}", file=sys.stderr, flush=True)

    @staticmethod
    def _coordinate(raw: str | None, place: str | None, geocoder: NominatimGeocoder) -> Coordinate:
        if raw is not None:
            return Coordinate.from_string(raw)
        matches = geocoder.search(place or "")
        if not matches:
            raise ValueError(f"No se encontró «{place}». Especifica la ciudad o usa coordenadas.")
        if len(matches) > 1:
            print(f"Lugar seleccionado: {matches[0].name} ({matches[0].latlon})", file=sys.stderr)
        return matches[0].coordinate

    def _build_parser(self) -> argparse.ArgumentParser:
        settings = self._settings
        parser = argparse.ArgumentParser(
            prog="python -m app",
            description="Calcula una ruta ciclista con A* sobre OpenStreetMap.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        origin_group = parser.add_mutually_exclusive_group()
        origin_group.add_argument("--origin", help="Origen LAT,LON")
        origin_group.add_argument("--origin-place", help="Nombre del lugar de origen")
        dest_group = parser.add_mutually_exclusive_group()
        dest_group.add_argument("--dest", help="Destino LAT,LON")
        dest_group.add_argument("--dest-place", help="Nombre del lugar de destino")
        parser.add_argument("--geocode", help="Busca lugares y muestra sus coordenadas")
        parser.add_argument(
            "--provider",
            choices=["osmnx", "overpass"],
            default=settings.provider,
            help="Backend de descarga",
        )
        parser.add_argument(
            "--profile",
            choices=["bike", "shortest"],
            default=settings.profile,
            help="Perfil de coste",
        )
        parser.add_argument(
            "--algorithm",
            choices=["astar", "dijkstra"],
            default=settings.algorithm,
            help="Algoritmo de búsqueda",
        )
        parser.add_argument(
            "--margin-km",
            type=float,
            default=settings.margin_m / 1000.0,
            help="Margen alrededor de los puntos",
        )
        parser.add_argument(
            "--max-area-km2",
            type=float,
            help="Fija un límite manual de superficie. Por defecto se ajusta a los puntos.",
        )
        parser.add_argument(
            "--speed-kmh",
            type=float,
            default=settings.bike_speed_kmh,
            help="Velocidad media para estimar el tiempo",
        )
        parser.add_argument(
            "--cache-dir",
            default=str(settings.cache_dir),
            help="Directorio de caché de grafos",
        )
        parser.add_argument(
            "--no-cache",
            action="store_true",
            help="Desactiva la caché en disco",
        )
        parser.add_argument(
            "--user-agent",
            default=settings.user_agent,
            help="User-Agent identificable para Overpass/OSM",
        )
        parser.add_argument(
            "--plot",
            dest="plot",
            action="store_true",
            default=True,
            help="Genera una imagen PNG con la ruta (activado por defecto)",
        )
        parser.add_argument(
            "--no-plot",
            dest="plot",
            action="store_false",
            help="No genera la imagen PNG",
        )
        parser.add_argument(
            "--plot-out",
            default="route.png",
            help="Ruta de salida de la imagen PNG",
        )
        parser.add_argument(
            "--no-show",
            action="store_true",
            help="Guarda la imagen sin abrir ventana (usa backend Agg)",
        )
        parser.add_argument(
            "--no-summary",
            action="store_true",
            help="Oculta el resumen de la ruta y las indicaciones por calle",
        )
        parser.add_argument(
            "--dpi",
            type=int,
            default=200,
            help="Resolución de la imagen PNG",
        )
        parser.add_argument(
            "--margin-m",
            type=float,
            default=150.0,
            help="Margen alrededor de la ruta en el mapa, en metros",
        )
        parser.add_argument(
            "--no-labels",
            action="store_true",
            help="Oculta los nombres de calles en el mapa",
        )
        parser.add_argument(
            "--basemap",
            choices=["none", "osm"],
            default="none",
            help="Fondo del mapa: red dibujada del grafo o tiles de OpenStreetMap",
        )
        return parser

    @staticmethod
    def _print_result(result: RouteResult) -> None:
        print("Ruta calculada")
        print("--------------")
        print(f"Distancia:        {result.distance_km:.2f} km")
        print(f"Tiempo estimado:  {result.duration_min:.1f} min")
        print(f"Nodos expandidos: {result.nodes_expanded}")
        print(f"Backend:          {result.backend}")
        print(f"Perfil:           {result.profile}")
        print(f"Algoritmo:        {result.algorithm}")
        print(f"Snap origen:      {result.snap_origin_m:.1f} m")
        print(f"Snap destino:     {result.snap_dest_m:.1f} m")
        print(f"Cómputo:          {result.compute_time_s * 1000.0:.1f} ms")
        for warning in result.warnings:
            print(f"Aviso: {warning}")
        print("Datos: © OpenStreetMap contributors")

    @staticmethod
    def _print_instructions(result: RouteResult) -> None:
        """Lista los metros recorridos en cada calle, agrupando tramos consecutivos."""
        groups = CliApp._street_groups(result)
        if not groups:
            return
        print()
        print("Indicaciones por calle")
        print("----------------------")
        for name, meters in groups:
            print(f"  {name}: {meters:.0f} m")

    @staticmethod
    def _street_groups(result: RouteResult) -> list[tuple[str, float]]:
        graph = getattr(result, "graph", None)
        if graph is None:
            return []
        groups: list[list] = []
        for source, target in zip(result.nodes, result.nodes[1:], strict=False):
            edges = graph.get_edge_data(source, target) or {}
            data = next(iter(edges.values()), {}) if edges else {}
            name = data.get("name")
            if isinstance(name, (list, tuple)):
                name = name[0] if name else None
            label = str(name).strip() if name is not None else ""
            if not label:
                label = "Vía sin nombre"
            try:
                meters = float(data.get("length") or 0.0)
            except (TypeError, ValueError):
                meters = 0.0
            if groups and groups[-1][0] == label:
                groups[-1][1] += meters
            else:
                groups.append([label, meters])
        return [(label, meters) for label, meters in groups if meters > 0.0]


def main(argv: Sequence[str] | None = None) -> int:
    """Entrada del comando ``python -m app``."""
    return CliApp().run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
