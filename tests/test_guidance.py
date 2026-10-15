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
