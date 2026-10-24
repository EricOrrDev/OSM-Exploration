"""Semantic Step Qualities Model for Accessible Pedestrian Navigation.

Represents the raw, unabridged physical, topological, tactile, signal,
and hazard attributes of each navigation route step prior to text preparation.
"""

from dataclasses import asdict
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, computed_field


class StepAction(str, Enum):
    """Categorical navigation action performed during a route step."""
    WALK_SIDEWALK = "WALK_SIDEWALK"
    APPROACH_CURB = "APPROACH_CURB"
    CROSS_STREET = "CROSS_STREET"
    EXIT_CURB = "EXIT_CURB"
    WAIT_REFUGE = "WAIT_REFUGE"
    ARRIVE = "ARRIVE"


class KerbQualities(BaseModel):
    """Physical and tactile qualities of a curb transition."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    present: bool = False
    action_type: Optional[str] = None  # "step_down", "step_up"
    kerb_type: Optional[str] = None  # "lowered", "raised", "flush", "unknown"
    height_cm: Optional[float] = None
    is_step_free: bool = True
    has_tactile_paving: bool = False
    tactile_description: Optional[str] = None  # "tactile truncated domes", "tactile paving"
    cross_target: Optional[str] = None  # e.g. "SW Innovation Way", "SW Century Drive"

    @computed_field
    @property
    def tactile_paving(self) -> bool:
        return self.has_tactile_paving

    @computed_field
    @property
    def ramp_present(self) -> bool:
        return self.is_step_free


class CrossingQualities(BaseModel):
    """Intersection and roadway qualities of a street crossing."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    is_crossing: bool = False
    intersection_type: Optional[str] = None  # "roundabout", "4-way intersection", "T-junction", "mid-block crossing"
    road_crossed: Optional[str] = None
    spoken_road_name: Optional[str] = None
    corridor_street: Optional[str] = None
    is_corridor_continuation: bool = True
    markings: Optional[str] = None  # "zebra", "lines", "ladder", "unmarked"
    has_refuge_island: bool = False
    lanes_crossed: Optional[int] = None
    turning_vehicle_warning: bool = False
    semantic_crossing_type: Optional[str] = None  # "public_street", "commercial_driveway", "private_driveway"

    @computed_field
    @property
    def crossing_type(self) -> Optional[str]:
        return self.markings or self.semantic_crossing_type

    @computed_field
    @property
    def lanes_count(self) -> Optional[int]:
        return self.lanes_crossed


class SignalQualities(BaseModel):
    """Electronic and auditory traffic signal infrastructure."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    has_signals: bool = False
    has_audible_signals: bool = False  # Accessible Pedestrian Signal (APS locator tone)
    has_vibrotactile: bool = False

    @computed_field
    @property
    def signalized(self) -> bool:
        return self.has_signals

    @computed_field
    @property
    def has_aps(self) -> bool:
        return self.has_audible_signals


class ButtonQualities(BaseModel):
    """Pedestrian push-button activation infrastructure."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    has_button: bool = False
    relative_direction: Optional[str] = None  # E.g., "at 2 o'clock, 0.8 meters"
    instruction_text: Optional[str] = None

    @computed_field
    @property
    def present(self) -> bool:
        return self.has_button

    @computed_field
    @property
    def location_desc(self) -> Optional[str]:
        return self.relative_direction


class PathQualities(BaseModel):
    """Physical sidewalk, footway, surface, and grade attributes."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: Optional[str] = None
    surface: Optional[str] = None  # "concrete", "asphalt", "gravel", "unpaved"
    smoothness: Optional[str] = None
    width_m: Optional[float] = None
    incline_pct: Optional[float] = None
    has_tactile_guideway: bool = False
    is_bridge: bool = False
    is_traffic_island: bool = False

    @computed_field
    @property
    def street_name(self) -> Optional[str]:
        return self.name

    @computed_field
    @property
    def tactile_paving(self) -> bool:
        return self.has_tactile_guideway


class TurnQualities(BaseModel):
    """Angular, quantized, and clock-face orientation attributes."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    is_turn: bool = False
    is_curve: bool = False
    turn_direction: Optional[str] = None  # "left", "right"
    turn_angle_deg: int = 0  # Quantized turn angle (e.g. 15°, 30°, 45°, 60°, 90°)
    raw_turn_angle_deg: Optional[float] = None
    clock_position: Optional[str] = None  # E.g. "10 o'clock", "1:30"
    curve_arc_deg: Optional[float] = None

    @computed_field
    @property
    def relative_direction(self) -> Optional[str]:
        """Alias for turn_direction (e.g. 'left', 'right')."""
        return self.turn_direction

    @computed_field
    @property
    def bearing_change_deg(self) -> float:
        """Alias for turn_angle_deg (quantized angle in degrees)."""
        return float(self.turn_angle_deg)

    @computed_field
    @property
    def clock_bearing(self) -> Optional[str]:
        """Alias for clock_position (e.g. '10 o'clock')."""
        return self.clock_position


class HazardQualities(BaseModel):
    """Accessibility risk, safety score, and spatial conflation consistency."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    hazard_metric: float = 0.0  # 0.0 (safe) to 1.0 (hazardous)
    safety_score: float = 1.0   # 0.0 to 1.0
    has_data_anomaly: bool = False
    anomaly_cue: Optional[str] = None

    @computed_field
    @property
    def risk_score(self) -> float:
        return self.hazard_metric

    @computed_field
    @property
    def data_anomaly(self) -> bool:
        return self.has_data_anomaly


class NavigationStepQualities(BaseModel):
    """Comprehensive semantic attributes of a single route step before text preparation."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_index: int
    action: StepAction
    distance_m: float
    coordinate: List[float] = Field(default_factory=lambda: [0.0, 0.0])
    coordinates: List[List[float]] = Field(default_factory=list)
    bearing_deg: Optional[float] = None

    kerb: KerbQualities = Field(default_factory=KerbQualities)
    crossing: CrossingQualities = Field(default_factory=CrossingQualities)
    signal: SignalQualities = Field(default_factory=SignalQualities)
    button: ButtonQualities = Field(default_factory=ButtonQualities)
    path: PathQualities = Field(default_factory=PathQualities)
    turn: TurnQualities = Field(default_factory=TurnQualities)
    hazard: HazardQualities = Field(default_factory=HazardQualities)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a JSON-serializable dictionary."""
        return self.model_dump()
