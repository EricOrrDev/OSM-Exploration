import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models.pedestrian import PedestrianNetwork
from .button_detector import ButtonDetector
from .intersection_classifier import IntersectionClassifier
from .pedestrian_graph import RouteResult, calculate_bearing, normalize_angle_diff
from .safety_weights import (
    DEFAULT_SAFETY_WEIGHTS,
    DEFAULT_VERBIAGE_CONFIG,
    CurveVerbiagePreset,
    DirectionMode,
    GuidanceVerbiageConfig,
    SafetyWeightsConfig,
)


class AudioGuidanceGenerator:
    """Formats route steps into explicit, tactile-aware spoken instructions."""

    def __init__(
        self,
        network: PedestrianNetwork,
        classifier: Optional[IntersectionClassifier] = None,
        button_detector: Optional[ButtonDetector] = None,
        map_data_dir: Optional[Path] = None,
        weights: Optional[SafetyWeightsConfig] = None,
        verbiage_config: Optional[GuidanceVerbiageConfig] = None,
    ):
        self.network = network
        self.classifier = classifier or IntersectionClassifier(network, map_data_dir=map_data_dir)
        self.button_detector = button_detector or ButtonDetector(network)
        self.weights = weights or DEFAULT_SAFETY_WEIGHTS
        self.verbiage = verbiage_config or self.weights.verbiage or DEFAULT_VERBIAGE_CONFIG

    def generate_instructions(self, route: RouteResult) -> List[Dict[str, Any]]:
        """Generate auditory instructions for each segment and transition along the route."""
        instructions: List[Dict[str, Any]] = []
        kerbs = self.network.kerbs
        edges = route.edges
        n = len(edges)
        nodes = self.network.raw_nodes

        # Pre-calculate compass bearings for each edge
        bearings: List[float] = []
        for e in edges:
            p1 = nodes.get(e.u, (0.0, 0.0))
            p2 = nodes.get(e.v, (0.0, 0.0))
            bearings.append(calculate_bearing(p1, p2))

        step_num = 1
        i = 0
        while i < n:
            edge = edges[i]

            # -------------------------------------------------------------
            # 1. Crosswalk feature handling
            # -------------------------------------------------------------
            if edge.feature_type == "crosswalk":
                cw = edge.crosswalk
                cw_name = cw.name if (cw and cw.name) else "street crossing"

                # Classify intersection topology and locate push-button
                ctx = self.classifier.classify_intersection(route, i)
                btn_cue = self.button_detector.detect_button_cue(route, i)

                prev_edge = edges[i - 1] if i > 0 else None
                next_edge = edges[i + 1] if (i + 1 < n) else None

                # Only emit entry curb at transition into crosswalk (not between consecutive crosswalk segments)
                is_crossing_entry = (prev_edge is None or prev_edge.feature_type != "crosswalk")
                is_crossing_exit = (next_edge is None or next_edge.feature_type != "crosswalk")

                # Resolve entry kerb
                u_kerb = kerbs.get(edge.u)
                entry_kerb = u_kerb
                if is_crossing_entry and not entry_kerb and self.classifier.registry and edge.u in nodes:
                    from ..spatial.gpkg_registry import LayerRole
                    from ..models.pedestrian import KerbFeature
                    u_coord = nodes[edge.u]
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
                    u_coord = nodes.get(edge.u, (0.0, 0.0))
                    entry_kerb = KerbFeature(
                        id=-1,
                        coordinate=u_coord,
                        kerb_type="lowered",
                        has_tactile_paving=False,
                    )

                # Curb entry instruction
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

                    u_pt = list(nodes.get(edge.u, (0.0, 0.0)))
                    entry_pt = list(entry_kerb.coordinate) if (entry_kerb and entry_kerb.coordinate != (0.0, 0.0)) else u_pt
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
                        "coordinate": entry_pt,
                    })
                    step_num += 1

                # Street crossing instruction
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

                # Append multi-source data conflict / anomaly warning if detected
                has_anomaly = getattr(cw, "has_data_anomaly", False) or getattr(edge, "has_data_anomaly", False)
                if has_anomaly:
                    anomaly = getattr(cw, "data_anomaly", None)
                    caution_msg = getattr(anomaly, "spoken_caution_cue", "Proceed with elevated caution: Inconsistent data between map sources for this crossing.")
                    crossing_speech += f" {caution_msg}"

                cw_pts = [list(c) for c in cw.coordinates] if (cw and len(cw.coordinates) >= 2) else [list(nodes.get(edge.u, (0.0, 0.0))), list(nodes.get(edge.v, (0.0, 0.0)))]
                mid_cw = [(cw_pts[0][0] + cw_pts[-1][0]) / 2.0, (cw_pts[0][1] + cw_pts[-1][1]) / 2.0] if cw_pts else [0.0, 0.0]
                inst_entry = {
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
                    "coordinate": mid_cw,
                    "coordinates": cw_pts,
                }
                if has_anomaly:
                    inst_entry["data_anomaly"] = True
                instructions.append(inst_entry)
                step_num += 1

                # Resolve exit kerb
                v_kerb = kerbs.get(edge.v)
                exit_kerb = v_kerb
                if is_crossing_exit and not exit_kerb and self.classifier.registry and edge.v in nodes:
                    from ..spatial.gpkg_registry import LayerRole
                    from ..models.pedestrian import KerbFeature
                    v_coord = nodes[edge.v]
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
                    v_coord = nodes.get(edge.v, (0.0, 0.0))
                    exit_kerb = KerbFeature(
                        id=-1,
                        coordinate=v_coord,
                        kerb_type="lowered",
                        has_tactile_paving=False,
                    )

                # Curb exit instruction
                if is_crossing_exit and exit_kerb:
                    exit_curb = "lowered curb ramp" if exit_kerb.is_step_free else "raised curb"
                    exit_tactile = " onto tactile paving" if exit_kerb.has_tactile_paving else ""
                    target_name = (ctx.spoken_road_name or ctx.road_crossed) if ctx else None
                    exit_target = f" to complete crossing {target_name}" if target_name else " to exit roadway"
                    exit_speech = f"Step up {exit_curb}{exit_tactile}{exit_target}."
                    v_pt = list(nodes.get(edge.v, (0.0, 0.0)))
                    exit_pt = list(exit_kerb.coordinate) if (exit_kerb and exit_kerb.coordinate != (0.0, 0.0)) else v_pt
                    instructions.append({
                        "step": step_num,
                        "action": "EXIT_CURB",
                        "spoken_instruction": exit_speech,
                        "tactile_cue": exit_kerb.has_tactile_paving,
                        "road_crossed": ctx.road_crossed if ctx else None,
                        "spoken_road_name": ctx.spoken_road_name if ctx else None,
                        "semantic_crossing_type": ctx.semantic_crossing_type.value if ctx else None,
                        "coordinate": exit_pt,
                    })
                    step_num += 1

                i += 1
                continue

            # -------------------------------------------------------------
            # 2. Sidewalk refuge island handling
            # -------------------------------------------------------------
            sw = edge.sidewalk
            is_traffic_island = sw and (sw.footway == "traffic_island" or getattr(sw, "footway", None) == "traffic_island")
            if is_traffic_island:
                speech = (
                    f"Wait on center median pedestrian refuge island ({edge.length_m:.0f} meters). "
                    "Listen and verify traffic is clear before crossing the next lane."
                )
                u_pt = list(nodes.get(edge.u, (0.0, 0.0)))
                v_pt = list(nodes.get(edge.v, (0.0, 0.0)))
                mid_isl = [(u_pt[0] + v_pt[0]) / 2.0, (u_pt[1] + v_pt[1]) / 2.0]
                instructions.append({
                    "step": step_num,
                    "action": "WALK_SIDEWALK",
                    "distance_m": edge.length_m,
                    "spoken_instruction": speech,
                    "tactile_cue": sw.has_tactile_paving if sw else False,
                    "is_refuge_island": True,
                    "coordinate": mid_isl,
                    "coordinates": [u_pt, v_pt],
                })
                step_num += 1
                i += 1
                continue

            # -------------------------------------------------------------
            # 3. Sidewalk run: Turn & Arc Detection
            # -------------------------------------------------------------
            turn_cfg = self.weights.turn
            if i == 0:
                turn_diff = 0.0
            else:
                turn_diff = normalize_angle_diff(bearings[i - 1], bearings[i])

            # Check if edge i starts a curving arc (2+ short consecutive edges turning same direction)
            arc_edges: List[int] = []
            if edge.length_m <= turn_cfg.arc_max_edge_length_m and abs(turn_diff) >= 10.0:
                arc_sign = 1 if turn_diff > 0 else -1
                cand_edges = [i]
                cum_angle = turn_diff
                j = i + 1
                while j < n and edges[j].feature_type == "sidewalk":
                    next_sw = edges[j].sidewalk
                    if next_sw and getattr(next_sw, "footway", None) == "traffic_island":
                        break
                    if edges[j].length_m > turn_cfg.arc_max_edge_length_m:
                        break
                    d = normalize_angle_diff(bearings[j - 1], bearings[j])
                    if (d * arc_sign > 0 and abs(d) >= 10.0) or (abs(d) < 10.0 and len(cand_edges) > 1):
                        cand_edges.append(j)
                        cum_angle += d
                        j += 1
                    else:
                        break
                if len(cand_edges) >= 2 and abs(cum_angle) >= turn_cfg.arc_min_cumulative_deg:
                    arc_edges = cand_edges

            if arc_edges:
                arc_dist = sum(edges[k].length_m for k in arc_edges)
                if arc_edges[0] > 0:
                    arc_cum_angle = normalize_angle_diff(bearings[arc_edges[0] - 1], bearings[arc_edges[-1]])
                else:
                    arc_cum_angle = normalize_angle_diff(bearings[0], bearings[arc_edges[-1]])

                q_angle = self.weights.quantize_turn_angle(arc_cum_angle)
                dir_str = "right" if arc_cum_angle > 0 else "left"
                clock_pos = self.verbiage.angle_to_clock(arc_cum_angle)

                curve_name = edges[arc_edges[0]].sidewalk.name if edges[arc_edges[0]].sidewalk else "sidewalk"
                speech = self.verbiage.format_curve(
                    direction=dir_str,
                    distance_m=arc_dist,
                    name=curve_name,
                )
                has_tactile = any(edges[k].sidewalk and edges[k].sidewalk.has_tactile_paving for k in arc_edges)

                arc_pts = []
                for k in arc_edges:
                    p_u = list(nodes.get(edges[k].u, (0.0, 0.0)))
                    p_v = list(nodes.get(edges[k].v, (0.0, 0.0)))
                    if not arc_pts or arc_pts[-1] != p_u:
                        arc_pts.append(p_u)
                    arc_pts.append(p_v)
                mid_arc = arc_pts[len(arc_pts) // 2] if arc_pts else [0.0, 0.0]

                instructions.append({
                    "step": step_num,
                    "action": "WALK_SIDEWALK",
                    "distance_m": round(arc_dist, 1),
                    "spoken_instruction": speech,
                    "tactile_cue": has_tactile,
                    "is_curve": True,
                    "turn_direction": dir_str,
                    "turn_angle_deg": q_angle,
                    "clock_position": clock_pos,
                    "coordinate": mid_arc,
                    "coordinates": arc_pts,
                })
                step_num += 1
                i = arc_edges[-1] + 1
                continue

            # Discrete turn or straight sidewalk walk
            is_discrete_turn = abs(turn_diff) >= turn_cfg.min_turn_angle_deg
            q_turn = self.weights.quantize_turn_angle(turn_diff) if is_discrete_turn else 0
            turn_dir = ("right" if turn_diff > 0 else "left") if is_discrete_turn else None
            clock_pos = self.verbiage.angle_to_clock(turn_diff) if is_discrete_turn else None

            # Accumulate straight sidewalk distance
            straight_dist = edge.length_m
            has_tactile = sw.has_tactile_paving if sw else False
            is_bridge = sw.is_bridge if sw else False
            default_name = "bridge walkway" if is_bridge else "sidewalk"
            name = sw.name if (sw and sw.name) else default_name
            surface = f"{sw.surface} " if (sw and sw.surface) else ""
            width = f"({sw.width_m}m wide) " if (sw and sw.width_m) else ""
            tactile = "with tactile guidance " if has_tactile else ""

            j = i + 1
            while j < n and edges[j].feature_type == "sidewalk":
                next_sw = edges[j].sidewalk
                if next_sw and getattr(next_sw, "footway", None) == "traffic_island":
                    break
                if next_sw and getattr(next_sw, "is_bridge", False) != is_bridge:
                    break
                d = normalize_angle_diff(bearings[j - 1], bearings[j])
                if abs(d) >= turn_cfg.min_turn_angle_deg:
                    break
                straight_dist += edges[j].length_m
                has_tactile = has_tactile or (next_sw and next_sw.has_tactile_paving)
                j += 1

            target_desc = f"{surface}{name} {width}{tactile}".strip()

            if is_discrete_turn:
                speech, meta = self.verbiage.format_turn(
                    angle_deg=q_turn,
                    direction=turn_dir,
                    target=target_desc,
                    distance_m=straight_dist,
                    raw_angle=turn_diff,
                )
            else:
                speech = f"Follow {target_desc} for {straight_dist:.0f} meters."

            speech = re.sub(r"\s+", " ", speech).strip()

            run_pts = []
            for k in range(i, j):
                p_u = list(nodes.get(edges[k].u, (0.0, 0.0)))
                p_v = list(nodes.get(edges[k].v, (0.0, 0.0)))
                if not run_pts or run_pts[-1] != p_u:
                    run_pts.append(p_u)
                run_pts.append(p_v)
            mid_run = run_pts[len(run_pts) // 2] if run_pts else [0.0, 0.0]

            inst_dict: Dict[str, Any] = {
                "step": step_num,
                "action": "WALK_SIDEWALK",
                "distance_m": round(straight_dist, 1),
                "spoken_instruction": speech,
                "tactile_cue": has_tactile,
                "coordinate": mid_run,
                "coordinates": run_pts,
            }
            if is_discrete_turn:
                inst_dict["turn_direction"] = turn_dir
                inst_dict["turn_angle_deg"] = q_turn
                inst_dict["clock_position"] = clock_pos
                inst_dict["direction_mode"] = self.verbiage.direction_mode.value

            instructions.append(inst_dict)
            step_num += 1
            i = j

        dest_coord = list(nodes.get(route.node_path[-1], (0.0, 0.0))) if route.node_path else [0.0, 0.0]
        instructions.append({
            "step": step_num,
            "action": "ARRIVE",
            "spoken_instruction": "You have arrived at your destination.",
            "coordinate": dest_coord,
        })

        return self._consolidate_instructions(instructions)

    def _consolidate_instructions(self, raw_instructions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Combine consecutive straight sidewalk and crosswalk steps into single clean announcements."""
        consolidated: List[Dict[str, Any]] = []

        i = 0
        while i < len(raw_instructions):
            curr = raw_instructions[i]

            # 1. Consolidate consecutive straight WALK_SIDEWALK actions
            # (skip refuge islands, curving arcs, and steps that start with a discrete turn)
            is_plain_straight_walk = (
                curr["action"] == "WALK_SIDEWALK"
                and not curr.get("is_refuge_island")
                and not curr.get("is_curve")
                and not curr.get("turn_direction")
            )

            if is_plain_straight_walk:
                total_dist = curr.get("distance_m", 0.0)
                tactile = curr.get("tactile_cue", False)
                base_speech = curr["spoken_instruction"]

                descriptor = base_speech.split(" for ")[0] if " for " in base_speech else "Follow sidewalk"

                j = i + 1
                while j < len(raw_instructions):
                    next_inst = raw_instructions[j]
                    next_is_plain = (
                        next_inst["action"] == "WALK_SIDEWALK"
                        and not next_inst.get("is_refuge_island")
                        and not next_inst.get("is_curve")
                        and not next_inst.get("turn_direction")
                    )
                    if not next_is_plain:
                        break

                    next_speech = next_inst["spoken_instruction"]
                    next_desc = next_speech.split(" for ")[0] if " for " in next_speech else "Follow sidewalk"

                    if descriptor == next_desc:
                        total_dist += next_inst.get("distance_m", 0.0)
                        tactile = tactile or next_inst.get("tactile_cue", False)
                        j += 1
                    else:
                        break

                combined_coords = []
                for k in range(i, j):
                    for pt in raw_instructions[k].get("coordinates", []):
                        if not combined_coords or combined_coords[-1] != pt:
                            combined_coords.append(pt)
                mid_c = combined_coords[len(combined_coords) // 2] if combined_coords else curr.get("coordinate")

                consolidated.append({
                    "step": len(consolidated) + 1,
                    "action": "WALK_SIDEWALK",
                    "distance_m": round(total_dist, 1),
                    "spoken_instruction": f"{descriptor} for {total_dist:.0f} meters.",
                    "tactile_cue": tactile,
                    "coordinate": mid_c,
                    "coordinates": combined_coords if combined_coords else curr.get("coordinates"),
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
