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
    # Archetype Prototype Presets (Short, isolated corridor evaluation)
    "century-chandler": {
        "name": "Roundabout Prototype: SW Century Dr & SW Chandler Ave",
        "start": (44.0416473, -121.3317034),
        "end": (44.0418175, -121.3317061),
        "bbox": (44.0405, -121.3340, 44.0430, -121.3305),
        "fixture": "prototype_century_chandler.json",
        "archetype": "roundabout",
    },
    "3rd-revere": {
        "name": "4-Way Stop/Signal Prototype: NE 3rd St & NE Revere Ave",
        "start": (44.06775, -121.30275),
        "end": (44.06765, -121.30225),
        "bbox": (44.0665, -121.3040, 44.0690, -121.3010),
        "fixture": "prototype_3rd_revere.json",
        "archetype": "4-way",
    },
    "colorado-straight": {
        "name": "Straight Road Prototype: SW Colorado Ave Sidewalk",
        "start": (44.04555, -121.32320),
        "end": (44.04545, -121.32240),
        "bbox": (44.0440, -121.3250, 44.0470, -121.3200),
        "fixture": "prototype_colorado_straight.json",
        "archetype": "straight",
    },
    "columbia-bridge": {
        "name": "Bridge Prototype: SW Columbia St Crossing",
        "start": (44.043624, -121.317574),
        "end": (44.043558, -121.317240),
        "bbox": (44.0425, -121.3190, 44.0445, -121.3160),
        "fixture": "prototype_columbia_bridge.json",
        "archetype": "bridge",
    },
    "hwy20-jamison": {
        "name": "Mid-Block Crosswalk Prototype: Hwy 20 by Jamison St",
        "start": (44.09638, -121.30359),
        "end": (44.09640, -121.30323),
        "bbox": (44.0950, -121.3055, 44.0980, -121.3015),
        "fixture": "prototype_hwy20_jamison.json",
        "archetype": "midblock",
    },
    "powers-hwy97": {
        "name": "Refuge Island Prototype: Powers & Hwy 97",
        "start": (44.02875, -121.31615),
        "end": (44.02865, -121.31570),
        "bbox": (44.0270, -121.3180, 44.0305, -121.3140),
        "fixture": "prototype_powers_hwy97.json",
        "archetype": "refuge_island",
    },
}

# =============================================================================
# Pedestrian Accessibility & Routing Safety Weights (Single Source of Truth)
# =============================================================================
from .routing.safety_weights import (
    DEFAULT_HAZARD_WEIGHTS,
    DEFAULT_SAFETY_WEIGHTS,
    CrosswalkMultipliers,
    HazardMetricWeights,
    KerbMultipliers,
    RatingThresholds,
    SafetyScoreWeights,
    SafetyWeightsConfig,
    SidewalkMultipliers,
    TurnPenaltyConfig,
)
from .models.pedestrian import (
    HAZARD_WEIGHTS,
    configure_hazard_weights,
    get_hazard_weights,
    set_hazard_weights,
)
