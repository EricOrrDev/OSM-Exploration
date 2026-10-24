"""Configurable verbiage templates, 15° turn quantization, and clock-face orientation.

Provides orientation-and-mobility calibrated speech formatting for blind pedestrians:
- 15° quantization increments for angular turn announcements
- 12-hour clock face orientation (with half-hour granularity)
- Sweeping vs curving vs bearing verbiage presets for winding paths
"""

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Any, Dict, Optional, Tuple


class DirectionMode(str, Enum):
    """Direction mode for turn-by-turn guidance announcements."""
    DEGREES = "degrees"  # E.g., "Turn 45 degrees left" (strictly in 15° increments)
    CLOCK = "clock"      # E.g., "Turn to 10 o'clock" / "Turn to 1:30"


class ClockGranularity(str, Enum):
    """Granularity for clock face direction mapping."""
    HOURLY = "hourly"            # 12 discrete positions (1 to 12 o'clock, 30° steps)
    HALF_HOURLY = "half_hourly"  # 24 discrete positions (e.g. 1:30, 2:30, 15° steps)


class CurveVerbiagePreset(str, Enum):
    """Verbiage style for announcing gentle curves and batched arcs."""
    SWEEP = "sweep"      # "Sweep left for 14 meters"
    CURVING = "curving"  # "Follow the curving sidewalk to the left for 14 meters"
    BEAR = "bear"        # "Bear left for 14 meters"
    CUSTOM = "custom"    # User-defined format template


class DistanceUnit(str, Enum):
    """Unit of distance measurement for spoken navigation instructions."""
    METERS = "meters"
    PACES = "paces"
    STRIDES = "strides"


@dataclass
class GuidanceVerbiageConfig:
    """User-configurable guidance verbiage, distance units, and direction output preferences."""

    # Direction output format (Degrees in 15° steps vs Clock face)
    direction_mode: DirectionMode = DirectionMode.DEGREES
    clock_granularity: ClockGranularity = ClockGranularity.HOURLY

    # Distance unit & stride preferences
    distance_unit: DistanceUnit = DistanceUnit.METERS
    stride_length_m: float = 0.75  # Average human walking stride in meters
    pace_margin: int = 0           # Buffer added to range (e.g. 0 -> '3 to 4', 1 -> '3 to 5')
    pace_unit_noun: str = "strides"  # "strides" or "paces"

    # Curve announcement style
    curve_preset: CurveVerbiagePreset = CurveVerbiagePreset.SWEEP
    curve_template: Optional[str] = None

    # Spoken templates
    turn_degree_template: str = "Turn {angle} degrees {direction}, then follow {target} for {distance:.0f} meters."
    turn_clock_template: str = "Turn to {clock}, then follow {target} for {distance:.0f} meters."

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

    def angle_to_clock(self, signed_angle_deg: float, granularity: Optional[ClockGranularity] = None) -> str:
        """Convert a signed turn angle (-180° to +180°) into a clock face direction."""
        gran = granularity or self.clock_granularity
        raw_clock = (signed_angle_deg / 30.0) % 12.0
        if raw_clock <= 0.0:
            raw_clock += 12.0

        if gran == ClockGranularity.HALF_HOURLY:
            rounded_half = round(raw_clock * 2.0) / 2.0
            if rounded_half > 12.0:
                rounded_half -= 12.0
            elif rounded_half <= 0.0:
                rounded_half += 12.0

            hours = int(math.floor(rounded_half))
            is_half = (rounded_half - hours) >= 0.4
            if is_half:
                h_display = 12 if hours == 0 else hours
                return f"{h_display}:30"
            else:
                h_display = 12 if hours == 0 else hours
                return f"{h_display} o'clock"
        else:
            hour = int(round(raw_clock))
            if hour <= 0 or hour > 12:
                hour = 12 if hour <= 0 else (hour - 12 if hour > 12 else hour)
            if hour == 0:
                hour = 12
            return f"{hour} o'clock"

    def format_curve(
        self,
        direction: str,
        distance_m: float,
        name: Optional[str] = None,
    ) -> str:
        """Format spoken instruction for curving / sweeping path segments."""
        dist_str = self.format_distance(distance_m)
        target = name if name else "sidewalk"

        if self.curve_preset == CurveVerbiagePreset.SWEEP:
            template = self.curve_template or "Sweep {direction} for {distance}."
        elif self.curve_preset == CurveVerbiagePreset.CURVING:
            template = "Follow the curving sidewalk to the {direction} for {distance}."
        elif self.curve_preset == CurveVerbiagePreset.BEAR:
            template = "Bear {direction} for {distance}."
        else:
            template = self.curve_template or "Sweep {direction} for {distance}."

        if "{distance:.0f} meters" in template:
            if self.distance_unit == DistanceUnit.METERS:
                return template.format(direction=direction, distance=distance_m, target=target, name=target)
            else:
                template = template.replace("{distance:.0f} meters", "{distance}")

        return template.format(
            direction=direction,
            distance=dist_str,
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
        dist_str = self.format_distance(distance_m)

        deg_tpl = self.turn_degree_template
        clk_tpl = self.turn_clock_template

        if self.distance_unit != DistanceUnit.METERS:
            deg_tpl = deg_tpl.replace("{distance:.0f} meters", "{distance}").replace("{distance} meters", "{distance}")
            clk_tpl = clk_tpl.replace("{distance:.0f} meters", "{distance}").replace("{distance} meters", "{distance}")
            dist_val: Any = dist_str
        else:
            dist_val = distance_m if "{distance:" in deg_tpl else dist_str

        if self.direction_mode == DirectionMode.CLOCK:
            speech = clk_tpl.format(
                clock=clock_pos,
                target=target,
                distance=dist_val,
                direction=direction,
            )
        else:
            speech = deg_tpl.format(
                angle=angle_deg,
                direction=direction,
                target=target,
                distance=dist_val,
                clock=clock_pos,
            )

        metadata = {
            "turn_angle_deg": angle_deg,
            "turn_direction": direction,
            "clock_position": clock_pos,
            "direction_mode": self.direction_mode.value,
        }
        return speech, metadata
