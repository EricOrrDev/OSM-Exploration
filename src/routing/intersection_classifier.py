"""Intersection topology classification and corridor continuity engine."""

from dataclasses import dataclass
from enum import Enum
import math
from pathlib import Path
import sqlite3
import struct
from typing import Any, Dict, List, Optional, Tuple

from ..config import MAP_DATA_DIR
from ..models.pedestrian import CrosswalkFeature, PedestrianNetwork
from .pedestrian_graph import RouteResult, haversine_distance_m


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
    corridor_street: Optional[str] = None
    is_corridor_continuation: bool = True
    turn_direction: str = "straight"  # "straight", "left", "right"
    has_refuge_island: bool = False
    lanes_crossed: Optional[int] = None
    classification_source: str = "osm_topology"  # "municipal_gis" or "osm_topology"
    spoken_summary: str = ""


# Common City of Bend engineering road prefix mappings
BEND_ROAD_NAMES: Dict[str, str] = {
    "CENTUR": "SW Century Drive",
    "SIMPSO": "SW Simpson Avenue",
    "CHANDL": "SW Chandler Avenue",
    "COLORA": "SW Colorado Avenue",
    "DAVENO": "NW Davenport Avenue",
    "COLLEG": "SW College Way",
    "MTWASH": "NW Mount Washington Drive",
    "REEDMK": "SE Reed Market Road",
    "SHIELD": "SW Shevlin Hixon Drive",
    "EMPIRE": "NW Empire Avenue",
    "PORTLA": "NW Portland Avenue",
    "NEWPOR": "NW Newport Avenue",
    "GREENW": "NE Greenwood Avenue",
    "BEARCR": "SE Bear Creek Road",
    "BOND": "NW Bond Street",
    "WALL": "NW Wall Street",
    "GALVES": "NW Galveston Avenue",
    "TAYLOR": "SW Taylor Drive",
    "PRIVATE": "private driveway",
}


def mercator_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    """Convert EPSG:3857 Web Mercator coordinate to EPSG:4326 (lat, lon)."""
    lon = x * 180.0 / 20037508.34
    lat = math.atan(math.sinh(y * math.pi / 20037508.34)) * 180.0 / math.pi
    return lat, lon


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
    """Convert raw municipal GIS street abbreviation into spoken title name."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() == "none" or "unknown" in cleaned.lower():
        return None

    upper = cleaned.upper()

    # Exact known mappings
    special_cases: Dict[str, str] = {
        "CENTURY": "SW Century Drive",
        "TAYLOR": "SW Taylor Drive",
        "SIMPSON": "SW Simpson Avenue",
        "CHANDLER": "SW Chandler Avenue",
        "COLORADO": "SW Colorado Avenue",
        "DAVENPORT": "NW Davenport Avenue",
        "COLLEGE": "SW College Way",
        "MT WASHINGTON": "NW Mount Washington Drive",
        "REED MARKET": "SE Reed Market Road",
        "S SAFEWAY DR": "South Safeway Drive",
        "SAFEWAY DRIVE": "Safeway Drive",
        "SAFEWAY": "Safeway Access Drive",
        "PRIVATE": "private driveway",
        "14TH": "NW 14th Street",
        "14TH NW": "NW 14th Street",
        "FIRE STATION S SIDE": "Fire Station South Driveway",
        "FIRE STATION N SIDE": "Fire Station North Driveway",
    }
    if upper in special_cases:
        return special_cases[upper]

    for prefix, full in BEND_ROAD_NAMES.items():
        if upper == prefix or upper.startswith(prefix):
            return full

    # Common abbreviation word replacements
    words = cleaned.split()
    expanded_words = []
    for w in words:
        w_up = w.upper()
        if w_up == "DR":
            expanded_words.append("Drive")
        elif w_up in ("ST", "STR"):
            expanded_words.append("Street")
        elif w_up in ("AVE", "AV"):
            expanded_words.append("Avenue")
        elif w_up in ("RD",):
            expanded_words.append("Road")
        elif w_up in ("BLVD",):
            expanded_words.append("Boulevard")
        elif w_up in ("LN",):
            expanded_words.append("Lane")
        elif w_up in ("CT",):
            expanded_words.append("Court")
        elif w_up in ("WY", "WAY"):
            expanded_words.append("Way")
        elif w_up == "S":
            expanded_words.append("South")
        elif w_up == "N":
            expanded_words.append("North")
        elif w_up == "E":
            expanded_words.append("East")
        elif w_up == "W":
            expanded_words.append("West")
        elif w_up in ("SW", "NW", "SE", "NE"):
            expanded_words.append(w_up)
        else:
            expanded_words.append(w.capitalize())

    return " ".join(expanded_words)


class IntersectionClassifier:
    """Identifies intersection typology and corridor continuity using municipal GIS & OSM topology."""

    def __init__(
        self,
        network: PedestrianNetwork,
        map_data_dir: Optional[Path] = None,
        enable_municipal: bool = True,
    ):
        self.network = network
        self.map_data_dir = map_data_dir or MAP_DATA_DIR
        self.enable_municipal = enable_municipal
        self._municipal_crosswalks: List[Dict[str, Any]] = []
        self._municipal_curb_ramps: List[Dict[str, Any]] = []

        if self.enable_municipal:
            self._load_municipal_data()

    def _load_municipal_data(self) -> None:
        """Parse municipal Crosswalk and Curb_Ramps GeoPackages to index geometries and cross streets."""
        if not self.map_data_dir.exists():
            return

        # 1. Crosswalks
        cw_files = list(self.map_data_dir.glob("Crosswalks_*.gpkg"))
        if cw_files:
            try:
                conn = sqlite3.connect(str(cw_files[0]))
                c = conn.cursor()
                c.execute(
                    "SELECT OBJECTID, SHAPE, IntersectionType, RoadCrossed, LanesCrossed, AreaRefuge, Signalized "
                    "FROM Crosswalk"
                )
                for row in c.fetchall():
                    obj_id, geom_blob, itype, road, lanes, refuge, sig = row
                    if not geom_blob or len(geom_blob) < 18:
                        continue
                    wkb = geom_blob[8:]
                    byte_order = "<" if wkb[0] == 1 else ">"
                    wkb_type = struct.unpack(f"{byte_order}I", wkb[1:5])[0]
                    if wkb_type == 5:  # MultiLineString
                        num_points = struct.unpack(f"{byte_order}I", wkb[14:18])[0]
                        coords = []
                        offset = 18
                        for _ in range(num_points):
                            px, py = struct.unpack(f"{byte_order}dd", wkb[offset : offset + 16])
                            coords.append(mercator_to_wgs84(px, py))
                            offset += 16
                        if coords:
                            mid_lat = sum(p[0] for p in coords) / len(coords)
                            mid_lon = sum(p[1] for p in coords) / len(coords)
                            self._municipal_crosswalks.append({
                                "id": obj_id,
                                "intersection_type": itype,
                                "road_crossed": road,
                                "lanes": lanes,
                                "refuge": refuge,
                                "signalized": sig,
                                "coord": (mid_lat, mid_lon),
                            })
                conn.close()
            except Exception:
                self._municipal_crosswalks = []

        # 2. Curb Ramps (with Mainstreet and Crosstreet)
        cr_files = list(self.map_data_dir.glob("sCurbRamps_*.gpkg"))
        if cr_files:
            try:
                conn = sqlite3.connect(str(cr_files[0]))
                c = conn.cursor()
                c.execute(
                    "SELECT OBJECTID, SHAPE, LocationDescription, Mainstreet, Crosstreet "
                    "FROM Curb_Ramps WHERE Mainstreet IS NOT NULL"
                )
                for row in c.fetchall():
                    obj_id, geom_blob, loc, main_st, cross_st = row
                    if not geom_blob or len(geom_blob) < 18:
                        continue
                    wkb = geom_blob[8:]
                    byte_order = "<" if wkb[0] == 1 else ">"
                    wkb_type = struct.unpack(f"{byte_order}I", wkb[1:5])[0]
                    if wkb_type == 1:  # Point
                        px, py = struct.unpack(f"{byte_order}dd", wkb[5:21])
                        lat, lon = mercator_to_wgs84(px, py)
                        self._municipal_curb_ramps.append({
                            "id": obj_id,
                            "location": loc,
                            "main": main_st,
                            "cross": cross_st,
                            "coord": (lat, lon),
                        })
                conn.close()
            except Exception:
                self._municipal_curb_ramps = []

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

        # 2. Resolve cross street via municipal curb ramp matching
        cr_match = self._match_municipal_curb_ramp(cw_mid, max_dist_m=12.0)
        resolved_crossed_street = None

        if cr_match:
            main_norm = normalize_street_name(cr_match["main"])
            cross_norm = normalize_street_name(cr_match["cross"])

            # If walking along main street, the street being crossed is cross street
            if corridor_name and main_norm and ("Century" in corridor_name or main_norm in corridor_name):
                resolved_crossed_street = cross_norm
            elif corridor_name and cross_norm and cross_norm in corridor_name:
                resolved_crossed_street = main_norm
            else:
                resolved_crossed_street = cross_norm or main_norm

        # 3. Match municipal Crosswalk GIS ground truth
        muni_match = self._match_municipal_crosswalk(cw_mid, max_dist_m=15.0)

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

            # Fallback to RoadCrossed from Crosswalk table if curb ramp did not supply it
            if not resolved_crossed_street:
                raw_road = muni_match.get("road_crossed")
                resolved_crossed_street = normalize_street_name(raw_road)

            lanes = muni_match.get("lanes")
            has_refuge = (muni_match.get("refuge") == "YES") or (cw.has_refuge_island if cw else False)

            context = IntersectionContext(
                intersection_type=itype,
                road_crossed=resolved_crossed_street,
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
    ) -> Optional[Dict[str, Any]]:
        """Find the closest municipal crosswalk within max_dist_m."""
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
        if cw and (cw.has_refuge_island or "roundabout" in str(cw.name or "").lower()):
            is_roundabout = True

        for nid, tags in self.network.node_tags.items():
            if nid in nodes:
                if haversine_distance_m(mid_coord, nodes[nid]) <= 25.0:
                    if tags.get("junction") == "roundabout" or tags.get("junction") == "circular":
                        is_roundabout = True
                        break

        if is_roundabout:
            return IntersectionContext(
                intersection_type=IntersectionType.ROUNDABOUT,
                road_crossed=road_crossed,
                corridor_street=corridor_name,
                is_corridor_continuation=is_continuation,
                turn_direction=turn_dir,
                has_refuge_island=cw.has_refuge_island if cw else False,
                lanes_crossed=2,
                classification_source="osm_topology",
            )

        # 2. Incident pathways degree count at entry and exit nodes
        u, v = edge.u, edge.v
        adj_u_count = sum(1 for sw in self.network.sidewalks.values() if u in sw.node_ids)
        adj_v_count = sum(1 for sw in self.network.sidewalks.values() if v in sw.node_ids)
        total_branches = max(adj_u_count, adj_v_count) + 1

        if total_branches >= 4:
            itype = IntersectionType.FOUR_WAY
        elif total_branches == 3:
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
        road_name = ctx.road_crossed or "the street"

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
