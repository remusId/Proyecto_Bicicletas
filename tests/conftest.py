"""Fixtures compartidas por las pruebas."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pytest

from app.domain.models import haversine_m


@pytest.fixture
def synthetic_graph() -> nx.MultiDiGraph:
    """Grafo dirigido 5x5 con longitudes en metros y coordenadas WGS84."""
    graph = nx.MultiDiGraph()
    graph.graph["crs"] = "epsg:4326"
    coords: dict[int, tuple[float, float]] = {}
    for row in range(5):
        for col in range(5):
            node = row * 5 + col
            lat = 40.0 + row * 0.001
            lon = -3.0 + col * 0.001
            coords[node] = (lat, lon)
            graph.add_node(
                node,
                x=lon,
                y=lat,
                lat=lat,
                lon=lon,
                street_count=4,
            )

    edge_id = 0
    for row in range(5):
        for col in range(5):
            node = row * 5 + col
            for drow, dcol in ((0, 1), (1, 0)):
                next_row, next_col = row + drow, col + dcol
                if next_row >= 5 or next_col >= 5:
                    continue
                neighbor = next_row * 5 + next_col
                lat1, lon1 = coords[node]
                lat2, lon2 = coords[neighbor]
                base = haversine_m(lat1, lon1, lat2, lon2)
                length = base * 1.05
                highway = "residential"
                for source, target in ((node, neighbor), (neighbor, node)):
                    edge_id += 1
                    graph.add_edge(
                        source,
                        target,
                        key=edge_id,
                        length=length,
                        highway=highway,
                        osmid=edge_id,
                        oneway=False,
                        reversed=source != node,
                    )

    # Una conexión diagonal de ciclo-ruta para dar variedad al grafo.
    graph.add_edge(
        0,
        6,
        key="cycle",
        length=haversine_m(*coords[0], *coords[6]) * 1.01,
        highway="cycleway",
        osmid="cycle",
        oneway=False,
        reversed=False,
    )
    graph.add_edge(
        6,
        0,
        key="cycle_rev",
        length=haversine_m(*coords[0], *coords[6]) * 1.01,
        highway="cycleway",
        osmid="cycle",
        oneway=False,
        reversed=True,
    )
    return graph


@pytest.fixture
def overpass_payload() -> dict:
    """Respuesta Overpass guardada para pruebas sin red."""
    fixture_path = Path(__file__).parent / "fixtures" / "overpass_response.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))
