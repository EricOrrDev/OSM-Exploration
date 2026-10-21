"""Pedestrian Accessibility, Safety & Hazard Weights (Single Source of Truth).

Consolidates all routing cost multipliers, hazard metric weights, safety scores,
curb penalties, and accessibility rating thresholds in accordance with PROWAG
(Public Rights-of-Way Accessibility Guidelines), MUTCD, and blind-navigation mobility research.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple, Union


class DirectionMode(str, Enum):
    """User-selectable format for turn direction announcements."""

    DEGREES = "degrees"  # Announce turns in 15° increments (e.g. "Turn 90 degrees left")
    CLOCK = "clock"      # Announce turns using clock face positions (e.g. "Turn to 9 o'clock")


class ClockGranularity(str, Enum):
    """Clock face time granularity for spoken navigation instructions."""

    HOURLY = "hourly"            # Nearest hour (1 to 12 o'clock, 30° steps)
    HALF_HOURLY = "half_hourly"  # Half-hour resolution (15° steps: 12:30, 1:00, 1:30, etc.)


class CurveVerbiagePreset(str, Enum):
    """User-configurable verbiage presets for curving and sweeping pathways."""

    SWEEP = "sweep"      # "Sweep left for 14 meters." / "Sweep right for 19 meters."
    CURVING = "curving"  # "Follow the curving sidewalk to the left for 14 meters."
    BEAR = "bear"        # "Bear left for 14 meters."
    CUSTOM = "custom"    # Custom format string


class RoutingPreference(str, Enum):
    """User-configurable routing mode optimizing for physical accessibility or cognitive ease."""

    BALANCED = "balanced"        # Standard ADA / PROWAG accessibility weighting
    FEWER_TURNS = "fewer_turns"  # Penalizes turns and curves heavily to reduce cognitive fatigue
    SHORTEST = "shortest"        # Minimizes physical distance regardless of turn count


@dataclass
class GuidanceVerbiageConfig:
    """User-configurable verbiage and phrasing preferences for audio navigation.

    Allows blind pedestrians, researchers, and orientation & mobility (O&M) specialists
    to tune spoken direction format (degrees vs clock face) and curve verbiage ('sweep' vs 'curving').
    """

    direction_mode: DirectionMode = DirectionMode.DEGREES
    clock_granularity: ClockGranularity = ClockGranularity.HOURLY
    curve_preset: CurveVerbiagePreset = CurveVerbiagePreset.SWEEP

    # Phrasing templates
    curve_template: str = "Sweep {direction} for {distance:.0f} meters."
    turn_degree_template: str = "Turn {angle} degrees {direction}, then follow {target} for {distance:.0f} meters."
    turn_clock_template: str = "Turn to {clock}, then follow {target} for {distance:.0f} meters."
    straight_template: str = "Follow {target} for {distance:.0f} meters."

    def angle_to_clock(
        self,
        angle_deg: float,
        granularity: Optional[ClockGranularity] = None,
    ) -> str:
        """Convert a relative turn angle in degrees [-180, 180] to a clock face position.

        12 o'clock represents straight ahead (0°). Positive angles are clockwise (right),
        negative angles are counter-clockwise (left).
        """
        g = granularity or self.clock_granularity
        rel_bearing = (angle_deg + 360.0) % 360.0

        if g == ClockGranularity.HALF_HOURLY:
            # 15° steps equal 30 minutes on a clock face (24 half-hour steps across 360°)
            half_hours = int(math.floor(rel_bearing / 15.0 + 0.5)) % 24
            h = half_hours // 2
            m = (half_hours % 2) * 30
            disp_h = 12 if h == 0 else h
            if m == 0:
                return f"{disp_h} o'clock"
            return f"{disp_h}:{m:02d}"
        else:
            # Standard hourly steps (30° per hour)
            hour = int(math.floor(rel_bearing / 30.0 + 0.5)) % 12
            disp_h = 12 if hour == 0 else hour
            return f"{disp_h} o'clock"

    def format_curve(
        self,
        direction: str,
        distance_m: float,
        name: Optional[str] = None,
    ) -> str:
        """Format spoken instruction for curving / sweeping path segments."""
        if self.curve_preset == CurveVerbiagePreset.SWEEP:
            template = self.curve_template or "Sweep {direction} for {distance:.0f} meters."
        elif self.curve_preset == CurveVerbiagePreset.CURVING:
            template = "Follow the curving sidewalk to the {direction} for {distance:.0f} meters."
        elif self.curve_preset == CurveVerbiagePreset.BEAR:
            template = "Bear {direction} for {distance:.0f} meters."
        else:
            template = self.curve_template

        target = name if name else "sidewalk"
        return template.format(
            direction=direction,
            distance=distance_m,
            target=target,
            name=target,
        )

    def format_turn(
        self,
        angle_deg: int,
        direction: str,
        target: str,
        distance_m: float,
        raw_angle: Optional[float] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Format spoken turn instruction based on active direction mode (degrees vs clock)."""
        signed_angle = angle_deg if direction == "right" else -angle_deg
        raw = raw_angle if raw_angle is not None else float(signed_angle)
        clock_pos = self.angle_to_clock(raw)

        if self.direction_mode == DirectionMode.CLOCK:
            speech = self.turn_clock_template.format(
                clock=clock_pos,
                target=target,
                distance=distance_m,
                direction=direction,
            )
        else:
            speech = self.turn_degree_template.format(
                angle=angle_deg,
                direction=direction,
                target=target,
                distance=distance_m,
                clock=clock_pos,
            )

        metadata = {
            "turn_angle_deg": angle_deg,
            "turn_direction": direction,
            "clock_position": clock_pos,
            "direction_mode": self.direction_mode.value,
        }
        return speech, metadata


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
    """Unified configuration container for pedestrian accessibility safety and hazard weights."""

    sidewalk: SidewalkMultipliers = field(default_factory=SidewalkMultipliers)
    crosswalk: CrosswalkMultipliers = field(default_factory=CrosswalkMultipliers)
    kerb: KerbMultipliers = field(default_factory=KerbMultipliers)
    turn: TurnPenaltyConfig = field(default_factory=TurnPenaltyConfig)
    safety_score: SafetyScoreWeights = field(default_factory=SafetyScoreWeights)
    hazard: HazardMetricWeights = field(default_factory=HazardMetricWeights)
    rating_thresholds: RatingThresholds = field(default_factory=RatingThresholds)
    verbiage: GuidanceVerbiageConfig = field(default_factory=GuidanceVerbiageConfig)

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
        w = self.hazard
        hazard = w.base_crossing_hazard

        # Hazard penalties
        if crossing_type == "unmarked":
            hazard += w.unmarked_crossing_penalty
        if is_roundabout:
            hazard += w.roundabout_penalty
        if lanes_crossed and lanes_crossed > 2:
            hazard += w.multilane_penalty
        if not has_audible_signals:
            hazard += w.missing_aps_penalty
        if not has_signals:
            hazard += w.missing_signals_penalty
        if not has_tactile_paving:
            hazard += w.missing_tactile_penalty
        if not has_refuge_island:
            hazard += w.missing_refuge_penalty

        # Safety mitigation discounts
        if has_audible_signals:
            hazard -= w.aps_discount
        if has_signals:
            hazard -= w.signals_discount
        if crossing_type in ("traffic_signals", "marked", "zebra"):
            hazard -= w.marked_discount
        if has_refuge_island:
            hazard -= w.refuge_discount
        if has_tactile_paving:
            hazard -= w.tactile_discount

        return max(0.0, min(1.0, round(hazard, 3)))

    def compute_sidewalk_hazard_metric(
        self,
        surface: Optional[str] = None,
        smoothness: Optional[str] = None,
        has_tactile_paving: bool = False,
        incline_pct: Optional[float] = None,
    ) -> float:
        """Calculate sidewalk walkway hazard metric (0.0 = smooth/safe, 1.0 = severe hazard)."""
        w = self.hazard
        hazard = w.base_sidewalk_hazard

        if surface in ("unpaved", "dirt", "gravel", "earth", "ground"):
            hazard += w.unpaved_surface_penalty
        if smoothness in ("bad", "very_bad", "horrible"):
            hazard += w.poor_smoothness_penalty
        if incline_pct and abs(incline_pct) > 8.0:
            hazard += w.steep_incline_penalty
        if has_tactile_paving:
            hazard -= w.sidewalk_tactile_discount

        return max(0.0, min(1.0, round(hazard, 3)))

    def compute_kerb_hazard_metric(
        self,
        kerb_type: str = "unknown",
        has_tactile_paving: bool = False,
    ) -> float:
        """Calculate curb transition hazard metric (0.0 = flush/safe, 1.0 = severe hazard)."""
        w = self.hazard
        hazard = w.base_kerb_hazard

        if kerb_type in ("raised", "barrier"):
            hazard += w.raised_curb_penalty
        elif not has_tactile_paving:
            hazard += w.missing_kerb_tactile_penalty

        return max(0.0, min(1.0, round(hazard, 3)))

    def compute_accessibility_rating(
        self,
        total_effective_cost: float,
        total_distance_m: float,
    ) -> str:
        """Categorize route accessibility rating based on the cost-to-distance ratio."""
        ratio = (total_effective_cost / total_distance_m) if total_distance_m > 0 else 1.0
        if ratio <= self.rating_thresholds.high_safety_ratio:
            return self.rating_thresholds.high_safety_label
        elif ratio <= self.rating_thresholds.moderate_safety_ratio:
            return self.rating_thresholds.moderate_safety_label
        else:
            return self.rating_thresholds.caution_required_label


# Global default safety, hazard weights, and guidance verbiage singletons
DEFAULT_SAFETY_WEIGHTS = SafetyWeightsConfig()
DEFAULT_HAZARD_WEIGHTS = DEFAULT_SAFETY_WEIGHTS.hazard
DEFAULT_VERBIAGE_CONFIG = DEFAULT_SAFETY_WEIGHTS.verbiage


def get_guidance_verbiage() -> GuidanceVerbiageConfig:
    """Retrieve active global guidance verbiage configuration."""
    return DEFAULT_VERBIAGE_CONFIG


def set_guidance_verbiage(config: GuidanceVerbiageConfig) -> None:
    """Set active global guidance verbiage configuration."""
    global DEFAULT_VERBIAGE_CONFIG
    DEFAULT_VERBIAGE_CONFIG = config
    DEFAULT_SAFETY_WEIGHTS.verbiage = config


def configure_guidance_verbiage(
    direction_mode: Optional[Union[str, DirectionMode]] = None,
    clock_granularity: Optional[Union[str, ClockGranularity]] = None,
    curve_preset: Optional[Union[str, CurveVerbiagePreset]] = None,
    curve_template: Optional[str] = None,
    turn_degree_template: Optional[str] = None,
    turn_clock_template: Optional[str] = None,
    straight_template: Optional[str] = None,
) -> GuidanceVerbiageConfig:
    """Quickly reconfigure guidance verbiage (degrees vs clock face, sweeping vs curving) in one place."""
    cfg = DEFAULT_VERBIAGE_CONFIG
    if direction_mode is not None:
        cfg.direction_mode = DirectionMode(direction_mode) if isinstance(direction_mode, str) else direction_mode
    if clock_granularity is not None:
        cfg.clock_granularity = ClockGranularity(clock_granularity) if isinstance(clock_granularity, str) else clock_granularity
    if curve_preset is not None:
        cfg.curve_preset = CurveVerbiagePreset(curve_preset) if isinstance(curve_preset, str) else curve_preset
    if curve_template is not None:
        cfg.curve_template = curve_template
    if turn_degree_template is not None:
        cfg.turn_degree_template = turn_degree_template
    if turn_clock_template is not None:
        cfg.turn_clock_template = turn_clock_template
    if straight_template is not None:
        cfg.straight_template = straight_template
    return cfg
