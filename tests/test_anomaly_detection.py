"""Unit tests for multi-source spatial conflation anomaly and data conflict detection."""

import pytest

from src.weights.anomaly import AnomalyDetectionConfig, DataAnomaly, DataAnomalyType
from src.weights.safety_weights import SafetyWeightsConfig


def test_anomaly_detection_geometry_mismatch():
    """Verify that geometry offsets > tolerance trigger DataAnomalyType.GEOMETRY_DISCREPANCY."""
    cfg = AnomalyDetectionConfig(max_geometry_tolerance_m=6.0)

    # Within tolerance (5.0m)
    anomaly_ok = cfg.detect_crossing_conflict(
        osm_marked=True,
        gis_marked=True,
        osm_signals=True,
        gis_signals=True,
        spatial_dist_m=5.0,
    )
    assert anomaly_ok is None

    # Exceeds tolerance (8.5m)
    anomaly_mismatch = cfg.detect_crossing_conflict(
        osm_marked=True,
        gis_marked=True,
        osm_signals=True,
        gis_signals=True,
        spatial_dist_m=8.5,
    )
    assert anomaly_mismatch is not None
    assert anomaly_mismatch.anomaly_type == DataAnomalyType.GEOMETRY_DISCREPANCY
    assert "misaligned" in anomaly_mismatch.description
    assert "elevated caution" in anomaly_mismatch.spoken_caution_cue.lower()


def test_anomaly_detection_marking_conflict():
    """Verify that contradictory marking records between OSM and City GIS trigger conflict anomaly."""
    cfg = AnomalyDetectionConfig()

    anomaly = cfg.detect_crossing_conflict(
        osm_marked=False,
        gis_marked=True,
        osm_signals=False,
        gis_signals=False,
        spatial_dist_m=2.0,
    )
    assert anomaly is not None
    assert anomaly.anomaly_type == DataAnomalyType.CROSSING_MARKING_CONFLICT
    assert "marked crossing while OSM indicates unmarked" in anomaly.description


def test_anomaly_routing_impedance_multiplier():
    """Verify that detected anomalies apply penalty multiplier to avoid uncertain crossings."""
    weights = SafetyWeightsConfig()
    normal_mult = weights.compute_crosswalk_multiplier(
        has_audible_signals=False,
        has_signals=True,
        is_marked=True,
        has_data_anomaly=False,
    )

    anomaly_mult = weights.compute_crosswalk_multiplier(
        has_audible_signals=False,
        has_signals=True,
        is_marked=True,
        has_data_anomaly=True,
    )

    assert anomaly_mult > normal_mult
    assert round(anomaly_mult, 3) == round(normal_mult * weights.anomaly.anomaly_cost_multiplier, 3)
