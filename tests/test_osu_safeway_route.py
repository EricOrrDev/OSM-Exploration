"""Unit tests for the OSU-Cascades to Safeway corridor route."""

import pytest
from src.clients.overpass_client import OverpassClient
from src.config import PRESETS
from src.parser.osm_parser import OSMParser
from src.routing.guidance import AudioGuidanceGenerator
from src.routing.pedestrian_graph import PedestrianGraph


def test_osu_safeway_preset_exists():
    assert "osu-to-safeway" in PRESETS
    preset = PRESETS["osu-to-safeway"]
    assert "start" in preset
    assert "end" in preset
    assert "bbox" in preset
    assert preset["fixture"] == "osu_cascades_safeway_pedestrian.json"


def test_osu_safeway_dataset_and_routing():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])

    parser = OSMParser()
    network = parser.parse(raw)

    assert len(network.raw_nodes) > 500
    assert len(network.crosswalks) > 20
    assert len(network.sidewalks) > 50

    graph = PedestrianGraph(network)
    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])

    assert start_node is not None
    assert end_node is not None
    assert start_node != end_node

    # Route computation from Tykeson Hall plaza (node 6250184405)
    assert start_node == 6250184405
    route = graph.route(start_node, end_node)
    assert route is not None
    # Tykeson Hall to Safeway is ~944 meters
    assert 850.0 < route.total_distance_m < 1100.0
    assert len(route.node_path) > 10


def test_osu_safeway_consolidated_audio_guidance():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])

    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)

    guidance_gen = AudioGuidanceGenerator(network)
    instructions = guidance_gen.generate_instructions(route)

    assert len(instructions) > 5
    # Consolidation should reduce instructions significantly compared to raw 90+ edges
    assert len(instructions) < len(route.edges)

    spoken_text = " ".join(inst["spoken_instruction"] for inst in instructions)
    assert "Follow" in spoken_text
    assert "meters" in spoken_text
    assert instructions[-1]["action"] == "ARRIVE"


def test_osu_safeway_intersection_and_continuity_guidance():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])

    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)

    guidance_gen = AudioGuidanceGenerator(network)
    instructions = guidance_gen.generate_instructions(route)

    crossing_steps = [inst for inst in instructions if inst["action"] == "CROSS_STREET"]
    assert len(crossing_steps) > 0

    spoken_text = " ".join(inst["spoken_instruction"] for inst in crossing_steps)

    # 1. SW Century Drive and SW Donovan Avenue crossing & corridor continuity
    assert "SW Donovan Avenue" in spoken_text
    assert "SW Century Drive" in spoken_text
    assert "stay on SW Century Drive" in spoken_text or "continue along SW Century Drive" in spoken_text
    assert "Roundabout intersection" not in spoken_text  # Cleanly conflated without false roundabout alert

    # 2. Intersection classification metadata attached to crossing steps
    itypes = [inst.get("intersection_type") for inst in crossing_steps]
    assert "4-way intersection" in itypes
    assert "T-junction" in itypes

    # 3. Explicit disambiguated street & commercial driveway naming (Safeway Driveway instead of Safeway Drive)
    assert "South Safeway commercial driveway" in spoken_text
    assert "Safeway commercial driveway" in spoken_text
    assert "Safeway Drive" not in spoken_text
    assert "SW Taylor Drive" not in spoken_text

    # 4. Refuge island spoken announcement
    all_spoken = " ".join(inst["spoken_instruction"] for inst in instructions)
    assert "center median pedestrian refuge island" in all_spoken

    # 5. Curb approach steps announce the upcoming street/driveway to be crossed with caution
    curb_steps = [inst for inst in instructions if inst["action"] == "APPROACH_CURB"]
    curb_text = " ".join(inst["spoken_instruction"] for inst in curb_steps)
    assert "to cross" in curb_text
    assert "to cross SW Donovan Avenue" in curb_text
    assert "to cross SW Century Drive" in curb_text
    assert "the Safeway commercial driveway" in curb_text or "the South Safeway commercial driveway" in curb_text
    assert "Be alert for turning customer vehicles entering or exiting the parking lot" in curb_text


def test_roundabout_avoidance_prefers_municipal_refuge_crosswalk():
    """Verify router avoids hazardous roundabout and chooses municipal refuge crosswalk {ECFA0F9D-248C-4AC1-92EF-CC29529F00C8}."""
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])

    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)

    cw_ids = {e.crosswalk.id for e in route.edges if e.crosswalk}

    # Must select crosswalk ways 1497234703 & 1497234704 ({ECFA0F9D-248C-4AC1-92EF-CC29529F00C8})
    assert 1497234703 in cw_ids
    assert 1497234704 in cw_ids

    # Must NOT use roundabout slip lane crosswalks
    assert 1497234715 not in cw_ids
    assert 1497234718 not in cw_ids


def test_roundabout_guidance_when_roundabout_traversed():
    """Verify roundabout audio guidance alerts pedestrians when a roundabout crossing is navigated."""
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])

    parser = OSMParser()
    network = parser.parse(raw)

    # Force route directly across roundabout crosswalk 1497234715
    from src.routing.pedestrian_graph import PedestrianEdge, RouteResult
    cw_rab = network.crosswalks[1497234715]
    u, v = cw_rab.node_ids[0], cw_rab.node_ids[1]
    edge = PedestrianEdge(
        u=u,
        v=v,
        length_m=12.0,
        effective_weight=12.0,
        feature_type="crosswalk",
        crosswalk=cw_rab,
    )
    fake_route = RouteResult(
        node_path=[u, v],
        edges=[edge],
        total_distance_m=12.0,
        total_effective_cost=12.0,
        accessibility_rating="Caution Required",
    )

    guidance_gen = AudioGuidanceGenerator(network)
    instructions = guidance_gen.generate_instructions(fake_route)
    spoken = " ".join(inst["spoken_instruction"] for inst in instructions)

    assert "Roundabout intersection" in spoken
    assert "Free-flowing traffic enters continuously from your left" in spoken

