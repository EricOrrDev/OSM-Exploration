"""Unit tests for centralized safety weights and routing multipliers."""

import pytest
from src.models.pedestrian import CrosswalkFeature, KerbFeature, PedestrianNetwork, SidewalkFeature
from src.routing.pedestrian_graph import PedestrianGraph
from src.routing.safety_weights import (
    DEFAULT_SAFETY_WEIGHTS,
    CrosswalkMultipliers,
    KerbMultipliers,
    RatingThresholds,
    SafetyScoreWeights,
    SafetyWeightsConfig,
    SidewalkMultipliers,
    TurnPenaltyConfig,
)


def test_default_safety_weights_values():
    """Verify default safety multipliers and scoring weights conform to accessibility specifications."""
    w = DEFAULT_SAFETY_WEIGHTS

    # Sidewalk multipliers
    assert w.sidewalk.tactile_paving == 0.85
    assert w.sidewalk.unpaved_surface == 2.0
    assert w.sidewalk.base == 1.0

    # Crosswalk multipliers
    assert w.crosswalk.aps_signals == 0.50
    assert w.crosswalk.standard_signals == 0.75
    assert w.crosswalk.marked_crossing == 0.90
    assert w.crosswalk.unmarked_crossing == 4.0
    assert w.crosswalk.refuge_island == 0.80
    assert w.crosswalk.preferred_corridor == 0.70
    assert w.crosswalk.roundabout_hazard == 3.0
    assert w.crosswalk.tactile_paving == 0.85

    # Kerb multipliers
    assert w.kerb.raised_curb == 2.0
    assert w.kerb.tactile_paving == 0.90

    # Rating thresholds
    assert w.rating_thresholds.high_safety_ratio == 0.8
    assert w.rating_thresholds.moderate_safety_ratio == 1.2


def test_compute_sidewalk_multiplier():
    """Verify sidewalk multiplier calculations."""
    w = DEFAULT_SAFETY_WEIGHTS

    # Standard paved sidewalk
    assert w.compute_sidewalk_multiplier(has_tactile_paving=False, surface="asphalt") == 1.0

    # Paved sidewalk with tactile paving
    assert w.compute_sidewalk_multiplier(has_tactile_paving=True, surface="concrete") == 0.85

    # Unpaved gravel sidewalk without tactile paving
    assert w.compute_sidewalk_multiplier(has_tactile_paving=False, surface="gravel") == 2.0

    # Unpaved dirt with tactile paving
    assert pytest.approx(w.compute_sidewalk_multiplier(has_tactile_paving=True, surface="dirt"), 0.001) == 0.85 * 2.0


def test_compute_crosswalk_multiplier():
    """Verify crosswalk multiplier calculations across various infrastructure combinations."""
    w = DEFAULT_SAFETY_WEIGHTS

    # APS crossing (50% discount)
    m_aps = w.compute_crosswalk_multiplier(has_audible_signals=True)
    assert m_aps == 0.50

    # Unmarked crossing (4.0x penalty)
    m_unmarked = w.compute_crosswalk_multiplier(crossing_type="unmarked")
    assert m_unmarked == 4.0

    # Roundabout slip lane (3.0x hazard)
    m_rab = w.compute_crosswalk_multiplier(is_roundabout=True, is_marked=True)
    assert pytest.approx(m_rab, 0.001) == 0.90 * 3.0

    # Marked crossing with median refuge island and transition kerb with tactile paving
    k = KerbFeature(id=1, coordinate=(44.0, -121.0), kerb_type="lowered", has_tactile_paving=True)
    m_refuge = w.compute_crosswalk_multiplier(
        is_marked=True,
        has_refuge_island=True,
        kerb_features=[k],
    )
    assert pytest.approx(m_refuge, 0.001) == 0.90 * 0.80 * 0.90


def test_crosswalk_feature_safety_score_delegation():
    """Verify CrosswalkFeature.safety_score delegates to safety weights engine."""
    # APS + signals + refuge + tactile
    cw_safe = CrosswalkFeature(
        id=1,
        crossing_type="marked",
        has_signals=True,
        has_audible_signals=True,
        has_tactile_paving=True,
        has_refuge_island=True,
    )
    assert cw_safe.safety_score == 1.0  # Cap at 1.0

    # Hazardous unmarked crossing
    cw_hazard = CrosswalkFeature(
        id=2,
        crossing_type="unmarked",
        has_signals=False,
    )
    assert cw_hazard.safety_score == 0.0  # 0.2 base - 0.3 unmarked, floor at 0.0


def test_compute_accessibility_rating():
    """Verify accessibility rating strings match cost/distance ratios."""
    w = DEFAULT_SAFETY_WEIGHTS

    # High safety: cost <= 0.8 * dist
    assert "High Safety" in w.compute_accessibility_rating(total_effective_cost=70.0, total_distance_m=100.0)

    # Moderate safety: cost <= 1.2 * dist
    assert "Moderate Safety" in w.compute_accessibility_rating(total_effective_cost=100.0, total_distance_m=100.0)

    # Caution required: cost > 1.2 * dist
    assert "Caution Required" in w.compute_accessibility_rating(total_effective_cost=150.0, total_distance_m=100.0)


def test_custom_safety_weights_injection():
    """Verify custom SafetyWeightsConfig modifies routing costs in PedestrianGraph."""
    network = PedestrianNetwork(
        raw_nodes={1: (44.050, -121.300), 2: (44.051, -121.300)},
        sidewalks={
            1: SidewalkFeature(id=1, node_ids=[1, 2], has_tactile_paving=True),
        },
    )

    # Default weights: tactile multiplier = 0.85
    g_default = PedestrianGraph(network)
    edge_default = g_default.adj[1][0]

    # Custom weights: tactile multiplier = 0.50
    custom_weights = SafetyWeightsConfig(
        sidewalk=SidewalkMultipliers(tactile_paving=0.50),
    )
    g_custom = PedestrianGraph(network, weights=custom_weights)
    edge_custom = g_custom.adj[1][0]

    assert edge_custom.effective_weight < edge_default.effective_weight
    assert pytest.approx(edge_custom.effective_weight / edge_default.effective_weight, 0.01) == 0.50 / 0.85


def test_turn_penalty_config_defaults():
    """Verify default turn penalty configuration values."""
    w = DEFAULT_SAFETY_WEIGHTS
    assert w.turn.turn_penalty_enabled is True
    assert w.turn.base_turn_penalty == 1.0
    assert w.turn.min_turn_angle_deg == 20.0
    assert w.turn.turn_angle_resolution_deg == 15
    assert w.turn.arc_max_edge_length_m == 20.0
    assert w.turn.arc_min_cumulative_deg == 30.0


def test_quantize_turn_angle():
    """Verify angle quantization rounds to nearest resolution step (default 15°)."""
    w = DEFAULT_SAFETY_WEIGHTS

    assert w.quantize_turn_angle(0.0) == 0
    assert w.quantize_turn_angle(4.2) == 0
    assert w.quantize_turn_angle(7.5) == 15   # half-way rounds up
    assert w.quantize_turn_angle(14.0) == 15
    assert w.quantize_turn_angle(17.7) == 15
    assert w.quantize_turn_angle(29.8) == 30
    assert w.quantize_turn_angle(40.0) == 45
    assert w.quantize_turn_angle(59.3) == 60
    assert w.quantize_turn_angle(-59.3) == 60  # absolute value
    assert w.quantize_turn_angle(85.2) == 90
    assert w.quantize_turn_angle(92.6) == 90

    # Custom resolution (e.g. 10°)
    custom_w = SafetyWeightsConfig(turn=TurnPenaltyConfig(turn_angle_resolution_deg=10))
    assert custom_w.quantize_turn_angle(59.3) == 60
    assert custom_w.quantize_turn_angle(64.0) == 60
    assert custom_w.quantize_turn_angle(66.0) == 70

