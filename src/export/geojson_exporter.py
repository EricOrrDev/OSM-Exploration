"""Exports PedestrianNetwork and RouteResults into GeoJSON, GeoPackage, and interactive HTML maps."""

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import struct
from typing import Any, Dict, List, Optional, Tuple

from ..models.pedestrian import PedestrianNetwork
from ..routing.pedestrian_graph import RouteResult


def _create_gpb_point(lon: float, lat: float, srs_id: int = 4326) -> bytes:
    """Create an OGC GeoPackage Binary geometry BLOB for a Point."""
    header = b"GP\x00\x01" + struct.pack("<i", srs_id)
    wkb = b"\x01\x01\x00\x00\x00" + struct.pack("<dd", lon, lat)
    return header + wkb


def _create_gpb_linestring(coords: List[Tuple[float, float]], srs_id: int = 4326) -> bytes:
    """Create an OGC GeoPackage Binary geometry BLOB for a LineString (coords are [lat, lon])."""
    header = b"GP\x00\x01" + struct.pack("<i", srs_id)
    num_pts = len(coords)
    wkb = b"\x01\x02\x00\x00\x00" + struct.pack("<I", num_pts)
    # GeoPackage WKB stores (x, y) = (lon, lat)
    pts_bytes = b"".join(struct.pack("<dd", pt[1], pt[0]) for pt in coords)
    return header + wkb + pts_bytes


class GeoJSONExporter:
    """Converts pedestrian networks and routes into GeoJSON, GeoPackage, and interactive web maps."""

    @staticmethod
    def export_network_to_geojson(network: PedestrianNetwork, output_path: Optional[Path] = None) -> Dict[str, Any]:
        """Convert entire pedestrian network into a GeoJSON FeatureCollection."""
        features: List[Dict[str, Any]] = []

        # 1. Crosswalks (LineString)
        for cw in network.crosswalks.values():
            if len(cw.coordinates) >= 2:
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
        instructions: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Convert a calculated route into a detailed GeoJSON FeatureCollection including:
        - Route corridor LineString
        - Segment-by-segment LineStrings with spoken instructions and physical attributes
        - Start, destination, and curb-ramp decision Points with tactile warnings.
        """
        nodes = network.raw_nodes
        features: List[Dict[str, Any]] = []

        # 1. Overall route corridor
        route_coords = [[nodes[nid][1], nodes[nid][0]] for nid in route.node_path if nid in nodes]
        features.append({
            "type": "Feature",
            "id": "route_corridor",
            "geometry": {
                "type": "LineString",
                "coordinates": route_coords,
            },
            "properties": {
                "feature_type": "route_corridor",
                "name": "Full Pedestrian Route Path",
                "total_distance_m": route.total_distance_m,
                "effective_cost": route.total_effective_cost,
                "accessibility_rating": route.accessibility_rating,
                "num_edges": len(route.edges),
                "num_instructions": len(instructions) if instructions else 0,
                "stroke": "#2563EB",
                "stroke-width": 6,
                "stroke-opacity": 0.85,
            },
        })

        # Match instructions to edge indices
        instruction_by_action: Dict[str, List[Dict[str, Any]]] = {}
        if instructions:
            for inst in instructions:
                act = inst.get("action", "")
                if act not in instruction_by_action:
                    instruction_by_action[act] = []
                instruction_by_action[act].append(inst)

        # 2. Individual segment edges with styling and guidance
        cross_idx = 0
        sw_idx = 0
        for i, edge in enumerate(route.edges):
            u_pt = nodes.get(edge.u)
            v_pt = nodes.get(edge.v)
            if not u_pt or not v_pt:
                continue

            seg_coords = [[u_pt[1], u_pt[0]], [v_pt[1], v_pt[0]]]
            if edge.feature_type == "crosswalk":
                cw = edge.crosswalk
                if cw and len(cw.coordinates) >= 2:
                    seg_coords = [[c[1], c[0]] for c in cw.coordinates]

                # Match CROSS_STREET instruction
                inst = None
                cross_list = instruction_by_action.get("CROSS_STREET", [])
                if cross_idx < len(cross_list):
                    inst = cross_list[cross_idx]
                    next_edge = route.edges[i + 1] if (i + 1 < len(route.edges)) else None
                    if not next_edge or next_edge.feature_type != "crosswalk":
                        cross_idx += 1

                road_name = (inst.get("spoken_road_name") or inst.get("road_crossed")) if inst else (cw.name if cw else "crosswalk")
                sem_type = inst.get("semantic_crossing_type") if inst else None
                itype = inst.get("intersection_type") if inst else None

                # Style crossing by typology
                if sem_type == "commercial_driveway":
                    stroke_color = "#DC2626"  # Red/Amber for commercial driveways
                elif itype == "roundabout":
                    stroke_color = "#7C3AED"  # Purple for roundabouts
                else:
                    stroke_color = "#F59E0B"  # Amber for standard street crossings

                features.append({
                    "type": "Feature",
                    "id": f"segment_{i}_crosswalk",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": seg_coords,
                    },
                    "properties": {
                        "feature_type": "route_segment",
                        "segment_type": "crosswalk",
                        "edge_index": i,
                        "road_crossed": road_name,
                        "intersection_type": itype,
                        "semantic_crossing_type": sem_type,
                        "length_m": edge.length_m,
                        "markings": cw.markings if cw else None,
                        "has_signals": cw.has_signals if cw else False,
                        "has_aps": cw.has_audible_signals if cw else False,
                        "has_refuge": cw.has_refuge_island if cw else False,
                        "spoken_instruction": inst.get("spoken_instruction") if inst else None,
                        "stroke": stroke_color,
                        "stroke-width": 5,
                        "stroke-dasharray": "6, 8",
                    },
                })
            else:
                sw = edge.sidewalk
                inst = None
                sw_list = instruction_by_action.get("WALK_SIDEWALK", [])
                if sw_idx < len(sw_list):
                    inst = sw_list[sw_idx]
                    next_edge = route.edges[i + 1] if (i + 1 < len(route.edges)) else None
                    if not next_edge or next_edge.feature_type != "sidewalk":
                        sw_idx += 1

                is_br = getattr(sw, "is_bridge", False) if sw else False
                stroke_color = "#0D9488" if is_br else "#10B981"
                features.append({
                    "type": "Feature",
                    "id": f"segment_{i}_sidewalk",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": seg_coords,
                    },
                    "properties": {
                        "feature_type": "route_segment",
                        "segment_type": "sidewalk",
                        "edge_index": i,
                        "street_name": sw.name if sw else ("bridge walkway" if is_br else "sidewalk"),
                        "length_m": edge.length_m,
                        "surface": sw.surface if sw else "concrete",
                        "has_tactile_paving": sw.has_tactile_paving if sw else False,
                        "spoken_instruction": inst.get("spoken_instruction") if inst else None,
                        "is_bridge": is_br,
                        "stroke": stroke_color,
                        "stroke-width": 5 if is_br else 4,
                    },
                })

        # 3. Decision Points (Start, Destination, Kerbs, Push Buttons)
        if route.node_path:
            start_nid = route.node_path[0]
            end_nid = route.node_path[-1]
            if start_nid in nodes:
                s_pt = nodes[start_nid]
                features.append({
                    "type": "Feature",
                    "id": "waypoint_start",
                    "geometry": {"type": "Point", "coordinates": [s_pt[1], s_pt[0]]},
                    "properties": {
                        "feature_type": "waypoint",
                        "waypoint_type": "start",
                        "name": "Route Start / Origin",
                        "marker-color": "#16A34A",
                        "marker-symbol": "star",
                    },
                })
            if end_nid in nodes:
                e_pt = nodes[end_nid]
                features.append({
                    "type": "Feature",
                    "id": "waypoint_end",
                    "geometry": {"type": "Point", "coordinates": [e_pt[1], e_pt[0]]},
                    "properties": {
                        "feature_type": "waypoint",
                        "waypoint_type": "destination",
                        "name": "Route Destination",
                        "marker-color": "#DC2626",
                        "marker-symbol": "flag",
                    },
                })

        # Curb transitions along route
        kerbs = network.kerbs
        for nid in set(route.node_path):
            if nid in kerbs and nid in nodes:
                kb = kerbs[nid]
                pt = nodes[nid]
                features.append({
                    "type": "Feature",
                    "id": f"curb_{nid}",
                    "geometry": {"type": "Point", "coordinates": [pt[1], pt[0]]},
                    "properties": {
                        "feature_type": "curb_ramp",
                        "kerb_type": kb.kerb_type,
                        "is_step_free": kb.is_step_free,
                        "has_tactile_paving": kb.has_tactile_paving,
                        "height_cm": kb.height_cm,
                        "marker-color": "#8B5CF6" if kb.has_tactile_paving else "#6B7280",
                    },
                })

        fc = {
            "type": "FeatureCollection",
            "properties": {
                "title": "Pedestrian Accessible Route",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_distance_m": route.total_distance_m,
                "accessibility_rating": route.accessibility_rating,
            },
            "features": features,
        }

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(fc, f, indent=2)

        return fc

    @staticmethod
    def export_route_to_gpkg(
        route: RouteResult,
        network: PedestrianNetwork,
        instructions: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Create a valid, standard OGC GeoPackage (SQLite database) containing:
        - Table 'route_corridor': Complete route LineString
        - Table 'route_segments': Individual sidewalk and crossing LineStrings with screen-reader text
        - Table 'route_waypoints': Start, destination, and curb-ramp Points with tactile warnings.
        """
        if not output_path:
            output_path = Path("output/route.gpkg")

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()

        conn = sqlite3.connect(str(out_path))
        c = conn.cursor()

        # 1. Create standard OGC GeoPackage metadata tables
        c.execute("""
            CREATE TABLE gpkg_spatial_ref_sys (
                srs_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL PRIMARY KEY,
                organization TEXT NOT NULL,
                organization_coordsys_id INTEGER NOT NULL,
                definition TEXT NOT NULL,
                description TEXT
            );
        """)
        c.execute("""
            INSERT INTO gpkg_spatial_ref_sys VALUES (
                'WGS 84', 4326, 'EPSG', 4326,
                'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
                'WGS 84 geographic coordinate reference system'
            );
        """)

        c.execute("""
            CREATE TABLE gpkg_contents (
                table_name TEXT NOT NULL PRIMARY KEY,
                data_type TEXT NOT NULL,
                identifier TEXT,
                description TEXT,
                last_change DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
                srs_id INTEGER
            );
        """)

        c.execute("""
            CREATE TABLE gpkg_geometry_columns (
                table_name TEXT NOT NULL PRIMARY KEY,
                column_name TEXT NOT NULL,
                geometry_type_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL,
                z TINYINT NOT NULL,
                m TINYINT NOT NULL
            );
        """)

        # 2. Table: route_corridor (LineString)
        c.execute("""
            CREATE TABLE route_corridor (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                geom BLOB,
                total_distance_m REAL,
                effective_cost REAL,
                accessibility_rating TEXT,
                num_steps INTEGER
            );
        """)
        c.execute("""
            INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id)
            VALUES ('route_corridor', 'features', 'route_corridor', 'Overall Pedestrian Route Corridor', 4326);
        """)
        c.execute("""
            INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m)
            VALUES ('route_corridor', 'geom', 'LINESTRING', 4326, 0, 0);
        """)

        nodes = network.raw_nodes
        route_pts = [nodes[nid] for nid in route.node_path if nid in nodes]
        if route_pts:
            gpb = _create_gpb_linestring(route_pts)
            c.execute(
                "INSERT INTO route_corridor (geom, total_distance_m, effective_cost, accessibility_rating, num_steps) "
                "VALUES (?, ?, ?, ?, ?)",
                (gpb, route.total_distance_m, route.total_effective_cost, route.accessibility_rating, len(route.edges)),
            )

        # 3. Table: route_segments (LineString)
        c.execute("""
            CREATE TABLE route_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                geom BLOB,
                edge_index INTEGER,
                feature_type TEXT,
                street_name TEXT,
                length_m REAL,
                has_tactile INTEGER,
                spoken_instruction TEXT
            );
        """)
        c.execute("""
            INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id)
            VALUES ('route_segments', 'features', 'route_segments', 'Detailed Route Segments & Spoken Steps', 4326);
        """)
        c.execute("""
            INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m)
            VALUES ('route_segments', 'geom', 'LINESTRING', 4326, 0, 0);
        """)

        # Insert segments
        for i, edge in enumerate(route.edges):
            u_pt = nodes.get(edge.u)
            v_pt = nodes.get(edge.v)
            if not u_pt or not v_pt:
                continue

            seg_coords = [u_pt, v_pt]
            name = "pedestrian_way"
            has_tactile = 0

            if edge.feature_type == "crosswalk":
                cw = edge.crosswalk
                if cw and len(cw.coordinates) >= 2:
                    seg_coords = cw.coordinates
                name = cw.name if (cw and cw.name) else "street_crossing"
                has_tactile = 1 if (cw and cw.has_tactile_paving) else 0
            else:
                sw = edge.sidewalk
                name = sw.name if (sw and sw.name) else "sidewalk"
                has_tactile = 1 if (sw and sw.has_tactile_paving) else 0

            gpb_seg = _create_gpb_linestring(seg_coords)
            c.execute(
                "INSERT INTO route_segments (geom, edge_index, feature_type, street_name, length_m, has_tactile) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gpb_seg, i, edge.feature_type, name, edge.length_m, has_tactile),
            )

        # 4. Table: route_waypoints (Point)
        c.execute("""
            CREATE TABLE route_waypoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                geom BLOB,
                waypoint_type TEXT,
                name TEXT,
                is_step_free INTEGER,
                has_tactile INTEGER
            );
        """)
        c.execute("""
            INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id)
            VALUES ('route_waypoints', 'features', 'route_waypoints', 'Start, End, and Curb Ramp Points', 4326);
        """)
        c.execute("""
            INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m)
            VALUES ('route_waypoints', 'geom', 'POINT', 4326, 0, 0);
        """)

        if route.node_path:
            s_pt = nodes.get(route.node_path[0])
            if s_pt:
                c.execute(
                    "INSERT INTO route_waypoints (geom, waypoint_type, name, is_step_free, has_tactile) VALUES (?, ?, ?, ?, ?)",
                    (_create_gpb_point(s_pt[1], s_pt[0]), "start", "Origin", 1, 0),
                )
            e_pt = nodes.get(route.node_path[-1])
            if e_pt:
                c.execute(
                    "INSERT INTO route_waypoints (geom, waypoint_type, name, is_step_free, has_tactile) VALUES (?, ?, ?, ?, ?)",
                    (_create_gpb_point(e_pt[1], e_pt[0]), "destination", "Destination", 1, 0),
                )

        # Curb ramps
        kerbs = network.kerbs
        for nid in set(route.node_path):
            if nid in kerbs and nid in nodes:
                kb = kerbs[nid]
                pt = nodes[nid]
                c.execute(
                    "INSERT INTO route_waypoints (geom, waypoint_type, name, is_step_free, has_tactile) VALUES (?, ?, ?, ?, ?)",
                    (_create_gpb_point(pt[1], pt[0]), "curb_ramp", kb.kerb_type, 1 if kb.is_step_free else 0, 1 if kb.has_tactile_paving else 0),
                )

        conn.commit()
        conn.close()
        return out_path

    @staticmethod
    def export_route_to_html(
        route: RouteResult,
        network: PedestrianNetwork,
        instructions: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[Path] = None,
        title: str = "Blind-Accessible Pedestrian Route",
        carto_api_key: Optional[str] = None,
    ) -> Path:
        """
        Generate a self-contained, interactive HTML web map using Leaflet.js and OpenStreetMap.
        Can be opened directly in any browser (Chrome, Edge, Firefox) without any server.
        """
        if not output_path:
            output_path = Path("output/route_map.html")

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if carto_api_key is None:
            try:
                from src.config import CARTO_API_KEY
                carto_api_key = CARTO_API_KEY
            except ImportError:
                carto_api_key = ""

        key_param = f"?key={carto_api_key.strip()}" if carto_api_key and carto_api_key.strip() else ""

        # Check for on-device cached CARTO basemap tiles
        try:
            from ..clients.carto_tile_cache import CartoTileCache
            tile_cache = CartoTileCache(api_key=carto_api_key)
            local_tile_template = tile_cache.get_local_url_template(relative_to=out_path.parent)
            stats = tile_cache.get_tile_stats(style="voyager")
            has_local_cache = stats["tile_count"] > 0
        except Exception:
            local_tile_template = "../cache/tiles/voyager/{z}/{x}/{y}.png"
            has_local_cache = False

        default_tile_script = "onDeviceTiles.addTo(map);" if has_local_cache else "cartoVoyager.addTo(map);"

        geojson_dict = GeoJSONExporter.export_route_to_geojson(route, network, instructions)
        geojson_str = json.dumps(geojson_dict)
        instructions_json_str = json.dumps(instructions or [])

        nodes = network.raw_nodes
        start_pt = nodes.get(route.node_path[0], (44.045, -121.331)) if route.node_path else (44.045, -121.331)

        # Dynamically build legend items based on features actually present in the route
        features_list = geojson_dict.get("features", [])
        has_sidewalk = any(
            f.get("properties", {}).get("segment_type") == "sidewalk"
            and not f.get("properties", {}).get("is_bridge")
            for f in features_list
        )
        has_bridge = any(
            f.get("properties", {}).get("is_bridge")
            for f in features_list
        )
        has_street_crossing = any(
            f.get("properties", {}).get("segment_type") == "crosswalk"
            and f.get("properties", {}).get("stroke") == "#F59E0B"
            for f in features_list
        )
        has_roundabout = any(
            f.get("properties", {}).get("segment_type") == "crosswalk"
            and f.get("properties", {}).get("stroke") == "#7C3AED"
            for f in features_list
        )
        has_driveway = any(
            f.get("properties", {}).get("segment_type") == "crosswalk"
            and f.get("properties", {}).get("stroke") == "#DC2626"
            for f in features_list
        )
        has_tactile_curb = any(
            f.get("properties", {}).get("feature_type") == "curb_ramp"
            and f.get("properties", {}).get("has_tactile_paving")
            for f in features_list
        )
        has_standard_curb = any(
            f.get("properties", {}).get("feature_type") == "curb_ramp"
            and not f.get("properties", {}).get("has_tactile_paving")
            for f in features_list
        )

        legend_items = []
        if has_sidewalk:
            legend_items.append('<div class="legend-item"><div class="legend-color" style="background:#10B981;"></div> Sidewalk Corridor</div>')
        if has_bridge:
            legend_items.append('<div class="legend-item"><div class="legend-color" style="background:#0D9488;"></div> Bridge Walkway</div>')
        if has_street_crossing:
            legend_items.append('<div class="legend-item"><div class="legend-color" style="background:#F59E0B; border-top: 2px dashed #F59E0B;"></div> Public Street Crossing</div>')
        if has_roundabout:
            legend_items.append('<div class="legend-item"><div class="legend-color" style="background:#7C3AED; border-top: 2px dashed #7C3AED;"></div> Roundabout Crossing</div>')
        if has_driveway:
            legend_items.append('<div class="legend-item"><div class="legend-color" style="background:#DC2626; border-top: 2px dashed #DC2626;"></div> Commercial Driveway</div>')
        if has_tactile_curb:
            legend_items.append('<div class="legend-item"><div class="legend-dot" style="background:#8B5CF6;"></div> Curb Ramp (Tactile Domes)</div>')
        if has_standard_curb:
            legend_items.append('<div class="legend-item"><div class="legend-dot" style="background:#64748B;"></div> Curb Cut (No Tactile)</div>')

        legend_html = "\n      ".join(legend_items) if legend_items else '<div class="legend-item"><div class="legend-color" style="background:#10B981;"></div> Sidewalk Corridor</div>'

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #0f172a;
      color: #f8fafc;
    }}
    #map {{
      width: 100vw;
      height: 100vh;
    }}
    .floating-card {{
      position: absolute;
      top: 16px;
      left: 16px;
      z-index: 1000;
      background: rgba(15, 23, 42, 0.92);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 12px;
      padding: 16px 20px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
      max-width: 360px;
    }}
    .floating-card h1 {{
      margin: 0 0 6px 0;
      font-size: 18px;
      color: #38bdf8;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .stat-row {{
      display: flex;
      justify-content: space-between;
      margin-top: 8px;
      font-size: 13px;
      color: #94a3b8;
    }}
    .stat-value {{
      font-weight: 600;
      color: #e2e8f0;
    }}
    .legend {{
      margin-top: 14px;
      border-top: 1px solid rgba(255, 255, 255, 0.1);
      padding-top: 10px;
      font-size: 12px;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 4px;
    }}
    .legend-color {{
      width: 16px;
      height: 4px;
      border-radius: 2px;
    }}
    .legend-dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      border: 1.5px solid #ffffff;
      flex-shrink: 0;
    }}
    .leaflet-popup-content-wrapper {{
      background: #1e293b;
      color: #f8fafc;
      border-radius: 10px;
      border: 1px solid #334155;
    }}
    .leaflet-popup-tip {{
      background: #1e293b;
    }}
    .popup-badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: 6px;
    }}
    .popup-speech {{
      font-size: 13px;
      line-height: 1.4;
      color: #cbd5e1;
      margin-top: 6px;
      font-style: italic;
    }}
    .leaflet-control-layers {{
      background: rgba(15, 23, 42, 0.92) !important;
      color: #f8fafc !important;
      border: 1px solid rgba(255, 255, 255, 0.15) !important;
      border-radius: 8px !important;
      padding: 10px 14px !important;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4) !important;
    }}
    .leaflet-control-layers-base label {{
      cursor: pointer;
      font-size: 13px;
      margin-bottom: 5px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    /* Navigation Stepper HUD Card */
    .nav-hud {{
      position: absolute;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      width: min(780px, calc(100vw - 32px));
      z-index: 1000;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1.5px solid rgba(56, 189, 248, 0.35);
      border-radius: 16px;
      padding: 16px 20px;
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.08);
      display: flex;
      flex-direction: column;
      gap: 10px;
      color: #f8fafc;
      transition: all 0.25s ease;
    }}
    .nav-hud:hover {{
      border-color: rgba(56, 189, 248, 0.6);
      box-shadow: 0 20px 48px rgba(0, 0, 0, 0.7), 0 0 20px rgba(56, 189, 248, 0.2);
    }}
    .nav-header-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .nav-badges {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .step-pill {{
      background: #0284c7;
      color: #ffffff;
      font-size: 12px;
      font-weight: 800;
      padding: 4px 10px;
      border-radius: 20px;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }}
    .action-badge {{
      font-size: 12px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 6px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .action-walk {{ background: #059669; color: #ffffff; }}
    .action-cross {{ background: #d97706; color: #ffffff; }}
    .action-curb-approach {{ background: #7c3aed; color: #ffffff; }}
    .action-curb-exit {{ background: #0d9488; color: #ffffff; }}
    .action-arrive {{ background: #e11d48; color: #ffffff; }}

    .nav-meta-chip {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.15);
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 6px;
      color: #cbd5e1;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}
    .chip-tactile {{
      background: rgba(139, 92, 246, 0.25);
      border-color: #8b5cf6;
      color: #c4b5fd;
    }}

    .nav-header-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .nav-icon-btn {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.18);
      color: #f8fafc;
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }}
    .nav-icon-btn:hover {{
      background: rgba(56, 189, 248, 0.2);
      border-color: #38bdf8;
      color: #38bdf8;
    }}
    .nav-icon-btn.active {{
      background: #0284c7;
      border-color: #38bdf8;
      color: #ffffff;
    }}

    .nav-instruction-text {{
      font-size: 17px;
      font-weight: 600;
      line-height: 1.45;
      color: #ffffff;
      margin: 2px 0;
      min-height: 48px;
      display: flex;
      align-items: center;
    }}

    .nav-progress-bar {{
      width: 100%;
      height: 4px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 2px;
      overflow: hidden;
      margin: 2px 0;
    }}
    .nav-progress-fill {{
      height: 100%;
      background: linear-gradient(90deg, #38bdf8, #10b981);
      width: 0%;
      transition: width 0.3s ease;
    }}

    .nav-controls-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 2px;
    }}
    .nav-btn-group {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .nav-btn {{
      background: #1e293b;
      border: 1px solid #475569;
      color: #f8fafc;
      padding: 7px 12px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
      user-select: none;
    }}
    .nav-btn:hover:not(:disabled) {{
      background: #334155;
      border-color: #38bdf8;
      color: #38bdf8;
    }}
    .nav-btn:disabled {{
      opacity: 0.4;
      cursor: not-allowed;
    }}
    .nav-btn-primary {{
      background: #0284c7;
      border-color: #38bdf8;
      color: #ffffff;
    }}
    .nav-btn-primary:hover:not(:disabled) {{
      background: #0369a1;
      color: #ffffff;
    }}

    .nav-step-select {{
      background: #1e293b;
      border: 1px solid #475569;
      color: #f8fafc;
      padding: 6px 10px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      max-width: 220px;
      outline: none;
    }}
    .nav-step-select:focus {{
      border-color: #38bdf8;
    }}

    .keyboard-hint {{
      font-size: 11px;
      color: #64748b;
    }}

    /* Pulsing Leaflet Pedestrian Avatar */
    .pulsing-avatar-container {{
      background: transparent;
      border: none;
    }}
    .pulsing-avatar {{
      display: flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      background: #0284c7;
      border: 2.5px solid #ffffff;
      border-radius: 50%;
      color: #ffffff;
      font-size: 16px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
      animation: avatarRipple 2s infinite ease-out;
    }}
    @keyframes avatarRipple {{
      0% {{
        box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.85);
      }}
      70% {{
        box-shadow: 0 0 0 16px rgba(56, 189, 248, 0);
      }}
      100% {{
        box-shadow: 0 0 0 0 rgba(56, 189, 248, 0);
      }}
    }}

    /* Steps List Drawer Modal */
    .nav-drawer {{
      position: absolute;
      top: 16px;
      right: 16px;
      width: min(400px, calc(100vw - 32px));
      max-height: calc(100vh - 200px);
      z-index: 1000;
      background: rgba(15, 23, 42, 0.96);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 14px;
      box-shadow: 0 16px 36px rgba(0, 0, 0, 0.55);
      display: none;
      flex-direction: column;
      overflow: hidden;
    }}
    .nav-drawer-header {{
      padding: 12px 16px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 14px;
      font-weight: 700;
      color: #38bdf8;
    }}
    .nav-drawer-close {{
      background: none;
      border: none;
      color: #94a3b8;
      font-size: 20px;
      cursor: pointer;
    }}
    .nav-drawer-close:hover {{ color: #f8fafc; }}
    .nav-drawer-list {{
      overflow-y: auto;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .drawer-step-item {{
      padding: 10px 12px;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.08);
      cursor: pointer;
      transition: all 0.15s ease;
      font-size: 13px;
    }}
    .drawer-step-item:hover {{
      background: rgba(56, 189, 248, 0.12);
      border-color: rgba(56, 189, 248, 0.35);
    }}
    .drawer-step-item.active {{
      background: rgba(2, 132, 199, 0.25);
      border-color: #38bdf8;
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
    }}
    .drawer-step-header {{
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      font-weight: 700;
      margin-bottom: 4px;
      color: #94a3b8;
    }}
    .drawer-step-item.active .drawer-step-header {{
      color: #38bdf8;
    }}
  </style>
</head>
<body>
  <div class="floating-card">
    <h1><span>🚶‍♂️</span> {title}</h1>
    <div class="stat-row">
      <span>Total Distance:</span>
      <span class="stat-value">{route.total_distance_m:.0f} meters (~{(route.total_distance_m / 1000 * 0.621371):.2f} mi)</span>
    </div>
    <div class="stat-row">
      <span>Safety Score:</span>
      <span class="stat-value">{route.accessibility_rating}</span>
    </div>
    <div class="stat-row">
      <span>Total Path Segments:</span>
      <span class="stat-value">{len(route.edges)} steps</span>
    </div>
    <div class="legend">
      {legend_html}
    </div>
  </div>

  <div id="map"></div>

  <!-- Step-by-Step Navigation Player HUD -->
  <div class="nav-hud" id="nav-hud" role="region" aria-label="Step-by-step pedestrian navigation">
    <div class="nav-header-row">
      <div class="nav-badges">
        <span class="step-pill" id="hud-step-pill">Step 1</span>
        <span class="action-badge action-walk" id="hud-action-badge">WALK</span>
        <span class="nav-meta-chip" id="hud-dist-chip">📏 0m</span>
        <span class="nav-meta-chip chip-tactile" id="hud-tactile-chip" style="display:none;">📳 Tactile Warning Domes</span>
        <span class="nav-meta-chip" id="hud-turn-chip" style="display:none;">Turn</span>
      </div>
      <div class="nav-header-actions">
        <label style="font-size:11px; display:flex; align-items:center; gap:4px; cursor:pointer; color:#94a3b8;" title="Automatically read aloud when advancing steps">
          <input type="checkbox" id="auto-speak-toggle" style="cursor:pointer;" /> Auto-Speak
        </label>
        <button class="nav-icon-btn" id="btn-speak" title="Read current instruction aloud (Web Speech API)">
          <span>🔊</span> Speak
        </button>
        <button class="nav-icon-btn" id="btn-toggle-drawer" title="Toggle full step list">
          <span>📋</span> All Steps
        </button>
      </div>
    </div>

    <div class="nav-instruction-text" id="hud-speech-text" aria-live="polite">
      Loading route guidance...
    </div>

    <div class="nav-progress-bar">
      <div class="nav-progress-fill" id="hud-progress-fill"></div>
    </div>

    <div class="nav-controls-row">
      <div class="nav-btn-group">
        <button class="nav-btn" id="btn-first" title="First step (Home)">⏮ First</button>
        <button class="nav-btn" id="btn-prev" title="Previous step (Left Arrow)">◀ Prev</button>
        <button class="nav-btn nav-btn-primary" id="btn-next" title="Next step (Right Arrow / Enter)">Next ▶</button>
        <button class="nav-btn" id="btn-last" title="Last step (End)">Last ⏭</button>
      </div>

      <select class="nav-step-select" id="hud-step-select" aria-label="Jump to specific step">
      </select>

      <div class="nav-btn-group">
        <button class="nav-btn" id="btn-autoplay" title="Play / Pause automatic step walkthrough">
          <span id="autoplay-icon">▶️</span> Auto-Play
        </button>
      </div>
      <span class="keyboard-hint">Keys: [←] Prev • [→] Next • [Space] Play/Speak</span>
    </div>
  </div>

  <!-- All Steps Drawer Modal -->
  <div class="nav-drawer" id="nav-drawer">
    <div class="nav-drawer-header">
      <span>Turn-by-Turn Guidance Steps</span>
      <button class="nav-drawer-close" id="btn-close-drawer">&times;</button>
    </div>
    <div class="nav-drawer-list" id="drawer-step-list"></div>
  </div>

  <script>
    var map = L.map('map').setView([{start_pt[0]}, {start_pt[1]}], 16);

    // 1. On-device cached raster tiles for offline field demonstrations
    var onDeviceTiles = L.tileLayer('{local_tile_template}', {{
      attribution: '&copy; <a href="https://carto.com/attributions">CARTO</a> (On-Device Cache)',
      maxZoom: 19,
      errorTileUrl: 'https://basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png{key_param}'
    }});

    // 2. Multi-source basemap tiles with open access policies that support local file:// viewing without 403 errors
    var cartoVoyager = L.tileLayer('https://basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png{key_param}', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxZoom: 20
    }});

    var cartoDark = L.tileLayer('https://basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png{key_param}', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxZoom: 20
    }});

    var cartoPositron = L.tileLayer('https://basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png{key_param}', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxZoom: 20
    }});

    var esriSatellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
      maxZoom: 19
    }});

    var esriStreet = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom, 2012',
      maxZoom: 19
    }});

    // Prefer on-device cached tiles when available; fallback to CartoDB Voyager
    {default_tile_script}

    var baseMaps = {{
      "📱 On-Device Cache (Offline)": onDeviceTiles,
      "🗺️ Streets (Voyager)": cartoVoyager,
      "🌙 Dark Mode": cartoDark,
      "☀️ Positron (Light)": cartoPositron,
      "🛰️ Satellite Imagery": esriSatellite,
      "🌐 Esri Topo / Streets": esriStreet
    }};

    L.control.layers(baseMaps, null, {{ position: 'topright' }}).addTo(map);

    var routeData = {geojson_str};

    var geojsonLayer = L.geoJSON(routeData, {{
      style: function(feature) {{
        var p = feature.properties || {{}};
        if (p.feature_type === 'route_corridor') {{
          return {{
            color: '#2563EB',
            weight: 7,
            opacity: 0.35
          }};
        }}
        if (p.feature_type === 'route_segment') {{
          return {{
            color: p.stroke || '#10B981',
            weight: p['stroke-width'] || 5,
            dashArray: p['stroke-dasharray'] || null,
            opacity: 0.95
          }};
        }}
        return {{ color: '#3b82f6', weight: 4 }};
      }},
      pointToLayer: function(feature, latlng) {{
        var p = feature.properties || {{}};
        if (p.waypoint_type === 'start') {{
          return L.circleMarker(latlng, {{
            radius: 8,
            fillColor: '#16A34A',
            color: '#ffffff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.95
          }}).bindPopup('<b>Start / Origin</b>');
        }}
        if (p.waypoint_type === 'destination') {{
          return L.circleMarker(latlng, {{
            radius: 8,
            fillColor: '#DC2626',
            color: '#ffffff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.95
          }}).bindPopup('<b>Destination</b>');
        }}
        if (p.feature_type === 'curb_ramp') {{
          var color = p.has_tactile_paving ? '#8B5CF6' : '#64748B';
          return L.circleMarker(latlng, {{
            radius: 5,
            fillColor: color,
            color: '#ffffff',
            weight: 1.5,
            opacity: 1,
            fillOpacity: 0.85
          }}).bindPopup('<b>Curb Ramp</b><br>Tactile domes: ' + (p.has_tactile_paving ? 'Yes' : 'No') + '<br>Step-free: ' + (p.is_step_free ? 'Yes' : 'No'));
        }}
        return L.circleMarker(latlng, {{ radius: 4 }});
      }},
      onEachFeature: function(feature, layer) {{
        var p = feature.properties || {{}};
        if (p.feature_type === 'route_segment') {{
          var badgeColor = p.segment_type === 'crosswalk' ? '#F59E0B' : '#10B981';
          var badgeText = p.segment_type === 'crosswalk' ? (p.road_crossed || 'CROSSING') : 'SIDEWALK';
          var speech = p.spoken_instruction ? '<div class="popup-speech">"' + p.spoken_instruction + '"</div>' : '';
          var popupContent = '<div>' +
            '<span class="popup-badge" style="background:' + badgeColor + '; color:#000;">' + badgeText + '</span>' +
            '<div style="font-size:12px; color:#94a3b8;">Length: ' + Math.round(p.length_m) + 'm</div>' +
            speech +
            '</div>';
          layer.bindPopup(popupContent);
        }}
      }}
    }}).addTo(map);

    try {{
      map.fitBounds(geojsonLayer.getBounds(), {{ padding: [40, 160] }});
    }} catch(e) {{}}

    // =========================================================================
    // Interactive Step-by-Step Navigation Player Engine
    // =========================================================================
    var navSteps = {instructions_json_str};
    var currentStepIdx = 0;
    var autoPlayTimer = null;
    var activeStepPolyline = null;
    var activeStepMarker = null;

    // Custom animated avatar icon
    var avatarIcon = L.divIcon({{
      className: 'pulsing-avatar-container',
      html: '<div class="pulsing-avatar">🚶</div>',
      iconSize: [32, 32],
      iconAnchor: [16, 16],
    }});

    var avatarMarker = null;

    // Populate Step Dropdown and Drawer List
    var stepSelect = document.getElementById('hud-step-select');
    var drawerList = document.getElementById('drawer-step-list');

    navSteps.forEach(function(s, idx) {{
      var opt = document.createElement('option');
      opt.value = idx;
      opt.textContent = 'Step ' + s.step + ': ' + (s.action || 'STEP').replace(/_/g, ' ');
      stepSelect.appendChild(opt);

      var item = document.createElement('div');
      item.className = 'drawer-step-item' + (idx === 0 ? ' active' : '');
      item.id = 'drawer-item-' + idx;
      item.innerHTML = '<div class="drawer-step-header">' +
        '<span>STEP ' + s.step + ' • ' + (s.action || 'STEP').replace(/_/g, ' ') + '</span>' +
        '<span>' + (s.distance_m ? Math.round(s.distance_m) + 'm' : '') + '</span>' +
        '</div>' +
        '<div>' + s.spoken_instruction + '</div>';
      item.onclick = function() {{
        goToStep(idx, true);
      }};
      drawerList.appendChild(item);
    }});

    function getActionBadgeStyle(action) {{
      switch(action) {{
        case 'WALK_SIDEWALK': return {{ cls: 'action-walk', label: '🚶 WALK SIDEWALK' }};
        case 'CROSS_STREET': return {{ cls: 'action-cross', label: '🚸 CROSS STREET' }};
        case 'APPROACH_CURB': return {{ cls: 'action-curb-approach', label: '🛑 APPROACH CURB' }};
        case 'EXIT_CURB': return {{ cls: 'action-curb-exit', label: '⬆️ EXIT CURB' }};
        case 'ARRIVE': return {{ cls: 'action-arrive', label: '🎯 DESTINATION' }};
        default: return {{ cls: 'action-walk', label: (action || 'WALK').replace(/_/g, ' ') }};
      }}
    }}

    function speakCurrentInstruction() {{
      if (!('speechSynthesis' in window)) return;
      window.speechSynthesis.cancel();
      var s = navSteps[currentStepIdx];
      if (!s || !s.spoken_instruction) return;
      var utter = new SpeechSynthesisUtterance(s.spoken_instruction);
      utter.rate = 1.0;
      window.speechSynthesis.speak(utter);
    }}

    function goToStep(idx, fromUserClick) {{
      if (!navSteps || navSteps.length === 0) return;
      if (idx < 0) idx = 0;
      if (idx >= navSteps.length) idx = navSteps.length - 1;
      currentStepIdx = idx;

      var s = navSteps[currentStepIdx];
      var total = navSteps.length;

      // Update UI Header
      document.getElementById('hud-step-pill').textContent = 'Step ' + (idx + 1) + ' of ' + total;
      var badgeInfo = getActionBadgeStyle(s.action);
      var badgeEl = document.getElementById('hud-action-badge');
      badgeEl.className = 'action-badge ' + badgeInfo.cls;
      badgeEl.textContent = badgeInfo.label;

      // Distance chip
      var distChip = document.getElementById('hud-dist-chip');
      if (s.distance_m && s.distance_m > 0) {{
        distChip.style.display = 'inline-flex';
        distChip.textContent = '📏 ' + Math.round(s.distance_m) + 'm';
      }} else {{
        distChip.style.display = 'none';
      }}

      // Tactile chip
      var tactileChip = document.getElementById('hud-tactile-chip');
      if (s.tactile_cue) {{
        tactileChip.style.display = 'inline-flex';
        tactileChip.textContent = '📳 Tactile Warning Domes';
      }} else {{
        tactileChip.style.display = 'none';
      }}

      // Turn chip
      var turnChip = document.getElementById('hud-turn-chip');
      if (s.turn_direction || s.clock_position) {{
        turnChip.style.display = 'inline-flex';
        turnChip.textContent = (s.clock_position ? s.clock_position + ' ' : '') + (s.turn_direction ? '(' + s.turn_direction + ')' : '');
      }} else {{
        turnChip.style.display = 'none';
      }}

      // Instruction text
      document.getElementById('hud-speech-text').textContent = s.spoken_instruction;

      // Progress bar
      var pct = Math.round(((idx + 1) / total) * 100);
      document.getElementById('hud-progress-fill').style.width = pct + '%';

      // Controls state
      document.getElementById('btn-prev').disabled = (idx === 0);
      document.getElementById('btn-first').disabled = (idx === 0);
      document.getElementById('btn-next').disabled = (idx === total - 1);
      document.getElementById('btn-last').disabled = (idx === total - 1);
      stepSelect.value = idx;

      // Drawer items state
      for (var i = 0; i < total; i++) {{
        var el = document.getElementById('drawer-item-' + i);
        if (el) {{
          if (i === idx) {{
            el.className = 'drawer-step-item active';
            el.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
          }} else {{
            el.className = 'drawer-step-item';
          }}
        }}
      }}

      // Map Coordinate Resolution
      var coord = s.coordinate;
      if (!coord || (coord[0] === 0 && coord[1] === 0)) {{
        coord = [{start_pt[0]}, {start_pt[1]}];
      }}

      // 1. Move Pedestrian Avatar
      if (!avatarMarker) {{
        avatarMarker = L.marker([coord[0], coord[1]], {{ icon: avatarIcon, zIndexOffset: 2000 }}).addTo(map);
      }} else {{
        avatarMarker.setLatLng([coord[0], coord[1]]);
      }}

      // 2. Highlight Active Segment Geometry
      if (activeStepPolyline) {{
        map.removeLayer(activeStepPolyline);
        activeStepPolyline = null;
      }}
      if (activeStepMarker) {{
        map.removeLayer(activeStepMarker);
        activeStepMarker = null;
      }}

      if (s.coordinates && s.coordinates.length >= 2) {{
        var latLngs = s.coordinates.map(function(c) {{ return [c[0], c[1]]; }});
        activeStepPolyline = L.polyline(latLngs, {{
          color: '#38bdf8',
          weight: 9,
          opacity: 0.9,
          lineCap: 'round',
          lineJoin: 'round',
        }}).addTo(map);
      }} else {{
        activeStepMarker = L.circleMarker([coord[0], coord[1]], {{
          radius: 12,
          color: '#38bdf8',
          fillColor: '#38bdf8',
          fillOpacity: 0.35,
          weight: 3,
        }}).addTo(map);
      }}

      // 3. Pan / Zoom Map to active step with padding for the bottom HUD
      map.panTo([coord[0], coord[1]], {{ animate: true, duration: 0.5 }});

      // 4. Auto-Speak if enabled
      if (document.getElementById('auto-speak-toggle').checked && fromUserClick) {{
        speakCurrentInstruction();
      }}
    }}

    // Button event listeners
    document.getElementById('btn-next').onclick = function() {{ goToStep(currentStepIdx + 1, true); }};
    document.getElementById('btn-prev').onclick = function() {{ goToStep(currentStepIdx - 1, true); }};
    document.getElementById('btn-first').onclick = function() {{ goToStep(0, true); }};
    document.getElementById('btn-last').onclick = function() {{ goToStep(navSteps.length - 1, true); }};
    document.getElementById('btn-speak').onclick = speakCurrentInstruction;

    stepSelect.onchange = function(e) {{
      goToStep(parseInt(e.target.value, 10), true);
    }};

    // Auto-play walkthrough toggle
    var autoPlayBtn = document.getElementById('btn-autoplay');
    var autoPlayIcon = document.getElementById('autoplay-icon');
    function toggleAutoPlay() {{
      if (autoPlayTimer) {{
        clearInterval(autoPlayTimer);
        autoPlayTimer = null;
        autoPlayBtn.classList.remove('active');
        autoPlayIcon.textContent = '▶️';
      }} else {{
        autoPlayBtn.classList.add('active');
        autoPlayIcon.textContent = '⏸️';
        if (currentStepIdx >= navSteps.length - 1) {{
          goToStep(0, true);
        }}
        autoPlayTimer = setInterval(function() {{
          if (currentStepIdx < navSteps.length - 1) {{
            goToStep(currentStepIdx + 1, true);
          }} else {{
            toggleAutoPlay();
          }}
        }}, 3600);
      }}
    }}
    autoPlayBtn.onclick = toggleAutoPlay;

    // Drawer toggle
    var drawer = document.getElementById('nav-drawer');
    var toggleDrawerBtn = document.getElementById('btn-toggle-drawer');
    var closeDrawerBtn = document.getElementById('btn-close-drawer');
    function toggleDrawer() {{
      var isVisible = drawer.style.display === 'flex';
      drawer.style.display = isVisible ? 'none' : 'flex';
      toggleDrawerBtn.classList.toggle('active', !isVisible);
    }}
    toggleDrawerBtn.onclick = toggleDrawer;
    closeDrawerBtn.onclick = toggleDrawer;

    // Keyboard navigation
    window.addEventListener('keydown', function(e) {{
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.key === 'ArrowRight' || e.key === 'Enter') {{
        goToStep(currentStepIdx + 1, true);
      }} else if (e.key === 'ArrowLeft') {{
        goToStep(currentStepIdx - 1, true);
      }} else if (e.key === 'Home') {{
        goToStep(0, true);
      }} else if (e.key === 'End') {{
        goToStep(navSteps.length - 1, true);
      }} else if (e.key === ' ') {{
        e.preventDefault();
        toggleAutoPlay();
      }}
    }});

    // Initialize to step 0
    if (navSteps.length > 0) {{
      goToStep(0, false);
    }}
  </script>
</body>
</html>
"""
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return out_path
