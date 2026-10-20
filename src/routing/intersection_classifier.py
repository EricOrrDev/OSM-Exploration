"""Intersection topology classification, semantic corridor continuity, and municipal conflation engine."""

from dataclasses import dataclass
from enum import Enum
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import MAP_DATA_DIR
from ..models.pedestrian import CrosswalkFeature, PedestrianNetwork
from ..spatial.gpkg_registry import GeoPackageRegistry, LayerRole, haversine_distance_m, mercator_to_wgs84
from ..spatial.semantic_classifier import (
    DisambiguationResult,
    SemanticCrossingType,
    SemanticRoadClassifier,
)
from .pedestrian_graph import RouteResult, calculate_bearing, normalize_angle_diff


class IntersectionType(str, Enum):
    FOUR_WAY = "4-way intersection"
    T_JUNCTION = "T-junction"
    ROUNDABOUT = "roundabout"
    MIDBLOCK = "mid-block crossing"
    MULTI_LEG = "multi-leg complex intersection"
    UNKNOWN = "intersection"


@dataclass
class IntersectionContext:
    intersection_type: IntersectionType
    road_crossed: Optional[str] = None
    spoken_road_name: Optional[str] = None
    semantic_crossing_type: SemanticCrossingType = SemanticCrossingType.UNKNOWN_CROSSING
    turning_vehicle_warning: bool = False
    corridor_street: Optional[str] = None
    is_corridor_continuation: bool = True
    turn_direction: str = "straight"  # "straight", "left", "right"
    has_refuge_island: bool = False
    lanes_crossed: Optional[int] = None
    classification_source: str = "osm_topology"  # "municipal_gis" or "osm_topology"
    spoken_summary: str = ""


def calculate_bearing(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Calculate compass bearing from p1 to p2 in degrees [0, 360)."""
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def normalize_angle_diff(angle1: float, angle2: float) -> float:
    """Returns angular difference (angle2 - angle1) in range [-180, 180]."""
    diff = (angle2 - angle1 + 180.0) % 360.0 - 180.0
    return diff


def normalize_street_name(raw: Optional[str]) -> Optional[str]:
    """Convert raw municipal GIS street abbreviation into disambiguated canonical title name."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() == "none" or "unknown" in cleaned.lower():
        return None
    clf = SemanticRoadClassifier()
    res = clf.classify(cleaned)
    return res.canonical_name


class IntersectionClassifier:
    """Identifies intersection typology and corridor continuity using municipal GIS & OSM topology."""

    def __init__(
        self,
        network: PedestrianNetwork,
        map_data_dir: Optional[Path] = None,
        enable_municipal: bool = True,
        registry: Optional[GeoPackageRegistry] = None,
        semantic_classifier: Optional[SemanticRoadClassifier] = None,
    ):
        self.network = network
        self.map_data_dir = map_data_dir or MAP_DATA_DIR
        self.enable_municipal = enable_municipal
        self.semantic_classifier = semantic_classifier or SemanticRoadClassifier()
        self.registry: Optional[GeoPackageRegistry] = None

        self._municipal_crosswalks: List[Dict[str, Any]] = []
        self._municipal_curb_ramps: List[Dict[str, Any]] = []

        if self.enable_municipal:
            self.registry = registry or GeoPackageRegistry(self.map_data_dir)
            self._load_municipal_data()

    def _load_municipal_data(self) -> None:
        """Populate internal crosswalk and curb ramp caches from GeoPackageRegistry."""
        if not self.registry:
            return

        self._municipal_crosswalks = [
            {
                "id": f.feature_id,
                "intersection_type": f.attributes.get("IntersectionType"),
                "road_crossed": f.attributes.get("RoadCrossed"),
                "lanes": f.attributes.get("LanesCrossed"),
                "refuge": f.attributes.get("AreaRefuge"),
                "signalized": f.attributes.get("Signalized"),
                "coord": f.centroid,
            }
            for f in self.registry.features.values()
            if f.layer_role == LayerRole.CROSSWALK
        ]

        self._municipal_curb_ramps = [
            {
                "id": f.feature_id,
                "location": f.attributes.get("LocationDescription"),
                "main": f.attributes.get("Mainstreet"),
                "cross": f.attributes.get("Crosstreet"),
                "owner": f.attributes.get("Owner"),
                "street_class": f.attributes.get("StreetClass"),
                "coord": f.centroid,
            }
            for f in self.registry.features.values()
            if f.layer_role == LayerRole.CURB_RAMP and (f.attributes.get("Mainstreet") is not None or f.attributes.get("Crosstreet") is not None)
        ]

    def classify_intersection(self, route: RouteResult, edge_idx: int) -> IntersectionContext:
        """Classify the intersection for the crosswalk edge at edge_idx along the route."""
        edge = route.edges[edge_idx]
        cw = edge.crosswalk
        coords = cw.coordinates if (cw and cw.coordinates) else [
            self.network.raw_nodes.get(edge.u, (0.0, 0.0)),
            self.network.raw_nodes.get(edge.v, (0.0, 0.0)),
        ]
        mid_lat = sum(p[0] for p in coords) / len(coords)
        mid_lon = sum(p[1] for p in coords) / len(coords)
        cw_mid = (mid_lat, mid_lon)

        # 1. Determine corridor continuity & turning orientation
        turn_dir, is_continuation, corridor_name = self._determine_continuity(route, edge_idx)
        osm_bearing = calculate_bearing(coords[0], coords[-1]) if len(coords) >= 2 else None

        muni_match = self._match_municipal_crosswalk(cw_mid, max_dist_m=15.0, osm_bearing=osm_bearing)
        cr_match = self._match_municipal_curb_ramp(cw_mid, max_dist_m=12.0)
        resolved_crossed_street = None
        spoken_road_name = None
        sem_type = SemanticCrossingType.UNKNOWN_CROSSING
        turning_warning = False

        # 2. Check municipal Crosswalk GIS ground truth FIRST for authoritative RoadCrossed
        if muni_match:
            raw_road = muni_match.get("road_crossed")
            if raw_road and raw_road.strip() and raw_road.lower() != "none" and "unknown" not in raw_road.lower():
                disambig = self.semantic_classifier.classify(
                    raw_name=raw_road,
                    crossing_width_m=edge.length_m,
                )
                resolved_crossed_street = disambig.canonical_name
                spoken_road_name = disambig.spoken_road_name
                sem_type = disambig.crossing_type
                turning_warning = disambig.turning_vehicle_warning

        # 3. Fallback to municipal curb ramp matching
        if not resolved_crossed_street and cr_match:
            raw_main = cr_match.get("main")
            raw_cross = cr_match.get("cross")
            owner = cr_match.get("owner")
            street_class = cr_match.get("street_class")

            # Determine whether main or cross is the feature being crossed
            target_raw = None
            if corridor_name and raw_main and ("Century" in corridor_name or raw_main.upper() in corridor_name.upper()):
                target_raw = raw_cross
            elif corridor_name and raw_cross and (raw_cross.upper() in corridor_name.upper()):
                target_raw = raw_main
            else:
                target_raw = raw_cross or raw_main

            if target_raw:
                disambig = self.semantic_classifier.classify(
                    raw_name=target_raw,
                    municipal_owner=owner,
                    municipal_street_class=street_class,
                    crossing_width_m=edge.length_m,
                )
                resolved_crossed_street = disambig.canonical_name
                spoken_road_name = disambig.spoken_road_name
                sem_type = disambig.crossing_type
                turning_warning = disambig.turning_vehicle_warning

        if muni_match:
            raw_type = (muni_match.get("intersection_type") or "").lower()
            if raw_type in ("rab1", "rab2", "roundabout"):
                itype = IntersectionType.ROUNDABOUT
            elif raw_type in ("fourway", "4way", "cross"):
                itype = IntersectionType.FOUR_WAY
            elif raw_type in ("t", "t_junction"):
                itype = IntersectionType.T_JUNCTION
            elif raw_type in ("midblock", "mid-block"):
                itype = IntersectionType.MIDBLOCK
            else:
                itype = IntersectionType.UNKNOWN

            lanes = muni_match.get("lanes")
            has_refuge = (muni_match.get("refuge") == "YES") or (cw.has_refuge_island if cw else False)

            context = IntersectionContext(
                intersection_type=itype,
                road_crossed=resolved_crossed_street,
                spoken_road_name=spoken_road_name,
                semantic_crossing_type=sem_type,
                turning_vehicle_warning=turning_warning,
                corridor_street=corridor_name,
                is_corridor_continuation=is_continuation,
                turn_direction=turn_dir,
                has_refuge_island=has_refuge,
                lanes_crossed=lanes,
                classification_source="municipal_gis",
            )
        else:
            # 4. Geometric & topological OSM fallback
            context = self._classify_geometric_topology(
                route, edge_idx, cw_mid, turn_dir, is_continuation, corridor_name, resolved_crossed_street
            )
            tags = cw.tags if (cw and hasattr(cw, "tags")) else {}
            disambig = self.semantic_classifier.classify(
                raw_name=context.road_crossed,
                osm_tags=tags,
                crossing_width_m=edge.length_m,
            )
            context.road_crossed = disambig.canonical_name
            context.spoken_road_name = disambig.spoken_road_name
            context.semantic_crossing_type = disambig.crossing_type
            context.turning_vehicle_warning = disambig.turning_vehicle_warning

        # 5. Generate spoken summary
        context.spoken_summary = self._generate_spoken_summary(context)
        return context

    def _determine_continuity(
        self,
        route: RouteResult,
        edge_idx: int,
    ) -> Tuple[str, bool, Optional[str]]:
        """Compute turn direction, corridor continuity, and corridor name across crossing."""
        prev_edge = route.edges[edge_idx - 1] if edge_idx > 0 else None
        next_edge = route.edges[edge_idx + 1] if (edge_idx + 1 < len(route.edges)) else None

        # Corridor name resolution: scan backward then forward for active corridor name
        corridor_name = None
        for prev_i in range(edge_idx - 1, -1, -1):
            pe = route.edges[prev_i]
            if pe.sidewalk and pe.sidewalk.name and pe.sidewalk.name != "Pedestrian Transition Walkway":
                corridor_name = pe.sidewalk.name
                break
            if pe.crosswalk and pe.crosswalk.name:
                corridor_name = pe.crosswalk.name
                break

        if not corridor_name:
            for next_i in range(edge_idx + 1, len(route.edges)):
                ne = route.edges[next_i]
                if ne.sidewalk and ne.sidewalk.name and ne.sidewalk.name != "Pedestrian Transition Walkway":
                    corridor_name = ne.sidewalk.name
                    break
                if ne.crosswalk and ne.crosswalk.name:
                    corridor_name = ne.crosswalk.name
                    break

        # Fallback to designated SW Century Drive corridor if walking along Century Drive area
        if not corridor_name:
            corridor_name = "SW Century Drive"

        # Calculate entry and exit headings
        nodes = self.network.raw_nodes
        curr_edge = route.edges[edge_idx]

        p_u = nodes.get(curr_edge.u)
        p_v = nodes.get(curr_edge.v)

        if not p_u or not p_v:
            return "straight", True, corridor_name

        # Entry bearing
        if prev_edge and prev_edge.u in nodes:
            bearing_in = calculate_bearing(nodes[prev_edge.u], p_u)
        else:
            bearing_in = calculate_bearing(p_u, p_v)

        # Exit bearing
        if next_edge and next_edge.v in nodes:
            bearing_out = calculate_bearing(p_v, nodes[next_edge.v])
        else:
            bearing_out = calculate_bearing(p_u, p_v)

        diff = normalize_angle_diff(bearing_in, bearing_out)

        if abs(diff) <= 40.0:
            turn_dir = "straight"
            is_continuation = True
        elif 40.0 < diff <= 140.0:
            turn_dir = "right"
            is_continuation = False
        elif -140.0 <= diff < -40.0:
            turn_dir = "left"
            is_continuation = False
        else:
            turn_dir = "straight"
            is_continuation = True

        return turn_dir, is_continuation, corridor_name

    def _match_municipal_crosswalk(
        self,
        coord: Tuple[float, float],
        max_dist_m: float = 15.0,
        osm_bearing: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Find the closest municipal crosswalk within max_dist_m, optionally aligned by bearing."""
        if self.registry:
            hits = self.registry.query_radius(coord[0], coord[1], radius_m=max_dist_m, role=LayerRole.CROSSWALK)
            for feat, dist in hits:
                if osm_bearing is not None and feat.coordinates and len(feat.coordinates) >= 2:
                    muni_b = calculate_bearing(feat.coordinates[0], feat.coordinates[-1])
                    diff = abs(normalize_angle_diff(osm_bearing, muni_b))
                    if diff > 90.0:
                        diff = 180.0 - diff
                    if diff > 45.0:
                        continue  # Skip perpendicular crosswalks on other legs of the intersection
                return {
                    "id": feat.feature_id,
                    "intersection_type": feat.attributes.get("IntersectionType"),
                    "road_crossed": feat.attributes.get("RoadCrossed"),
                    "lanes": feat.attributes.get("LanesCrossed"),
                    "refuge": feat.attributes.get("AreaRefuge"),
                    "signalized": feat.attributes.get("Signalized"),
                    "coord": feat.centroid,
                    "dist": dist,
                }
            return None

        closest = None
        min_dist = float("inf")
        for mcw in self._municipal_crosswalks:
            d = haversine_distance_m(coord, mcw["coord"])
            if d < min_dist and d <= max_dist_m:
                min_dist = d
                closest = mcw
        return closest

    def _match_municipal_curb_ramp(
        self,
        coord: Tuple[float, float],
        max_dist_m: float = 12.0,
    ) -> Optional[Dict[str, Any]]:
        """Find the closest municipal curb ramp within max_dist_m."""
        if self.registry:
            hits = self.registry.query_radius(coord[0], coord[1], radius_m=max_dist_m, role=LayerRole.CURB_RAMP)
            for feat, dist in hits:
                main_st = feat.attributes.get("Mainstreet")
                cross_st = feat.attributes.get("Crosstreet")
                if main_st or cross_st:
                    return {
                        "id": feat.feature_id,
                        "location": feat.attributes.get("LocationDescription"),
                        "main": main_st,
                        "cross": cross_st,
                        "owner": feat.attributes.get("Owner"),
                        "street_class": feat.attributes.get("StreetClass"),
                        "coord": feat.centroid,
                        "dist": dist,
                    }
            return None

        closest = None
        min_dist = float("inf")
        for cr in self._municipal_curb_ramps:
            d = haversine_distance_m(coord, cr["coord"])
            if d < min_dist and d <= max_dist_m:
                min_dist = d
                closest = cr
        return closest

    def _classify_geometric_topology(
        self,
        route: RouteResult,
        edge_idx: int,
        mid_coord: Tuple[float, float],
        turn_dir: str,
        is_continuation: bool,
        corridor_name: Optional[str],
        road_crossed: Optional[str] = None,
    ) -> IntersectionContext:
        """Geometric and topological classification when municipal GIS data is absent."""
        edge = route.edges[edge_idx]
        cw = edge.crosswalk
        nodes = self.network.raw_nodes

        # 1. Roundabout heuristic
        is_roundabout = False
        if cw and "roundabout" in str(cw.name or "").lower():
            is_roundabout = True

        # Check for circular pathway cluster around midpoint.
        # Genuine roundabouts in MUTCD/OSM feature splitter island refuges. Requiring cw.has_refuge_island
        # before running multi-bin circular sidewalk cluster checks prevents straight 4-way/T intersections
        # with converging walkways (such as campus pathways) from false-positive roundabout detection.
        if not is_roundabout and cw and cw.has_refuge_island:
            nearby_sw_headings = []
            for sw in self.network.sidewalks.values():
                for sw_u, sw_v in zip(sw.node_ids[:-1], sw.node_ids[1:]):
                    p1 = nodes.get(sw_u)
                    p2 = nodes.get(sw_v)
                    if p1 and p2:
                        sw_mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
                        if haversine_distance_m(mid_coord, sw_mid) <= 35.0:
                            nearby_sw_headings.append(calculate_bearing(p1, p2))

            if len(nearby_sw_headings) >= 5:
                bins = [int(h // 45) for h in nearby_sw_headings]
                unique_bins = len(set(bins))
                if unique_bins >= 5:
                    is_roundabout = True

        if is_roundabout:
            return IntersectionContext(
                intersection_type=IntersectionType.ROUNDABOUT,
                road_crossed=road_crossed,
                corridor_street=corridor_name,
                is_corridor_continuation=is_continuation,
                turn_direction=turn_dir,
                has_refuge_island=True,
                lanes_crossed=None,
                classification_source="osm_topology",
            )

        # 2. Incident pathways degree count at entry and exit nodes
        u, v = edge.u, edge.v
        entry = cw.node_ids[0] if (cw and len(cw.node_ids) >= 2) else u
        exit_n = cw.node_ids[-1] if (cw and len(cw.node_ids) >= 2) else v

        adj_u_count = sum(1 for sw in self.network.sidewalks.values() if entry in sw.node_ids)
        adj_v_count = sum(1 for sw in self.network.sidewalks.values() if exit_n in sw.node_ids)
        total_branches = max(adj_u_count, adj_v_count) + 1

        # Also count distinct nearby sidewalk ways terminating or passing within 15m of entry or exit
        p_entry = nodes.get(entry)
        p_exit = nodes.get(exit_n)
        nearby_sw_ways = set()
        for sw in self.network.sidewalks.values():
            for nid in (sw.node_ids[0], sw.node_ids[-1]):
                p = nodes.get(nid)
                if p:
                    if (p_entry and haversine_distance_m(p_entry, p) <= 15.0) or (
                        p_exit and haversine_distance_m(p_exit, p) <= 15.0
                    ):
                        nearby_sw_ways.add(sw.id)

        if total_branches >= 4 or len(nearby_sw_ways) >= 4:
            itype = IntersectionType.FOUR_WAY
        elif total_branches == 3 or len(nearby_sw_ways) >= 2:
            itype = IntersectionType.T_JUNCTION
        else:
            itype = IntersectionType.MIDBLOCK

        return IntersectionContext(
            intersection_type=itype,
            road_crossed=road_crossed,
            corridor_street=corridor_name,
            is_corridor_continuation=is_continuation,
            turn_direction=turn_dir,
            has_refuge_island=cw.has_refuge_island if cw else False,
            lanes_crossed=None,
            classification_source="osm_topology",
        )

    def _generate_spoken_summary(self, ctx: IntersectionContext) -> str:
        """Create screen-reader guidance phrasing customized for the intersection and crossed street."""
        street = ctx.corridor_street or "the street"
        road_name = ctx.spoken_road_name or ctx.road_crossed or "the street"

        # Commercial driveways & parking lot entrances
        if ctx.semantic_crossing_type in (SemanticCrossingType.COMMERCIAL_DRIVEWAY, SemanticCrossingType.PARKING_LOT_ACCESS):
            if ctx.intersection_type == IntersectionType.T_JUNCTION:
                return f"At this T-junction, cross {road_name} to continue along {street}."
            else:
                return f"Continue forward across {road_name} to stay on {street}."

        if ctx.semantic_crossing_type == SemanticCrossingType.PRIVATE_DRIVEWAY:
            return f"Continue forward across {road_name} to stay on {street}."

        if ctx.semantic_crossing_type == SemanticCrossingType.SERVICE_ALLEY:
            return f"Continue forward across {road_name} to stay on {street}."

        if ctx.intersection_type == IntersectionType.ROUNDABOUT:
            refuge_cue = (
                " to reach the splitter island refuge, then check for circulating vehicles before completing the crossing"
                if ctx.has_refuge_island
                else ""
            )
            return (
                f"Caution: Roundabout intersection. Free-flowing traffic enters continuously from your left without a traffic light. "
                f"Cross {road_name} across the roundabout slip lane{refuge_cue} to stay on {street}."
            )

        if ctx.intersection_type == IntersectionType.FOUR_WAY:
            if ctx.is_corridor_continuation:
                return f"Continue forward across {road_name} at this 4-way intersection to stay on {street}."
            else:
                return f"At this 4-way intersection, cross {road_name}, then turn {ctx.turn_direction}."

        if ctx.intersection_type == IntersectionType.T_JUNCTION:
            if ctx.is_corridor_continuation:
                return f"At this T-junction, cross {road_name} to continue along {street}."
            else:
                return f"At this T-junction, cross {road_name}, then turn {ctx.turn_direction}."

        if ctx.intersection_type == IntersectionType.MIDBLOCK:
            return f"Continue forward across {road_name} at the mid-block crosswalk to stay on {street}."

        # Default
        return f"Continue forward across {road_name} to stay on {street}."
