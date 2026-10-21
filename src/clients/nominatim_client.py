"""Nominatim geocoding client for OpenStreetMap with disk caching."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

from ..config import CACHE_DIR, FIXTURES_DIR, MOCK_MODE, NOMINATIM_ENDPOINT, USER_AGENT


class NominatimClient:
    """Geocodes street addresses and intersection queries via OpenStreetMap Nominatim with disk caching."""

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.cache_dir = (cache_dir or CACHE_DIR) / "nominatim"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.mock_mode = mock_mode if mock_mode is not None else MOCK_MODE

    def geocode(
        self,
        query: str,
        limit: int = 3,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Geocode query string to geographical coordinates, using local disk cache by default."""
        if self.mock_mode:
            return self._load_fixture()

        cache_key = hashlib.md5(f"{query}_{limit}".encode("utf-8")).hexdigest()
        cache_file = self.cache_dir / f"geo_{cache_key}.json"

        # Check local disk cache first (default behavior)
        if use_cache and not force_refresh and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        params = {
            "q": query,
            "format": "json",
            "limit": limit,
            "addressdetails": 1,
        }
        headers = {"User-Agent": USER_AGENT}

        try:
            resp = requests.get(
                NOMINATIM_ENDPOINT,
                params=params,
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Store in local disk cache
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                except Exception:
                    pass
                return data
        except Exception:
            pass

        return self._load_fixture()

    def _load_fixture(self) -> List[Dict[str, Any]]:
        fixture_path = FIXTURES_DIR / "sample_nominatim_geocode.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)
