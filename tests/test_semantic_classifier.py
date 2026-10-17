"""Unit tests for SemanticRoadClassifier."""

import pytest
from src.spatial.semantic_classifier import (
    SemanticCrossingType,
    SemanticRoadClassifier,
)


def test_safeway_commercial_driveway_disambiguation():
    clf = SemanticRoadClassifier()

    res1 = clf.classify("SAFEWAY DRIVE", municipal_street_class="A")
    assert res1.crossing_type == SemanticCrossingType.COMMERCIAL_DRIVEWAY
    assert res1.canonical_name == "Safeway commercial driveway"
    assert res1.spoken_road_name == "the Safeway commercial driveway"
    assert res1.turning_vehicle_warning is True

    res2 = clf.classify("S SAFEWAY DR")
    assert res2.crossing_type == SemanticCrossingType.COMMERCIAL_DRIVEWAY
    assert res2.canonical_name == "South Safeway commercial driveway"
    assert res2.spoken_road_name == "the South Safeway commercial driveway"
    assert res2.turning_vehicle_warning is True

    res3 = clf.classify("CENTURY - SAFEWAY DRIVE")
    assert res3.crossing_type == SemanticCrossingType.COMMERCIAL_DRIVEWAY
    assert res3.canonical_name == "Safeway commercial driveway"


def test_other_commercial_brands():
    clf = SemanticRoadClassifier()

    res_fm = clf.classify("NORTH FRED MEYER ENTRANCE")
    assert res_fm.crossing_type == SemanticCrossingType.COMMERCIAL_DRIVEWAY
    assert res_fm.canonical_name == "North Fred Meyer store entrance"
    assert res_fm.turning_vehicle_warning is True

    res_sb = clf.classify("STARBUCKS DRIVEWAY")
    assert res_sb.crossing_type == SemanticCrossingType.COMMERCIAL_DRIVEWAY
    assert res_sb.canonical_name == "Starbucks driveway"

    res_wm = clf.classify("WALMART PARKING LOT")
    assert res_wm.crossing_type == SemanticCrossingType.COMMERCIAL_DRIVEWAY
    assert res_wm.canonical_name == "Walmart parking lot entrance"


def test_public_street_canonicalization():
    clf = SemanticRoadClassifier()

    res_cent = clf.classify("CENTURY")
    assert res_cent.crossing_type == SemanticCrossingType.PUBLIC_STREET
    assert res_cent.canonical_name == "SW Century Drive"
    assert res_cent.spoken_road_name == "SW Century Drive"
    assert res_cent.turning_vehicle_warning is False

    res_taylor = clf.classify("TAYLOR")
    assert res_taylor.crossing_type == SemanticCrossingType.PUBLIC_STREET
    assert res_taylor.canonical_name == "SW Taylor Drive"

    res_simp = clf.classify("SIMPSON")
    assert res_simp.crossing_type == SemanticCrossingType.PUBLIC_STREET
    assert res_simp.canonical_name == "SW Simpson Avenue"


def test_special_access_types():
    clf = SemanticRoadClassifier()

    res_alley = clf.classify("TIN PAN ALLEY")
    assert res_alley.crossing_type == SemanticCrossingType.SERVICE_ALLEY
    assert res_alley.canonical_name == "Tin Pan Alley"

    res_fire = clf.classify("FIRE STATION S SIDE")
    assert res_fire.crossing_type == SemanticCrossingType.COMMERCIAL_DRIVEWAY
    assert res_fire.canonical_name == "Fire Station south driveway"
    assert res_fire.turning_vehicle_warning is True

    res_priv = clf.classify("PRIVATE")
    assert res_priv.crossing_type == SemanticCrossingType.PRIVATE_DRIVEWAY
    assert res_priv.canonical_name == "private driveway"


def test_osm_tags_override():
    clf = SemanticRoadClassifier()

    res_osm_dw = clf.classify(osm_tags={"highway": "service", "service": "driveway"})
    assert res_osm_dw.crossing_type == SemanticCrossingType.PRIVATE_DRIVEWAY
    assert res_osm_dw.canonical_name == "private driveway"

    res_osm_park = clf.classify(osm_tags={"highway": "service", "service": "parking_aisle"})
    assert res_osm_park.crossing_type == SemanticCrossingType.PARKING_LOT_ACCESS
    assert res_osm_park.turning_vehicle_warning is True


def test_geometric_fallback():
    clf = SemanticRoadClassifier()

    # Narrow width < 6m inferred as driveway
    res_narrow = clf.classify(None, crossing_width_m=4.5)
    assert res_narrow.crossing_type == SemanticCrossingType.COMMERCIAL_DRIVEWAY
    assert res_narrow.confidence == "LOW"
    assert res_narrow.turning_vehicle_warning is True

    # Wider road >= 6m inferred as public street
    res_wide = clf.classify(None, crossing_width_m=8.0)
    assert res_wide.crossing_type == SemanticCrossingType.PUBLIC_STREET
    assert res_wide.confidence == "LOW"
