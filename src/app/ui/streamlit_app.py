"""Interfaz Streamlit con selección de puntos sobre un mapa."""

from __future__ import annotations

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
from app.services.planner import RoutePlanner
from app.ui.map_renderer import MapRenderer


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
            max_area = st.number_input(
                "Área máxima (km²)",
                min_value=1.0,
                max_value=100.0,
                value=float(settings.max_area_km2),
                step=1.0,
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
            max_area_km2=float(max_area),
            use_cache=bool(use_cache),
        )

    @staticmethod
    def _init_state() -> None:
        defaults: dict[str, Any] = {
            "origin": None,
            "dest": None,
            "last_click": None,
            "last_mode": "Origen",
            "route_result": None,
        }
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value

    def _map_click_panel(self, settings: Settings) -> None:
        origin: Coordinate | None = st.session_state["origin"]
        dest: Coordinate | None = st.session_state["dest"]
        mode = st.radio(
            "Punto que vas a marcar",
            options=["Origen", "Destino"],
            horizontal=True,
            key="point_mode",
        )
        if st.session_state["last_mode"] != mode:
            st.session_state["last_mode"] = mode
            st.session_state["last_click"] = None

        map_obj = self._renderer.render(
            origin=origin,
            dest=dest,
            center=settings.default_center,
            zoom=settings.map_zoom,
        )
        map_output = st_folium(
            map_obj,
            height=480,
            key="click_map",
            returned_objects=["last_clicked"],
        )
        clicked = map_output.get("last_clicked") if isinstance(map_output, dict) else None
        if clicked:
            clicked_pair = (float(clicked["lat"]), float(clicked["lng"]))
            if clicked_pair != st.session_state["last_click"]:
                st.session_state["last_click"] = clicked_pair
                coordinate = Coordinate(lat=clicked_pair[0], lon=clicked_pair[1])
                if mode == "Origen":
                    st.session_state["origin"] = coordinate
                else:
                    st.session_state["dest"] = coordinate
                st.session_state["route_result"] = None
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
            st.session_state["last_click"] = None
            st.session_state["route_result"] = None
            st.rerun()
        if calculate and origin is not None and dest is not None:
            self._calculate(settings, origin, dest)

    def _calculate(self, settings: Settings, origin: Coordinate, dest: Coordinate) -> None:
        cache = GraphCache(settings.cache_dir, enabled=settings.use_cache)
        provider = GraphProviderFactory.create(settings.provider, cache, settings)
        profile = profile_from_name(settings.profile)
        pathfinder = PathFinderFactory.create(settings.algorithm)
        planner = RoutePlanner(provider, profile, pathfinder, settings)
        try:
            with st.spinner("Descargando red y calculando la ruta..."):
                result = planner.plan(origin, dest)
        except RoutingError as exc:
            st.session_state["route_result"] = None
            st.error(str(exc))
            return
        except Exception:
            st.session_state["route_result"] = None
            st.error(
                "No se pudo calcular la ruta. Revisa la conexión, el área o la "
                "configuración e inténtalo de nuevo."
            )
            return
        st.session_state["route_result"] = result

    def _result_panel(self, settings: Settings) -> None:
        result: RouteResult | None = st.session_state["route_result"]
        if result is None:
            st.info(
                "Marca un origen y un destino en el mapa. El área se descarga con "
                "el margen configurado y se valida contra el límite de superficie."
            )
            return

        origin = st.session_state["origin"]
        dest = st.session_state["dest"]
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
    StreamlitApp(Settings.from_env()).run()


if __name__ == "__main__":
    main()
