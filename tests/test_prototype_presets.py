"""
Tests for all 6 Prototype Intersection Presets.
Verifies that short, isolated archetype routes produce the expected
screen-reader guidance and tactile cues for blind pedestrians.
"""

import pytest
from src.config import PRESETS
from src.clients.overpass_client import OverpassClient
from src.parser.osm_parser import OSMParser
from src.routing.pedestrian_graph import PedestrianGraph
from src.routing.guidance import AudioGuidanceGenerator


PROTOTYPE_KEYS = [
    "century-chandler",
    "3rd-revere",
    "colorado-straight",
    "columbia-bridge",
    "hwy20-jamison",
    "powers-hwy97",
]


@pytest.fixture(scope="module")
def client():
    return OverpassClient()


@pytest.mark.parametrize("preset_key", PROTOTYPE_KEYS)
def test_prototype_preset_routing_and_guidance(client, preset_key):
    """Verify each prototype preset loads offline fixture, routes successfully, and generates instructions."""
    assert preset_key in PRESETS, f"Preset {preset_key} not found in PRESETS"
    preset = PRESETS[preset_key]

    raw = client.fetch_pedestrian_data(
        preset["bbox"],
        fixture_name=preset.get("fixture"),
        offline=True,
    )
    assert raw is not None and "elements" in raw, f"Failed to load fixture for {preset_key}"

    parser = OSMParser()
    net = parser.parse(raw)
    assert len(net.raw_nodes) > 0, f"Network had 0 nodes for {preset_key}"

    graph = PedestrianGraph(net)
    start_nid = graph.find_nearest_node(preset["start"])
    end_nid = graph.find_nearest_node(preset["end"])
    assert start_nid is not None, f"Could not find start node for {preset_key}"
    assert end_nid is not None, f"Could not find end node for {preset_key}"

    route = graph.route(start_nid, end_nid)
    assert route is not None, f"Pathfinding failed for {preset_key}"
    # Corridors must be short (< 60 meters) to isolate the specific prototype physical archetype
    assert route.total_distance_m < 60.0, f"Route too long ({route.total_distance_m}m) for prototype {preset_key}"

    gen = AudioGuidanceGenerator(net)
    instructions = gen.generate_instructions(route)
    assert len(instructions) >= 2, f"Expected multiple guidance steps for {preset_key}"
    spoken_texts = " ".join(s["spoken_instruction"] for s in instructions)

    # Specific archetype checks
    if preset_key == "century-chandler":
        assert "Caution: Roundabout intersection" in spoken_texts
        assert "splitter island refuge" in spoken_texts or "refuge island" in spoken_texts
        assert any(s.get("tactile_cue") for s in instructions)
    elif preset_key == "3rd-revere":
        assert "4-way intersection" in spoken_texts
        assert "activation button" in spoken_texts
    elif preset_key == "colorado-straight":
        assert "Follow concrete sidewalk" in spoken_texts
        assert route.total_distance_m < 35.0
    elif preset_key == "columbia-bridge":
        assert "bridge walkway" in spoken_texts
    elif preset_key == "hwy20-jamison":
        assert "mid-block crosswalk" in spoken_texts
    elif preset_key == "powers-hwy97":
        assert "Wait on center median pedestrian refuge island" in spoken_texts
