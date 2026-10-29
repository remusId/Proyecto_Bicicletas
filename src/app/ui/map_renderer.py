"""Renderizado de mapas Folium."""

from __future__ import annotations

import folium

from app.domain.models import Coordinate, RouteResult


class MapRenderer:
    """Dibuja origen, destino y ruta sobre OpenStreetMap."""

    def render(
        self,
        origin: Coordinate | None = None,
        dest: Coordinate | None = None,
        result: RouteResult | None = None,
        *,
        center: Coordinate | None = None,
        zoom: int = 14,
    ) -> folium.Map:
        """Construye un mapa Folium con la ruta y los marcadores."""
        map_center = center or origin or dest or Coordinate(40.4168, -3.7038)
        fmap = folium.Map(
            location=[map_center.lat, map_center.lon],
            zoom_start=zoom,
            tiles="OpenStreetMap",
            control_scale=True,
        )

        if result is not None and result.geometry:
            locations = [(point.lat, point.lon) for point in result.geometry]
            folium.PolyLine(
                locations,
                color="#1565c0",
                weight=6,
                opacity=0.85,
                tooltip="Ruta ciclista",
            ).add_to(fmap)
            latitudes = [point[0] for point in locations]
            longitudes = [point[1] for point in locations]
            fmap.fit_bounds([[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]])

        if origin is not None:
            folium.Marker(
                [origin.lat, origin.lon],
                tooltip="Origen",
                popup="Origen",
                icon=folium.Icon(color="green", icon="play", prefix="fa"),
            ).add_to(fmap)
        if dest is not None:
            folium.Marker(
                [dest.lat, dest.lon],
                tooltip="Destino",
                popup="Destino",
                icon=folium.Icon(color="red", icon="flag-checkered", prefix="fa"),
            ).add_to(fmap)

        attribution = folium.Element(
            '<div style="position: absolute; bottom: 0; left: 0; z-index: 9999; '
            "background: rgba(255,255,255,0.85); padding: 2px 6px; "
            'font: 12px sans-serif;">© OpenStreetMap contributors</div>'
        )
        fmap.get_root().html.add_child(attribution)
        return fmap
