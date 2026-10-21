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
    assert w.crosswalk.roundabout_hazard == 5.5
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

    # Roundabout slip lane (> 5.0x hazard)
    m_rab = w.compute_crosswalk_multiplier(is_roundabout=True, is_marked=True)
    assert pytest.approx(m_rab, 0.001) == 0.90 * 5.5

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
    assert w.turn.min_turn_angle_deg == 15.0
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


def test_hazard_metric_accessibility_from_models():
    """Verify hazard metric weights are directly accessible and adjustable in src.models.pedestrian."""
    from src.models.pedestrian import (
        HAZARD_WEIGHTS,
        HazardMetricWeights,
        configure_hazard_weights,
        get_hazard_weights,
        set_hazard_weights,
    )

    # Weights accessible directly from models module
    assert isinstance(HAZARD_WEIGHTS, HazardMetricWeights)
    assert HAZARD_WEIGHTS.base_crossing_hazard == 0.40
    assert HAZARD_WEIGHTS.unmarked_crossing_penalty == 0.40
    assert HAZARD_WEIGHTS.roundabout_penalty == 0.60
    assert HAZARD_WEIGHTS.aps_discount == 0.25

    # Getter returns identical active instance
    assert get_hazard_weights() is HAZARD_WEIGHTS


def test_crosswalk_hazard_metric_calculation():
    """Verify CrosswalkFeature.hazard_metric accurately computes crossing risk."""
    from src.models.pedestrian import CrosswalkFeature

    # 1. Ideal safe crossing
    cw_safe = CrosswalkFeature(
        id=10,
        crossing_type="marked",
        has_signals=True,
        has_audible_signals=True,
        has_tactile_paving=True,
        has_refuge_island=True,
    )
    assert cw_safe.hazard_metric == 0.0  # Safe
    assert cw_safe.hazard_score == 0.0   # Alias works

    # 2. Maximum hazard crossing (unmarked, multi-lane, no signals, no refuge, no tactile)
    cw_extreme = CrosswalkFeature(
        id=11,
        crossing_type="unmarked",
        has_signals=False,
        has_audible_signals=False,
        has_tactile_paving=False,
        has_refuge_island=False,
        lanes_crossed=4,
    )
    assert cw_extreme.hazard_metric == 1.0  # Max risk capped at 1.0

    # 3. Roundabout slip lane crossing
    cw_roundabout = CrosswalkFeature(
        id=12,
        name="Century & Chandler Roundabout slip lane",
        intersection_type="roundabout",
        crossing_type="marked",
        has_signals=False,
        has_audible_signals=False,
        has_tactile_paving=True,
        has_refuge_island=True,
    )
    assert cw_roundabout.hazard_metric > 0.40  # Elevated risk due to roundabout penalty


def test_sidewalk_and_kerb_hazard_metric():
    """Verify SidewalkFeature and KerbFeature compute hazard metrics."""
    from src.models.pedestrian import KerbFeature, SidewalkFeature

    # Smooth paved sidewalk
    sw_safe = SidewalkFeature(id=20, surface="concrete", smoothness="good", has_tactile_paving=True)
    assert sw_safe.hazard_metric == 0.0

    # Hazardous unpaved steep sidewalk
    sw_hazard = SidewalkFeature(id=21, surface="dirt", incline_pct=12.0)
    assert sw_hazard.hazard_metric >= 0.50

    # Flush curb cut with tactile paving
    kerb_safe = KerbFeature(id=30, coordinate=(44.0, -121.3), kerb_type="lowered", has_tactile_paving=True)
    assert kerb_safe.hazard_metric == 0.05

    # Raised curb drop-off without ramp
    kerb_hazard = KerbFeature(id=31, coordinate=(44.0, -121.3), kerb_type="raised")
    assert kerb_hazard.hazard_metric >= 0.50


def test_adjusting_hazard_weights_in_one_place():
    """Verify adjusting hazard weights in one place updates all calculations system-wide."""
    from src.models.pedestrian import (
        CrosswalkFeature,
        HAZARD_WEIGHTS,
        configure_hazard_weights,
    )

    cw = CrosswalkFeature(
        id=40,
        intersection_type="roundabout",
        crossing_type="marked",
        has_signals=False,
        has_refuge_island=True,
    )
    initial_hazard = cw.hazard_metric
    assert initial_hazard >= 0.70  # Extreme risk for roundabout

    # Adjust roundabout penalty in one place (e.g. reduce to 0.20)
    try:
        configure_hazard_weights(roundabout_penalty=0.20)
        assert HAZARD_WEIGHTS.roundabout_penalty == 0.20
        new_hazard = cw.hazard_metric
        assert new_hazard < initial_hazard
    finally:
        # Reset back to default 0.60
        configure_hazard_weights(roundabout_penalty=0.60)
        assert HAZARD_WEIGHTS.roundabout_penalty == 0.60


def test_roundabout_hazard_more_than_five_times_normal():
    """Verify roundabout hazard multiplier and risk penalty exceed normal crossing values by > 5x."""
    w = DEFAULT_SAFETY_WEIGHTS

    # Normal signalized marked crossing multiplier: 0.90 * 0.75 = 0.675
    normal_mult = w.compute_crosswalk_multiplier(is_marked=True, has_signals=True)
    # Roundabout crossing multiplier: 0.90 * 5.5 = 4.95
    rab_mult = w.compute_crosswalk_multiplier(is_marked=True, is_roundabout=True)

    ratio = rab_mult / normal_mult
    assert ratio > 5.0, f"Roundabout multiplier ratio {ratio:.2f} should be > 5.0x normal"

    # Also exceeds unmarked/standard crossing by >= 5.5x
    base_crossing_mult = w.compute_crosswalk_multiplier(is_marked=True)
    assert (rab_mult / base_crossing_mult) >= 5.5

    # Safe crossing with APS and signals: hazard = 0.05
    normal_aps_hazard = w.compute_crosswalk_hazard_metric(crossing_type="marked", has_signals=True, has_audible_signals=True)
    # Roundabout crossing hazard metric: 1.0 (maximum situational risk)
    rab_hazard = w.compute_crosswalk_hazard_metric(crossing_type="marked", is_roundabout=True)

    assert normal_aps_hazard == 0.05
    assert rab_hazard == 1.0
    hazard_ratio = rab_hazard / normal_aps_hazard
    assert hazard_ratio > 5.0, f"Roundabout hazard metric ratio {hazard_ratio:.2f} should be > 5.0x normal"


def test_guidance_verbiage_config_and_clock_face():
    """Verify GuidanceVerbiageConfig accurately converts angles to clock face directions."""
    from src.models.safety_weights import (
        ClockGranularity,
        CurveVerbiagePreset,
        DirectionMode,
        GuidanceVerbiageConfig,
        configure_guidance_verbiage,
        get_guidance_verbiage,
    )

    cfg = GuidanceVerbiageConfig()

    # Default hourly mode
    assert cfg.angle_to_clock(0.0) == "12 o'clock"       # Straight ahead
    assert cfg.angle_to_clock(30.0) == "1 o'clock"       # 30° right
    assert cfg.angle_to_clock(60.0) == "2 o'clock"       # 60° right
    assert cfg.angle_to_clock(90.0) == "3 o'clock"       # 90° right
    assert cfg.angle_to_clock(180.0) == "6 o'clock"      # Behind / reverse
    assert cfg.angle_to_clock(-90.0) == "9 o'clock"      # 90° left (270°)
    assert cfg.angle_to_clock(-60.0) == "10 o'clock"     # 60° left (300°)
    assert cfg.angle_to_clock(-30.0) == "11 o'clock"     # 30° left (330°)

    # Half-hourly mode (15° resolution = 30 minutes on clock)
    assert cfg.angle_to_clock(15.0, granularity=ClockGranularity.HALF_HOURLY) == "12:30"
    assert cfg.angle_to_clock(30.0, granularity=ClockGranularity.HALF_HOURLY) == "1 o'clock"
    assert cfg.angle_to_clock(45.0, granularity=ClockGranularity.HALF_HOURLY) == "1:30"
    assert cfg.angle_to_clock(-15.0, granularity=ClockGranularity.HALF_HOURLY) == "11:30"
    assert cfg.angle_to_clock(-45.0, granularity=ClockGranularity.HALF_HOURLY) == "10:30"
    assert cfg.angle_to_clock(-90.0, granularity=ClockGranularity.HALF_HOURLY) == "9 o'clock"

    # Curve formatting
    assert cfg.format_curve("left", 25.0) == "Sweep left for 25 meters."
    assert cfg.format_curve("right", 18.0) == "Sweep right for 18 meters."

    # Turn formatting: Degrees vs Clock
    speech_deg, meta_deg = cfg.format_turn(90, "left", "Sidewalk", 45.0, raw_angle=-90.0)
    assert speech_deg == "Turn 90 degrees left, then follow Sidewalk for 45 meters."
    assert meta_deg["clock_position"] == "9 o'clock"
    assert meta_deg["turn_angle_deg"] == 90

    cfg.direction_mode = DirectionMode.CLOCK
    speech_clk, meta_clk = cfg.format_turn(90, "left", "Sidewalk", 45.0, raw_angle=-90.0)
    assert speech_clk == "Turn to 9 o'clock, then follow Sidewalk for 45 meters."
    assert meta_clk["clock_position"] == "9 o'clock"

    # Reconfigure global helper
    configure_guidance_verbiage(direction_mode=DirectionMode.DEGREES)
    assert get_guidance_verbiage().direction_mode == DirectionMode.DEGREES


def test_fewer_turns_routing_preference():
    """Verify FEWER_TURNS preference chooses a single sharp turn route over a route with multiple curving turns."""
    from src.models.pedestrian import PedestrianNetwork, SidewalkFeature
    from src.routing.pedestrian_graph import PedestrianGraph, RoutingPreference

    # Construct two alternate paths between Node 1 and Node 10:
    # Path A (Single Sharp Turn):
    #   1 -> 2 -> 10 (1 sharp 90° turn at node 2)
    #   Segment 1-2: 50m (east)
    #   Segment 2-10: 50m (north)
    #   Total physical length = 100m, 1 turn.
    #
    # Path B (Winding / Curving Path with 4 bends):
    #   1 -> 3 -> 4 -> 5 -> 10
    #   Each segment is 23m. Total physical length = 92m (slightly shorter physically!).
    #   Heading angles:
    #     1->3: 45°
    #     3->4: 70° (+25° turn)
    #     4->5: 30° (-40° turn)
    #     5->10: 0° (-30° turn)
    #   Total turns = 3-4 direction changes.
    network = PedestrianNetwork(
        raw_nodes={
            1: (44.0500, -121.3010),
            2: (44.0500, -121.3003),
            10: (44.0507, -121.3003),
            # Winding path nodes
            3: (44.0502, -121.3008),
            4: (44.0503, -121.3006),
            5: (44.0505, -121.3005),
        },
        sidewalks={
            1: SidewalkFeature(id=1, node_ids=[1, 2], name="Straight East"),
            2: SidewalkFeature(id=2, node_ids=[2, 10], name="Straight North"),
            3: SidewalkFeature(id=3, node_ids=[1, 3, 4, 5, 10], name="Winding Arc"),
        },
    )

    graph = PedestrianGraph(network)

    # In shortest mode, Path B (92m) is physically shorter than Path A (100m)
    route_shortest = graph.route(1, 10, preference=RoutingPreference.SHORTEST)
    assert route_shortest is not None
    assert 3 in route_shortest.node_path  # Selected the winding path B because it's shorter

    # In FEWER_TURNS mode, the cognitive overhead of 4 turns outweighs the 8m physical difference,
    # so Path A (1 sharp turn) MUST be chosen!
    route_fewer = graph.route(1, 10, preference=RoutingPreference.FEWER_TURNS)
    assert route_fewer is not None
    assert 2 in route_fewer.node_path  # Selected Path A (1 turn)
    assert 3 not in route_fewer.node_path


