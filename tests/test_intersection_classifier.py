"""Unit tests for IntersectionClassifier."""

import pytest
from src.clients.overpass_client import OverpassClient
from src.config import PRESETS
from src.parser.osm_parser import OSMParser
from src.routing.intersection_classifier import (
    IntersectionClassifier,
    IntersectionType,
    calculate_bearing,
    normalize_angle_diff,
)
from src.routing.pedestrian_graph import PedestrianGraph


def test_bearing_and_angle_difference():
    # Due North: (0, 0) -> (1, 0)
    assert round(calculate_bearing((0.0, 0.0), (1.0, 0.0))) == 0
    # Due East: (0, 0) -> (0, 1)
    assert round(calculate_bearing((0.0, 0.0), (0.0, 1.0))) == 90
    # Due South: (1, 0) -> (0, 0)
    assert round(calculate_bearing((1.0, 0.0), (0.0, 0.0))) == 180
    # Due West: (0, 1) -> (0, 0)
    assert round(calculate_bearing((0.0, 1.0), (0.0, 0.0))) == 270

    # Angular differences
    assert normalize_angle_diff(10.0, 30.0) == 20.0
    assert normalize_angle_diff(30.0, 10.0) == -20.0
    assert normalize_angle_diff(350.0, 10.0) == 20.0
    assert normalize_angle_diff(10.0, 350.0) == -20.0


def test_intersection_classifier_municipal_matching():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)
    assert route is not None

    classifier = IntersectionClassifier(network, enable_municipal=True)

    # Classify all crosswalk edges along the route
    cw_indices = [i for i, e in enumerate(route.edges) if e.feature_type == "crosswalk"]
    assert len(cw_indices) > 0

    contexts = [classifier.classify_intersection(route, idx) for idx in cw_indices]

    # Verify municipal classifications are identified
    sources = [ctx.classification_source for ctx in contexts]
    assert "municipal_gis" in sources

    # Check for roundabout and 4-way/T-junction detection
    types = [ctx.intersection_type for ctx in contexts]
    assert IntersectionType.ROUNDABOUT in types
    assert IntersectionType.FOUR_WAY in types or IntersectionType.T_JUNCTION in types

    # Verify corridor continuity is identified
    continuations = [ctx.is_corridor_continuation for ctx in contexts]
    assert True in continuations

    # Verify spoken summaries contain critical navigation cues
    summaries = " ".join(ctx.spoken_summary for ctx in contexts)
    assert "SW Century Drive" in summaries
    assert "Caution: Roundabout" in summaries
    assert "stay on" in summaries or "continue" in summaries


def test_intersection_classifier_geometric_fallback():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)
    assert route is not None

    # Disable municipal to test pure OSM topological / geometric classification
    classifier = IntersectionClassifier(network, enable_municipal=False)

    cw_indices = [i for i, e in enumerate(route.edges) if e.feature_type == "crosswalk"]
    contexts = [classifier.classify_intersection(route, idx) for idx in cw_indices]

    for ctx in contexts:
        assert ctx.classification_source == "osm_topology"
        assert ctx.intersection_type in (
            IntersectionType.ROUNDABOUT,
            IntersectionType.FOUR_WAY,
            IntersectionType.T_JUNCTION,
            IntersectionType.MIDBLOCK,
        )
        assert len(ctx.spoken_summary) > 0


def test_normalize_street_name():
    from src.routing.intersection_classifier import normalize_street_name

    assert normalize_street_name("S SAFEWAY DR") == "South Safeway commercial driveway"
    assert normalize_street_name("SAFEWAY DRIVE") == "Safeway commercial driveway"
    assert normalize_street_name("TAYLOR") == "SW Taylor Drive"
    assert normalize_street_name("SIMPSON") == "SW Simpson Avenue"
    assert normalize_street_name("CENTURY") == "SW Century Drive"
    assert normalize_street_name("14TH") == "NW 14th Street"
    assert normalize_street_name("None") is None
    assert normalize_street_name("") is None


def test_intersection_classifier_resolves_cross_streets():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)
    assert route is not None

    classifier = IntersectionClassifier(network, enable_municipal=True)

    cw_indices = [i for i, e in enumerate(route.edges) if e.feature_type == "crosswalk"]
    contexts = [classifier.classify_intersection(route, idx) for idx in cw_indices]

    # Every single crosswalk along the corridor must have an identified cross street
    crossed_roads = [ctx.road_crossed for ctx in contexts]
    assert None not in crossed_roads

    assert "SW Taylor Drive" in crossed_roads
    assert "South Safeway commercial driveway" in crossed_roads
    assert "Safeway commercial driveway" in crossed_roads
    assert "Safeway Drive" not in crossed_roads

    # Check spoken summaries
    summaries = " ".join(ctx.spoken_summary for ctx in contexts)
    assert "Cross SW Taylor Drive" in summaries
    assert "South Safeway commercial driveway" in summaries
    assert "cross the Safeway commercial driveway" in summaries
    assert "cross Safeway Drive" not in summaries
