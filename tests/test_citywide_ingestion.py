"""Unit tests for spatial grid tiling and citywide ingestion."""

import pytest
from src.clients.overpass_client import OverpassClient
from src.config import BEND_CITY_BBOX


def test_bend_city_bbox_validity():
    south, west, north, east = BEND_CITY_BBOX
    assert south < north
    assert west < east
    # Verify bounds cover Bend, OR
    assert 43.9 < south < 44.05
    assert 44.10 < north < 44.20
    assert -121.4 < west < -121.3
    assert -121.3 < east < -121.2


def test_generate_grid_tiles_2x2():
    tiles = OverpassClient.generate_grid_tiles(BEND_CITY_BBOX, rows=2, cols=2)
    assert len(tiles) == 4

    south, west, north, east = BEND_CITY_BBOX
    # First tile should start at south, west
    assert tiles[0][0] == south
    assert tiles[0][1] == west
    # Last tile should end at north, east
    assert tiles[-1][2] == north
    assert tiles[-1][3] == east


def test_generate_grid_tiles_3x3():
    tiles = OverpassClient.generate_grid_tiles(BEND_CITY_BBOX, rows=3, cols=3)
    assert len(tiles) == 9


def test_element_deduplication():
    client = OverpassClient(mock_mode=True)
    # Mock data has unique elements
    data = client.fetch_citywide_pedestrian_data(BEND_CITY_BBOX)
    elements = data.get("elements", [])
    assert len(elements) > 0

    # Ensure no duplicates by (type, id)
    seen = set()
    for el in elements:
        key = (el.get("type"), el.get("id"))
        assert key not in seen
        seen.add(key)
