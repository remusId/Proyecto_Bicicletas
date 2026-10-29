"""Pruebas del orquestador con dobles de prueba."""

from __future__ import annotations

import networkx as nx
import pytest

from app.config import Settings
from app.domain.exceptions import (
    AreaTooLargeError,
    NoRouteFoundError,
    SnapDistanceError,
)
from app.domain.models import BoundingBox, Coordinate
from app.providers.base import GraphProvider
from app.providers.overpass_provider import OverpassProvider
from app.routing.astar import AStarPathFinder
from app.routing.base import PathFinder, PathSearchResult
from app.routing.dijkstra import DijkstraPathFinder
from app.routing.profile import BikeFriendlyProfile, CostProfile, ShortestProfile
from app.services.planner import RoutePlanner


class FakeProvider(GraphProvider):
    """Proveedor en memoria para probar la composición."""

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        origin_node: int = 0,
        dest_node: int = 24,
        origin_snap: float = 0.0,
        dest_snap: float = 0.0,
    ) -> None:
        super().__init__(None)
        self._graph = graph
        self._origin_node = origin_node
        self._dest_node = dest_node
        self._origin_snap = origin_snap
        self._dest_snap = dest_snap
        self.loaded_profile: str | None = None
        self.loaded_bbox: BoundingBox | None = None
        self.load_calls = 0

    @property
    def name(self) -> str:
        return "fake"

    def load_graph(self, bbox: BoundingBox, profile: str = "bike") -> nx.MultiDiGraph:
        self.loaded_profile = profile
        self.loaded_bbox = bbox
        self.load_calls += 1
        return self._graph

    def nearest_node(self, graph: nx.MultiDiGraph, coordinate: Coordinate) -> tuple[int, float]:
        if coordinate == Coordinate(40.0, -3.0):
            return self._origin_node, self._origin_snap
        return self._dest_node, self._dest_snap


class FakePathFinder(PathFinder):
    """Buscador falso que devuelve un camino fijo."""

    def __init__(self, nodes=(0, 24), distance_m=500.0, cost=500.0) -> None:
        super().__init__()
        self._nodes = tuple(nodes)
        self._distance_m = distance_m
        self._cost = cost

    def find_path(self, origin, dest) -> PathSearchResult:
        return PathSearchResult(
            nodes=self._nodes,
            cost=self._cost,
            distance_m=self._distance_m,
            nodes_expanded=3,
            elapsed_s=0.01,
            algorithm="fake",
        )


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def _coords() -> tuple[Coordinate, Coordinate]:
    return Coordinate(40.0, -3.0), Coordinate(40.004, -2.996)


@pytest.mark.parametrize("profile", [ShortestProfile(), BikeFriendlyProfile()])
@pytest.mark.parametrize("pathfinder", [AStarPathFinder(), DijkstraPathFinder()])
def test_planner_works_with_profile_pathfinder_combinations(
    synthetic_graph, profile: CostProfile, pathfinder: PathFinder
) -> None:
    provider = FakeProvider(synthetic_graph)
    planner = RoutePlanner(provider, profile, pathfinder, _settings())
    origin, dest = _coords()
    result = planner.plan(origin, dest)
    assert result.backend == "fake"
    assert result.profile == profile.name
    assert result.algorithm in {"A*", "Dijkstra"}
    assert result.distance_m > 0.0
    assert result.duration_s > 0.0
    assert result.nodes[0] == 0
    assert result.nodes[-1] == 24
    assert len(result.geometry) == len(result.nodes)
    assert provider.loaded_profile == profile.name
    assert provider.loaded_bbox is not None


def test_planner_uses_injected_fake_pathfinder(synthetic_graph) -> None:
    provider = FakeProvider(synthetic_graph)
    planner = RoutePlanner(
        provider,
        ShortestProfile(),
        FakePathFinder(),
        _settings(),
    )
    result = planner.plan(*_coords())
    assert result.algorithm == "fake"
    assert result.nodes_expanded == 3
    assert result.distance_m == 500.0
    assert result.compute_time_s == 0.01


def test_planner_rejects_area_too_large(synthetic_graph) -> None:
    provider = FakeProvider(synthetic_graph)
    planner = RoutePlanner(provider, ShortestProfile(), AStarPathFinder(), _settings())
    with pytest.raises(AreaTooLargeError):
        planner.plan(Coordinate(40.0, -3.0), Coordinate(41.0, -3.0))
    assert provider.load_calls == 0


def test_planner_warns_about_long_snap(synthetic_graph) -> None:
    provider = FakeProvider(synthetic_graph, origin_snap=250.0, dest_snap=10.0)
    planner = RoutePlanner(provider, ShortestProfile(), AStarPathFinder(), _settings())
    result = planner.plan(*_coords())
    assert len(result.warnings) == 1
    assert "origen" in result.warnings[0]


def test_planner_can_enforce_max_snap(synthetic_graph) -> None:
    provider = FakeProvider(synthetic_graph, origin_snap=250.0)
    planner = RoutePlanner(
        provider,
        ShortestProfile(),
        AStarPathFinder(),
        _settings(max_snap_m=100.0),
    )
    with pytest.raises(SnapDistanceError):
        planner.plan(*_coords())


def test_planner_propagates_no_route(synthetic_graph) -> None:
    class NoRouteFinder(PathFinder):
        def find_path(self, origin, dest):
            raise NoRouteFoundError("sin ruta")

    planner = RoutePlanner(
        FakeProvider(synthetic_graph),
        ShortestProfile(),
        NoRouteFinder(),
        _settings(),
    )
    with pytest.raises(NoRouteFoundError):
        planner.plan(*_coords())


def test_planner_snaps_to_node_usable_by_profile() -> None:
    """Un nodo cercano pero intransitable no debe capturar el snap.

    Reproduce el caso de un punto dentro de un recinto: el nodo más cercano
    solo tiene pasillos (``corridor``, excluido por ambos perfiles) y debe
    ignorarse en favor de la calle transitable más próxima.
    """
    graph = nx.MultiDiGraph()
    graph.graph["crs"] = "epsg:4326"
    nodes = {
        0: (40.0, -3.0),
        1: (40.0001, -3.0001),
        2: (40.0002, -3.0002),
        3: (40.001, -3.001),
    }
    for node, (lat, lon) in nodes.items():
        graph.add_node(node, x=lon, y=lat, lat=lat, lon=lon, street_count=1)
    for source, target in ((0, 3), (3, 0)):
        graph.add_edge(
            source,
            target,
            length=140.0,
            highway="residential",
            oneway=False,
            reversed=source != 0,
        )
    for source, target in ((1, 2), (2, 1)):
        graph.add_edge(
            source,
            target,
            length=15.0,
            highway="corridor",
            oneway=False,
            reversed=source != 1,
        )

    provider = OverpassProvider.__new__(OverpassProvider)
    provider._cache = None
    provider.load_graph = lambda bbox, profile="bike": graph  # type: ignore[method-assign]
    planner = RoutePlanner(
        provider,
        BikeFriendlyProfile(),
        DijkstraPathFinder(),
        _settings(),
    )
    origin = Coordinate(*nodes[1])
    dest = Coordinate(*nodes[3])
    result = planner.plan(origin, dest)

    assert result.origin_node == 0
    assert result.snap_origin_m > 0.0
    assert result.nodes[0] == 0
    assert result.nodes[-1] == 3
