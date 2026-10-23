"""Anomaly and data inconsistency detection for multi-source pedestrian GIS conflation.

In urban pedestrian navigation, no single spatial data source represents an infallible "ground truth."
OpenStreetMap, municipal GIS inventories, and aerial imagery often disagree on crossing markings,
curb cut coordinates, and signal hardware.

This module detects discrepancies across sources, flags affected route segments, and generates
calibrated "elevated caution" cues for orientation and mobility guidance.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DataAnomalyType(str, Enum):
    """Categorization of data discrepancy between independent spatial sources."""
    GEOMETRY_DISCREPANCY = "geometry_discrepancy"          # Spatial coordinates diverge beyond threshold (> 5m)
    CROSSING_MARKING_CONFLICT = "marking_conflict"        # One source says marked, another says unmarked
    SIGNAL_PRESENCE_CONFLICT = "signal_conflict"          # Disagreement on visual traffic signals
    AUDIBLE_CUE_UNCERTAINTY = "audible_cue_uncertainty"   # Disagreement on APS audible chirp / vibrotactile walk phases
    INFRASTRUCTURE_DISCREPANCY = "infrastructure_missing" # Curb ramp exists in GIS but missing connected sidewalk in OSM


@dataclass
class DataAnomaly:
    """Represents a specific detected conflict between spatial datasets on a feature."""

    anomaly_type: DataAnomalyType
    source_a: str
    source_b: str
    description: str
    caution_level: str = "ELEVATED"  # "ELEVATED" or "MODERATE"
    distance_discrepancy_m: Optional[float] = None
    spoken_caution_cue: str = "Proceed with elevated caution: Inconsistent data between map sources for this crossing."


@dataclass
class AnomalyDetectionConfig:
    """Configuration thresholds for flagging multi-source data discrepancies."""

    # Distance tolerance in meters before flagging geometry discrepancy
    max_geometry_tolerance_m: float = 6.0

    # Whether anomaly detection adds an impedance penalty in Dijkstra routing
    penalize_inconsistent_data: bool = True
    anomaly_cost_multiplier: float = 1.35  # 35% virtual penalty nudges routing toward high-confidence crossings

    # Audio cue settings
    elevated_caution_enabled: bool = True
    spoken_caution_template: str = "Proceed with elevated caution: Inconsistent map data on {feature_name}."

    def detect_crossing_conflict(
        self,
        osm_marked: bool,
        gis_marked: Optional[bool],
        osm_signals: bool,
        gis_signals: Optional[bool],
        spatial_dist_m: Optional[float] = None,
    ) -> Optional[DataAnomaly]:
        """Detect and return an anomaly if OSM and GIS layers conflict."""
        if spatial_dist_m is not None and spatial_dist_m > self.max_geometry_tolerance_m:
            return DataAnomaly(
                anomaly_type=DataAnomalyType.GEOMETRY_DISCREPANCY,
                source_a="OpenStreetMap",
                source_b="Municipal_GIS",
                description=f"Crosswalk geometry misaligned by {spatial_dist_m:.1f} meters between sources.",
                distance_discrepancy_m=spatial_dist_m,
                spoken_caution_cue="Proceed with elevated caution: Inconsistent crossing alignment between map sources.",
            )

        if gis_marked is not None and osm_marked != gis_marked:
            desc = "OSM indicates marked crossing while City GIS indicates unmarked." if osm_marked else "City GIS indicates marked crossing while OSM indicates unmarked."
            return DataAnomaly(
                anomaly_type=DataAnomalyType.CROSSING_MARKING_CONFLICT,
                source_a="OpenStreetMap",
                source_b="Municipal_GIS",
                description=desc,
                spoken_caution_cue="Proceed with elevated caution: Inconsistent crosswalk marking data between sources.",
            )

        if gis_signals is not None and osm_signals != gis_signals:
            return DataAnomaly(
                anomaly_type=DataAnomalyType.SIGNAL_PRESENCE_CONFLICT,
                source_a="OpenStreetMap",
                source_b="Municipal_GIS",
                description="Traffic signal presence conflicts between OSM and municipal GIS records.",
                spoken_caution_cue="Proceed with elevated caution: Inconsistent traffic signal data between sources.",
            )

        return None
