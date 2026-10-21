"""Pedestrian Accessibility & Routing Safety Weights (Re-export Shim).

All safety, hazard, and routing weights are defined in `src.models.safety_weights`
to serve as the single source of truth across models, routing, and guidance.
"""

from ..models.safety_weights import (
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

__all__ = [
    "DEFAULT_HAZARD_WEIGHTS",
    "DEFAULT_SAFETY_WEIGHTS",
    "DEFAULT_VERBIAGE_CONFIG",
    "ClockGranularity",
    "CrosswalkMultipliers",
    "CurveVerbiagePreset",
    "DirectionMode",
    "GuidanceVerbiageConfig",
    "HazardMetricWeights",
    "KerbMultipliers",
    "RatingThresholds",
    "RoutingPreference",
    "SafetyScoreWeights",
    "SafetyWeightsConfig",
    "SidewalkMultipliers",
    "TurnPenaltyConfig",
    "configure_guidance_verbiage",
    "get_guidance_verbiage",
    "set_guidance_verbiage",
]
