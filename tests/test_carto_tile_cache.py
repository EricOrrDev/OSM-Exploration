"""Unit tests for CARTO on-device raster tile caching and Leaflet offline integration."""

import math
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src.clients.carto_tile_cache import CartoTileCache, bbox_to_tile_bounds, deg2num, num2deg
from src.config import WEST_YELLOWSTONE_BBOX


def test_deg2num_and_num2deg():
    """Verify Slippy Map tile coordinate conversion round-trip math."""
    lat, lon, z = 44.056, -121.305, 14
    x, y = deg2num(lat, lon, z)

    assert isinstance(x, int)
    assert isinstance(y, int)
    assert x > 0
    assert y > 0

    # Invert back to lat/lon
    lat_deg, lon_deg = num2deg(x, y, z)
    # nw corner should be within 0.1 degrees of original coordinate
    assert abs(lat_deg - lat) < 0.1
    assert abs(lon_deg - lon) < 0.1


def test_bbox_to_tile_bounds():
    """Verify tile coordinate bounding range calculation."""
    # West Yellowstone bbox at zoom 14
    min_x, max_x, min_y, max_y = bbox_to_tile_bounds(WEST_YELLOWSTONE_BBOX, zoom=14)

    assert min_x <= max_x
    assert min_y <= max_y
    # Small town bbox should only span a couple of tiles at zoom 14
    assert (max_x - min_x + 1) <= 3
    assert (max_y - min_y + 1) <= 3


def test_carto_tile_cache_paths_and_caching(tmp_path):
    """Verify local cache path structure and tile presence detection."""
    cache = CartoTileCache(cache_dir=tmp_path, api_key="test_api_key")

    p = cache.tile_path(14, 2671, 5954, style="voyager")
    assert str(tmp_path) in str(p)
    assert p.name == "5954.png"
    assert p.parent.name == "2671"
    assert p.parent.parent.name == "14"

    # Initially tile does not exist
    assert cache.is_tile_cached(14, 2671, 5954) is False

    # Create dummy tile
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_bytes")

    assert cache.is_tile_cached(14, 2671, 5954) is True


def test_carto_tile_cache_download_and_hit(tmp_path):
    """Verify download_tile saves image and subsequent calls hit local cache without network."""
    cache = CartoTileCache(cache_dir=tmp_path, api_key="test_api_key")

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"\x89PNG\r\n\x1a\ntile_content_123"
    mock_session.get.return_value = mock_resp

    # First download: should make HTTP request
    result = cache.download_tile(14, 10, 20, style="voyager", session=mock_session)
    assert result is not None
    assert result.exists()
    assert result.read_bytes() == b"\x89PNG\r\n\x1a\ntile_content_123"
    assert mock_session.get.call_count == 1

    # Second call without force_refresh: should hit cache directly without calling session.get
    result2 = cache.download_tile(14, 10, 20, style="voyager", session=mock_session)
    assert result2 == result
    assert mock_session.get.call_count == 1  # Unchanged!


def test_carto_tile_cache_stats_and_coverage(tmp_path):
    """Verify cache coverage detection and disk storage statistics."""
    cache = CartoTileCache(cache_dir=tmp_path)

    # Empty stats
    empty_stats = cache.get_tile_stats(style="voyager")
    assert empty_stats["tile_count"] == 0
    assert empty_stats["total_bytes"] == 0

    # Write 3 mock tiles
    for y in [100, 101, 102]:
        p = cache.tile_path(14, 50, y, style="voyager")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"tile_bytes_data")

    stats = cache.get_tile_stats(style="voyager")
    assert stats["tile_count"] == 3
    assert stats["total_bytes"] == 3 * len(b"tile_bytes_data")
    assert stats["zoom_levels"] == [14]


def test_geojson_exporter_includes_on_device_tile_layer(tmp_path):
    """Verify exported Leaflet HTML contains on-device offline tile layer and fallback url."""
    from src.export.geojson_exporter import GeoJSONExporter
    from src.models.pedestrian import PedestrianNetwork
    from src.routing.pedestrian_graph import PedestrianEdge, RouteResult

    network = PedestrianNetwork(raw_nodes={1: (44.050, -121.300), 2: (44.051, -121.300)})
    edge = PedestrianEdge(u=1, v=2, length_m=10.0, effective_weight=10.0, feature_type="sidewalk")
    route = RouteResult(node_path=[1, 2], edges=[edge], total_distance_m=10.0, total_effective_cost=10.0, accessibility_rating="Moderate Safety")

    out_file = tmp_path / "test_offline_map.html"
    GeoJSONExporter.export_route_to_html(route, network, instructions=[], output_path=out_file, carto_api_key="my_carto_key")

    content = out_file.read_text(encoding="utf-8")
    assert "On-Device Cache" in content
    assert "errorTileUrl" in content
    assert "key=my_carto_key" in content
