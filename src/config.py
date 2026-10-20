"""Configuration settings for OpenStreetMap Pedestrian Exploration."""

import os
from pathlib import Path
from typing import Tuple
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"

# Load .env from multiple potential locations (OSMExploration, parent Capstone, adjacent dirs)
load_dotenv(Path.cwd() / ".env")
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR.parent / "GoogleMapsExploration" / ".env")
load_dotenv()

# CARTO API Key for basemap tile authentication
CARTO_API_KEY = os.getenv("CARTO_API_KEY", "").strip()

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

# West Yellowstone, Montana official bounding box (south, west, north, east)
WEST_YELLOWSTONE_BBOX: Tuple[float, float, float, float] = (44.6540, -111.1150, 44.6730, -111.0970)

# Project Prototyping Areas (Bend, OR & West Yellowstone, MT)
PROTOTYPE_AREAS: Dict[str, Tuple[float, float, float, float]] = {
    "bend-corridor": (44.0410, -121.3410, 44.0490, -121.3260),
    "bend-city": BEND_CITY_BBOX,
    "west-yellowstone": WEST_YELLOWSTONE_BBOX,
}

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
        "name": "OSU-Cascades (Tykeson Hall) to Safeway on Century Drive",
        "start": (44.0432484, -121.3342388),  # Tykeson Hall, OSU-Cascades
        "end": (44.0470397, -121.3295531),
        "bbox": (44.0410, -121.3410, 44.0490, -121.3260),
        "fixture": "osu_cascades_safeway_pedestrian.json",
    },
    "west-yellowstone": {
        "name": "West Yellowstone Town Center to Historic Center",
        "start": (44.6625, -111.1040),
        "end": (44.6635, -111.0980),
        "bbox": WEST_YELLOWSTONE_BBOX,
        "fixture": "west_yellowstone_pedestrian.json",
    },
}

# =============================================================================
# Pedestrian Accessibility & Routing Safety Weights (Single Source of Truth)
# =============================================================================
from .routing.safety_weights import (
    DEFAULT_SAFETY_WEIGHTS,
    CrosswalkMultipliers,
    KerbMultipliers,
    RatingThresholds,
    SafetyScoreWeights,
    SafetyWeightsConfig,
    SidewalkMultipliers,
    TurnPenaltyConfig,
)
