"""Overpass API client for querying OpenStreetMap pedestrian networks."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import requests

from ..config import (
    CACHE_DIR,
    FIXTURES_DIR,
    MOCK_MODE,
    OVERPASS_ENDPOINT,
    OVERPASS_MIRRORS,
    USER_AGENT,
)


class OverpassClient:
    """Queries OpenStreetMap pedestrian data using Overpass QL with disk caching."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.endpoint = endpoint or OVERPASS_ENDPOINT
        base_cache = cache_dir or CACHE_DIR
        self.cache_dir = base_cache if base_cache.name == "overpass" else base_cache / "overpass"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.mock_mode = mock_mode if mock_mode is not None else MOCK_MODE

    def build_pedestrian_query(self, bbox: Tuple[float, float, float, float]) -> str:
        """Construct Overpass QL query for sidewalks, crossings, curb cuts, and traffic signals."""
        south, west, north, east = bbox
        return f"""
        [out:json][timeout:25];
        (
          // Sidewalks, footways, and multi-use pedestrian paths
          way["highway"="footway"]({south},{west},{north},{east});
          way["highway"="path"]({south},{west},{north},{east});
          way["highway"="pedestrian"]({south},{west},{north},{east});
          way["footway"="sidewalk"]({south},{west},{north},{east});

          // Dedicated crossing ways
          way["footway"="crossing"]({south},{west},{north},{east});

          // Crossing nodes and curb ramps
          node["highway"="crossing"]({south},{west},{north},{east});
          node["kerb"]({south},{west},{north},{east});
          node["traffic_signals:sound"]({south},{west},{north},{east});
          node["tactile_paving"]({south},{west},{north},{east});
        );
        out body;
        >;
        out skel qt;
        """

    def fetch_pedestrian_data(
        self,
        bbox: Tuple[float, float, float, float],
        use_cache: bool = True,
        force_refresh: bool = False,
        fixture_name: Optional[str] = None,
        offline: bool = False,
        timeout: int = 6,
    ) -> Dict[str, Any]:
        """Fetch pedestrian features inside bounding box, using disk cache when available."""
        if self.mock_mode or offline:
            return self._load_fixture(fixture_name)

        cache_key = hashlib.md5(f"{bbox}".encode("utf-8")).hexdigest()
        cache_file = self.cache_dir / f"overpass_{cache_key}.json"

        if use_cache and not force_refresh and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        query = self.build_pedestrian_query(bbox)
        headers = {"User-Agent": USER_AGENT}

        # Try primary endpoint, then mirrors with fast timeout
        endpoints = [self.endpoint] + [m for m in OVERPASS_MIRRORS if m != self.endpoint]
        for url in endpoints:
            try:
                resp = requests.post(
                    url,
                    data={"data": query},
                    headers=headers,
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Cache result to disk
                    try:
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(data, f)
                    except Exception:
                        pass
                    return data
            except Exception:
                continue

        # Fallback to curated fixture if network or endpoints fail, caching locally
        fallback_data = self._load_fixture(fixture_name)
        if fallback_data and use_cache:
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(fallback_data, f)
            except Exception:
                pass
        return fallback_data

    @staticmethod
    def generate_grid_tiles(
        bbox: Tuple[float, float, float, float],
        rows: int = 2,
        cols: int = 2,
    ) -> List[Tuple[float, float, float, float]]:
        """Subdivide a large bounding box into a grid of smaller non-overlapping tiles."""
        south, west, north, east = bbox
        lat_step = (north - south) / rows
        lon_step = (east - west) / cols

        tiles = []
        for r in range(rows):
            for c in range(cols):
                tile_s = south + r * lat_step
                tile_n = tile_s + lat_step
                tile_w = west + c * lon_step
                tile_e = tile_w + lon_step
                tiles.append((round(tile_s, 6), round(tile_w, 6), round(tile_n, 6), round(tile_e, 6)))
        return tiles

    def fetch_citywide_pedestrian_data(
        self,
        bbox: Tuple[float, float, float, float],
        rows: int = 2,
        cols: int = 2,
        force_refresh: bool = False,
        cache_file: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Fetch pedestrian infrastructure for an entire city using spatial grid tiling."""
        target_cache = cache_file or (self.cache_dir / "bend_citywide_pedestrian.json")

        if not force_refresh and target_cache.exists():
            try:
                with open(target_cache, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        if self.mock_mode:
            raw = self._load_fixture("osu_cascades_safeway_pedestrian.json")
            dedup = {}
            for el in raw.get("elements", []):
                key = (el.get("type"), el.get("id"))
                if key not in dedup:
                    dedup[key] = el
            return {
                "version": 0.6,
                "generator": "Overpass API (Mock Deduplicated)",
                "elements": list(dedup.values()),
            }

        tiles = self.generate_grid_tiles(bbox, rows=rows, cols=cols)
        print(f"Divided study area into {len(tiles)} grid tiles ({rows}x{cols}) for reliable querying...")

        merged_elements_dict = {}

        import time

        for idx, tile in enumerate(tiles, 1):
            print(f"  Fetching tile {idx}/{len(tiles)}: BBox {tile}...")
            tile_data = self.fetch_pedestrian_data(tile, use_cache=True)
            elements = tile_data.get("elements", [])
            print(f"    -> Received {len(elements)} elements")

            for el in elements:
                key = (el.get("type"), el.get("id"))
                if key not in merged_elements_dict:
                    merged_elements_dict[key] = el

            # Polite pause to prevent server rate limiting
            if idx < len(tiles):
                time.sleep(1.0)

        merged_elements = list(merged_elements_dict.values())
        print(f"[OK] Completed citywide merge: {len(merged_elements)} total unique elements.")

        merged_payload = {
            "version": 0.6,
            "generator": "Overpass API (Citywide Spatial Tiler)",
            "elements": merged_elements,
        }

        # Cache merged payload
        try:
            target_cache.parent.mkdir(parents=True, exist_ok=True)
            with open(target_cache, "w", encoding="utf-8") as f:
                json.dump(merged_payload, f)
            print(f"Saved complete citywide dataset to: {target_cache.resolve()}")
        except Exception as e:
            print(f"Warning: Could not save citywide cache: {e}")

        return merged_payload

    def _load_fixture(self, fixture_name: Optional[str] = None) -> Dict[str, Any]:
        filename = fixture_name or "sample_overpass_pedestrian.json"
        fixture_path = FIXTURES_DIR / filename
        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)
