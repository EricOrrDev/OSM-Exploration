"""On-Device CARTO Basemap Raster Tile Caching Engine.

Enables offline / on-device raster basemap tile caching for pedestrian navigation
prototypes in Bend, Oregon and West Yellowstone, Montana without live network dependencies.
"""

import math
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import requests

from ..config import CACHE_DIR, CARTO_API_KEY, USER_AGENT


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> Tuple[int, int]:
    """Convert geographical latitude and longitude to Slippy Map tile (x, y) coordinates."""
    lat_rad = math.radians(lat_deg)
    n = 1 << zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)


def num2deg(xtile: int, ytile: int, zoom: int) -> Tuple[float, float]:
    """Convert Slippy Map tile (x, y) and zoom to North-West corner (lat, lon) in degrees."""
    n = 1 << zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)


def bbox_to_tile_bounds(
    bbox: Tuple[float, float, float, float],
    zoom: int,
) -> Tuple[int, int, int, int]:
    """Convert bounding box (south, west, north, east) to Slippy tile coordinate range.

    Returns (min_x, max_x, min_y, max_y) covering the entire bounding box.
    """
    south, west, north, east = bbox
    x1, y_south = deg2num(south, west, zoom)
    x2, y_north = deg2num(north, east, zoom)

    min_x = min(x1, x2)
    max_x = max(x1, x2)
    min_y = min(y_north, y_south)
    max_y = max(y_north, y_south)
    return (min_x, max_x, min_y, max_y)


class CartoTileCache:
    """Manages downloading, storing, and serving on-device CARTO raster basemap tiles."""

    STYLE_ENDPOINTS = {
        "voyager": "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "dark": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "positron": "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    }

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        api_key: Optional[str] = None,
    ):
        self.cache_dir = (cache_dir or CACHE_DIR) / "tiles"
        self.api_key = (api_key if api_key is not None else CARTO_API_KEY).strip()

    def tile_path(self, z: int, x: int, y: int, style: str = "voyager") -> Path:
        """Get the filesystem path for a specific cached tile."""
        return self.cache_dir / style / str(z) / str(x) / f"{y}.png"

    def is_tile_cached(self, z: int, x: int, y: int, style: str = "voyager") -> bool:
        """Check whether a tile exists in local storage and is non-empty."""
        p = self.tile_path(z, x, y, style=style)
        return p.exists() and p.stat().st_size > 0

    def get_online_tile_url(self, z: int, x: int, y: int, style: str = "voyager") -> str:
        """Construct the authenticated online CARTO tile URL."""
        endpoint = self.STYLE_ENDPOINTS.get(style, self.STYLE_ENDPOINTS["voyager"])
        url = endpoint.format(z=z, x=x, y=y)
        if self.api_key:
            url += f"?key={self.api_key}"
        return url

    def download_tile(
        self,
        z: int,
        x: int,
        y: int,
        style: str = "voyager",
        force_refresh: bool = False,
        session: Optional[requests.Session] = None,
    ) -> Optional[Path]:
        """Download and cache a single CARTO tile to local disk storage."""
        target = self.tile_path(z, x, y, style=style)
        if not force_refresh and target.exists() and target.stat().st_size > 0:
            return target

        url = self.get_online_tile_url(z, x, y, style=style)
        headers = {"User-Agent": USER_AGENT}

        try:
            client = session or requests
            resp = client.get(url, headers=headers, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 0:
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "wb") as f:
                    f.write(resp.content)
                return target
        except Exception:
            pass

        return None

    def cache_bbox(
        self,
        bbox: Tuple[float, float, float, float],
        min_zoom: int = 14,
        max_zoom: int = 17,
        style: str = "voyager",
        force_refresh: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Pre-fetch and store all tiles covering a bounding box across zoom levels.

        Returns statistics on downloaded and cached tiles.
        """
        all_tiles: List[Tuple[int, int, int]] = []
        for z in range(min_zoom, max_zoom + 1):
            min_x, max_x, min_y, max_y = bbox_to_tile_bounds(bbox, z)
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    all_tiles.append((z, x, y))

        total = len(all_tiles)
        newly_downloaded = 0
        already_cached = 0
        failed = 0
        total_bytes = 0

        session = requests.Session()
        for idx, (z, x, y) in enumerate(all_tiles, 1):
            if not force_refresh and self.is_tile_cached(z, x, y, style=style):
                already_cached += 1
                try:
                    total_bytes += self.tile_path(z, x, y, style=style).stat().st_size
                except Exception:
                    pass
                if progress_callback:
                    progress_callback(idx, total, "cached")
                continue

            result = self.download_tile(z, x, y, style=style, force_refresh=force_refresh, session=session)
            if result and result.exists():
                newly_downloaded += 1
                total_bytes += result.stat().st_size
                if progress_callback:
                    progress_callback(idx, total, "downloaded")
            else:
                failed += 1
                if progress_callback:
                    progress_callback(idx, total, "failed")

        session.close()

        return {
            "total_tiles": total,
            "newly_downloaded": newly_downloaded,
            "already_cached": already_cached,
            "failed_tiles": failed,
            "total_bytes": total_bytes,
            "style": style,
            "min_zoom": min_zoom,
            "max_zoom": max_zoom,
        }

    def has_coverage(
        self,
        bbox: Tuple[float, float, float, float],
        min_zoom: int = 14,
        max_zoom: int = 17,
        style: str = "voyager",
    ) -> bool:
        """Check if all tiles covering the bounding box are present in local storage."""
        for z in range(min_zoom, max_zoom + 1):
            min_x, max_x, min_y, max_y = bbox_to_tile_bounds(bbox, z)
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    if not self.is_tile_cached(z, x, y, style=style):
                        return False
        return True

    def get_tile_stats(self, style: str = "voyager") -> Dict[str, Any]:
        """Compute disk storage footprint and zoom level distribution for cached tiles."""
        style_dir = self.cache_dir / style
        if not style_dir.exists():
            return {"tile_count": 0, "total_bytes": 0, "zoom_levels": []}

        tile_count = 0
        total_bytes = 0
        zoom_levels = set()

        for p in style_dir.glob("*/*/*.png"):
            if p.is_file():
                tile_count += 1
                total_bytes += p.stat().st_size
                try:
                    zoom_levels.add(int(p.parent.parent.name))
                except Exception:
                    pass

        return {
            "tile_count": tile_count,
            "total_bytes": total_bytes,
            "zoom_levels": sorted(list(zoom_levels)),
            "cache_dir": str(style_dir),
        }

    def get_local_url_template(
        self,
        relative_to: Optional[Path] = None,
        style: str = "voyager",
    ) -> str:
        """Return the URL template string suitable for Leaflet L.tileLayer.

        If relative_to is provided (e.g. output directory), computes relative path.
        """
        target_dir = self.cache_dir / style
        if relative_to:
            try:
                rel = os.path.relpath(target_dir, relative_to).replace("\\", "/")
                return f"{rel}/{{z}}/{{x}}/{{y}}.png"
            except Exception:
                pass
        return f"{target_dir.as_posix()}/{{z}}/{{x}}/{{y}}.png"
