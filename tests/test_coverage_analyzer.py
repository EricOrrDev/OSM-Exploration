"""Unit tests for CoverageAnalyzer and municipal benchmark comparison."""

import pytest
from src.clients.overpass_client import OverpassClient
from src.config import DEFAULT_BBOX
from src.parser.osm_parser import OSMParser
from src.benchmark.coverage_analyzer import CoverageAnalyzer


def test_coverage_analyzer_network_completeness():
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(DEFAULT_BBOX)
    parser = OSMParser()
    network = parser.parse(raw)

    analyzer = CoverageAnalyzer()
    stats = analyzer.analyze_network_completeness(network)

    assert stats["crosswalks"]["total"] > 0
    assert stats["crosswalks"]["with_markings_pct"] > 0
    assert stats["crosswalks"]["with_audible_signals_aps_pct"] > 0
    assert stats["kerbs"]["total"] > 0
    assert stats["sidewalks"]["total"] > 0


def test_coverage_analyzer_municipal_ground_truth():
    analyzer = CoverageAnalyzer()
    muni = analyzer.fetch_municipal_ground_truth()

    # Verify connection to local MapData/*.gpkg
    assert muni["crosswalks_total"] > 0
    assert muni["curb_ramps_total"] > 0
    assert muni["sidewalks_total"] > 0
