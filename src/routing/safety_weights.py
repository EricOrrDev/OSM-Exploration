"""Pedestrian Accessibility & Routing Safety Weights (Single Source of Truth).

Consolidates all routing cost multipliers, safety scores, curb penalties,
and accessibility rating thresholds in accordance with PROWAG (Public Rights-of-Way
Accessibility Guidelines), MUTCD, and blind-navigation mobility research.
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional


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
    roundabout_hazard: float = 3.0   # 3.0x severe penalty: free-flowing roundabout slip lanes lack stop control
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
class RatingThresholds:
    """Thresholds for categorizing overall route accessibility ratings."""

    high_safety_ratio: float = 0.8      # ratio <= 0.8: predominantly APS and tactile paving
    moderate_safety_ratio: float = 1.2  # ratio <= 1.2: standard marked sidewalks
    high_safety_label: str = "High Safety (APS and tactile paving throughout)"
    moderate_safety_label: str = "Moderate Safety (Standard marked sidewalks)"
    caution_required_label: str = "Caution Required (Unmarked crossings or obstacles present)"


@dataclass
class SafetyWeightsConfig:
    """Unified configuration container for pedestrian accessibility safety weights."""

    sidewalk: SidewalkMultipliers = field(default_factory=SidewalkMultipliers)
    crosswalk: CrosswalkMultipliers = field(default_factory=CrosswalkMultipliers)
    kerb: KerbMultipliers = field(default_factory=KerbMultipliers)
    safety_score: SafetyScoreWeights = field(default_factory=SafetyScoreWeights)
    rating_thresholds: RatingThresholds = field(default_factory=RatingThresholds)

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


# Global default safety weights singleton
DEFAULT_SAFETY_WEIGHTS = SafetyWeightsConfig()
