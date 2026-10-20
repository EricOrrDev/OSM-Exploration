"""Unit tests for PedestrianGraph routing and accessibility weighting."""

import pytest
from src.clients.overpass_client import OverpassClient
from src.config import DEFAULT_BBOX
from src.parser.osm_parser import OSMParser
from src.routing.pedestrian_graph import PedestrianGraph


def test_pedestrian_graph_routing_prefers_aps():
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(DEFAULT_BBOX)
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    # Route from Node 5 (NW Approach) to Node 8 (SE Destination)
    # Option A (Safe): 5 -> 1 -> (APS Crossing 101) -> 2 -> 4 -> 8
    # Option B (Hazardous): 5 -> 1 -> 3 -> (Unmarked Crossing 103) -> 4 -> 8
    route = graph.route(5, 8)
    assert route is not None
    assert route.total_distance_m > 0
    assert route.node_path[0] == 5
    assert route.node_path[-1] == 8

    # The router should choose Node 2 (via safe APS Crossing 101) instead of Node 3 (hazardous Crossing 103)
    assert 2 in route.node_path
    assert 101 in [e.crosswalk.id for e in route.edges if e.crosswalk]
    assert 103 not in [e.crosswalk.id for e in route.edges if e.crosswalk]


def test_nearest_node_finding():
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(DEFAULT_BBOX)
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    # Coordinate near Node 1 (44.05800, -121.30260)
    target = (44.05801, -121.30259)
    nearest = graph.find_nearest_node(target)
    assert nearest == 1


def test_turn_penalty_favors_straight_route():
    """Verify Dijkstra pathfinding with turn penalty prefers straight routes over zigzag routes."""
    from src.models.pedestrian import PedestrianNetwork, SidewalkFeature
    from src.routing.safety_weights import SafetyWeightsConfig, TurnPenaltyConfig

    # Straight: 1 -> 2 -> 3 (0 turns)
    # Zigzag:   1 -> 4 -> 5 -> 3 (three 90° turns)
    network = PedestrianNetwork(
        raw_nodes={
            1: (44.0500, -121.3020),
            2: (44.0500, -121.3010),
            3: (44.0500, -121.3000),
            4: (44.0502, -121.3020),
            5: (44.0502, -121.3000),
        },
        sidewalks={
            1: SidewalkFeature(id=1, node_ids=[1, 2, 3], name="Straight Sidewalk"),
            2: SidewalkFeature(id=2, node_ids=[1, 4, 5, 3], name="Zigzag Sidewalk"),
        },
    )

    # 1. With turn penalty enabled
    cfg_with_penalty = SafetyWeightsConfig(turn=TurnPenaltyConfig(turn_penalty_enabled=True, base_turn_penalty=2.0))
    graph_with_penalty = PedestrianGraph(network, weights=cfg_with_penalty)
    route_straight = graph_with_penalty.route(1, 3)

    assert route_straight is not None
    assert route_straight.node_path == [1, 2, 3]  # Chose straight path, avoiding the zigzag turns!

