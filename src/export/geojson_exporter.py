"""Exports PedestrianNetwork and RouteResults into standard GeoJSON."""

import json
from pathlib import Path
from typing import Any, Dict, List
from ..models.pedestrian import PedestrianNetwork
from ..routing.pedestrian_graph import RouteResult


class GeoJSONExporter:
    """Converts pedestrian networks and routes into GeoJSON FeatureCollections."""

    @staticmethod
    def export_network_to_geojson(network: PedestrianNetwork, output_path: Optional[Path] = None) -> Dict[str, Any]:
        """Convert entire pedestrian network into a GeoJSON FeatureCollection."""
        features: List[Dict[str, Any]] = []

        # 1. Crosswalks (LineString)
        for cw in network.crosswalks.values():
            if len(cw.coordinates) >= 2:
                # GeoJSON coordinates are [lon, lat]
                coords = [[c[1], c[0]] for c in cw.coordinates]
                features.append({
                    "type": "Feature",
                    "id": f"crosswalk_{cw.id}",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords,
                    },
                    "properties": {
                        "feature_type": "crosswalk",
                        "name": cw.name,
                        "crossing_type": cw.crossing_type,
                        "markings": cw.markings,
                        "has_signals": cw.has_signals,
                        "has_audible_signals": cw.has_audible_signals,
                        "has_vibrotactile": cw.has_vibrotactile,
                        "has_tactile_paving": cw.has_tactile_paving,
                        "has_refuge_island": cw.has_refuge_island,
                        "safety_score": cw.safety_score,
                    },
                })

        # 2. Sidewalks (LineString)
        for sw in network.sidewalks.values():
            if len(sw.coordinates) >= 2:
                coords = [[c[1], c[0]] for c in sw.coordinates]
                features.append({
                    "type": "Feature",
                    "id": f"sidewalk_{sw.id}",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords,
                    },
                    "properties": {
                        "feature_type": "sidewalk",
                        "name": sw.name,
                        "width_m": sw.width_m,
                        "surface": sw.surface,
                        "smoothness": sw.smoothness,
                        "has_tactile_paving": sw.has_tactile_paving,
                        "incline_pct": sw.incline_pct,
                    },
                })

        # 3. Kerbs (Point)
        for kb in network.kerbs.values():
            features.append({
                "type": "Feature",
                "id": f"kerb_{kb.id}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [kb.coordinate[1], kb.coordinate[0]],
                },
                "properties": {
                    "feature_type": "kerb",
                    "kerb_type": kb.kerb_type,
                    "has_tactile_paving": kb.has_tactile_paving,
                    "is_step_free": kb.is_step_free,
                    "height_cm": kb.height_cm,
                },
            })

        fc = {
            "type": "FeatureCollection",
            "features": features,
        }

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(fc, f, indent=2)

        return fc

    @staticmethod
    def export_route_to_geojson(
        route: RouteResult,
        network: PedestrianNetwork,
        output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Convert a calculated route into a GeoJSON FeatureCollection."""
        nodes = network.raw_nodes
        coords = [[nodes[nid][1], nodes[nid][0]] for nid in route.node_path if nid in nodes]

        route_feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": {
                "total_distance_m": route.total_distance_m,
                "effective_cost": route.total_effective_cost,
                "accessibility_rating": route.accessibility_rating,
                "num_steps": len(route.edges),
            },
        }

        fc = {
            "type": "FeatureCollection",
            "features": [route_feature],
        }

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(fc, f, indent=2)

        return fc
