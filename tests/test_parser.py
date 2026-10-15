"""Unit tests for OSMParser and OpenSidewalks models."""

import pytest
from src.clients.overpass_client import OverpassClient
from src.config import DEFAULT_BBOX
from src.parser.osm_parser import OSMParser


def test_osm_parser_elements():
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(DEFAULT_BBOX)
    parser = OSMParser()
    network = parser.parse(raw)

    assert len(network.raw_nodes) > 0
    assert len(network.crosswalks) > 0
    assert len(network.sidewalks) > 0
    assert len(network.kerbs) > 0


def test_crosswalk_tags_and_safety_score():
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(DEFAULT_BBOX)
    parser = OSMParser()
    network = parser.parse(raw)

    # Way 101: NE Franklin Ave APS Crossing
    assert 101 in network.crosswalks
    cw101 = network.crosswalks[101]
    assert cw101.has_signals is True
    assert cw101.has_audible_signals is True
    assert cw101.has_tactile_paving is True
    assert cw101.has_refuge_island is True
    assert cw101.markings == "zebra"
    assert cw101.safety_score >= 0.8  # Very high safety score

    # Way 103: Hazardous Unmarked Crossing
    assert 103 in network.crosswalks
    cw103 = network.crosswalks[103]
    assert cw103.crossing_type == "unmarked"
    assert cw103.has_audible_signals is False
    assert cw103.safety_score < 0.3  # Very low safety score


def test_kerb_features():
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(DEFAULT_BBOX)
    parser = OSMParser()
    network = parser.parse(raw)

    # Node 1 is lowered curb with tactile
    assert 1 in network.kerbs
    k1 = network.kerbs[1]
    assert k1.is_step_free is True
    assert k1.has_tactile_paving is True

    # Node 4 is raised curb without tactile
    assert 4 in network.kerbs
    k4 = network.kerbs[4]
    assert k4.is_step_free is False
    assert k4.has_tactile_paving is False
