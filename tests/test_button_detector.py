"""Unit tests for ButtonDetector."""

import pytest
from src.models.pedestrian import CrosswalkFeature, KerbFeature, PedestrianNetwork, SidewalkFeature
from src.routing.button_detector import ButtonDetector
from src.routing.pedestrian_graph import PedestrianEdge, RouteResult


def test_button_detector_relative_orientation():
    # Construct synthetic network:
    # Curb node 1 at (44.0500, -121.3300)
    # Opposite curb node 2 at (44.0501, -121.3300) -> crossing heads DUE NORTH
    # Button node 101 to the WEST of curb 1 -> "to your left"
    # Button node 102 to the EAST of curb 1 -> "to your right"
    # Button node 103 directly ahead -> "directly ahead"

    raw_nodes = {
        1: (44.0500, -121.3300),
        2: (44.0501, -121.3300),
        101: (44.0500, -121.33002),  # West (Left of northbound traveler)
        102: (44.0500, -121.32998),  # East (Right of northbound traveler)
        103: (44.05002, -121.3300),  # North (Ahead of traveler)
    }

    cw = CrosswalkFeature(
        id=900,
        name="Test Crosswalk",
        node_ids=[1, 2],
        coordinates=[raw_nodes[1], raw_nodes[2]],
        has_signals=True,
    )

    edge = PedestrianEdge(
        u=1,
        v=2,
        length_m=11.1,
        effective_weight=11.1,
        feature_type="crosswalk",
        crosswalk=cw,
    )
    route = RouteResult(
        node_path=[1, 2],
        edges=[edge],
        total_distance_m=11.1,
        total_effective_cost=11.1,
        accessibility_rating="Moderate Safety",
    )

    # 1. Test button to traveler's left
    net_left = PedestrianNetwork(
        crosswalks={900: cw},
        raw_nodes=raw_nodes,
        button_nodes={101: raw_nodes[101]},
        node_tags={101: {"button_operated": "yes", "traffic_signals:sound": "yes", "traffic_signals:vibration": "yes"}},
    )
    detector_left = ButtonDetector(net_left)
    cue_left = detector_left.detect_button_cue(route, 0)

    assert cue_left.has_button is True
    assert cue_left.relative_direction == "to your left"
    assert cue_left.has_audible_locator is True
    assert cue_left.has_vibrotactile_arrow is True
    assert "To your left" in cue_left.instruction_text
    assert "audible locator tone" in cue_left.instruction_text
    assert "raised vibrotactile arrow" in cue_left.instruction_text

    # 2. Test button to traveler's right
    net_right = PedestrianNetwork(
        crosswalks={900: cw},
        raw_nodes=raw_nodes,
        button_nodes={102: raw_nodes[102]},
        node_tags={102: {"button_operated": "yes"}},
    )
    detector_right = ButtonDetector(net_right)
    cue_right = detector_right.detect_button_cue(route, 0)

    assert cue_right.has_button is True
    assert cue_right.relative_direction == "to your right"
    assert "To your right" in cue_right.instruction_text

    # 3. Test button directly ahead
    net_ahead = PedestrianNetwork(
        crosswalks={900: cw},
        raw_nodes=raw_nodes,
        button_nodes={103: raw_nodes[103]},
        node_tags={103: {"button_operated": "yes"}},
    )
    detector_ahead = ButtonDetector(net_ahead)
    cue_ahead = detector_ahead.detect_button_cue(route, 0)

    assert cue_ahead.has_button is True
    assert cue_ahead.relative_direction == "directly ahead"
    assert "Directly ahead" in cue_ahead.instruction_text


def test_button_detector_fallback_on_signals():
    raw_nodes = {
        1: (44.0500, -121.3300),
        2: (44.0501, -121.3300),
    }
    cw = CrosswalkFeature(
        id=901,
        node_ids=[1, 2],
        coordinates=[raw_nodes[1], raw_nodes[2]],
        has_signals=True,
        has_audible_signals=True,
    )
    edge = PedestrianEdge(
        u=1,
        v=2,
        length_m=11.1,
        effective_weight=11.1,
        feature_type="crosswalk",
        crosswalk=cw,
    )
    route = RouteResult(
        node_path=[1, 2],
        edges=[edge],
        total_distance_m=11.1,
        total_effective_cost=11.1,
        accessibility_rating="High Safety",
    )
    net = PedestrianNetwork(
        crosswalks={901: cw},
        raw_nodes=raw_nodes,
    )
    detector = ButtonDetector(net)
    cue = detector.detect_button_cue(route, 0)

    assert cue.has_button is True
    assert cue.relative_direction == "to your right"
    assert "signal pole" in cue.instruction_text
    assert "audible locator tone" in cue.instruction_text
