"""Text Preparation Layer & User-Tunable Guidance Formatter.

Transforms raw NavigationStepQualities into customizable, orientation-and-mobility
calibrated spoken instructions based on user verbosity, stride length, and feature toggles.
"""

from enum import Enum
import math
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from ..models.qualities import NavigationStepQualities, StepAction
from ..weights.verbiage import (
    ClockGranularity,
    CurveVerbiagePreset,
    DirectionMode,
    DistanceUnit,
    GuidanceVerbiageConfig,
)


class VerbosityLevel(str, Enum):
    """User-selectable verbosity scale for spoken instructions."""
    MINIMAL = "minimal"      # Bare essentials (turns, street crossings, arrival; curbs omitted)
    COMPACT = "compact"      # Concise guidance with key street names and turns
    STANDARD = "standard"    # Balanced O&M calibrated defaults
    DETAILED = "detailed"    # Comprehensive cues (truncated domes, zebra patterns, APS, island refuges)
    MAXIMAL = "maximal"      # Exhaustive audit (surfaces, curb height, width, hazard metrics)


class TextPreparationConfig(BaseModel):
    """Configuration controls for the Text Preparation Layer."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    verbosity: VerbosityLevel = VerbosityLevel.STANDARD
    distance_unit: DistanceUnit = DistanceUnit.METERS
    stride_length_m: float = 0.75
    pace_margin: int = 0
    pace_unit_noun: str = "strides"

    # Feature announcement toggles
    announce_curbs: bool = True
    announce_tactile: bool = True
    announce_signals_and_aps: bool = True
    announce_push_buttons: bool = True
    announce_refuge_islands: bool = True
    announce_surface_and_incline: bool = True
    announce_turning_vehicles: bool = True
    announce_intersection_topology: bool = True
    announce_anomalies: bool = True

    # Direction and curve preferences
    direction_mode: DirectionMode = DirectionMode.DEGREES
    clock_granularity: ClockGranularity = ClockGranularity.HOURLY
    curve_preset: CurveVerbiagePreset = CurveVerbiagePreset.SWEEP
    curve_template: Optional[str] = None

    def get_verbiage_config(self) -> GuidanceVerbiageConfig:
        """Create a synchronized GuidanceVerbiageConfig."""
        return GuidanceVerbiageConfig(
            direction_mode=self.direction_mode,
            clock_granularity=self.clock_granularity,
            curve_preset=self.curve_preset,
            curve_template=self.curve_template,
            distance_unit=self.distance_unit,
            stride_length_m=self.stride_length_m,
            pace_margin=self.pace_margin,
            pace_unit_noun=self.pace_unit_noun,
        )

    def format_distance(self, distance_m: float) -> str:
        """Format a metric distance according to active distance unit (meters vs paces/strides).

        When distance_unit is PACES or STRIDES:
        - Never gives fractional strides (no decimals like 3.49).
        - Returns a natural integer range (e.g. '3 to 4 strides').
        - Supports an optional user-configured margin (e.g. '3 to 5 strides').
        """
        if self.distance_unit == DistanceUnit.METERS:
            d_round = round(distance_m)
            if d_round == 1:
                return "1 meter"
            return f"{d_round} meters"

        stride_len = self.stride_length_m if self.stride_length_m > 0 else 0.75
        raw_paces = distance_m / stride_len
        low = max(1, math.floor(raw_paces))
        high = max(1, math.ceil(raw_paces))
        noun = self.pace_unit_noun or ("paces" if self.distance_unit == DistanceUnit.PACES else "strides")
        margin = max(0, int(self.pace_margin))
        high_with_margin = high + margin

        if low == high:
            if margin > 0:
                return f"{low} to {high_with_margin} {noun}"
            else:
                single_noun = noun[:-1] if noun.endswith("s") and low == 1 else noun
                return f"{low} {single_noun}"
        else:
            return f"{low} to {high_with_margin} {noun}"


class GuidanceTextPreparer:
    """Prepares auditory instructions from NavigationStepQualities based on user settings."""

    def __init__(self, config: Optional[TextPreparationConfig] = None):
        self.config = config or TextPreparationConfig()

    def prepare_instructions(
        self,
        qualities: List[NavigationStepQualities],
        config: Optional[TextPreparationConfig] = None,
    ) -> List[Dict[str, Any]]:
        """Transform raw step qualities into final spoken instructions."""
        cfg = config or self.config
        verbiage = cfg.get_verbiage_config()
        instructions: List[Dict[str, Any]] = []

        # If verbosity is MINIMAL, curbs are omitted unless explicitly forced
        announce_curbs = cfg.announce_curbs and (cfg.verbosity != VerbosityLevel.MINIMAL)

        step_counter = 1
        for sq in qualities:
            # 1. Curb steps filtering
            if sq.action in (StepAction.APPROACH_CURB, StepAction.EXIT_CURB) and not announce_curbs:
                continue

            inst = self._prepare_single_step(sq, cfg, verbiage, step_counter)
            if inst is not None:
                instructions.append(inst)
                step_counter += 1

        return instructions

    def _prepare_single_step(
        self,
        sq: NavigationStepQualities,
        cfg: TextPreparationConfig,
        verbiage: GuidanceVerbiageConfig,
        step_num: int,
    ) -> Optional[Dict[str, Any]]:
        """Prepare spoken instruction and output dictionary for a single step."""
        dist_str = cfg.format_distance(sq.distance_m)

        # -------------------------------------------------------------
        # 1. APPROACH_CURB
        # -------------------------------------------------------------
        if sq.action == StepAction.APPROACH_CURB:
            curb_desc = "lowered curb ramp" if sq.kerb.is_step_free else "vertical raised curb drop-off"
            if cfg.announce_tactile:
                tactile_desc = f"with {sq.kerb.tactile_description}" if sq.kerb.has_tactile_paving else "without tactile warning"
            else:
                tactile_desc = ""

            target_name = sq.kerb.cross_target or sq.crossing.spoken_road_name or sq.crossing.road_crossed
            cross_target = f" to cross {target_name}" if target_name else ""

            speech = f"Approach curb edge{cross_target}: Step down {curb_desc} {tactile_desc}."
            speech = re.sub(r"\s+", " ", speech).replace(" .", ".").strip()

            if cfg.announce_turning_vehicles and sq.crossing.turning_vehicle_warning:
                speech += " Be alert for turning customer vehicles entering or exiting the parking lot."

            if cfg.announce_push_buttons and sq.button.has_button and sq.button.instruction_text:
                speech += f" {sq.button.instruction_text}"

            return {
                "step": step_num,
                "action": "APPROACH_CURB",
                "spoken_instruction": speech.strip(),
                "tactile_cue": sq.kerb.has_tactile_paving,
                "button_cue": sq.button.instruction_text if sq.button.has_button else None,
                "relative_button_direction": sq.button.relative_direction,
                "road_crossed": sq.crossing.road_crossed,
                "spoken_road_name": sq.crossing.spoken_road_name,
                "semantic_crossing_type": sq.crossing.semantic_crossing_type,
                "turning_vehicle_warning": sq.crossing.turning_vehicle_warning,
                "coordinate": sq.coordinate,
                "qualities": sq.to_dict(),
            }

        # -------------------------------------------------------------
        # 2. CROSS_STREET
        # -------------------------------------------------------------
        elif sq.action == StepAction.CROSS_STREET:
            road_name = sq.crossing.spoken_road_name or sq.crossing.road_crossed or "the street"
            street = sq.crossing.corridor_street or "the street"
            itype = sq.crossing.intersection_type

            # Intersection typology summary
            if cfg.announce_intersection_topology and itype == "roundabout":
                refuge_cue = (
                    " to reach the splitter island refuge, then check for circulating vehicles before completing the crossing"
                    if (sq.crossing.has_refuge_island and cfg.announce_refuge_islands)
                    else ""
                )
                if "slip lane" in road_name.lower():
                    slip_phrase = road_name
                elif road_name and road_name != "the street":
                    slip_phrase = f"{road_name} across the roundabout slip lane"
                else:
                    slip_phrase = "the roundabout slip lane"

                summary = (
                    f"Caution: Roundabout intersection. Free-flowing traffic enters continuously from your left without a traffic light. "
                    f"Cross {slip_phrase}{refuge_cue} to stay on {street}."
                )

            elif cfg.announce_intersection_topology and sq.crossing.semantic_crossing_type in ("commercial_driveway", "parking_lot_access"):
                if itype == "T-junction":
                    summary = f"At this T-junction, cross {road_name} to continue along {street}."
                else:
                    summary = f"Continue forward across {road_name} to stay on {street}."

            elif cfg.announce_intersection_topology and sq.crossing.semantic_crossing_type in ("private_driveway", "service_alley"):
                summary = f"Continue forward across {road_name} to stay on {street}."

            elif cfg.announce_intersection_topology and itype == "4-way intersection":
                if sq.crossing.is_corridor_continuation:
                    summary = f"Continue forward across {road_name} at this 4-way intersection to stay on {street}."
                else:
                    summary = f"At this 4-way intersection, cross {road_name}."

            elif cfg.announce_intersection_topology and itype == "T-junction":
                summary = f"At this T-junction, cross {road_name} to continue along {street}."

            elif cfg.announce_intersection_topology and itype == "mid-block crossing":
                summary = f"Continue forward across {road_name} at the mid-block crosswalk to stay on {street}."

            else:
                summary = f"Cross {road_name} to stay on {street}."

            # Markings
            markings = ""
            if sq.crossing.markings and cfg.verbosity != VerbosityLevel.MINIMAL:
                markings = f" ({sq.crossing.markings} pattern)"

            # APS / Signal info
            aps_info = ""
            if cfg.announce_signals_and_aps and cfg.verbosity != VerbosityLevel.MINIMAL:
                if sq.signal.has_audible_signals:
                    aps_info = " Accessible Pedestrian Signal active with audible locator tone."
                elif sq.signal.has_signals:
                    aps_info = " Traffic signalized intersection (no audible signal detected, verify traffic sounds)."
                else:
                    aps_info = " Unsignalized crossing, listen carefully for approaching vehicular traffic."

            speech = f"{summary} ({dist_str}{markings}).{aps_info}"
            speech = re.sub(r"\s+", " ", speech).strip()

            if cfg.announce_anomalies and sq.hazard.has_data_anomaly and sq.hazard.anomaly_cue:
                speech += f" {sq.hazard.anomaly_cue}"

            inst_entry = {
                "step": step_num,
                "action": "CROSS_STREET",
                "distance_m": sq.distance_m,
                "spoken_instruction": speech.strip(),
                "has_aps": sq.signal.has_audible_signals,
                "intersection_type": sq.crossing.intersection_type,
                "is_continuation": sq.crossing.is_corridor_continuation,
                "road_crossed": sq.crossing.road_crossed,
                "spoken_road_name": sq.crossing.spoken_road_name,
                "semantic_crossing_type": sq.crossing.semantic_crossing_type,
                "corridor_street": sq.crossing.corridor_street,
                "coordinate": sq.coordinate,
                "coordinates": sq.coordinates,
                "qualities": sq.to_dict(),
            }
            if sq.hazard.has_data_anomaly:
                inst_entry["data_anomaly"] = True
            return inst_entry

        # -------------------------------------------------------------
        # 3. EXIT_CURB
        # -------------------------------------------------------------
        elif sq.action == StepAction.EXIT_CURB:
            exit_curb = "lowered curb ramp" if sq.kerb.is_step_free else "raised curb"
            exit_tactile = " onto tactile paving" if (cfg.announce_tactile and sq.kerb.has_tactile_paving) else ""
            target_name = sq.kerb.cross_target or sq.crossing.spoken_road_name or sq.crossing.road_crossed
            exit_target = f" to complete crossing {target_name}" if target_name else " to exit roadway"

            speech = f"Step up {exit_curb}{exit_tactile}{exit_target}."
            speech = re.sub(r"\s+", " ", speech).strip()

            return {
                "step": step_num,
                "action": "EXIT_CURB",
                "spoken_instruction": speech,
                "tactile_cue": sq.kerb.has_tactile_paving,
                "road_crossed": sq.crossing.road_crossed,
                "spoken_road_name": sq.crossing.spoken_road_name,
                "semantic_crossing_type": sq.crossing.semantic_crossing_type,
                "coordinate": sq.coordinate,
                "qualities": sq.to_dict(),
            }

        # -------------------------------------------------------------
        # 4. WAIT_REFUGE
        # -------------------------------------------------------------
        elif sq.action == StepAction.WAIT_REFUGE:
            speech = (
                f"Wait on center median pedestrian refuge island ({dist_str}). "
                "Listen and verify traffic is clear before crossing the next lane."
            )
            return {
                "step": step_num,
                "action": "WALK_SIDEWALK",
                "distance_m": sq.distance_m,
                "spoken_instruction": speech,
                "tactile_cue": sq.path.has_tactile_guideway,
                "is_refuge_island": True,
                "coordinate": sq.coordinate,
                "coordinates": sq.coordinates,
                "qualities": sq.to_dict(),
            }

        # -------------------------------------------------------------
        # 5. WALK_SIDEWALK
        # -------------------------------------------------------------
        elif sq.action == StepAction.WALK_SIDEWALK:
            # A. Curving Arc
            if sq.turn.is_curve:
                curve_name = sq.path.name or "sidewalk"
                speech = verbiage.format_curve(
                    direction=sq.turn.turn_direction or "forward",
                    distance_m=sq.distance_m,
                    name=curve_name,
                )
                inst_dict: Dict[str, Any] = {
                    "step": step_num,
                    "action": "WALK_SIDEWALK",
                    "distance_m": sq.distance_m,
                    "spoken_instruction": speech,
                    "tactile_cue": sq.path.has_tactile_guideway,
                    "is_curve": True,
                    "turn_direction": sq.turn.turn_direction,
                    "turn_angle_deg": sq.turn.turn_angle_deg,
                    "clock_position": sq.turn.clock_position,
                    "coordinate": sq.coordinate,
                    "coordinates": sq.coordinates,
                    "qualities": sq.to_dict(),
                }
                return inst_dict

            # B. Discrete Turn
            target_name = sq.path.name or ("bridge walkway" if sq.path.is_bridge else "sidewalk")
            if cfg.announce_surface_and_incline:
                surface = f"{sq.path.surface} " if sq.path.surface else ""
                width = f"({sq.path.width_m}m wide) " if (sq.path.width_m and cfg.verbosity in (VerbosityLevel.DETAILED, VerbosityLevel.MAXIMAL)) else ""
                tactile = "with tactile guidance " if (sq.path.has_tactile_guideway and cfg.announce_tactile) else ""
                target_desc = f"{surface}{target_name} {width}{tactile}".strip()
            else:
                target_desc = target_name

            if sq.turn.is_turn and sq.turn.turn_direction:
                speech, meta = verbiage.format_turn(
                    angle_deg=sq.turn.turn_angle_deg,
                    direction=sq.turn.turn_direction,
                    target=target_desc,
                    distance_m=sq.distance_m,
                    raw_angle=sq.turn.raw_turn_angle_deg,
                )
                inst_dict = {
                    "step": step_num,
                    "action": "WALK_SIDEWALK",
                    "distance_m": sq.distance_m,
                    "spoken_instruction": speech,
                    "tactile_cue": sq.path.has_tactile_guideway,
                    "coordinate": sq.coordinate,
                    "coordinates": sq.coordinates,
                    "turn_direction": sq.turn.turn_direction,
                    "turn_angle_deg": sq.turn.turn_angle_deg,
                    "clock_position": sq.turn.clock_position,
                    "direction_mode": verbiage.direction_mode.value,
                    "qualities": sq.to_dict(),
                }
                return inst_dict

            # C. Plain Straight Sidewalk Walk
            speech = f"Follow {target_desc} for {dist_str}."
            return {
                "step": step_num,
                "action": "WALK_SIDEWALK",
                "distance_m": sq.distance_m,
                "spoken_instruction": speech,
                "tactile_cue": sq.path.has_tactile_guideway,
                "coordinate": sq.coordinate,
                "coordinates": sq.coordinates,
                "qualities": sq.to_dict(),
            }

        # -------------------------------------------------------------
        # 6. ARRIVE
        # -------------------------------------------------------------
        elif sq.action == StepAction.ARRIVE:
            return {
                "step": step_num,
                "action": "ARRIVE",
                "spoken_instruction": "You have arrived at your destination.",
                "coordinate": sq.coordinate,
                "qualities": sq.to_dict(),
            }

        return None
