"""Pydantic models for pedestrian infrastructure based on OpenSidewalks schema."""

from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# HAZARD & ACCESSIBILITY WEIGHTS (CENTRALIZED CONTROLS)
#
# Adjust hazard metric weights, penalties, and multipliers directly here.
# Changes to HAZARD_WEIGHTS or DEFAULT_SAFETY_WEIGHTS apply system-wide.
# =============================================================================
from .safety_weights import (
    DEFAULT_HAZARD_WEIGHTS,
    DEFAULT_SAFETY_WEIGHTS,
    DEFAULT_VERBIAGE_CONFIG,
    ClockGranularity,
    CrosswalkMultipliers,
    CurveVerbiagePreset,
    DirectionMode,
    GuidanceVerbiageConfig,
    HazardMetricWeights,
    KerbMultipliers,
    RatingThresholds,
    RoutingPreference,
    SafetyScoreWeights,
    SafetyWeightsConfig,
    SidewalkMultipliers,
    TurnPenaltyConfig,
    configure_guidance_verbiage,
    get_guidance_verbiage,
    set_guidance_verbiage,
)

# Active hazard weights & verbiage instances (modify attributes directly or via helper methods)
HAZARD_WEIGHTS: HazardMetricWeights = DEFAULT_HAZARD_WEIGHTS
SAFETY_WEIGHTS: SafetyWeightsConfig = DEFAULT_SAFETY_WEIGHTS
VERBIAGE_CONFIG: GuidanceVerbiageConfig = DEFAULT_VERBIAGE_CONFIG


def get_hazard_weights() -> HazardMetricWeights:
    """Retrieve the current active hazard metric weights."""
    return DEFAULT_SAFETY_WEIGHTS.hazard


def set_hazard_weights(weights: HazardMetricWeights) -> None:
    """Update the global hazard metric weights in one place."""
    global HAZARD_WEIGHTS
    DEFAULT_SAFETY_WEIGHTS.hazard = weights
    HAZARD_WEIGHTS = weights


def configure_hazard_weights(**kwargs: float) -> HazardMetricWeights:
    """Convenience helper to adjust specific hazard metric weights in one place.

    Example:
        configure_hazard_weights(roundabout_penalty=0.50, unmarked_crossing_penalty=0.60)
    """
    for key, val in kwargs.items():
        if hasattr(DEFAULT_SAFETY_WEIGHTS.hazard, key):
            setattr(DEFAULT_SAFETY_WEIGHTS.hazard, key, float(val))
        else:
            raise AttributeError(f"HazardMetricWeights has no attribute '{key}'")
    return DEFAULT_SAFETY_WEIGHTS.hazard


class CrosswalkFeature(BaseModel):
    """Represents a marked or unmarked street crossing corridor."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int
    name: Optional[str] = None
    node_ids: List[int] = Field(default_factory=list)
    coordinates: List[Tuple[float, float]] = Field(default_factory=list)
    crossing_type: Optional[str] = None  # traffic_signals, marked, unmarked, uncontrolled
    markings: Optional[str] = None       # zebra, lines, ladder, surface
    has_signals: bool = False
    has_audible_signals: bool = False   # traffic_signals:sound=yes (APS)
    has_vibrotactile: bool = False      # traffic_signals:vibration=yes
    has_tactile_paving: bool = False    # tactile_paving=yes
    has_refuge_island: bool = False     # crossing:island=yes
    has_button: bool = False            # button_operated=yes
    intersection_type: Optional[str] = None  # fourway, t, roundabout, midblock
    road_crossed: Optional[str] = None       # Name or code of road being crossed
    lanes_crossed: Optional[int] = None      # Number of vehicular lanes crossed
    has_data_anomaly: bool = False           # Flagged if multi-source data conflict detected
    data_anomaly: Optional[Any] = None       # Detailed DataAnomaly metadata

    @property
    def safety_score(self) -> float:
        """Heuristic score (0.0 to 1.0) assessing crossing safety for blind pedestrians."""
        return DEFAULT_SAFETY_WEIGHTS.compute_crosswalk_safety_score(
            crossing_type=self.crossing_type,
            has_signals=self.has_signals,
            has_audible_signals=self.has_audible_signals,
            has_tactile_paving=self.has_tactile_paving,
            has_refuge_island=self.has_refuge_island,
        )

    @property
    def hazard_metric(self) -> float:
        """Hazard metric (0.0 = safe, 1.0 = severe hazard) assessing crossing risk for blind pedestrians."""
        is_rab = (self.intersection_type == "roundabout") or ("roundabout" in str(self.name or "").lower())
        return DEFAULT_SAFETY_WEIGHTS.compute_crosswalk_hazard_metric(
            crossing_type=self.crossing_type,
            has_signals=self.has_signals,
            has_audible_signals=self.has_audible_signals,
            has_tactile_paving=self.has_tactile_paving,
            has_refuge_island=self.has_refuge_island,
            is_roundabout=is_rab,
            lanes_crossed=self.lanes_crossed,
        )

    @property
    def hazard_score(self) -> float:
        """Alias for hazard_metric."""
        return self.hazard_metric


class KerbFeature(BaseModel):
    """Represents a transition between sidewalk and roadway (curb cut / curb ramp)."""

    id: Union[int, str]
    coordinate: Tuple[float, float]
    kerb_type: str = "unknown"          # lowered, flush, raised, rolled
    has_tactile_paving: bool = False
    height_cm: Optional[float] = None

    @property
    def is_step_free(self) -> bool:
        return self.kerb_type in ("lowered", "flush")

    @property
    def hazard_metric(self) -> float:
        """Hazard metric (0.0 = flush/safe, 1.0 = severe hazard) assessing curb transition risk."""
        return DEFAULT_SAFETY_WEIGHTS.compute_kerb_hazard_metric(
            kerb_type=self.kerb_type,
            has_tactile_paving=self.has_tactile_paving,
        )

    @property
    def hazard_score(self) -> float:
        """Alias for hazard_metric."""
        return self.hazard_metric


class SidewalkFeature(BaseModel):
    """Represents a pedestrian walkway segment along a street."""

    id: int
    name: Optional[str] = None
    node_ids: List[int] = Field(default_factory=list)
    coordinates: List[Tuple[float, float]] = Field(default_factory=list)
    width_m: Optional[float] = None
    surface: Optional[str] = None       # concrete, asphalt, paving_stones, unpaved
    smoothness: Optional[str] = None    # excellent, good, intermediate, bad
    has_tactile_paving: bool = False
    incline_pct: Optional[float] = None
    footway: Optional[str] = None
    is_bridge: bool = False

    @property
    def hazard_metric(self) -> float:
        """Hazard metric (0.0 = smooth/safe, 1.0 = severe hazard) assessing walkway tripping and obstacle risks."""
        return DEFAULT_SAFETY_WEIGHTS.compute_sidewalk_hazard_metric(
            surface=self.surface,
            smoothness=self.smoothness,
            has_tactile_paving=self.has_tactile_paving,
            incline_pct=self.incline_pct,
        )

    @property
    def hazard_score(self) -> float:
        """Alias for hazard_metric."""
        return self.hazard_metric


class PedestrianNetwork(BaseModel):
    """Container holding all parsed pedestrian assets for an area."""

    crosswalks: Dict[int, CrosswalkFeature] = Field(default_factory=dict)
    kerbs: Dict[int, KerbFeature] = Field(default_factory=dict)
    sidewalks: Dict[int, SidewalkFeature] = Field(default_factory=dict)
    raw_nodes: Dict[int, Tuple[float, float]] = Field(default_factory=dict)
    button_nodes: Dict[int, Tuple[float, float]] = Field(default_factory=dict)
    node_tags: Dict[int, Dict[str, str]] = Field(default_factory=dict)

    @property
    def total_features(self) -> int:
        return len(self.crosswalks) + len(self.kerbs) + len(self.sidewalks)
