"""Unit tests for AudioGuidanceGenerator."""

import pytest
from src.clients.overpass_client import OverpassClient
from src.config import DEFAULT_BBOX
from src.parser.osm_parser import OSMParser
from src.routing.guidance import AudioGuidanceGenerator
from src.routing.pedestrian_graph import PedestrianGraph


def test_audio_guidance_generation():
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(DEFAULT_BBOX)
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    route = graph.route(5, 8)
    assert route is not None

    guidance_gen = AudioGuidanceGenerator(network)
    instructions = guidance_gen.generate_instructions(route)

    assert len(instructions) > 0
    # Check that arrival instruction is last
    assert instructions[-1]["action"] == "ARRIVE"

    # Check for curb approach and crosswalk instructions
    actions = [inst["action"] for inst in instructions]
    assert "WALK_SIDEWALK" in actions
    assert "APPROACH_CURB" in actions
    assert "CROSS_STREET" in actions

    # Check that APS signal is mentioned
    spoken_text = " ".join(inst["spoken_instruction"] for inst in instructions)
    assert "Accessible Pedestrian Signal" in spoken_text
    assert "lowered curb ramp" in spoken_text


def test_guidance_discrete_turn_generation():
    """Verify discrete turn instructions announce direction and quantized 15° angles."""
    from src.models.pedestrian import PedestrianNetwork, SidewalkFeature
    from src.routing.pedestrian_graph import PedestrianEdge, RouteResult

    # Node 1 -> Node 2 heading East (bearing 90°)
    # Node 2 -> Node 3 heading North (bearing 0°, -90° left turn)
    network = PedestrianNetwork(
        raw_nodes={
            1: (44.0500, -121.3010),
            2: (44.0500, -121.3000),
            3: (44.0510, -121.3000),
        },
        sidewalks={
            1: SidewalkFeature(id=1, node_ids=[1, 2], name="Campus Walk"),
            2: SidewalkFeature(id=2, node_ids=[2, 3], name="Century Sidewalk"),
        },
    )

    edge1 = PedestrianEdge(u=1, v=2, length_m=80.0, effective_weight=80.0, feature_type="sidewalk", sidewalk=network.sidewalks[1])
    edge2 = PedestrianEdge(u=2, v=3, length_m=110.0, effective_weight=110.0, feature_type="sidewalk", sidewalk=network.sidewalks[2])
    route = RouteResult(
        node_path=[1, 2, 3],
        edges=[edge1, edge2],
        total_distance_m=190.0,
        total_effective_cost=190.0,
        accessibility_rating="High Safety",
    )

    gen = AudioGuidanceGenerator(network)
    instructions = gen.generate_instructions(route)

    # Step 1: Follow Campus Walk for 80 meters.
    # Step 2: Turn 90 degrees left, then follow Century Sidewalk for 110 meters.
    # Step 3: Arrive.
    assert len(instructions) == 3
    assert instructions[0]["action"] == "WALK_SIDEWALK"
    assert "Follow Campus Walk for 80 meters." in instructions[0]["spoken_instruction"]

    assert instructions[1]["action"] == "WALK_SIDEWALK"
    assert "Turn 90 degrees left, then follow Century Sidewalk for 110 meters." in instructions[1]["spoken_instruction"]
    assert instructions[1]["turn_direction"] == "left"
    assert instructions[1]["turn_angle_deg"] == 90

    assert instructions[2]["action"] == "ARRIVE"


def test_guidance_arc_batching():
    """Verify consecutive curving micro-edges in the same direction are batched into a single arc instruction."""
    from src.models.pedestrian import PedestrianNetwork, SidewalkFeature
    from src.routing.pedestrian_graph import PedestrianEdge, RouteResult

    # Arc curving to the right:
    # Seg 1: Bearing ~45° (len 10m)
    # Seg 2: Bearing ~75° (+30° right, len 10m)
    # Seg 3: Bearing ~105° (+30° right, len 10m)
    # Seg 4: Bearing ~135° (+30° right, len 10m)
    network = PedestrianNetwork(
        raw_nodes={
            1: (44.0500, -121.3000),
            2: (44.05006, -121.29990),
            3: (44.05009, -121.29978),
            4: (44.05006, -121.29966),
            5: (44.05000, -121.29956),
        },
        sidewalks={
            1: SidewalkFeature(id=1, node_ids=[1, 2, 3, 4, 5], name="Curving Path"),
        },
    )

    edges = [
        PedestrianEdge(u=1, v=2, length_m=10.0, effective_weight=10.0, feature_type="sidewalk", sidewalk=network.sidewalks[1]),
        PedestrianEdge(u=2, v=3, length_m=10.0, effective_weight=10.0, feature_type="sidewalk", sidewalk=network.sidewalks[1]),
        PedestrianEdge(u=3, v=4, length_m=10.0, effective_weight=10.0, feature_type="sidewalk", sidewalk=network.sidewalks[1]),
        PedestrianEdge(u=4, v=5, length_m=10.0, effective_weight=10.0, feature_type="sidewalk", sidewalk=network.sidewalks[1]),
    ]
    route = RouteResult(
        node_path=[1, 2, 3, 4, 5],
        edges=edges,
        total_distance_m=40.0,
        total_effective_cost=40.0,
        accessibility_rating="High Safety",
    )

    gen = AudioGuidanceGenerator(network)
    instructions = gen.generate_instructions(route)

    # Should detect the curve and produce a sweeping sidewalk instruction
    curve_steps = [inst for inst in instructions if inst.get("is_curve")]
    assert len(curve_steps) == 1
    curve = curve_steps[0]
    assert "Sweep right" in curve["spoken_instruction"]
    assert curve["turn_direction"] == "right"
    assert curve["turn_angle_deg"] >= 60  # ~90° cumulative curve quantized to 15°
    assert curve["distance_m"] >= 30.0
    assert "o'clock" in curve["clock_position"]


def test_guidance_clock_face_mode():
    """Verify AudioGuidanceGenerator outputs clock face directions when configured."""
    from src.models.pedestrian import PedestrianNetwork, SidewalkFeature
    from src.models.safety_weights import DirectionMode, GuidanceVerbiageConfig
    from src.routing.pedestrian_graph import PedestrianEdge, RouteResult

    # Node 1 -> Node 2 heading East (bearing 90°)
    # Node 2 -> Node 3 heading North (bearing 0°, -90° left turn -> 9 o'clock)
    network = PedestrianNetwork(
        raw_nodes={
            1: (44.0500, -121.3010),
            2: (44.0500, -121.3000),
            3: (44.0510, -121.3000),
        },
        sidewalks={
            1: SidewalkFeature(id=1, node_ids=[1, 2], name="Campus Walk"),
            2: SidewalkFeature(id=2, node_ids=[2, 3], name="Century Sidewalk"),
        },
    )

    edge1 = PedestrianEdge(u=1, v=2, length_m=80.0, effective_weight=80.0, feature_type="sidewalk", sidewalk=network.sidewalks[1])
    edge2 = PedestrianEdge(u=2, v=3, length_m=110.0, effective_weight=110.0, feature_type="sidewalk", sidewalk=network.sidewalks[2])
    route = RouteResult(
        node_path=[1, 2, 3],
        edges=[edge1, edge2],
        total_distance_m=190.0,
        total_effective_cost=190.0,
        accessibility_rating="High Safety",
    )

    verbiage = GuidanceVerbiageConfig(direction_mode=DirectionMode.CLOCK)
    gen = AudioGuidanceGenerator(network, verbiage_config=verbiage)
    instructions = gen.generate_instructions(route)

    assert instructions[1]["action"] == "WALK_SIDEWALK"
    assert "Turn to 9 o'clock, then follow Century Sidewalk for 110 meters." in instructions[1]["spoken_instruction"]
    assert instructions[1]["clock_position"] == "9 o'clock"
    assert instructions[1]["direction_mode"] == "clock"


def test_guidance_custom_curve_preset_and_template():
    """Verify customizable curve verbiage presets (curving, bear, custom)."""
    from src.models.pedestrian import PedestrianNetwork, SidewalkFeature
    from src.models.safety_weights import CurveVerbiagePreset, GuidanceVerbiageConfig
    from src.routing.pedestrian_graph import PedestrianEdge, RouteResult

    network = PedestrianNetwork(
        raw_nodes={
            1: (44.0500, -121.3000),
            2: (44.05006, -121.29990),
            3: (44.05009, -121.29978),
            4: (44.05006, -121.29966),
            5: (44.05000, -121.29956),
        },
        sidewalks={
            1: SidewalkFeature(id=1, node_ids=[1, 2, 3, 4, 5], name="Pathway"),
        },
    )

    edges = [
        PedestrianEdge(u=1, v=2, length_m=10.0, effective_weight=10.0, feature_type="sidewalk", sidewalk=network.sidewalks[1]),
        PedestrianEdge(u=2, v=3, length_m=10.0, effective_weight=10.0, feature_type="sidewalk", sidewalk=network.sidewalks[1]),
        PedestrianEdge(u=3, v=4, length_m=10.0, effective_weight=10.0, feature_type="sidewalk", sidewalk=network.sidewalks[1]),
        PedestrianEdge(u=4, v=5, length_m=10.0, effective_weight=10.0, feature_type="sidewalk", sidewalk=network.sidewalks[1]),
    ]
    route = RouteResult(
        node_path=[1, 2, 3, 4, 5],
        edges=edges,
        total_distance_m=40.0,
        total_effective_cost=40.0,
        accessibility_rating="High Safety",
    )

    # 1. Curve preset: CURVING
    v_curving = GuidanceVerbiageConfig(curve_preset=CurveVerbiagePreset.CURVING)
    gen_curving = AudioGuidanceGenerator(network, verbiage_config=v_curving)
    inst_curving = gen_curving.generate_instructions(route)
    curve_c = [inst for inst in inst_curving if inst.get("is_curve")][0]
    assert "Follow the curving sidewalk to the right for 30 meters." in curve_c["spoken_instruction"]

    # 2. Custom template: "Sidewalk arcs {direction} gently along {name} for {distance:.0f} meters."
    v_custom = GuidanceVerbiageConfig(
        curve_preset=CurveVerbiagePreset.CUSTOM,
        curve_template="Sidewalk arcs {direction} gently along {name} for {distance:.0f} meters.",
    )
    gen_custom = AudioGuidanceGenerator(network, verbiage_config=v_custom)
    inst_custom = gen_custom.generate_instructions(route)
    curve_cust = [inst for inst in inst_custom if inst.get("is_curve")][0]
    assert "Sidewalk arcs right gently along Pathway for 30 meters." in curve_cust["spoken_instruction"]

