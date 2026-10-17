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

    # Route computation
    route = graph.route(start_node, end_node)
    assert route is not None
    # Distance should be between 900m and 1500m (~1.1 km)
    assert 800.0 < route.total_distance_m < 2000.0
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

    # 1. Roundabout detection & continuous circulating traffic cue
    assert "Roundabout intersection" in spoken_text
    assert "Free-flowing traffic enters continuously from your left" in spoken_text

    # 2. Corridor continuity cues along SW Century Drive
    assert "stay on SW Century Drive" in spoken_text or "continue along SW Century Drive" in spoken_text

    # 3. Intersection classification metadata attached to crossing steps
    itypes = [inst.get("intersection_type") for inst in crossing_steps]
    assert "roundabout" in itypes
    assert "4-way intersection" in itypes or "T-junction" in itypes

    # 4. Explicit cross-street naming to ground user on map
    assert "SW Innovation Way" in spoken_text
    assert "South Safeway commercial driveway" in spoken_text
    assert "Safeway commercial driveway" in spoken_text
    assert "Safeway Drive" not in spoken_text
    assert "SW Taylor Drive" not in spoken_text

    # 5. Curb approach steps announce the upcoming street/driveway to be crossed with caution
    curb_steps = [inst for inst in instructions if inst["action"] == "APPROACH_CURB"]
    curb_text = " ".join(inst["spoken_instruction"] for inst in curb_steps)
    assert "to cross" in curb_text
    assert "SW Innovation Way" in curb_text
    assert "the Safeway commercial driveway" in curb_text or "the South Safeway commercial driveway" in curb_text
    assert "Be alert for turning customer vehicles entering or exiting the parking lot" in curb_text

