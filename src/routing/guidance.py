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
                is_traffic_island = sw and (sw.footway == "traffic_island" or getattr(sw, "footway", None) == "traffic_island")
                if is_traffic_island:
                    speech = (
                        f"Wait on center median pedestrian refuge island ({edge.length_m:.0f} meters). "
                        "Listen and verify traffic is clear before crossing the next lane."
                    )
                    instructions.append({
                        "step": step_num,
                        "action": "WALK_SIDEWALK",
                        "distance_m": edge.length_m,
                        "spoken_instruction": speech,
                        "tactile_cue": sw.has_tactile_paving if sw else False,
                        "is_refuge_island": True,
                    })
                    step_num += 1
                else:
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

                prev_edge = route.edges[i - 1] if i > 0 else None
                next_edge = route.edges[i + 1] if (i + 1 < len(route.edges)) else None

                # Only emit entry curb at transition into crosswalk (not between consecutive crosswalk segments)
                is_crossing_entry = (prev_edge is None or prev_edge.feature_type != "crosswalk")
                is_crossing_exit = (next_edge is None or next_edge.feature_type != "crosswalk")

                # Resolve entry kerb
                entry_kerb = u_kerb
                if is_crossing_entry and not entry_kerb and self.classifier.registry and edge.u in self.network.raw_nodes:
                    from ..spatial.gpkg_registry import LayerRole
                    from ..models.pedestrian import KerbFeature
                    u_coord = self.network.raw_nodes[edge.u]
                    match = self.classifier.registry.find_nearest(u_coord[0], u_coord[1], role=LayerRole.CURB_RAMP, max_dist_m=12.0)
                    if match:
                        f, _ = match
                        is_comp = str(f.attributes.get("Compliant") or "").upper() == "YES"
                        needs_domes = str(f.attributes.get("CorrectiveAction") or "").upper() == "DOMES"
                        entry_kerb = KerbFeature(
                            id=f.feature_id,
                            coordinate=u_coord,
                            kerb_type="lowered",
                            has_tactile_paving=(is_comp and not needs_domes),
                        )
                elif is_crossing_entry and not entry_kerb:
                    from ..models.pedestrian import KerbFeature
                    u_coord = self.network.raw_nodes.get(edge.u, (0.0, 0.0))
                    entry_kerb = KerbFeature(
                        id=-1,
                        coordinate=u_coord,
                        kerb_type="lowered",
                        has_tactile_paving=False,
                    )

                # 1. Curb entry instruction
                if is_crossing_entry and entry_kerb:
                    curb_desc = "lowered curb ramp" if entry_kerb.is_step_free else "vertical raised curb drop-off"
                    tactile_desc = "with tactile truncated domes" if entry_kerb.has_tactile_paving else "without tactile warning"
                    target_name = (ctx.spoken_road_name or ctx.road_crossed) if ctx else None
                    cross_target = f" to cross {target_name}" if target_name else ""
                    curb_speech = f"Approach curb edge{cross_target}: Step down {curb_desc} {tactile_desc}."

                    # Inject turning vehicle caution for commercial driveways & parking entrances
                    if ctx and ctx.turning_vehicle_warning:
                        curb_speech += " Be alert for turning customer vehicles entering or exiting the parking lot."

                    # Inject button cue if detected
                    if btn_cue.has_button and btn_cue.instruction_text:
                        curb_speech += f" {btn_cue.instruction_text}"

                    instructions.append({
                        "step": step_num,
                        "action": "APPROACH_CURB",
                        "spoken_instruction": curb_speech,
                        "tactile_cue": entry_kerb.has_tactile_paving,
                        "button_cue": btn_cue.instruction_text if btn_cue.has_button else None,
                        "relative_button_direction": btn_cue.relative_direction,
                        "road_crossed": ctx.road_crossed if ctx else None,
                        "spoken_road_name": ctx.spoken_road_name if ctx else None,
                        "semantic_crossing_type": ctx.semantic_crossing_type.value if ctx else None,
                        "turning_vehicle_warning": ctx.turning_vehicle_warning if ctx else False,
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
                    "spoken_road_name": ctx.spoken_road_name if ctx else None,
                    "semantic_crossing_type": ctx.semantic_crossing_type.value if ctx else None,
                    "corridor_street": ctx.corridor_street,
                })
                step_num += 1

                # Resolve exit kerb
                exit_kerb = v_kerb
                if is_crossing_exit and not exit_kerb and self.classifier.registry and edge.v in self.network.raw_nodes:
                    from ..spatial.gpkg_registry import LayerRole
                    from ..models.pedestrian import KerbFeature
                    v_coord = self.network.raw_nodes[edge.v]
                    match = self.classifier.registry.find_nearest(v_coord[0], v_coord[1], role=LayerRole.CURB_RAMP, max_dist_m=12.0)
                    if match:
                        f, _ = match
                        is_comp = str(f.attributes.get("Compliant") or "").upper() == "YES"
                        needs_domes = str(f.attributes.get("CorrectiveAction") or "").upper() == "DOMES"
                        exit_kerb = KerbFeature(
                            id=f.feature_id,
                            coordinate=v_coord,
                            kerb_type="lowered",
                            has_tactile_paving=(is_comp and not needs_domes),
                        )
                elif is_crossing_exit and not exit_kerb:
                    from ..models.pedestrian import KerbFeature
                    v_coord = self.network.raw_nodes.get(edge.v, (0.0, 0.0))
                    exit_kerb = KerbFeature(
                        id=-1,
                        coordinate=v_coord,
                        kerb_type="lowered",
                        has_tactile_paving=False,
                    )

                # 3. Curb exit instruction
                if is_crossing_exit and exit_kerb:
                    exit_curb = "lowered curb ramp" if exit_kerb.is_step_free else "raised curb"
                    exit_tactile = " onto tactile paving" if exit_kerb.has_tactile_paving else ""
                    target_name = (ctx.spoken_road_name or ctx.road_crossed) if ctx else None
                    exit_target = f" to complete crossing {target_name}" if target_name else " to exit roadway"
                    exit_speech = f"Step up {exit_curb}{exit_tactile}{exit_target}."
                    instructions.append({
                        "step": step_num,
                        "action": "EXIT_CURB",
                        "spoken_instruction": exit_speech,
                        "tactile_cue": exit_kerb.has_tactile_paving,
                        "road_crossed": ctx.road_crossed if ctx else None,
                        "spoken_road_name": ctx.spoken_road_name if ctx else None,
                        "semantic_crossing_type": ctx.semantic_crossing_type.value if ctx else None,
                    })
                    step_num += 1

        instructions.append({
            "step": step_num,
            "action": "ARRIVE",
            "spoken_instruction": "You have arrived at your destination.",
        })

        return self._consolidate_instructions(instructions)

    def _consolidate_instructions(self, raw_instructions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Combine consecutive sidewalk and crosswalk steps into single clean announcements."""
        import re
        consolidated: List[Dict[str, Any]] = []

        i = 0
        while i < len(raw_instructions):
            curr = raw_instructions[i]

            # 1. Consolidate consecutive WALK_SIDEWALK actions (skipping refuge islands)
            if curr["action"] == "WALK_SIDEWALK" and not curr.get("is_refuge_island"):
                total_dist = curr.get("distance_m", 0.0)
                tactile = curr.get("tactile_cue", False)
                base_speech = curr["spoken_instruction"]

                # Extract descriptor (everything before 'for X meters')
                if " for " in base_speech:
                    descriptor = base_speech.split(" for ")[0]
                else:
                    descriptor = "Follow sidewalk"

                j = i + 1
                while j < len(raw_instructions) and raw_instructions[j]["action"] == "WALK_SIDEWALK" and not raw_instructions[j].get("is_refuge_island"):
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

            # 2. Consolidate consecutive CROSS_STREET actions crossing the same roadway feature
            elif curr["action"] == "CROSS_STREET":
                total_dist = curr.get("distance_m", 0.0)
                road = curr.get("road_crossed")
                itype = curr.get("intersection_type")
                j = i + 1
                while j < len(raw_instructions) and raw_instructions[j]["action"] == "CROSS_STREET":
                    next_inst = raw_instructions[j]
                    if (
                        next_inst.get("road_crossed") == road
                        and next_inst.get("intersection_type") == itype
                    ):
                        total_dist += next_inst.get("distance_m", 0.0)
                        j += 1
                    else:
                        break

                curr_copy = dict(curr)
                curr_copy["step"] = len(consolidated) + 1
                curr_copy["distance_m"] = round(total_dist, 1)

                # Update the spoken instruction's meter count
                speech = curr["spoken_instruction"]
                speech = re.sub(r"\(\d+\s*meters", f"({total_dist:.0f} meters", speech)
                curr_copy["spoken_instruction"] = speech

                consolidated.append(curr_copy)
                i = j

            else:
                curr_copy = dict(curr)
                curr_copy["step"] = len(consolidated) + 1
                consolidated.append(curr_copy)
                i += 1

        return consolidated
