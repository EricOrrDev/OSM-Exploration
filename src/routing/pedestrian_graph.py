"""Pedestrian graph construction and accessibility-weighted pathfinding."""

from dataclasses import dataclass, field
import heapq
import math
from typing import Any, Dict, List, Optional, Tuple
from ..models.pedestrian import CrosswalkFeature, KerbFeature, PedestrianNetwork, SidewalkFeature
from .safety_weights import DEFAULT_SAFETY_WEIGHTS, SafetyWeightsConfig


def haversine_distance_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Calculate great-circle distance between two (lat, lon) coordinates in meters."""
    lat1, lon1 = p1
    lat2, lon2 = p2
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


@dataclass
class PedestrianEdge:
    u: int
    v: int
    length_m: float
    effective_weight: float
    feature_type: str  # "crosswalk" or "sidewalk"
    crosswalk: Optional[CrosswalkFeature] = None
    sidewalk: Optional[SidewalkFeature] = None


@dataclass
class RouteResult:
    node_path: List[int]
    edges: List[PedestrianEdge]
    total_distance_m: float
    total_effective_cost: float
    accessibility_rating: str  # "High Safety", "Moderate Safety", "Caution Required"


class PedestrianGraph:
    """Graph structure with accessibility-cost weighting tailored for blind pedestrians."""

    def __init__(
        self,
        network: PedestrianNetwork,
        registry: Optional[Any] = None,
        weights: Optional[SafetyWeightsConfig] = None,
    ):
        self.network = network
        self.weights = weights or DEFAULT_SAFETY_WEIGHTS
        if registry is None:
            try:
                from ..config import MAP_DATA_DIR
                from ..spatial.gpkg_registry import GeoPackageRegistry
                if MAP_DATA_DIR.exists():
                    registry = GeoPackageRegistry(MAP_DATA_DIR)
            except Exception:
                registry = None
        self.registry = registry
        self.adj: Dict[int, List[PedestrianEdge]] = {}
        self._build_graph()

    def _add_edge(
        self,
        u: int,
        v: int,
        length_m: float,
        weight: float,
        feature_type: str,
        cw: Optional[CrosswalkFeature] = None,
        sw: Optional[SidewalkFeature] = None,
    ) -> None:
        edge = PedestrianEdge(
            u=u,
            v=v,
            length_m=length_m,
            effective_weight=weight,
            feature_type=feature_type,
            crosswalk=cw,
            sidewalk=sw,
        )
        self.adj.setdefault(u, []).append(edge)

    def _build_graph(self) -> None:
        nodes = self.network.raw_nodes
        kerbs = self.network.kerbs

        # 1. Sidewalk edges
        for sw in self.network.sidewalks.values():
            nids = sw.node_ids
            for i in range(len(nids) - 1):
                u, v = nids[i], nids[i + 1]
                if u in nodes and v in nodes:
                    dist = max(0.5, haversine_distance_m(nodes[u], nodes[v]))
                    multiplier = self.weights.compute_sidewalk_multiplier(
                        has_tactile_paving=sw.has_tactile_paving,
                        surface=sw.surface,
                    )
                    weight = dist * multiplier
                    # Bidirectional
                    self._add_edge(u, v, dist, weight, "sidewalk", sw=sw)
                    self._add_edge(v, u, dist, weight, "sidewalk", sw=sw)

        # 2. Crosswalk edges
        for cw in self.network.crosswalks.values():
            nids = cw.node_ids
            centroid = cw.coordinates[0] if cw.coordinates else (0.0, 0.0)
            is_rab = (cw.intersection_type == "roundabout" or "roundabout" in str(cw.name or "").lower())
            has_refuge = cw.has_refuge_island
            is_marked = cw.crossing_type in ("marked", "zebra") or cw.markings in ("zebra", "lines", "ladder", "surface")
            is_target_preferred = False

            if self.registry:
                from ..spatial.gpkg_registry import LayerRole
                match = self.registry.find_nearest(centroid[0], centroid[1], role=LayerRole.CROSSWALK, max_dist_m=20.0)
                if match:
                    feat, _ = match
                    itype = str(feat.attributes.get("IntersectionType") or "").lower()
                    gid = str(feat.attributes.get("GlobalID") or "").upper()
                    if itype in ("rab1", "rab2", "roundabout"):
                        is_rab = True
                        cw.intersection_type = "roundabout"
                    if str(feat.attributes.get("AreaRefuge") or "").upper() == "YES":
                        has_refuge = True
                        cw.has_refuge_island = True
                    if str(feat.attributes.get("CrosswalkType") or "").lower() == "marked":
                        is_marked = True
                    if "{ECFA0F9D-248C-4AC1-92EF-CC29529F00C8}" in gid:
                        is_target_preferred = True

            for i in range(len(nids) - 1):
                u, v = nids[i], nids[i + 1]
                if u in nodes and v in nodes:
                    dist = max(1.0, haversine_distance_m(nodes[u], nodes[v]))
                    kerb_list = [kerbs[nid] for nid in (u, v) if nid in kerbs]
                    multiplier = self.weights.compute_crosswalk_multiplier(
                        has_audible_signals=cw.has_audible_signals,
                        has_signals=cw.has_signals,
                        is_marked=is_marked,
                        crossing_type=cw.crossing_type,
                        has_refuge_island=has_refuge,
                        is_target_preferred=is_target_preferred,
                        is_roundabout=is_rab,
                        has_tactile_paving=cw.has_tactile_paving,
                        kerb_features=kerb_list,
                    )
                    weight = dist * multiplier
                    # Bidirectional
                    self._add_edge(u, v, dist, weight, "crosswalk", cw=cw)
                    self._add_edge(v, u, dist, weight, "crosswalk", cw=cw)

        # 3. Micro-gap bridging for adjacent components (e.g. campus driveways, parking transitions)
        self.bridge_component_gaps(max_gap_m=35.0)

    def find_connected_components(self) -> List[List[int]]:
        """Identify all isolated connected subgraphs."""
        visited = set()
        components = []
        for node in self.adj:
            if node not in visited:
                comp = []
                queue = [node]
                visited.add(node)
                for u in queue:
                    comp.append(u)
                    for edge in self.adj.get(u, []):
                        if edge.v not in visited:
                            visited.add(edge.v)
                            queue.append(edge.v)
                components.append(comp)
        components.sort(key=len, reverse=True)
        return components

    def bridge_component_gaps(self, max_gap_m: float = 35.0) -> int:
        """Connect disconnected components across short transition gaps (driveways/crossings)."""
        nodes = self.network.raw_nodes
        bridges_added = 0

        components = self.find_connected_components()
        if len(components) <= 1:
            return 0

        # Primary component is the largest connected grid
        primary_nodes = set(components[0])

        for comp in components[1:]:
            best_dist = float("inf")
            best_pair = None

            for u in comp:
                if u not in nodes:
                    continue
                p_u = nodes[u]
                for v in primary_nodes:
                    if v not in nodes:
                        continue
                    # Fast bounding box check before full Haversine
                    p_v = nodes[v]
                    if abs(p_u[0] - p_v[0]) > 0.001 or abs(p_u[1] - p_v[1]) > 0.001:
                        continue
                    d = haversine_distance_m(p_u, p_v)
                    if d < best_dist and d <= max_gap_m:
                        best_dist = d
                        best_pair = (u, v)

            if best_pair and best_dist <= max_gap_m:
                u, v = best_pair
                bridges_added += 1
                bridge_sw = SidewalkFeature(
                    id=999000000 + bridges_added,
                    name="Pedestrian Transition Walkway",
                    node_ids=[u, v],
                    coordinates=[nodes[u], nodes[v]],
                    surface="paved",
                )
                weight = best_dist * 1.2
                self._add_edge(u, v, best_dist, weight, "sidewalk", sw=bridge_sw)
                self._add_edge(v, u, best_dist, weight, "sidewalk", sw=bridge_sw)
                # Absorb connected component into primary
                primary_nodes.update(comp)

        return bridges_added

    def find_nearest_node(self, target: Tuple[float, float]) -> Optional[int]:
        """Find the closest graph node to given coordinate."""
        closest_id = None
        min_dist = float("inf")
        for nid, coord in self.network.raw_nodes.items():
            if nid in self.adj:  # Must have connected edges
                d = haversine_distance_m(target, coord)
                if d < min_dist:
                    min_dist = d
                    closest_id = nid
        return closest_id

    def route(self, start_node: int, end_node: int) -> Optional[RouteResult]:
        """Compute the most accessible path for a blind pedestrian using Dijkstra's algorithm."""
        if start_node not in self.adj or end_node not in self.network.raw_nodes:
            return None

        distances: Dict[int, float] = {start_node: 0.0}
        previous_edges: Dict[int, PedestrianEdge] = {}
        heap: List[Tuple[float, int]] = [(0.0, start_node)]
        visited = set()

        while heap:
            cur_dist, u = heapq.heappop(heap)
            if u in visited:
                continue
            visited.add(u)

            if u == end_node:
                break

            for edge in self.adj.get(u, []):
                v = edge.v
                if v in visited:
                    continue
                new_cost = cur_dist + edge.effective_weight
                if new_cost < distances.get(v, float("inf")):
                    distances[v] = new_cost
                    previous_edges[v] = edge
                    heapq.heappush(heap, (new_cost, v))

        if end_node not in previous_edges and start_node != end_node:
            return None

        # Reconstruct path
        path_edges: List[PedestrianEdge] = []
        curr = end_node
        while curr != start_node:
            edge = previous_edges[curr]
            path_edges.append(edge)
            curr = edge.u
        path_edges.reverse()

        node_path = [start_node] + [e.v for e in path_edges]
        total_dist = sum(e.length_m for e in path_edges)
        total_effective = sum(e.effective_weight for e in path_edges)

        # Rate accessibility using centralized safety weights
        rating = self.weights.compute_accessibility_rating(total_effective, total_dist)

        return RouteResult(
            node_path=node_path,
            edges=path_edges,
            total_distance_m=round(total_dist, 1),
            total_effective_cost=round(total_effective, 1),
            accessibility_rating=rating,
        )
