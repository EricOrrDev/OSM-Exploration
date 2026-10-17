"""Unit tests for spatial export to GeoJSON, GeoPackage, and Leaflet HTML."""

import json
from pathlib import Path
import sqlite3
import pytest

from src.clients.overpass_client import OverpassClient
from src.config import PRESETS
from src.export.geojson_exporter import GeoJSONExporter
from src.parser.osm_parser import OSMParser
from src.routing.guidance import AudioGuidanceGenerator
from src.routing.pedestrian_graph import PedestrianGraph


@pytest.fixture
def osu_route_and_network():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)
    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)
    guidance = AudioGuidanceGenerator(network)
    instructions = guidance.generate_instructions(route)
    return route, network, instructions


def test_export_route_to_geojson(tmp_path, osu_route_and_network):
    route, network, instructions = osu_route_and_network
    out_file = tmp_path / "test_route.geojson"

    fc = GeoJSONExporter.export_route_to_geojson(route, network, instructions, out_file)

    assert out_file.exists()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) > 10

    # Verify features include corridor, segments, and waypoints
    types = [f["properties"].get("feature_type") for f in fc["features"]]
    assert "route_corridor" in types
    assert "route_segment" in types
    assert "waypoint" in types

    # Check that GeoJSON file parses cleanly as valid JSON
    with open(out_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert len(loaded["features"]) == len(fc["features"])


def test_export_route_to_gpkg(tmp_path, osu_route_and_network):
    route, network, instructions = osu_route_and_network
    out_file = tmp_path / "test_route.gpkg"

    res_path = GeoJSONExporter.export_route_to_gpkg(route, network, instructions, out_file)
    assert res_path.exists()

    conn = sqlite3.connect(str(res_path))
    c = conn.cursor()

    # Verify OGC GeoPackage tables
    tables = [r[0] for r in c.execute("SELECT table_name FROM gpkg_contents").fetchall()]
    assert "route_corridor" in tables
    assert "route_segments" in tables
    assert "route_waypoints" in tables

    # Verify record counts
    corridor_count = c.execute("SELECT count(*) FROM route_corridor").fetchone()[0]
    segment_count = c.execute("SELECT count(*) FROM route_segments").fetchone()[0]
    waypoint_count = c.execute("SELECT count(*) FROM route_waypoints").fetchone()[0]

    assert corridor_count == 1
    assert segment_count == len(route.edges)
    assert waypoint_count >= 2

    conn.close()


def test_export_route_to_html(tmp_path, osu_route_and_network):
    route, network, instructions = osu_route_and_network
    out_file = tmp_path / "test_map.html"

    res_path = GeoJSONExporter.export_route_to_html(route, network, instructions, out_file, title="Test Route Map")
    assert res_path.exists()

    content = out_file.read_text(encoding="utf-8")
    assert "leaflet.js" in content
    assert "leaflet.css" in content
    assert "Test Route Map" in content
    assert "SW Innovation Way" in content or "SW Century Drive" in content
    assert "cartocdn.com" in content
    assert "arcgisonline.com" in content


def test_export_route_to_html_carto_api_key(tmp_path, osu_route_and_network):
    route, network, instructions = osu_route_and_network
    out_file = tmp_path / "test_map_auth.html"

    res_path = GeoJSONExporter.export_route_to_html(
        route, network, instructions, out_file, title="Auth Route Map", carto_api_key="test_carto_token_123"
    )
    assert res_path.exists()

    content = out_file.read_text(encoding="utf-8")
    assert "key=test_carto_token_123" in content
    assert "rastertiles/voyager/{z}/{x}/{y}{r}.png?key=test_carto_token_123" in content
    assert "dark_all/{z}/{x}/{y}{r}.png?key=test_carto_token_123" in content
    assert "light_all/{z}/{x}/{y}{r}.png?key=test_carto_token_123" in content

