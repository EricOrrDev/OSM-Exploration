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
                    cross_idx += 1

                road_name = inst.get("spoken_road_name") or inst.get("road_crossed") or (cw.name if cw else "crosswalk")
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
                    sw_idx += 1

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
                        "street_name": sw.name if sw else "sidewalk",
                        "length_m": edge.length_m,
                        "surface": sw.surface if sw else "concrete",
                        "has_tactile_paving": sw.has_tactile_paving if sw else False,
                        "spoken_instruction": inst.get("spoken_instruction") if inst else None,
                        "stroke": "#10B981",  # Emerald green for sidewalks
                        "stroke-width": 4,
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
    ) -> Path:
        """
        Generate a self-contained, interactive HTML web map using Leaflet.js and OpenStreetMap.
        Can be opened directly in any browser (Chrome, Edge, Firefox) without any server.
        """
        if not output_path:
            output_path = Path("output/route_map.html")

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        geojson_dict = GeoJSONExporter.export_route_to_geojson(route, network, instructions)
        geojson_str = json.dumps(geojson_dict)

        nodes = network.raw_nodes
        start_pt = nodes.get(route.node_path[0], (44.045, -121.331)) if route.node_path else (44.045, -121.331)

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
      <div class="legend-item"><div class="legend-color" style="background:#10B981;"></div> Sidewalk Corridor</div>
      <div class="legend-item"><div class="legend-color" style="background:#F59E0B; border-top: 2px dashed #F59E0B;"></div> Public Street Crossing</div>
      <div class="legend-item"><div class="legend-color" style="background:#DC2626; border-top: 2px dashed #DC2626;"></div> Commercial Driveway (Safeway)</div>
      <div class="legend-item"><div class="legend-color" style="background:#7C3AED; border-top: 2px dashed #7C3AED;"></div> Roundabout Slip Lane (Innovation Way)</div>
    </div>
  </div>

  <div id="map"></div>

  <script>
    var map = L.map('map').setView([{start_pt[0]}, {start_pt[1]}], 16);

    // Multi-source basemap tiles with open access policies that support local file:// viewing without 403 errors
    var cartoVoyager = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20
    }});

    var cartoDark = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
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

    // Default to CartoDB Voyager (clean street geometry and labels)
    cartoVoyager.addTo(map);

    var baseMaps = {{
      "🗺️ Streets (Voyager)": cartoVoyager,
      "🌙 Dark Mode": cartoDark,
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
          }}).bindPopup('<b>Destination: Safeway</b>');
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
      map.fitBounds(geojsonLayer.getBounds(), {{ padding: [40, 40] }});
    }} catch(e) {{}}
  </script>
</body>
</html>
"""
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return out_path
