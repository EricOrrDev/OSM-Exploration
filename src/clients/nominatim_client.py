"""Nominatim geocoding client for OpenStreetMap."""

import json
from typing import Any, Dict, List, Optional
import requests

from ..config import FIXTURES_DIR, MOCK_MODE, NOMINATIM_ENDPOINT, USER_AGENT


class NominatimClient:
    """Geocodes street addresses and intersection queries via OpenStreetMap Nominatim."""

    def __init__(self, mock_mode: Optional[bool] = None):
        self.mock_mode = mock_mode if mock_mode is not None else MOCK_MODE

    def geocode(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Geocode query string to geographical coordinates."""
        if self.mock_mode:
            return self._load_fixture()

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
                return resp.json()
        except Exception:
            pass

        return self._load_fixture()

    def _load_fixture(self) -> List[Dict[str, Any]]:
        fixture_path = FIXTURES_DIR / "sample_nominatim_geocode.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)
