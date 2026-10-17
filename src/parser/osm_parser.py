"""Parses raw Overpass JSON into structured OpenSidewalks PedestrianNetwork."""

from typing import Any, Dict, List, Optional, Tuple
from ..models.pedestrian import (
    CrosswalkFeature,
    KerbFeature,
    PedestrianNetwork,
    SidewalkFeature,
)


class OSMParser:
    """Transforms OpenStreetMap nodes and ways into accessible pedestrian entities."""

    def parse(self, overpass_data: Dict[str, Any]) -> PedestrianNetwork:
        """Parse raw Overpass response into a typed PedestrianNetwork."""
        elements: List[Dict[str, Any]] = overpass_data.get("elements", [])

        raw_nodes: Dict[int, Tuple[float, float]] = {}
        node_tags_map: Dict[int, Dict[str, str]] = {}
        kerbs: Dict[int, KerbFeature] = {}
        crosswalk_nodes: Dict[int, Dict[str, Any]] = {}
        button_nodes: Dict[int, Tuple[float, float]] = {}
        ways: List[Dict[str, Any]] = []

        # First pass: Index all nodes and their tags
        for el in elements:
            if el.get("type") == "node":
                node_id = el["id"]
                lat = float(el["lat"])
                lon = float(el["lon"])
                raw_nodes[node_id] = (lat, lon)
                tags = el.get("tags", {})
                node_tags_map[node_id] = tags

                # Curb nodes (must have explicit kerb tag or barrier=kerb, not bare highway=crossing)
                if "kerb" in tags or tags.get("barrier") == "kerb":
                    kerb_type = tags.get("kerb", "unknown")
                    has_tactile = tags.get("tactile_paving") == "yes" or tags.get("kerb:tactile_paving") == "yes"
                    height = self._parse_float(tags.get("kerb:height"))
                    kerbs[node_id] = KerbFeature(
                        id=node_id,
                        coordinate=(lat, lon),
                        kerb_type=kerb_type,
                        has_tactile_paving=has_tactile,
                        height_cm=height,
                    )

                # Standalone crossing nodes
                if tags.get("highway") == "crossing":
                    crosswalk_nodes[node_id] = {
                        "lat": lat,
                        "lon": lon,
                        "tags": tags,
                    }

                # Push-button and APS signal nodes
                if tags.get("button_operated") == "yes" or "traffic_signals:sound" in tags or tags.get("highway") == "traffic_signals":
                    button_nodes[node_id] = (lat, lon)

            elif el.get("type") == "way":
                ways.append(el)

        crosswalks: Dict[int, CrosswalkFeature] = {}
        sidewalks: Dict[int, SidewalkFeature] = {}

        # Second pass: Process ways
        for way in ways:
            way_id = way["id"]
            node_ids = way.get("nodes", [])
            coords = [raw_nodes[nid] for nid in node_ids if nid in raw_nodes]
            tags = way.get("tags", {})
            name = tags.get("name")

            is_crossing = (
                tags.get("footway") == "crossing"
                or tags.get("highway") == "crossing"
                or "crossing" in tags
            )

            if is_crossing:
                # Check way-level tags first, then inherit from constituent nodes
                crossing_type = tags.get("crossing")
                markings = tags.get("crossing:markings")
                has_signals = tags.get("crossing:signals") == "yes" or tags.get("crossing") == "traffic_signals"
                has_sound = tags.get("traffic_signals:sound") in ("yes", "locate", "acoustic")
                has_vibe = tags.get("traffic_signals:vibration") == "yes"
                has_tactile = tags.get("tactile_paving") == "yes"
                has_island = tags.get("crossing:island") == "yes"
                has_button = tags.get("button_operated") == "yes"

                # Check if any constituent node has APS, tactile, or button attributes
                for nid in node_ids:
                    n_tags = node_tags_map.get(nid, {})
                    if n_tags.get("traffic_signals:sound") in ("yes", "locate", "acoustic"):
                        has_sound = True
                    if n_tags.get("traffic_signals:vibration") == "yes":
                        has_vibe = True
                    if n_tags.get("tactile_paving") == "yes" or n_tags.get("kerb:tactile_paving") == "yes":
                        has_tactile = True
                    if n_tags.get("crossing") == "traffic_signals":
                        has_signals = True
                    if n_tags.get("button_operated") == "yes":
                        has_button = True

                crosswalks[way_id] = CrosswalkFeature(
                    id=way_id,
                    name=name,
                    node_ids=node_ids,
                    coordinates=coords,
                    crossing_type=crossing_type,
                    markings=markings,
                    has_signals=has_signals,
                    has_audible_signals=has_sound,
                    has_vibrotactile=has_vibe,
                    has_tactile_paving=has_tactile,
                    has_refuge_island=has_island,
                    has_button=has_button,
                )
            else:
                # Regular sidewalk / footway
                width = self._parse_float(tags.get("width"))
                surface = tags.get("surface")
                smoothness = tags.get("smoothness")
                has_tactile = tags.get("tactile_paving") == "yes"
                incline = self._parse_float(tags.get("incline"))
                footway = tags.get("footway")

                sidewalks[way_id] = SidewalkFeature(
                    id=way_id,
                    name=name,
                    node_ids=node_ids,
                    coordinates=coords,
                    width_m=width,
                    surface=surface,
                    smoothness=smoothness,
                    has_tactile_paving=has_tactile,
                    incline_pct=incline,
                    footway=footway,
                )

        return PedestrianNetwork(
            crosswalks=crosswalks,
            kerbs=kerbs,
            sidewalks=sidewalks,
            raw_nodes=raw_nodes,
            button_nodes=button_nodes,
            node_tags=node_tags_map,
        )

    def _parse_float(self, value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        cleaned = value.replace("m", "").replace("cm", "").replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
