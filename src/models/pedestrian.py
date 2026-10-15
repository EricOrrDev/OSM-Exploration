"""Pydantic models for pedestrian infrastructure based on OpenSidewalks schema."""

from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class CrosswalkFeature(BaseModel):
    """Represents a marked or unmarked street crossing corridor."""

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

    @property
    def safety_score(self) -> float:
        """Heuristic score (0.0 to 1.0) assessing crossing safety for blind pedestrians."""
        score = 0.2  # Base score for any mapped crossing
        if self.crossing_type in ("traffic_signals", "marked", "zebra"):
            score += 0.2
        if self.has_signals:
            score += 0.2
        if self.has_audible_signals:
            score += 0.2  # Huge safety asset for blind pedestrians
        if self.has_tactile_paving:
            score += 0.1
        if self.has_refuge_island:
            score += 0.1
        if self.crossing_type == "unmarked":
            score -= 0.3  # Heavy penalty for unmarked crossing
        return max(0.0, min(1.0, score))


class KerbFeature(BaseModel):
    """Represents a transition between sidewalk and roadway (curb cut / curb ramp)."""

    id: int
    coordinate: Tuple[float, float]
    kerb_type: str = "unknown"          # lowered, flush, raised, rolled
    has_tactile_paving: bool = False
    height_cm: Optional[float] = None

    @property
    def is_step_free(self) -> bool:
        return self.kerb_type in ("lowered", "flush")


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
