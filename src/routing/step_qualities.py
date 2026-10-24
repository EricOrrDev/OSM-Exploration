"""Step Qualities Extractor for Pedestrian Routes.

Traverses route edges to assemble rich, un-pruned physical, topological,
tactile, signal, and hazard qualities into a list of NavigationStepQualities.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

from ..models.pedestrian import KerbFeature, PedestrianNetwork
from ..models.qualities import (
    ButtonQualities,
    CrossingQualities,
    HazardQualities,
    KerbQualities,
    NavigationStepQualities,
    PathQualities,
    SignalQualities,
    StepAction,
    TurnQualities,
)
from ..spatial.gpkg_registry import LayerRole
from .button_detector import ButtonDetector
from .intersection_classifier import IntersectionClassifier
from .pedestrian_graph import RouteResult, calculate_bearing, normalize_angle_diff
from .safety_weights import DEFAULT_SAFETY_WEIGHTS, SafetyWeightsConfig


class StepQualitiesExtractor:
    """Extracts raw semantic qualities for each navigation step along a pedestrian route."""

    def __init__(
        self,
        network: PedestrianNetwork,
        classifier: Optional[IntersectionClassifier] = None,
        button_detector: Optional[ButtonDetector] = None,
        map_data_dir: Optional[Path] = None,
        weights: Optional[SafetyWeightsConfig] = None,
    ):
        self.network = network
        self.classifier = classifier or IntersectionClassifier(network, map_data_dir=map_data_dir)
        self.button_detector = button_detector or ButtonDetector(network)
        self.weights = weights or DEFAULT_SAFETY_WEIGHTS

    def extract_qualities(self, route: RouteResult) -> List[NavigationStepQualities]:
        """Extract comprehensive raw semantic qualities for each route step."""
        raw_steps: List[NavigationStepQualities] = []
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

                ctx = self.classifier.classify_intersection(route, i)
                btn_cue = self.button_detector.detect_button_cue(route, i)

                prev_edge = edges[i - 1] if i > 0 else None
                next_edge = edges[i + 1] if (i + 1 < n) else None

                is_crossing_entry = (prev_edge is None or prev_edge.feature_type != "crosswalk")
                is_crossing_exit = (next_edge is None or next_edge.feature_type != "crosswalk")

                # Resolve entry kerb
                u_kerb = kerbs.get(edge.u)
                entry_kerb = u_kerb
                if is_crossing_entry and not entry_kerb and self.classifier.registry and edge.u in nodes:
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
                    u_coord = nodes.get(edge.u, (0.0, 0.0))
                    entry_kerb = KerbFeature(
                        id=-1,
                        coordinate=u_coord,
                        kerb_type="lowered",
                        has_tactile_paving=False,
                    )

                # Entry curb step
                target_name = (ctx.spoken_road_name or ctx.road_crossed) if ctx else None
                if is_crossing_entry and entry_kerb:
                    u_pt = list(nodes.get(edge.u, (0.0, 0.0)))
                    entry_pt = list(entry_kerb.coordinate) if (entry_kerb and entry_kerb.coordinate != (0.0, 0.0)) else u_pt
                    tactile_desc = "tactile truncated domes" if entry_kerb.has_tactile_paving else None

                    raw_steps.append(NavigationStepQualities(
                        step_index=step_num,
                        action=StepAction.APPROACH_CURB,
                        distance_m=0.0,
                        coordinate=entry_pt,
                        coordinates=[entry_pt],
                        bearing_deg=bearings[i] if i < len(bearings) else None,
                        kerb=KerbQualities(
                            present=True,
                            action_type="step_down",
                            kerb_type=entry_kerb.kerb_type,
                            is_step_free=entry_kerb.is_step_free,
                            has_tactile_paving=entry_kerb.has_tactile_paving,
                            tactile_description=tactile_desc,
                            cross_target=target_name,
                        ),
                        crossing=CrossingQualities(
                            is_crossing=True,
                            road_crossed=ctx.road_crossed if ctx else None,
                            spoken_road_name=ctx.spoken_road_name if ctx else None,
                            corridor_street=ctx.corridor_street if ctx else None,
                            semantic_crossing_type=ctx.semantic_crossing_type.value if (ctx and hasattr(ctx.semantic_crossing_type, "value")) else None,
                            turning_vehicle_warning=ctx.turning_vehicle_warning if ctx else False,
                        ),
                        button=ButtonQualities(
                            has_button=btn_cue.has_button,
                            relative_direction=btn_cue.relative_direction,
                            instruction_text=btn_cue.instruction_text if btn_cue.has_button else None,
                        ),
                    ))
                    step_num += 1

                # Street crossing step
                has_anomaly = getattr(cw, "has_data_anomaly", False) or getattr(edge, "has_data_anomaly", False)
                anomaly_cue = None
                if has_anomaly:
                    anomaly = getattr(cw, "data_anomaly", None)
                    anomaly_cue = getattr(anomaly, "spoken_caution_cue", "Proceed with elevated caution: Inconsistent data between map sources for this crossing.")

                cw_pts = [list(c) for c in cw.coordinates] if (cw and len(cw.coordinates) >= 2) else [list(nodes.get(edge.u, (0.0, 0.0))), list(nodes.get(edge.v, (0.0, 0.0)))]
                mid_cw = [(cw_pts[0][0] + cw_pts[-1][0]) / 2.0, (cw_pts[0][1] + cw_pts[-1][1]) / 2.0] if cw_pts else [0.0, 0.0]

                raw_steps.append(NavigationStepQualities(
                    step_index=step_num,
                    action=StepAction.CROSS_STREET,
                    distance_m=edge.length_m,
                    coordinate=mid_cw,
                    coordinates=cw_pts,
                    bearing_deg=bearings[i] if i < len(bearings) else None,
                    crossing=CrossingQualities(
                        is_crossing=True,
                        intersection_type=ctx.intersection_type.value if ctx else None,
                        road_crossed=ctx.road_crossed if ctx else None,
                        spoken_road_name=ctx.spoken_road_name if ctx else None,
                        corridor_street=ctx.corridor_street if ctx else None,
                        is_corridor_continuation=ctx.is_corridor_continuation if ctx else True,
                        markings=cw.markings if cw else None,
                        has_refuge_island=ctx.has_refuge_island if ctx else False,
                        lanes_crossed=ctx.lanes_crossed if ctx else None,
                        turning_vehicle_warning=ctx.turning_vehicle_warning if ctx else False,
                        semantic_crossing_type=ctx.semantic_crossing_type.value if (ctx and hasattr(ctx.semantic_crossing_type, "value")) else None,
                    ),
                    signal=SignalQualities(
                        has_signals=cw.has_signals if cw else False,
                        has_audible_signals=cw.has_audible_signals if cw else False,
                        has_vibrotactile=cw.has_vibrotactile if cw else False,
                    ),
                    hazard=HazardQualities(
                        hazard_metric=cw.hazard_metric if cw else 0.0,
                        safety_score=cw.safety_score if cw else 1.0,
                        has_data_anomaly=has_anomaly,
                        anomaly_cue=anomaly_cue,
                    ),
                ))
                step_num += 1

                # Exit curb step
                v_kerb = kerbs.get(edge.v)
                exit_kerb = v_kerb
                if is_crossing_exit and not exit_kerb and self.classifier.registry and edge.v in nodes:
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
                    v_coord = nodes.get(edge.v, (0.0, 0.0))
                    exit_kerb = KerbFeature(
                        id=-1,
                        coordinate=v_coord,
                        kerb_type="lowered",
                        has_tactile_paving=False,
                    )

                if is_crossing_exit and exit_kerb:
                    v_pt = list(nodes.get(edge.v, (0.0, 0.0)))
                    exit_pt = list(exit_kerb.coordinate) if (exit_kerb and exit_kerb.coordinate != (0.0, 0.0)) else v_pt
                    exit_tactile_desc = "tactile paving" if exit_kerb.has_tactile_paving else None

                    raw_steps.append(NavigationStepQualities(
                        step_index=step_num,
                        action=StepAction.EXIT_CURB,
                        distance_m=0.0,
                        coordinate=exit_pt,
                        coordinates=[exit_pt],
                        bearing_deg=bearings[i] if i < len(bearings) else None,
                        kerb=KerbQualities(
                            present=True,
                            action_type="step_up",
                            kerb_type=exit_kerb.kerb_type,
                            is_step_free=exit_kerb.is_step_free,
                            has_tactile_paving=exit_kerb.has_tactile_paving,
                            tactile_description=exit_tactile_desc,
                            cross_target=target_name,
                        ),
                        crossing=CrossingQualities(
                            is_crossing=True,
                            road_crossed=ctx.road_crossed if ctx else None,
                            spoken_road_name=ctx.spoken_road_name if ctx else None,
                            corridor_street=ctx.corridor_street if ctx else None,
                            semantic_crossing_type=ctx.semantic_crossing_type.value if (ctx and hasattr(ctx.semantic_crossing_type, "value")) else None,
                        ),
                    ))
                    step_num += 1

                i += 1
                continue

            # -------------------------------------------------------------
            # 2. Sidewalk refuge island handling
            # -------------------------------------------------------------
            sw = edge.sidewalk
            is_traffic_island = sw and (sw.footway == "traffic_island" or getattr(sw, "footway", None) == "traffic_island")
            if is_traffic_island:
                u_pt = list(nodes.get(edge.u, (0.0, 0.0)))
                v_pt = list(nodes.get(edge.v, (0.0, 0.0)))
                mid_isl = [(u_pt[0] + v_pt[0]) / 2.0, (u_pt[1] + v_pt[1]) / 2.0]

                raw_steps.append(NavigationStepQualities(
                    step_index=step_num,
                    action=StepAction.WAIT_REFUGE,
                    distance_m=edge.length_m,
                    coordinate=mid_isl,
                    coordinates=[u_pt, v_pt],
                    bearing_deg=bearings[i] if i < len(bearings) else None,
                    path=PathQualities(
                        name="pedestrian refuge island",
                        is_traffic_island=True,
                        has_tactile_guideway=sw.has_tactile_paving if sw else False,
                    ),
                ))
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
                clock_pos = self.weights.verbiage.angle_to_clock(arc_cum_angle)
                curve_name = edges[arc_edges[0]].sidewalk.name if edges[arc_edges[0]].sidewalk else "sidewalk"
                has_tactile = any(edges[k].sidewalk and edges[k].sidewalk.has_tactile_paving for k in arc_edges)

                arc_pts = []
                for k in arc_edges:
                    p_u = list(nodes.get(edges[k].u, (0.0, 0.0)))
                    p_v = list(nodes.get(edges[k].v, (0.0, 0.0)))
                    if not arc_pts or arc_pts[-1] != p_u:
                        arc_pts.append(p_u)
                    arc_pts.append(p_v)
                mid_arc = arc_pts[len(arc_pts) // 2] if arc_pts else [0.0, 0.0]

                raw_steps.append(NavigationStepQualities(
                    step_index=step_num,
                    action=StepAction.WALK_SIDEWALK,
                    distance_m=round(arc_dist, 1),
                    coordinate=mid_arc,
                    coordinates=arc_pts,
                    bearing_deg=bearings[arc_edges[-1]],
                    path=PathQualities(
                        name=curve_name,
                        has_tactile_guideway=has_tactile,
                    ),
                    turn=TurnQualities(
                        is_turn=True,
                        is_curve=True,
                        turn_direction=dir_str,
                        turn_angle_deg=q_angle,
                        raw_turn_angle_deg=arc_cum_angle,
                        clock_position=clock_pos,
                        curve_arc_deg=arc_cum_angle,
                    ),
                ))
                step_num += 1
                i = arc_edges[-1] + 1
                continue

            # Discrete turn or straight sidewalk walk
            is_discrete_turn = abs(turn_diff) >= turn_cfg.min_turn_angle_deg
            q_turn = self.weights.quantize_turn_angle(turn_diff) if is_discrete_turn else 0
            turn_dir = ("right" if turn_diff > 0 else "left") if is_discrete_turn else None
            clock_pos = self.weights.verbiage.angle_to_clock(turn_diff) if is_discrete_turn else None

            straight_dist = edge.length_m
            has_tactile = sw.has_tactile_paving if sw else False
            is_bridge = sw.is_bridge if sw else False
            default_name = "bridge walkway" if is_bridge else "sidewalk"
            name = sw.name if (sw and sw.name) else default_name
            surface = sw.surface if (sw and sw.surface) else None
            smoothness = sw.smoothness if (sw and sw.smoothness) else None
            width = sw.width_m if (sw and sw.width_m) else None
            incline = sw.incline_pct if (sw and sw.incline_pct) else None

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

            run_pts = []
            for k in range(i, j):
                p_u = list(nodes.get(edges[k].u, (0.0, 0.0)))
                p_v = list(nodes.get(edges[k].v, (0.0, 0.0)))
                if not run_pts or run_pts[-1] != p_u:
                    run_pts.append(p_u)
                run_pts.append(p_v)
            mid_run = run_pts[len(run_pts) // 2] if run_pts else [0.0, 0.0]

            raw_steps.append(NavigationStepQualities(
                step_index=step_num,
                action=StepAction.WALK_SIDEWALK,
                distance_m=round(straight_dist, 1),
                coordinate=mid_run,
                coordinates=run_pts,
                bearing_deg=bearings[j - 1],
                path=PathQualities(
                    name=name,
                    surface=surface,
                    smoothness=smoothness,
                    width_m=width,
                    incline_pct=incline,
                    has_tactile_guideway=has_tactile,
                    is_bridge=is_bridge,
                ),
                turn=TurnQualities(
                    is_turn=is_discrete_turn,
                    is_curve=False,
                    turn_direction=turn_dir,
                    turn_angle_deg=q_turn,
                    raw_turn_angle_deg=turn_diff if is_discrete_turn else None,
                    clock_position=clock_pos,
                ),
            ))
            step_num += 1
            i = j

        # Final arrival step
        dest_coord = list(nodes.get(route.node_path[-1], (0.0, 0.0))) if route.node_path else [0.0, 0.0]
        raw_steps.append(NavigationStepQualities(
            step_index=step_num,
            action=StepAction.ARRIVE,
            distance_m=0.0,
            coordinate=dest_coord,
            coordinates=[dest_coord],
        ))

        return self._consolidate_qualities(raw_steps)

    def _consolidate_qualities(self, raw_steps: List[NavigationStepQualities]) -> List[NavigationStepQualities]:
        """Combine consecutive straight sidewalk runs and consecutive crosswalk segments crossing the same road."""
        consolidated: List[NavigationStepQualities] = []
        i = 0
        while i < len(raw_steps):
            curr = raw_steps[i]

            # 1. Consolidate consecutive straight WALK_SIDEWALK actions
            is_plain_straight = (
                curr.action == StepAction.WALK_SIDEWALK
                and not curr.path.is_traffic_island
                and not curr.turn.is_curve
                and not curr.turn.is_turn
            )

            if is_plain_straight:
                total_dist = curr.distance_m
                tactile = curr.path.has_tactile_guideway
                name = curr.path.name

                j = i + 1
                while j < len(raw_steps):
                    next_s = raw_steps[j]
                    next_is_plain = (
                        next_s.action == StepAction.WALK_SIDEWALK
                        and not next_s.path.is_traffic_island
                        and not next_s.turn.is_curve
                        and not next_s.turn.is_turn
                    )
                    if not next_is_plain or next_s.path.name != name:
                        break
                    total_dist += next_s.distance_m
                    tactile = tactile or next_s.path.has_tactile_guideway
                    j += 1

                combined_coords = []
                for k in range(i, j):
                    for pt in raw_steps[k].coordinates:
                        if not combined_coords or combined_coords[-1] != pt:
                            combined_coords.append(pt)
                mid_c = combined_coords[len(combined_coords) // 2] if combined_coords else curr.coordinate

                c_step = curr.model_copy(deep=True)
                c_step.step_index = len(consolidated) + 1
                c_step.distance_m = round(total_dist, 1)
                c_step.coordinate = mid_c
                c_step.coordinates = combined_coords if combined_coords else curr.coordinates
                c_step.path.has_tactile_guideway = tactile
                consolidated.append(c_step)
                i = j

            # 2. Consolidate consecutive CROSS_STREET actions crossing the same roadway feature
            elif curr.action == StepAction.CROSS_STREET:
                total_dist = curr.distance_m
                road = curr.crossing.road_crossed
                itype = curr.crossing.intersection_type

                j = i + 1
                while j < len(raw_steps) and raw_steps[j].action == StepAction.CROSS_STREET:
                    next_s = raw_steps[j]
                    if (
                        next_s.crossing.road_crossed == road
                        and next_s.crossing.intersection_type == itype
                    ):
                        total_dist += next_s.distance_m
                        j += 1
                    else:
                        break

                c_step = curr.model_copy(deep=True)
                c_step.step_index = len(consolidated) + 1
                c_step.distance_m = round(total_dist, 1)
                consolidated.append(c_step)
                i = j

            else:
                c_step = curr.model_copy(deep=True)
                c_step.step_index = len(consolidated) + 1
                consolidated.append(c_step)
                i += 1

        return consolidated
