"""Centralized configuration for pedestrian accessibility safety weights, hazard scoring, and verbiage.

This module acts as the single source of truth for:
- Routing cost multipliers (APS audible signals, tactile paving, marked vs unmarked crossings, roundabouts)
- Hazard metric calculation (normalized 0.0 to 1.0 situational danger score)
- Anomaly & inconsistency detection thresholds across conflicting data sources
- Directional announcements (15° quantized angles vs clock face directions)
- Cognitive turn penalties and curve batching presets
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple

from .anomaly import AnomalyDetectionConfig, DataAnomaly, DataAnomalyType
from .hazard_metric import (
    HazardMetricWeights,
    compute_crosswalk_hazard_metric,
    compute_kerb_hazard_metric,
    compute_sidewalk_hazard_metric,
)
from .verbiage import (
    ClockGranularity,
    CurveVerbiagePreset,
    DirectionMode,
    GuidanceVerbiageConfig,
)


@dataclass
class SidewalkMultipliers:
    """Routing cost multipliers for sidewalk pedestrian segments."""

    base: float = 1.0
    tactile_paving: float = 0.85     # 15% discount: continuous tactile guideway provides reliable heading
    unpaved_surface: float = 2.0    # 2.0x penalty: dirt/gravel/unpaved surfaces are tripping hazards


@dataclass
class CrosswalkMultipliers:
    """Routing cost multipliers for street and driveway crossings."""

    base: float = 1.0
    aps_signals: float = 0.50        # 50% discount: Accessible Pedestrian Signals provide audible/vibrotactile walk phases
    standard_signals: float = 0.75   # 25% discount: visual traffic signals stop cross-traffic
    marked_crossing: float = 0.90    # 10% discount: high-visibility zebra/ladder markings alert drivers
    unmarked_crossing: float = 4.0   # 4.0x severe penalty: crossing multi-lane roadway without markings is high risk
    refuge_island: float = 0.80      # 20% discount: median refuge island splits crossing exposure into 2 shorter stages
    preferred_corridor: float = 0.70 # 30% priority discount: municipal ADA-curated safe corridor crosswalks
    roundabout_hazard: float = 5.5   # > 5.0x severe hazard penalty: free-flowing roundabout slip lanes lack stop control
    tactile_paving: float = 0.85     # 15% discount: tactile truncated domes indicate edge of roadway


@dataclass
class KerbMultipliers:
    """Routing cost multipliers for curb transitions between sidewalk and street."""

    raised_curb: float = 2.0         # 2.0x penalty: vertical curb drop-off without curb cut ramp
    tactile_paving: float = 0.90     # 10% discount: lowered curb ramp equipped with tactile warning domes


@dataclass
class SafetyScoreWeights:
    """Heuristic scoring weights (0.0 to 1.0) assessing crossing safety for blind pedestrians."""

    base_score: float = 0.2          # Base score for any mapped crossing
    marked_bonus: float = 0.2        # Marked zebra/ladder crossing
    signals_bonus: float = 0.2       # Visual traffic signals present
    aps_bonus: float = 0.2           # Accessible Pedestrian Signals (audible/vibrotactile)
    tactile_bonus: float = 0.1       # Tactile warning paving present
    refuge_bonus: float = 0.1        # Center median refuge island present
    unmarked_penalty: float = 0.3    # Heavy penalty for unmarked crossings


@dataclass
class TurnPenaltyConfig:
    """Routing cost penalties and guidance quantization for turns and curves."""

    turn_penalty_enabled: bool = True
    base_turn_penalty: float = 1.0          # Base meter penalty for a 90° turn in pathfinding
    min_turn_angle_deg: float = 15.0        # Minimum angle to recognize a distinct turn (strictly 15° quantized)
    turn_angle_resolution_deg: int = 15     # Quantization step in degrees (strictly 15° increments)
    arc_max_edge_length_m: float = 20.0     # Max length of an edge to qualify as an arc micro-segment
    arc_min_cumulative_deg: float = 30.0    # Min cumulative angle change to qualify as a curving arc

    # Cognitive fatigue & turn reduction options
    fixed_turn_penalty: float = 0.0         # Fixed penalty per turn in balanced mode
    fewer_turns_fixed_penalty: float = 25.0 # Fixed penalty per turn in FEWER_TURNS mode (reduces turn fatigue)
    fewer_turns_multiplier: float = 3.0     # Angle penalty multiplier in FEWER_TURNS mode
    fewer_turns_curve_penalty: float = 15.0 # Virtual penalty on curving micro-segments in FEWER_TURNS mode


@dataclass
class RatingThresholds:
    """Thresholds for categorizing overall route accessibility ratings."""

    high_safety_ratio: float = 0.8      # ratio <= 0.8: predominantly APS and tactile paving
    moderate_safety_ratio: float = 1.2  # ratio <= 1.2: standard marked sidewalks
    high_safety_label: str = "High Safety (APS and tactile paving throughout)"
    moderate_safety_label: str = "Moderate Safety (Standard marked sidewalks)"
    caution_required_label: str = "Caution Required (Unmarked crossings or obstacles present)"


@dataclass
class SafetyWeightsConfig:
    """Unified configuration container for pedestrian accessibility safety, hazard, and anomaly weights."""

    sidewalk: SidewalkMultipliers = field(default_factory=SidewalkMultipliers)
    crosswalk: CrosswalkMultipliers = field(default_factory=CrosswalkMultipliers)
    kerb: KerbMultipliers = field(default_factory=KerbMultipliers)
    turn: TurnPenaltyConfig = field(default_factory=TurnPenaltyConfig)
    safety_score: SafetyScoreWeights = field(default_factory=SafetyScoreWeights)
    hazard: HazardMetricWeights = field(default_factory=HazardMetricWeights)
    rating_thresholds: RatingThresholds = field(default_factory=RatingThresholds)
    verbiage: GuidanceVerbiageConfig = field(default_factory=GuidanceVerbiageConfig)
    anomaly: AnomalyDetectionConfig = field(default_factory=AnomalyDetectionConfig)

    def quantize_turn_angle(self, angle_deg: float) -> int:
        """Quantize an angle in degrees to the configured resolution (default 15°)."""
        res = max(1, self.turn.turn_angle_resolution_deg)
        return int(math.floor(abs(angle_deg) / res + 0.5)) * res

    def compute_sidewalk_multiplier(
        self,
        has_tactile_paving: bool = False,
        surface: Optional[str] = None,
    ) -> float:
        """Calculate the total effective multiplier for a sidewalk segment."""
        mult = self.sidewalk.base
        if has_tactile_paving:
            mult *= self.sidewalk.tactile_paving
        if surface in ("unpaved", "dirt", "gravel"):
            mult *= self.sidewalk.unpaved_surface
        return mult

    def compute_crosswalk_multiplier(
        self,
        has_audible_signals: bool = False,
        has_signals: bool = False,
        is_marked: bool = False,
        crossing_type: Optional[str] = None,
        has_refuge_island: bool = False,
        is_target_preferred: bool = False,
        is_roundabout: bool = False,
        has_tactile_paving: bool = False,
        kerb_features: Optional[List[Any]] = None,
        has_data_anomaly: bool = False,
    ) -> float:
        """Calculate the total effective multiplier for a crosswalk edge."""
        mult = self.crosswalk.base

        if has_audible_signals:
            mult *= self.crosswalk.aps_signals
        elif has_signals:
            mult *= self.crosswalk.standard_signals
        elif is_marked:
            mult *= self.crosswalk.marked_crossing
        elif crossing_type == "unmarked":
            mult *= self.crosswalk.unmarked_crossing

        if has_refuge_island:
            mult *= self.crosswalk.refuge_island

        if is_target_preferred:
            mult *= self.crosswalk.preferred_corridor

        if is_roundabout:
            mult *= self.crosswalk.roundabout_hazard

        if has_tactile_paving:
            mult *= self.crosswalk.tactile_paving

        # Apply kerb transitions at crossing endpoints
        if kerb_features:
            for k in kerb_features:
                if getattr(k, "kerb_type", None) == "raised":
                    mult *= self.kerb.raised_curb
                elif getattr(k, "has_tactile_paving", False):
                    mult *= self.kerb.tactile_paving

        # If data discrepancy was detected across sources, apply anomaly impedance
        if has_data_anomaly and self.anomaly.penalize_inconsistent_data:
            mult *= self.anomaly.anomaly_cost_multiplier

        return mult

    def compute_crosswalk_safety_score(
        self,
        crossing_type: Optional[str] = None,
        has_signals: bool = False,
        has_audible_signals: bool = False,
        has_tactile_paving: bool = False,
        has_refuge_island: bool = False,
    ) -> float:
        """Heuristic score (0.0 to 1.0) assessing crossing safety for blind pedestrians."""
        score = self.safety_score.base_score
        if crossing_type in ("traffic_signals", "marked", "zebra"):
            score += self.safety_score.marked_bonus
        if has_signals:
            score += self.safety_score.signals_bonus
        if has_audible_signals:
            score += self.safety_score.aps_bonus
        if has_tactile_paving:
            score += self.safety_score.tactile_bonus
        if has_refuge_island:
            score += self.safety_score.refuge_bonus
        if crossing_type == "unmarked":
            score -= self.safety_score.unmarked_penalty
        return max(0.0, min(1.0, score))

    def compute_crosswalk_hazard_metric(
        self,
        crossing_type: Optional[str] = None,
        has_signals: bool = False,
        has_audible_signals: bool = False,
        has_tactile_paving: bool = False,
        has_refuge_island: bool = False,
        is_roundabout: bool = False,
        lanes_crossed: Optional[int] = None,
    ) -> float:
        """Calculate normalized crossing hazard metric (0.0 = safe, 1.0 = maximum hazard)."""
        return compute_crosswalk_hazard_metric(
            self.hazard,
            crossing_type=crossing_type,
            has_signals=has_signals,
            has_audible_signals=has_audible_signals,
            has_tactile_paving=has_tactile_paving,
            has_refuge_island=has_refuge_island,
            is_roundabout=is_roundabout,
            lanes_crossed=lanes_crossed,
        )

    def compute_sidewalk_hazard_metric(
        self,
        surface: Optional[str] = None,
        smoothness: Optional[str] = None,
        has_tactile_paving: bool = False,
        incline_pct: Optional[float] = None,
    ) -> float:
        """Calculate sidewalk walkway hazard metric (0.0 = smooth/safe, 1.0 = severe hazard)."""
        return compute_sidewalk_hazard_metric(
            self.hazard,
            surface=surface,
            smoothness=smoothness,
            has_tactile_paving=has_tactile_paving,
            incline_pct=incline_pct,
        )

    def compute_kerb_hazard_metric(
        self,
        kerb_type: Optional[str] = None,
        has_tactile_paving: bool = False,
        is_step_free: bool = True,
    ) -> float:
        """Calculate curb transition hazard metric (0.0 = flush with tactile, 1.0 = raised drop-off)."""
        return compute_kerb_hazard_metric(
            self.hazard,
            kerb_type=kerb_type,
            has_tactile_paving=has_tactile_paving,
            is_step_free=is_step_free,
        )

    def compute_accessibility_rating(
        self,
        total_effective_cost: float,
        total_distance_m: float,
    ) -> str:
        """Categorize overall route accessibility based on effective cost ratio."""
        if total_distance_m <= 0:
            return self.rating_thresholds.high_safety_label

        ratio = total_effective_cost / total_distance_m
        if ratio <= self.rating_thresholds.high_safety_ratio:
            return self.rating_thresholds.high_safety_label
        elif ratio <= self.rating_thresholds.moderate_safety_ratio:
            return self.rating_thresholds.moderate_safety_label
        else:
            return self.rating_thresholds.caution_required_label


class RoutingPreference(str, Enum):
    """Routing preference modes for blind pedestrian pathfinding."""
    BALANCED = "balanced"        # Standard accessibility safety weighting
    FEWER_TURNS = "fewer_turns"  # Penalizes turns and curves to reduce cognitive fatigue
    SHORTEST = "shortest"        # Raw distance minimization (bypasses safety multipliers)


# Global default instances
DEFAULT_SAFETY_WEIGHTS = SafetyWeightsConfig()
DEFAULT_HAZARD_WEIGHTS = DEFAULT_SAFETY_WEIGHTS.hazard
DEFAULT_VERBIAGE_CONFIG = DEFAULT_SAFETY_WEIGHTS.verbiage
HAZARD_WEIGHTS = DEFAULT_SAFETY_WEIGHTS.hazard
VERBIAGE_CONFIG = DEFAULT_SAFETY_WEIGHTS.verbiage
ANOMALY_CONFIG = DEFAULT_SAFETY_WEIGHTS.anomaly


def get_guidance_verbiage() -> GuidanceVerbiageConfig:
    """Retrieve the current active guidance verbiage configuration."""
    return DEFAULT_SAFETY_WEIGHTS.verbiage


def set_guidance_verbiage(config: GuidanceVerbiageConfig) -> None:
    """Update the active guidance verbiage configuration."""
    DEFAULT_SAFETY_WEIGHTS.verbiage = config


def configure_hazard_weights(
    base_crossing_hazard: Optional[float] = None,
    unmarked_crossing_penalty: Optional[float] = None,
    roundabout_penalty: Optional[float] = None,
    multilane_penalty: Optional[float] = None,
    missing_aps_penalty: Optional[float] = None,
    missing_signals_penalty: Optional[float] = None,
    missing_tactile_penalty: Optional[float] = None,
    missing_refuge_penalty: Optional[float] = None,
    aps_discount: Optional[float] = None,
    signals_discount: Optional[float] = None,
    marked_discount: Optional[float] = None,
    refuge_discount: Optional[float] = None,
    tactile_discount: Optional[float] = None,
    unpaved_surface_penalty: Optional[float] = None,
    poor_smoothness_penalty: Optional[float] = None,
    steep_incline_penalty: Optional[float] = None,
    sidewalk_tactile_discount: Optional[float] = None,
    raised_curb_penalty: Optional[float] = None,
    missing_kerb_tactile_penalty: Optional[float] = None,
) -> HazardMetricWeights:
    """Helper function to update hazard metric weights in the centralized default instance."""
    w = DEFAULT_SAFETY_WEIGHTS.hazard
    if base_crossing_hazard is not None:
        w.base_crossing_hazard = base_crossing_hazard
    if unmarked_crossing_penalty is not None:
        w.unmarked_crossing_penalty = unmarked_crossing_penalty
    if roundabout_penalty is not None:
        w.roundabout_penalty = roundabout_penalty
    if multilane_penalty is not None:
        w.multilane_penalty = multilane_penalty
    if missing_aps_penalty is not None:
        w.missing_aps_penalty = missing_aps_penalty
    if missing_signals_penalty is not None:
        w.missing_signals_penalty = missing_signals_penalty
    if missing_tactile_penalty is not None:
        w.missing_tactile_penalty = missing_tactile_penalty
    if missing_refuge_penalty is not None:
        w.missing_refuge_penalty = missing_refuge_penalty
    if aps_discount is not None:
        w.aps_discount = aps_discount
    if signals_discount is not None:
        w.signals_discount = signals_discount
    if marked_discount is not None:
        w.marked_discount = marked_discount
    if refuge_discount is not None:
        w.refuge_discount = refuge_discount
    if tactile_discount is not None:
        w.tactile_discount = tactile_discount
    if unpaved_surface_penalty is not None:
        w.unpaved_surface_penalty = unpaved_surface_penalty
    if poor_smoothness_penalty is not None:
        w.poor_smoothness_penalty = poor_smoothness_penalty
    if steep_incline_penalty is not None:
        w.steep_incline_penalty = steep_incline_penalty
    if sidewalk_tactile_discount is not None:
        w.sidewalk_tactile_discount = sidewalk_tactile_discount
    if raised_curb_penalty is not None:
        w.raised_curb_penalty = raised_curb_penalty
    if missing_kerb_tactile_penalty is not None:
        w.missing_kerb_tactile_penalty = missing_kerb_tactile_penalty
    return w


def configure_guidance_verbiage(
    direction_mode: Optional[DirectionMode] = None,
    clock_granularity: Optional[ClockGranularity] = None,
    curve_preset: Optional[CurveVerbiagePreset] = None,
    curve_template: Optional[str] = None,
    turn_degree_template: Optional[str] = None,
    turn_clock_template: Optional[str] = None,
) -> GuidanceVerbiageConfig:
    """Helper function to update verbiage and direction mode in the centralized default instance."""
    v = DEFAULT_SAFETY_WEIGHTS.verbiage
    if direction_mode is not None:
        v.direction_mode = direction_mode
    if clock_granularity is not None:
        v.clock_granularity = clock_granularity
    if curve_preset is not None:
        v.curve_preset = curve_preset
    if curve_template is not None:
        v.curve_template = curve_template
    if turn_degree_template is not None:
        v.turn_degree_template = turn_degree_template
    if turn_clock_template is not None:
        v.turn_clock_template = turn_clock_template
    return v
