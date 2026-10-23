"""Hazard metric calculations evaluating situational risk for blind and low-vision pedestrians.

Evaluates situational danger on a normalized 0.0 (safe / low risk) to 1.0 (severe hazard) scale.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class HazardMetricWeights:
    """Configurable weights for computing the blind-pedestrian hazard metric.

    The hazard metric evaluates situational danger on a normalized 0.0 (safe / low risk)
    to 1.0 (maximum danger / severe hazard) scale. Adjust these weights in one place
    to calibrate risk assessment across all infrastructure models.
    """

    # Baseline crossing exposure hazard
    base_crossing_hazard: float = 0.40

    # Crosswalk Hazard Penalties (Increases risk score)
    unmarked_crossing_penalty: float = 0.40   # Severe hazard: no markings or yield control
    roundabout_penalty: float = 0.60          # Extreme hazard: free-flowing roundabout traffic without signals (> 5x normal crossing risk)
    multilane_penalty: float = 0.15           # Hazard: crossing > 2 vehicular lanes
    missing_aps_penalty: float = 0.15         # Hazard: signal present but no audible / vibrotactile guidance
    missing_signals_penalty: float = 0.10     # Hazard: no visual traffic lights
    missing_tactile_penalty: float = 0.10     # Hazard: no curb edge warning truncated domes
    missing_refuge_penalty: float = 0.10      # Hazard: continuous multi-lane crossing without refuge island

    # Crosswalk Safety Mitigations (Reduces hazard score)
    aps_discount: float = 0.25                # Accessible Pedestrian Signals provide clear audible walk phase
    signals_discount: float = 0.15            # Standard visual signals stop vehicular traffic
    marked_discount: float = 0.15             # High-visibility marked zebra/ladder crosswalk
    refuge_discount: float = 0.15             # Protected center median refuge island splits crossing
    tactile_discount: float = 0.10            # Tactile truncated domes indicate edge of roadway

    # Sidewalk Tripping & Obstacle Hazards
    base_sidewalk_hazard: float = 0.05
    unpaved_surface_penalty: float = 0.40     # Dirt/gravel surfaces are tripping hazards
    poor_smoothness_penalty: float = 0.25     # Cracked, uneven, or bad pavement
    steep_incline_penalty: float = 0.20       # Longitudinal slope > 8% (exceeds PROWAG limit)
    sidewalk_tactile_discount: float = 0.10   # Continuous directional tactile paving

    # Kerb / Curb Transition Hazards
    base_kerb_hazard: float = 0.05
    raised_curb_penalty: float = 0.50         # Vertical curb drop without ramp cut
    missing_kerb_tactile_penalty: float = 0.20 # Curb ramp lacking tactile truncated domes


def compute_crosswalk_hazard_metric(
    weights: HazardMetricWeights,
    crossing_type: Optional[str] = None,
    has_signals: bool = False,
    has_audible_signals: bool = False,
    has_tactile_paving: bool = False,
    has_refuge_island: bool = False,
    is_roundabout: bool = False,
    lanes_crossed: Optional[int] = None,
) -> float:
    """Calculate normalized crossing hazard metric (0.0 = safe, 1.0 = maximum hazard)."""
    hazard = weights.base_crossing_hazard

    # Hazard penalties
    if crossing_type == "unmarked":
        hazard += weights.unmarked_crossing_penalty
    if is_roundabout:
        hazard += weights.roundabout_penalty
    if lanes_crossed and lanes_crossed > 2:
        hazard += weights.multilane_penalty
    if not has_audible_signals:
        hazard += weights.missing_aps_penalty
    if not has_signals:
        hazard += weights.missing_signals_penalty
    if not has_tactile_paving:
        hazard += weights.missing_tactile_penalty
    if not has_refuge_island:
        hazard += weights.missing_refuge_penalty

    # Safety mitigation discounts
    if has_audible_signals:
        hazard -= weights.aps_discount
    if has_signals:
        hazard -= weights.signals_discount
    if crossing_type in ("traffic_signals", "marked", "zebra"):
        hazard -= weights.marked_discount
    if has_refuge_island:
        hazard -= weights.refuge_discount
    if has_tactile_paving:
        hazard -= weights.tactile_discount

    return max(0.0, min(1.0, round(hazard, 3)))


def compute_sidewalk_hazard_metric(
    weights: HazardMetricWeights,
    surface: Optional[str] = None,
    smoothness: Optional[str] = None,
    has_tactile_paving: bool = False,
    incline_pct: Optional[float] = None,
) -> float:
    """Calculate sidewalk walkway hazard metric (0.0 = smooth/safe, 1.0 = severe hazard)."""
    hazard = weights.base_sidewalk_hazard
    if surface in ("unpaved", "dirt", "gravel", "grass"):
        hazard += weights.unpaved_surface_penalty
    if smoothness in ("bad", "very_bad", "horrible"):
        hazard += weights.poor_smoothness_penalty
    if incline_pct and abs(incline_pct) > 8.0:
        hazard += weights.steep_incline_penalty
    if has_tactile_paving:
        hazard -= weights.sidewalk_tactile_discount
    return max(0.0, min(1.0, round(hazard, 3)))


def compute_kerb_hazard_metric(
    weights: HazardMetricWeights,
    kerb_type: Optional[str] = None,
    has_tactile_paving: bool = False,
    is_step_free: bool = True,
) -> float:
    """Calculate curb transition hazard metric (0.0 = flush with tactile, 1.0 = raised drop-off)."""
    hazard = weights.base_kerb_hazard
    if kerb_type == "raised" or not is_step_free:
        hazard += weights.raised_curb_penalty
    if not has_tactile_paving:
        hazard += weights.missing_kerb_tactile_penalty
    return max(0.0, min(1.0, round(hazard, 3)))
