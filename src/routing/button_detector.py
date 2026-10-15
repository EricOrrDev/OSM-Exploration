"""Crosswalk push-button and Accessible Pedestrian Signal (APS) locator detection."""

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Tuple

from ..models.pedestrian import CrosswalkFeature, PedestrianNetwork
from .intersection_classifier import calculate_bearing, normalize_angle_diff
from .pedestrian_graph import RouteResult, haversine_distance_m


@dataclass
class ButtonCue:
    """Spoken and tactile guidance cue for an Accessible Pedestrian Signal or push-button."""

    has_button: bool
    relative_direction: Optional[str] = None  # "to your left", "to your right", "directly ahead"
    distance_m: Optional[float] = None
    has_audible_locator: bool = False
    has_vibrotactile_arrow: bool = False
    instruction_text: Optional[str] = None


class ButtonDetector:
    """Calculates relative orientation (left/right) and proximity to crosswalk activation buttons."""

    def __init__(self, network: PedestrianNetwork):
        self.network = network

    def detect_button_cue(self, route: RouteResult, edge_idx: int) -> ButtonCue:
        """Evaluate the crosswalk edge at edge_idx to locate push-button signals relative to traveler."""
        edge = route.edges[edge_idx]
        if edge.feature_type != "crosswalk":
            return ButtonCue(has_button=False)

        cw: Optional[CrosswalkFeature] = edge.crosswalk
        u = edge.u  # Departure curb ramp node
        v = edge.v  # Arrival curb ramp node

        nodes = self.network.raw_nodes
        if u not in nodes or v not in nodes:
            return ButtonCue(has_button=False)

        p_u = nodes[u]
        p_v = nodes[v]

        # Bearing of the crossing corridor from curb u across to curb v
        crossing_bearing = calculate_bearing(p_u, p_v)

        # 1. Search for nearby button nodes within 6 meters of curb ramp u
        best_btn_id = None
        min_btn_dist = float("inf")

        for btn_id, p_btn in self.network.button_nodes.items():
            dist = haversine_distance_m(p_u, p_btn)
            if dist < min_btn_dist and dist <= 6.0:
                min_btn_dist = dist
                best_btn_id = btn_id

        # Also inspect tags of node u itself or constituent nodes
        u_tags = self.network.node_tags.get(u, {})
        has_btn_on_node = u_tags.get("button_operated") == "yes"
        has_aps_sound = (
            u_tags.get("traffic_signals:sound") in ("yes", "locate", "acoustic")
            or (cw.has_audible_signals if cw else False)
        )
        has_vibe = (
            u_tags.get("traffic_signals:vibration") == "yes"
            or (cw.has_vibrotactile if cw else False)
        )

        if best_btn_id is not None:
            p_btn = self.network.button_nodes[best_btn_id]
            btn_tags = self.network.node_tags.get(best_btn_id, {})

            if btn_tags.get("traffic_signals:sound") in ("yes", "locate", "acoustic"):
                has_aps_sound = True
            if btn_tags.get("traffic_signals:vibration") == "yes":
                has_vibe = True

            # If the button node is offset from the curb, calculate relative bearing
            if min_btn_dist > 0.4:
                btn_bearing = calculate_bearing(p_u, p_btn)
                diff = normalize_angle_diff(crossing_bearing, btn_bearing)

                if -165.0 <= diff <= -15.0:
                    rel_dir = "to your left"
                elif 15.0 <= diff <= 165.0:
                    rel_dir = "to your right"
                else:
                    rel_dir = "directly ahead"
            else:
                rel_dir = "at your curb ramp"

            dist_str = f", approximately {min_btn_dist:.1f} meters away," if min_btn_dist >= 0.8 else ""

            features = []
            if has_aps_sound:
                features.append("audible locator tone")
            if has_vibe:
                features.append("raised vibrotactile arrow")

            feat_str = f" with {' and '.join(features)}" if features else ""
            instruction = (
                f"{rel_dir.capitalize()}{dist_str} there is an Accessible Pedestrian Signal push-button{feat_str}."
            )

            return ButtonCue(
                has_button=True,
                relative_direction=rel_dir,
                distance_m=round(min_btn_dist, 1),
                has_audible_locator=has_aps_sound,
                has_vibrotactile_arrow=has_vibe,
                instruction_text=instruction,
            )

        # 2. If no separate button node was found, but way or curb indicates button operation
        if (cw and cw.has_button) or has_btn_on_node or (cw and cw.has_signals):
            rel_dir = "to your right"  # PROWAG standard mounting
            features = []
            if has_aps_sound:
                features.append("audible locator tone")
            if has_vibe:
                features.append("raised vibrotactile arrow")

            feat_str = f" with {' and '.join(features)}" if features else ""
            btn_type = "Accessible Pedestrian Signal push-button" if has_aps_sound else "crosswalk activation button"
            instruction = f"{rel_dir.capitalize()} there is a {btn_type}{feat_str} on the signal pole."

            return ButtonCue(
                has_button=True,
                relative_direction=rel_dir,
                distance_m=1.5,
                has_audible_locator=has_aps_sound,
                has_vibrotactile_arrow=has_vibe,
                instruction_text=instruction,
            )

        return ButtonCue(has_button=False)
