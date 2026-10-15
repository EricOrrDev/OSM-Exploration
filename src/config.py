"""Configuration settings for OpenStreetMap Pedestrian Exploration."""

import os
from pathlib import Path
from typing import Tuple
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"

# Cache directory for Overpass queries
cache_env = os.getenv("CACHE_DIR", "./cache")
CACHE_DIR = (BASE_DIR / cache_env).resolve()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# MapData directory resolution
env_map_data = os.getenv("MAP_DATA_DIR")
if env_map_data:
    MAP_DATA_DIR = (BASE_DIR / env_map_data).resolve()
else:
    MAP_DATA_DIR = (BASE_DIR.parent / "MapData").resolve()

# Overpass & Nominatim endpoints
OVERPASS_ENDPOINT = os.getenv(
    "OVERPASS_ENDPOINT",
    "https://overpass-api.de/api/interpreter"
)
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "CapstoneBlindAccessibilityExplorer/1.0 (academic-accessibility-research)"

# Mock mode
mock_env = os.getenv("MOCK_MODE", "").lower()
MOCK_MODE = mock_env in ("true", "1", "yes")

# Default study area bounding box (south, west, north, east) around Bend, OR intersection
DEFAULT_BBOX: Tuple[float, float, float, float] = (44.0560, -121.3050, 44.0600, -121.3000)

# Default routing points (NW approach to SE destination)
DEFAULT_START: Tuple[float, float] = (44.05850, -121.30260)  # Node 5
DEFAULT_END: Tuple[float, float] = (44.05710, -121.30220)    # Node 8

# Citywide Bend, Oregon official bounding box (south, west, north, east)
BEND_CITY_BBOX: Tuple[float, float, float, float] = (44.0000, -121.3660, 44.1200, -121.2400)
BEND_CITY_CACHE_FILE = CACHE_DIR / "bend_citywide_pedestrian.json"

# Named routing presets for accessibility evaluation
PRESETS = {
    "default": {
        "name": "NE Franklin & 3rd St Intersection",
        "start": (44.05850, -121.30260),
        "end": (44.05710, -121.30220),
        "bbox": (44.0560, -121.3050, 44.0600, -121.3000),
        "fixture": "sample_overpass_pedestrian.json",
    },
    "osu-to-safeway": {
        "name": "OSU-Cascades to Safeway on Century Drive",
        "start": (44.0444095, -121.3379453),
        "end": (44.0470397, -121.3295531),
        "bbox": (44.0410, -121.3410, 44.0490, -121.3260),
        "fixture": "osu_cascades_safeway_pedestrian.json",
    },
}
