"""Unit tests for GeoPackageRegistry and spatial index."""

from pathlib import Path
import pytest
from src.config import MAP_DATA_DIR
from src.spatial.gpkg_registry import (
    GeoPackageRegistry,
    LayerRole,
    SpatialFeature,
    haversine_distance_m,
    mercator_to_wgs84,
    parse_gpkg_geometry,
)


def test_mercator_to_wgs84():
    # Bend, OR approx in EPSG:3857: x ~ -13506500, y ~ 5472800
    lat, lon = mercator_to_wgs84(-13506573.0, 5472856.0)
    assert 43.9 < lat < 44.2
    assert -121.5 < lon < -121.2


def test_haversine_distance():
    p1 = (44.0470, -121.3314)
    p2 = (44.0470, -121.3314)
    assert haversine_distance_m(p1, p2) == 0.0

    # 1 deg latitude is approx 111 km
    p3 = (44.0570, -121.3314)
    d = haversine_distance_m(p1, p3)
    assert 1100.0 < d < 1120.0


def test_parse_gpkg_geometry_errors():
    with pytest.raises(ValueError, match="too short"):
        parse_gpkg_geometry(b"")

    with pytest.raises(ValueError, match="magic"):
        parse_gpkg_geometry(b"XX1234567890")


def test_gpkg_registry_discovery():
    registry = GeoPackageRegistry(MAP_DATA_DIR)

    assert len(registry.loaded_files) >= 3
    assert any("Crosswalk" in f for f in registry.loaded_files)
    assert any("CurbRamps" in f or "sCurbRamps" in f for f in registry.loaded_files)
    assert any("Sidewalk" in f for f in registry.loaded_files)

    # Layer counts
    assert registry.layer_counts[LayerRole.CROSSWALK] > 1000
    assert registry.layer_counts[LayerRole.CURB_RAMP] > 5000
    assert registry.layer_counts[LayerRole.SIDEWALK] > 5000


def test_gpkg_registry_spatial_query_near_safeway():
    registry = GeoPackageRegistry(MAP_DATA_DIR)

    # Safeway driveway entrance coordinates
    lat, lon = 44.0470, -121.3314
    hits = registry.query_radius(lat, lon, radius_m=20.0)

    assert len(hits) > 0
    # Must find curb ramps within 10m
    curb_hits = [f for f, d in hits if f.layer_role == LayerRole.CURB_RAMP and d <= 10.0]
    assert len(curb_hits) > 0

    nearest_cr = curb_hits[0]
    assert "SAFEWAY" in (nearest_cr.attributes.get("Crosstreet") or "")
    assert nearest_cr.attributes.get("Mainstreet") == "CENTURY"


def test_gpkg_registry_find_nearest():
    registry = GeoPackageRegistry(MAP_DATA_DIR)
    lat, lon = 44.0470, -121.3314

    nearest = registry.find_nearest(lat, lon, max_dist_m=10.0, role=LayerRole.CURB_RAMP)
    assert nearest is not None
    feature, dist = nearest
    assert dist <= 10.0
    assert feature.layer_role == LayerRole.CURB_RAMP


def test_gpkg_registry_resilience_missing_dir(tmp_path):
    empty_dir = tmp_path / "non_existent_map_data"
    registry = GeoPackageRegistry(empty_dir)
    assert len(registry.features) == 0
    assert len(registry.loaded_files) == 0
    assert registry.query_radius(44.0, -121.0, 50.0) == []
