"""Interfaz Streamlit con selección de puntos sobre un mapa."""

from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import replace
from typing import Any

import streamlit as st
from streamlit_folium import st_folium

from app.config import Settings
from app.domain.exceptions import RoutingError
from app.domain.models import Coordinate, RouteResult
from app.providers.factory import GraphProviderFactory
from app.routing.factory import PathFinderFactory
from app.routing.profile import profile_from_name
from app.services.cache import GraphCache
from app.services.geocoder import NominatimGeocoder
from app.services.planner import RoutePlanner
from app.services.ui_state import MapView, ViewStore
from app.ui.map_renderer import MapRenderer


@st.cache_resource
def _graph_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="grafo")


@st.fragment(run_every=1.0)
def _prefetch_progress(future: Future[None], calculate_when_ready: bool = False) -> None:
    if not future.done():
        message = "Preparando red ciclista (caché o descarga)…"
        if calculate_when_ready:
            message += " La ruta se calculará al terminar."
        st.progress(0, text=message)
    elif calculate_when_ready:
        st.rerun()
    elif not future.cancelled() and future.exception() is None:
        st.progress(50, text="Red lista. Pulsa Calcular ruta.")
    else:
        st.warning("No se pudo preparar la red. Pulsa Calcular ruta para ver el detalle.")


class StreamlitApp:
    """Aplicación interactiva; delega todo el routing en ``RoutePlanner``."""

    def __init__(self, settings: Settings, renderer: MapRenderer | None = None) -> None:
        self._settings = settings
        self._renderer = renderer or MapRenderer()

    def run(self) -> None:
        """Punto de entrada de la aplicación Streamlit."""
        st.set_page_config(
            page_title="Rutas ciclistas con A*",
            page_icon="🚲",
            layout="wide",
        )
        st.title("🚲 Rutas ciclistas con A* propio")
        st.caption(
            "Datos de OpenStreetMap. © OpenStreetMap contributors. "
            "Haz clic en el mapa para marcar origen y destino."
        )
        settings = self._sidebar()
        self._init_state()
        if "map_view" not in st.session_state:
            fallback = MapView(settings.default_center, min(settings.map_zoom, 19))
            st.session_state["map_view"] = ViewStore().load(fallback)
        self._map_click_panel(settings)
        self._result_panel(settings)

    def _sidebar(self) -> Settings:
        settings = self._settings
        with st.sidebar:
            st.header("Configuración")
            provider = st.selectbox(
                "Backend de datos",
                options=["osmnx", "overpass"],
                index=0 if settings.provider == "osmnx" else 1,
                help="OSMnx o consulta directa a Overpass API.",
            )
            profile = st.selectbox(
                "Perfil",
                options=["bike", "shortest"],
                index=0 if settings.profile == "bike" else 1,
                help="'bike' prioriza vías ciclables; 'shortest' usa solo longitud.",
            )
            algorithm = st.selectbox(
                "Algoritmo",
                options=["astar", "dijkstra"],
                index=0 if settings.algorithm == "astar" else 1,
                help="Dijkstra se incluye para comparar con A*.",
            )
            speed = st.number_input(
                "Velocidad media (km/h)",
                min_value=1.0,
                max_value=50.0,
                value=float(settings.bike_speed_kmh),
                step=1.0,
            )
            margin_km = st.number_input(
                "Margen del bbox (km)",
                min_value=0.1,
                max_value=10.0,
                value=float(settings.margin_m / 1000.0),
                step=0.1,
            )
            use_cache = st.checkbox("Usar caché en disco", value=settings.use_cache)
            st.caption(f"User-Agent: `{settings.user_agent}`")
            st.caption(f"Caché: `{settings.cache_dir}`")

        return replace(
            settings,
            provider=provider,
            profile=profile,
            algorithm=algorithm,
            bike_speed_kmh=float(speed),
            margin_m=float(margin_km) * 1000.0,
            use_cache=bool(use_cache),
        )

    @staticmethod
    def _init_state() -> None:
        defaults: dict[str, Any] = {
            "origin": None,
            "dest": None,
            "last_click": None,
            "route_result": None,
        }
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value

    def _map_click_panel(self, settings: Settings) -> None:
        mode = st.radio(
            "Punto que vas a marcar",
            options=["Origen", "Destino"],
            horizontal=True,
            key="point_mode",
        )
        point_key = "origin" if mode == "Origen" else "dest"
        self._coordinate_form(mode, point_key)
        self._place_search(settings, mode)
        origin: Coordinate | None = st.session_state["origin"]
        dest: Coordinate | None = st.session_state["dest"]
        view = st.session_state["map_view"]
        # El JS de Folium determina la identidad del componente. Mantén estable
        # su vista inicial mientras Leaflet controla los movimientos del usuario.
        if st.session_state.get("map_points") != (origin, dest):
            st.session_state["map_points"] = (origin, dest)
            st.session_state["map_initial_view"] = view
        initial_view = st.session_state["map_initial_view"]

        map_obj = self._renderer.render(
            origin=origin,
            dest=dest,
            center=initial_view.center,
            zoom=initial_view.zoom,
        )
        map_output = st_folium(
            map_obj,
            height=480,
            key=f"click_map_{st.session_state.get('map_revision', 0)}",
            returned_objects=["last_clicked", "center", "zoom"],
        )
        if isinstance(map_output, dict) and map_output.get("center"):
            center = map_output["center"]
            with suppress(ValueError, TypeError, KeyError):
                self._save_view(
                    MapView(Coordinate(center["lat"], center["lng"]), map_output["zoom"])
                )
        clicked = map_output.get("last_clicked") if isinstance(map_output, dict) else None
        if clicked:
            clicked_pair = (float(clicked["lat"]), float(clicked["lng"]))
            if clicked_pair != st.session_state["last_click"]:
                st.session_state["last_click"] = clicked_pair
                coordinate = Coordinate(lat=clicked_pair[0], lon=clicked_pair[1])
                self._set_point(point_key, coordinate)
                st.rerun()

        col_calc, col_clear = st.columns(2)
        calculate = col_calc.button(
            "Calcular ruta",
            type="primary",
            disabled=origin is None or dest is None,
            use_container_width=True,
        )
        clear = col_clear.button("Limpiar puntos", use_container_width=True)
        if clear:
            st.session_state["origin"] = None
            st.session_state["dest"] = None
            st.session_state["route_result"] = None
            self._recenter(view.center, view.zoom)
            st.rerun()
        if origin is None or dest is None:
            st.session_state.pop("pending_calculation", None)
            self._prefetch(settings, origin, dest)
            return
        try:
            route_settings = settings.with_area_for(origin, dest)
        except ValueError as exc:
            st.error(str(exc))
            return
        if route_settings.max_area_km2 > settings.max_area_km2:
            st.caption(f"Área ajustada automáticamente a {route_settings.max_area_km2:.1f} km².")
        request = (route_settings, origin, dest)
        if calculate:
            st.session_state["pending_calculation"] = request
        pending = st.session_state.get("pending_calculation") == request
        if not pending:
            st.session_state.pop("pending_calculation", None)
        if pending or st.session_state["route_result"] is None:
            planner, future = self._prefetch(route_settings, origin, dest)
            if pending and future.done():
                st.session_state.pop("pending_calculation")
                self._calculate(planner, future, origin, dest)
            else:
                _prefetch_progress(future, pending)

    def _coordinate_form(self, mode: str, point_key: str) -> None:
        current: Coordinate | None = st.session_state[point_key]
        value = f"{current.lat},{current.lon}" if current is not None else ""
        name = mode.lower()
        with st.form(f"coordinates_{point_key}"):
            raw = st.text_input(
                f"Coordenadas de {name} (LAT,LON)",
                value=value,
                key=f"{point_key}_coordinates_{value}",
            )
            if st.form_submit_button(f"Fijar {name}"):
                try:
                    coordinate = Coordinate.from_string(raw)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    self._set_point(point_key, coordinate)
                    self._recenter(coordinate)

    @staticmethod
    def _set_point(point_key: str, coordinate: Coordinate) -> None:
        st.session_state[point_key] = coordinate
        st.session_state["route_result"] = None

    @staticmethod
    def _save_view(view: MapView) -> None:
        if view != st.session_state["map_view"]:
            st.session_state["map_view"] = view
            try:
                ViewStore().save(view)
            except OSError:
                st.warning("No se pudo guardar la vista del mapa en este equipo.")

    def _recenter(self, coordinate: Coordinate, zoom: int = 16) -> None:
        view = MapView(coordinate, zoom)
        self._save_view(view)
        st.session_state["map_initial_view"] = view
        st.session_state["map_revision"] = st.session_state.get("map_revision", 0) + 1
        st.session_state["last_click"] = None

    def _place_search(self, settings: Settings, mode: str) -> None:
        with st.form("place_search"):
            query = st.text_input("Buscar lugar por nombre")
            if st.form_submit_button("Buscar"):
                st.session_state["places"] = ()
                try:
                    st.session_state["places"] = NominatimGeocoder(settings.user_agent).search(
                        query
                    )
                    if not st.session_state["places"]:
                        st.info("No se encontraron lugares. Añade la ciudad o el distrito.")
                except (ValueError, RoutingError) as exc:
                    st.error(str(exc))
        places = st.session_state.get("places", ())
        if places:
            selected = st.selectbox(
                "Resultado",
                places,
                index=None,
                format_func=lambda place: f"{place.name} ({place.latlon})",
            )
            if selected is not None and st.button(f"Usar como {mode.lower()}"):
                self._set_point("origin" if mode == "Origen" else "dest", selected.coordinate)
                self._recenter(selected.coordinate)

    def _calculate(
        self, planner: RoutePlanner, future: Future[None], origin: Coordinate, dest: Coordinate
    ) -> None:
        progress = st.progress(50, text="Calculando ruta…")
        try:
            future.result()
            result = planner.plan_with_alternatives(origin, dest)
        except RoutingError as exc:
            progress.empty()
            st.session_state["route_result"] = None
            self._forget_failed_prefetch()
            st.error(str(exc))
            if exc.diagnostic:
                with st.expander("Diagnóstico"):
                    for line in exc.diagnostic.splitlines():
                        st.write(line)
            return
        except Exception:
            progress.empty()
            st.session_state["route_result"] = None
            self._forget_failed_prefetch()
            st.error(
                "No se pudo calcular la ruta. Revisa la conexión, el área o la "
                "configuración e inténtalo de nuevo."
            )
            return
        progress.progress(100, text="Ruta calculada.")
        st.session_state["route_result"] = result

    @staticmethod
    def _forget_failed_prefetch() -> None:
        job = st.session_state.get("prefetch")
        if job and job[2].done() and job[2].exception() is not None:
            st.session_state.pop("prefetch")

    @staticmethod
    def _prefetch(settings: Settings, origin: Coordinate | None, dest: Coordinate | None):
        key = (settings, origin, dest)
        job = st.session_state.get("prefetch")
        if job:
            if job[0] == key:
                return job[1], job[2]
            job[2].cancel()
            st.session_state.pop("prefetch")
        if origin is None or dest is None:
            return None
        cache = GraphCache(settings.cache_dir, enabled=settings.use_cache)
        provider = GraphProviderFactory.create(settings.provider, cache, settings)
        profile = profile_from_name(settings.profile)
        pathfinder = PathFinderFactory.create(settings.algorithm)
        planner = RoutePlanner(provider, profile, pathfinder, settings)
        future = _graph_executor().submit(planner.prefetch, origin, dest)
        st.session_state["prefetch"] = (key, planner, future)
        return planner, future

    def _result_panel(self, settings: Settings) -> None:
        result: RouteResult | None = st.session_state["route_result"]
        if result is None:
            st.info(
                "Marca un origen y un destino en el mapa. El área se ajusta a ambos "
                "puntos y al margen configurado."
            )
            return

        origin = result.alternative_origin or st.session_state["origin"]
        dest = result.alternative_dest or st.session_state["dest"]
        st.subheader("Resultado")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Distancia", f"{result.distance_km:.2f} km")
        col2.metric("Tiempo estimado", f"{result.duration_min:.0f} min")
        col3.metric("Nodos expandidos", f"{result.nodes_expanded:,}")
        col4.metric("Backend", result.backend)
        st.write(
            f"**Perfil:** `{result.profile}` · **Algoritmo:** `{result.algorithm}` · "
            f"**Velocidad:** {settings.bike_speed_kmh:.0f} km/h"
        )
        st.caption(
            f"Snap origen: {result.snap_origin_m:.1f} m · "
            f"Snap destino: {result.snap_dest_m:.1f} m · "
            f"Cómputo: {result.compute_time_s * 1000.0:.1f} ms"
        )
        for warning in result.warnings:
            st.warning(warning)

        result_map = self._renderer.render(
            origin=origin,
            dest=dest,
            result=result,
            center=settings.default_center,
            zoom=settings.map_zoom,
        )
        st_folium(result_map, height=520, key="route_map", returned_objects=[])
        st.caption("© OpenStreetMap contributors")


def main() -> None:
    """Entrada usada por ``streamlit run``."""
    settings = Settings.from_env()
    if os.getenv("APP_PROVIDER") is None:
        settings = replace(settings, provider="overpass")
    StreamlitApp(settings).run()


if __name__ == "__main__":
    main()
