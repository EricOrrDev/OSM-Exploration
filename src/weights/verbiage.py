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


@dataclass
class GuidanceVerbiageConfig:
    """User-configurable guidance verbiage and direction output preferences."""

    # Direction output format (Degrees in 15° steps vs Clock face)
    direction_mode: DirectionMode = DirectionMode.DEGREES
    clock_granularity: ClockGranularity = ClockGranularity.HOURLY

    # Curve announcement style
    curve_preset: CurveVerbiagePreset = CurveVerbiagePreset.SWEEP
    curve_template: Optional[str] = None

    # Spoken templates
    turn_degree_template: str = "Turn {angle} degrees {direction}, then follow {target} for {distance:.0f} meters."
    turn_clock_template: str = "Turn to {clock}, then follow {target} for {distance:.0f} meters."

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
        if self.curve_preset == CurveVerbiagePreset.SWEEP:
            template = self.curve_template or "Sweep {direction} for {distance:.0f} meters."
        elif self.curve_preset == CurveVerbiagePreset.CURVING:
            template = "Follow the curving sidewalk to the {direction} for {distance:.0f} meters."
        elif self.curve_preset == CurveVerbiagePreset.BEAR:
            template = "Bear {direction} for {distance:.0f} meters."
        else:
            template = self.curve_template or "Sweep {direction} for {distance:.0f} meters."

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
