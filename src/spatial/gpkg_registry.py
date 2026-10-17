"""Resilient, pluggable GeoPackage SQLite registry and in-memory spatial index."""

from dataclasses import dataclass, field
from enum import Enum
import logging
import math
from pathlib import Path
import sqlite3
import struct
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class LayerRole(str, Enum):
    CROSSWALK = "crosswalk"
    CURB_RAMP = "curb_ramp"
    SIDEWALK = "sidewalk"
    ROADWAY = "roadway"
    GENERIC = "generic"


@dataclass
class SpatialFeature:
    """Represents an extracted spatial asset from any municipal GeoPackage database."""
    feature_id: str
    layer_role: LayerRole
    table_name: str
    source_file: str
    geometry_type: str
    coordinates: List[Tuple[float, float]]  # List of (lat, lon)
    centroid: Tuple[float, float]           # (lat, lon)
    attributes: Dict[str, Any] = field(default_factory=dict)


def mercator_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    """Convert EPSG:3857 Web Mercator coordinate to EPSG:4326 (lat, lon)."""
    lon = x * 180.0 / 20037508.34
    lat = math.atan(math.sinh(y * math.pi / 20037508.34)) * 180.0 / math.pi
    return lat, lon


def haversine_distance_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Calculate distance in meters between two (lat, lon) points."""
    r = 6371000.0  # Earth radius in meters
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def parse_gpkg_geometry(blob: bytes) -> Tuple[str, List[Tuple[float, float]], Tuple[float, float]]:
    """
    Parse a GeoPackage binary geometry BLOB into (geom_type, coordinates, centroid).
    Handles GeoPackage binary header with variable envelope headers and EPSG:3857/4326 coords.
    """
    if not blob or len(blob) < 8:
        raise ValueError("Geometry blob is too short")

    magic = blob[:2]
    if magic != b"GP":
        raise ValueError(f"Invalid GeoPackage magic header: {magic!r}")

    flags = blob[3]
    envelope_type = (flags >> 1) & 0x07
    srs_id = struct.unpack("<i" if (flags & 0x01) else ">i", blob[4:8])[0]

    # Calculate WKB offset based on envelope presence
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    env_size = envelope_sizes.get(envelope_type, 0)
    wkb_offset = 8 + env_size

    if len(blob) < wkb_offset + 5:
        raise ValueError("Geometry blob truncated before WKB header")

    wkb = blob[wkb_offset:]
    byte_order = "<" if wkb[0] == 1 else ">"
    raw_type = struct.unpack(f"{byte_order}I", wkb[1:5])[0]
    # Handle ISO / postgis 3D flags: mask to base type
    base_type = raw_type % 1000

    coords: List[Tuple[float, float]] = []
    geom_name = "Unknown"

    if base_type == 1:  # Point
        geom_name = "Point"
        px, py = struct.unpack(f"{byte_order}dd", wkb[5:21])
        if srs_id == 3857 or abs(px) > 180.0:
            lat, lon = mercator_to_wgs84(px, py)
        else:
            lat, lon = py, px
        coords = [(lat, lon)]
        centroid = (lat, lon)

    elif base_type == 2:  # LineString
        geom_name = "LineString"
        num_points = struct.unpack(f"{byte_order}I", wkb[5:9])[0]
        offset = 9
        for _ in range(num_points):
            px, py = struct.unpack(f"{byte_order}dd", wkb[offset : offset + 16])
            if srs_id == 3857 or abs(px) > 180.0:
                lat, lon = mercator_to_wgs84(px, py)
            else:
                lat, lon = py, px
            coords.append((lat, lon))
            offset += 16
        mid_lat = sum(p[0] for p in coords) / len(coords) if coords else 0.0
        mid_lon = sum(p[1] for p in coords) / len(coords) if coords else 0.0
        centroid = (mid_lat, mid_lon)

    elif base_type == 5:  # MultiLineString
        geom_name = "MultiLineString"
        num_lines = struct.unpack(f"{byte_order}I", wkb[5:9])[0]
        offset = 9
        for _ in range(num_lines):
            # sub-linestring header
            sub_order = "<" if wkb[offset] == 1 else ">"
            sub_num_points = struct.unpack(f"{sub_order}I", wkb[offset + 5 : offset + 9])[0]
            offset += 9
            for _ in range(sub_num_points):
                px, py = struct.unpack(f"{sub_order}dd", wkb[offset : offset + 16])
                if srs_id == 3857 or abs(px) > 180.0:
                    lat, lon = mercator_to_wgs84(px, py)
                else:
                    lat, lon = py, px
                coords.append((lat, lon))
                offset += 16
        mid_lat = sum(p[0] for p in coords) / len(coords) if coords else 0.0
        mid_lon = sum(p[1] for p in coords) / len(coords) if coords else 0.0
        centroid = (mid_lat, mid_lon)

    else:
        geom_name = f"Type{base_type}"
        centroid = (0.0, 0.0)

    return geom_name, coords, centroid


class GeoPackageRegistry:
    """
    Extensible registry for scanning, ingesting, and spatially querying municipal GeoPackage SQLite files.
    Builds in-memory spatial grid buckets for sub-millisecond proximity lookups.
    """

    GRID_BUCKET_SIZE_DEG = 0.001  # ~110m grid bucket

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir
        self.features: Dict[str, SpatialFeature] = {}
        # (grid_x, grid_y) -> list of feature_ids
        self._spatial_grid: Dict[Tuple[int, int], List[str]] = {}
        self.loaded_files: List[str] = []
        self.layer_counts: Dict[LayerRole, int] = {role: 0 for role in LayerRole}

        if self.data_dir and self.data_dir.exists():
            self.discover_and_load(self.data_dir)

    def _grid_key(self, lat: float, lon: float) -> Tuple[int, int]:
        """Convert lat, lon into integer spatial grid bucket indices."""
        return (
            int(math.floor(lat / self.GRID_BUCKET_SIZE_DEG)),
            int(math.floor(lon / self.GRID_BUCKET_SIZE_DEG)),
        )

    def _detect_layer_role(self, table_name: str, columns: List[str]) -> LayerRole:
        """Infer functional role of a GeoPackage table from its column schema."""
        col_set = {c.lower() for c in columns}
        tbl_lower = table_name.lower()

        # Crosswalk indicators
        if "intersectiontype" in col_set or "roadcrossed" in col_set or "crosswalk" in tbl_lower:
            return LayerRole.CROSSWALK

        # Curb ramp indicators
        if ("mainstreet" in col_set and "crosstreet" in col_set) or "curb_ramp" in tbl_lower or "curbramp" in tbl_lower:
            return LayerRole.CURB_RAMP

        # Sidewalk indicators
        if "swwidth" in col_set or "swstatus" in col_set or "sidewalk" in tbl_lower:
            return LayerRole.SIDEWALK

        # Roadway centerline indicators
        if "st_name" in col_set or "speed_limit" in col_set or "street_name" in col_set:
            return LayerRole.ROADWAY

        return LayerRole.GENERIC

    def discover_and_load(self, data_dir: Path) -> int:
        """
        Dynamically scan directory for all *.gpkg files, inspect tables, and index spatial records.
        Returns total number of loaded features.
        """
        if not data_dir.exists():
            logger.warning(f"MapData directory does not exist: {data_dir}")
            return 0

        gpkg_files = list(data_dir.glob("*.gpkg"))
        total_loaded = 0

        for gpkg_path in gpkg_files:
            try:
                loaded = self._load_file(gpkg_path)
                total_loaded += loaded
                self.loaded_files.append(gpkg_path.name)
            except Exception as e:
                logger.error(f"Failed to load GeoPackage {gpkg_path.name}: {e}")

        return total_loaded

    def _load_file(self, gpkg_path: Path) -> int:
        """Load feature tables from a single GeoPackage SQLite database."""
        count = 0
        try:
            conn = sqlite3.connect(str(gpkg_path))
            c = conn.cursor()

            # 1. Discover feature tables via gpkg_contents
            c.execute("SELECT table_name FROM gpkg_contents WHERE data_type = 'features'")
            feature_tables = [r[0] for r in c.fetchall()]

            for tbl in feature_tables:
                # 2. Inspect table schema
                c.execute(f"PRAGMA table_info({tbl})")
                col_info = c.fetchall()
                col_names = [col[1] for col in col_info]
                role = self._detect_layer_role(tbl, col_names)

                geom_col = "SHAPE" if "SHAPE" in col_names else ("geom" if "geom" in col_names else None)
                if not geom_col:
                    continue

                # Identify primary key column
                pk_col = "OBJECTID" if "OBJECTID" in col_names else col_names[0]

                # Select all columns
                cols_str = ", ".join(f'"{col}"' for col in col_names)
                c.execute(f"SELECT {cols_str} FROM {tbl} WHERE {geom_col} IS NOT NULL")
                rows = c.fetchall()

                geom_idx = col_names.index(geom_col)
                pk_idx = col_names.index(pk_col)

                for row in rows:
                    raw_geom = row[geom_idx]
                    pk_val = row[pk_idx]
                    if not raw_geom:
                        continue

                    try:
                        gname, coords, centroid = parse_gpkg_geometry(raw_geom)
                    except Exception:
                        continue

                    if not coords:
                        continue

                    attr_dict = {col_names[i]: row[i] for i in range(len(col_names)) if i != geom_idx}
                    fid = f"{tbl}:{pk_val}"

                    feature = SpatialFeature(
                        feature_id=fid,
                        layer_role=role,
                        table_name=tbl,
                        source_file=gpkg_path.name,
                        geometry_type=gname,
                        coordinates=coords,
                        centroid=centroid,
                        attributes=attr_dict,
                    )

                    self.features[fid] = feature
                    self.layer_counts[role] += 1
                    count += 1

                    # Index centroid and line endpoints/midpoints into spatial grid
                    indexed_points = {self._grid_key(centroid[0], centroid[1])}
                    if len(coords) > 1:
                        indexed_points.add(self._grid_key(coords[0][0], coords[0][1]))
                        indexed_points.add(self._grid_key(coords[-1][0], coords[-1][1]))
                        mid_pt = coords[len(coords) // 2]
                        indexed_points.add(self._grid_key(mid_pt[0], mid_pt[1]))

                    for key in indexed_points:
                        if key not in self._spatial_grid:
                            self._spatial_grid[key] = []
                        self._spatial_grid[key].append(fid)

            conn.close()
        except Exception as e:
            logger.warning(f"Error reading GeoPackage {gpkg_path.name}: {e}")

        return count

    def query_radius(
        self,
        lat: float,
        lon: float,
        radius_m: float = 15.0,
        role: Optional[LayerRole] = None,
    ) -> List[Tuple[SpatialFeature, float]]:
        """
        Query spatial features within radius_m of (lat, lon), optionally filtering by LayerRole.
        Returns a list of (feature, distance_meters) tuples sorted by closest distance.
        """
        # Determine candidate grid cells
        deg_delta = (radius_m + 5.0) / 111320.0
        min_key = self._grid_key(lat - deg_delta, lon - deg_delta)
        max_key = self._grid_key(lat + deg_delta, lon + deg_delta)

        candidate_fids: Set[str] = set()
        for gx in range(min_key[0], max_key[0] + 1):
            for gy in range(min_key[1], max_key[1] + 1):
                fids = self._spatial_grid.get((gx, gy))
                if fids:
                    candidate_fids.update(fids)

        results: List[Tuple[SpatialFeature, float]] = []
        target_pt = (lat, lon)

        for fid in candidate_fids:
            feat = self.features.get(fid)
            if not feat:
                continue
            if role is not None and feat.layer_role != role:
                continue

            # Calculate minimum distance to feature (checking centroid or coordinates)
            dist_centroid = haversine_distance_m(target_pt, feat.centroid)
            min_dist = dist_centroid

            if len(feat.coordinates) > 1:
                # Check line vertices for closer approach
                for pt in feat.coordinates:
                    d = haversine_distance_m(target_pt, pt)
                    if d < min_dist:
                        min_dist = d

            if min_dist <= radius_m:
                results.append((feat, min_dist))

        results.sort(key=lambda item: item[1])
        return results

    def find_nearest(
        self,
        lat: float,
        lon: float,
        max_dist_m: float = 20.0,
        role: Optional[LayerRole] = None,
    ) -> Optional[Tuple[SpatialFeature, float]]:
        """Find single nearest feature within max_dist_m, optionally matching role."""
        matches = self.query_radius(lat, lon, radius_m=max_dist_m, role=role)
        return matches[0] if matches else None
