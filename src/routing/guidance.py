from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models.pedestrian import PedestrianNetwork
from .button_detector import ButtonDetector
from .intersection_classifier import IntersectionClassifier
from .pedestrian_graph import RouteResult


class AudioGuidanceGenerator:
    """Formats route steps into explicit, tactile-aware spoken instructions."""

    def __init__(
        self,
        network: PedestrianNetwork,
        classifier: Optional[IntersectionClassifier] = None,
        button_detector: Optional[ButtonDetector] = None,
        map_data_dir: Optional[Path] = None,
    ):
        self.network = network
        self.classifier = classifier or IntersectionClassifier(network, map_data_dir=map_data_dir)
        self.button_detector = button_detector or ButtonDetector(network)

    def generate_instructions(self, route: RouteResult) -> List[Dict[str, Any]]:
        """Generate auditory instructions for each segment and transition along the route."""
        instructions: List[Dict[str, Any]] = []
        kerbs = self.network.kerbs

        step_num = 1
        for i, edge in enumerate(route.edges):
            u_kerb = kerbs.get(edge.u)
            v_kerb = kerbs.get(edge.v)

            if edge.feature_type == "sidewalk":
                sw = edge.sidewalk
                name = sw.name if (sw and sw.name) else "sidewalk"
                surface = f"{sw.surface} " if (sw and sw.surface) else ""
                width = f"({sw.width_m}m wide) " if (sw and sw.width_m) else ""
                tactile = "with tactile guidance " if (sw and sw.has_tactile_paving) else ""

                speech = (
                    f"Follow {surface}{name} {width}{tactile}for {edge.length_m:.0f} meters."
                )
                instructions.append({
                    "step": step_num,
                    "action": "WALK_SIDEWALK",
                    "distance_m": edge.length_m,
                    "spoken_instruction": speech,
                    "tactile_cue": sw.has_tactile_paving if sw else False,
                })
                step_num += 1

            elif edge.feature_type == "crosswalk":
                cw = edge.crosswalk
                cw_name = cw.name if (cw and cw.name) else "street crossing"

                # Classify intersection topology and locate push-button
                ctx = self.classifier.classify_intersection(route, i)
                btn_cue = self.button_detector.detect_button_cue(route, i)

                # 1. Curb entry instruction
                if u_kerb:
                    curb_desc = "lowered curb ramp" if u_kerb.is_step_free else "vertical raised curb drop-off"
                    tactile_desc = "with tactile truncated domes" if u_kerb.has_tactile_paving else "without tactile warning"
                    cross_target = f" to cross {ctx.road_crossed}" if (ctx and ctx.road_crossed) else ""
                    curb_speech = f"Approach curb edge{cross_target}: Step down {curb_desc} {tactile_desc}."

                    # Inject button cue if detected
                    if btn_cue.has_button and btn_cue.instruction_text:
                        curb_speech += f" {btn_cue.instruction_text}"

                    instructions.append({
                        "step": step_num,
                        "action": "APPROACH_CURB",
                        "spoken_instruction": curb_speech,
                        "tactile_cue": u_kerb.has_tactile_paving,
                        "button_cue": btn_cue.instruction_text if btn_cue.has_button else None,
                        "relative_button_direction": btn_cue.relative_direction,
                        "road_crossed": ctx.road_crossed if ctx else None,
                    })
                    step_num += 1

                # 2. Street crossing instruction
                markings = f" ({cw.markings} pattern)" if cw.markings else ""
                aps_info = ""
                if cw.has_audible_signals:
                    aps_info = " Accessible Pedestrian Signal active with audible locator tone."
                elif cw.has_signals:
                    aps_info = " Traffic signalized intersection (no audible signal detected, verify traffic sounds)."
                else:
                    aps_info = " Unsignalized crossing, listen carefully for approaching vehicular traffic."

                # Compose contextual guidance using IntersectionContext
                if ctx and ctx.spoken_summary:
                    crossing_speech = f"{ctx.spoken_summary} ({edge.length_m:.0f} meters{markings}).{aps_info}"
                else:
                    island_info = " Pedestrian refuge island present in median." if cw.has_refuge_island else ""
                    crossing_speech = (
                        f"Cross {cw_name}{markings} for {edge.length_m:.0f} meters.{aps_info}{island_info}"
                    )

                instructions.append({
                    "step": step_num,
                    "action": "CROSS_STREET",
                    "distance_m": edge.length_m,
                    "spoken_instruction": crossing_speech,
                    "has_aps": cw.has_audible_signals,
                    "intersection_type": ctx.intersection_type.value,
                    "is_continuation": ctx.is_corridor_continuation,
                    "road_crossed": ctx.road_crossed,
                    "corridor_street": ctx.corridor_street,
                })
                step_num += 1

                # 3. Curb exit instruction
                if v_kerb:
                    exit_curb = "lowered curb ramp" if v_kerb.is_step_free else "raised curb"
                    exit_tactile = " onto tactile paving" if v_kerb.has_tactile_paving else ""
                    exit_target = f" to complete crossing {ctx.road_crossed}" if (ctx and ctx.road_crossed) else " to exit roadway"
                    exit_speech = f"Step up {exit_curb}{exit_tactile}{exit_target}."
                    instructions.append({
                        "step": step_num,
                        "action": "EXIT_CURB",
                        "spoken_instruction": exit_speech,
                        "tactile_cue": v_kerb.has_tactile_paving,
                        "road_crossed": ctx.road_crossed if ctx else None,
                    })
                    step_num += 1

        instructions.append({
            "step": step_num,
            "action": "ARRIVE",
            "spoken_instruction": "You have arrived at your destination.",
        })

        return self._consolidate_instructions(instructions)

    def _consolidate_instructions(self, raw_instructions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Combine consecutive sidewalk steps with the same name/surface into a single clean announcement."""
        consolidated: List[Dict[str, Any]] = []

        i = 0
        while i < len(raw_instructions):
            curr = raw_instructions[i]

            # Only consolidate WALK_SIDEWALK actions
            if curr["action"] == "WALK_SIDEWALK":
                total_dist = curr.get("distance_m", 0.0)
                tactile = curr.get("tactile_cue", False)
                base_speech = curr["spoken_instruction"]

                # Extract descriptor (everything before 'for X meters')
                if " for " in base_speech:
                    descriptor = base_speech.split(" for ")[0]
                else:
                    descriptor = "Follow sidewalk"

                j = i + 1
                while j < len(raw_instructions) and raw_instructions[j]["action"] == "WALK_SIDEWALK":
                    next_inst = raw_instructions[j]
                    next_speech = next_inst["spoken_instruction"]
                    next_desc = next_speech.split(" for ")[0] if " for " in next_speech else "Follow sidewalk"

                    # If descriptors match, accumulate distance
                    if descriptor == next_desc:
                        total_dist += next_inst.get("distance_m", 0.0)
                        tactile = tactile or next_inst.get("tactile_cue", False)
                        j += 1
                    else:
                        break

                consolidated.append({
                    "step": len(consolidated) + 1,
                    "action": "WALK_SIDEWALK",
                    "distance_m": round(total_dist, 1),
                    "spoken_instruction": f"{descriptor} for {total_dist:.0f} meters.",
                    "tactile_cue": tactile,
                })
                i = j
            else:
                curr_copy = dict(curr)
                curr_copy["step"] = len(consolidated) + 1
                consolidated.append(curr_copy)
                i += 1

        return consolidated
