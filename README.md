# OpenStreetMap (OSM) Pedestrian Accessibility & Navigation Engine

A specialized Python engine built on **OpenStreetMap (OSM)** and the **OpenSidewalks schema** to power accessible, tactile-aware, and auditory navigation for blind and visually impaired pedestrians crossing sidewalks and intersections.

---

## Why OpenStreetMap Over Google Maps?

In our earlier empirical exploration ([`../GoogleMapsExploration/`](../GoogleMapsExploration)), Google Maps Platform scored **2.5%** for blind pedestrian crossing suitability because it routes pedestrians along vehicle road centerlines and provides zero semantic attributes for crosswalks, curb ramps, or audio signals.

In contrast, **OpenStreetMap provides dedicated, community-standardized micro-pedestrian tagging**:
- **Accessible Pedestrian Signals (APS)**: `traffic_signals:sound=yes`, `traffic_signals:vibration=yes`
- **Tactile Warning Surfaces**: `tactile_paving=yes`, `kerb:tactile_paving=yes`
- **Curb Ramp Transition**: `kerb=lowered`, `kerb=flush`, `kerb=raised`
- **Crosswalk Markings**: `highway=crossing`, `crossing=marked`, `crossing:markings=zebra`
- **Sidewalks**: `highway=footway`, `footway=sidewalk`, `width=*`, `surface=*`

---

## Architecture & Capabilities

```mermaid
flowchart TD
    subgraph Ingestion ["1. Data & Parsing"]
        api["Overpass API / Offline Cache"] --> parser["OSMParser"]
        parser --> models["Pedestrian Feature Models"]
    end

    subgraph Weights ["2. Centralized Weights & Controls"]
        models --> weights["SafetyWeightsConfig (Single Source of Truth)"]
        weights --> hazard["Hazard Metric (0.0 to 1.0)"]
        weights --> rab["> 5x Roundabout Hazard Multiplier (5.5x)"]
    end

    subgraph Routing ["3. Accessibility Pathfinding"]
        weights --> graph["PedestrianGraph"]
        pref["Routing Preference (BALANCED vs FEWER_TURNS)"] --> graph
        graph --> route["Accessible Dijkstra Router"]
    end

    subgraph Guidance ["4. Spoken Audio Guidance"]
        route --> audio["AudioGuidanceGenerator"]
        audio --> quant["15° Turn Quantization & Clock Face Mode"]
        audio --> sweep["Curving Arc Batching ('Sweep Left / Right')"]
    end
```

---

## Technical Documentation Guides

For in-depth architecture, mathematical specifications, and code recipes:
- 📖 [**Safety Weights, Hazard Metric & Guidance Guide**](docs/SAFETY_AND_ROUTING_GUIDE.md): Mathematical formulations, 15° quantization, clock face directions, sweeping curves, fewer-turns pathfinding, and >5x roundabout risk modeling.
- 💾 [**Universal Offline Caching Guide**](docs/OFFLINE_CACHING_GUIDE.md): Architecture for default persistent disk caching across Nominatim, Overpass, Carto basemap tiles, and Google Maps clients.

---

## Key Capabilities

1. **Centralized Accessibility & Hazard Weights**:
   - Single source of truth in [`src/models/safety_weights.py`](src/models/safety_weights.py) directly exposed at the top of [`src/models/pedestrian.py`](src/models/pedestrian.py).
   - Adjust `HAZARD_WEIGHTS` or `SAFETY_WEIGHTS` dynamically; all calculations and pathfinding costs update system-wide immediately.
2. **Audio Guidance with Strict 15° Quantization & Clock Face Directions**:
   - Spoken turns in degrees are strictly quantized to the nearest 15° increment ($15^\circ, 30^\circ, 45^\circ, \dots, 180^\circ$).
   - User-configurable **Clock Face Mode** (e.g. *"Turn to 9 o'clock"* or *"Turn to 1:30"*) based on Orientation & Mobility standards.
3. **Curving Arc Batching & Sweeping Verbiage**:
   - Consecutive curving segments batch into unified sweeping instructions: *"Sweep right for 14 meters."*
   - Configurable templates and presets (`CurveVerbiagePreset.SWEEP`, `CURVING`, `BEAR`, `CUSTOM`).
4. **Fewer-Turns Navigation Preference (`RoutingPreference.FEWER_TURNS`)**:
   - Incorporates fixed turn penalties and curve costs into Dijkstra pathfinding to minimize cognitive fatigue and guidance interruptions, preferencing 1 sharp turn over navigating winding curves.
5. **Roundabout Hazard Escalation (> 5x Normal Crossing)**:
   - Roundabout crosswalks incur a $5.5\times$ routing multiplier and an extreme risk penalty ($1.00$ hazard score) reflecting the danger of uncontrolled entering traffic.
6. **Default Persistent Disk Caching**:
   - All network calls (Nominatim geocoding, Overpass queries, Carto basemap tiles) automatically cache to disk by default.

---

## Quickstart

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- No API key required! OpenStreetMap APIs are completely open and free.

### Installation
```bash
cd OSMExploration
pip install -r requirements.txt
```

---

## CLI Usage

### 1. Compute Accessible Route & Audio Guidance (Primary Feature)
Finds the safest accessible route between two points and generates turn-by-turn spoken instructions:
```bash
# Default intersection demo
python main.py route

# OSU-Cascades to Safeway on Century Drive (Real-World Campus Corridor)
python main.py route --preset osu-to-safeway --export-geojson osu_to_safeway_route.geojson
```
**Example Screen-Reader Output**:
```text
Step 1 [WALK_SIDEWALK]
  Speaker: "Follow sidewalk for 164 meters."

Step 2 [WALK_SIDEWALK]
  Speaker: "Turn 60 degrees left, then follow sidewalk for 10 meters."
  [Heading shift: 60° left, Clock direction: 10 o'clock]

Step 3 [WALK_SIDEWALK]
  Speaker: "Sweep right for 14 meters."
  [Curving micro-arc batched into sweeping instruction]

Step 4 [APPROACH_CURB]
  Speaker: "Approach curb edge to cross SW Donovan Avenue: Step down lowered curb ramp with tactile truncated domes."
  [Haptic/Tactile Cue: Vibrates cane/wearable upon approaching truncated domes]

Step 5 [CROSS_STREET]
  Speaker: "Cross SW Donovan Avenue at midblock crossing (9 meters). Traffic signalized intersection (no audible signal detected, verify traffic sounds)."

Step 6 [EXIT_CURB]
  Speaker: "Step up lowered curb ramp onto tactile paving to complete crossing SW Donovan Avenue."

Step 7 [WALK_SIDEWALK]
  Speaker: "Turn 90 degrees left, then follow sidewalk for 67 meters."
  [Heading shift: 90° left, Clock direction: 9 o'clock]

Step 8 [ARRIVE]
  Speaker: "You have arrived at your destination."
```

### 2. Fetch & Parse Pedestrian Network
Fetches live OSM pedestrian features within a bounding box or across the entire city:
```bash
# Fetch single bounding box (e.g. downtown)
python main.py fetch --south 44.0560 --west -121.3050 --north 44.0600 --east -121.3000

# Fetch FULL CITYWIDE pedestrian network for Bend, OR (using spatial grid tiling)
python main.py fetch --citywide
```

### 3. Benchmark Tag Completeness Against Municipal GIS
Compares OSM pedestrian tagging against the 41,000+ municipal GIS assets in `../MapData/`:
```bash
# Benchmark corridor sample
python main.py coverage

# Full Citywide Benchmark (Compares OSM Citywide vs 6,602 crosswalks, 14,827 curb ramps, 19,989 sidewalks)
python main.py coverage --citywide
```

### 4. Export to GeoJSON
Exports the parsed pedestrian network for visualization in QGIS, Mapbox, or Leaflet:
```bash
# Export corridor network
python main.py export-geojson --output osm_pedestrian_network.geojson

# Export full citywide pedestrian network
python main.py export-geojson --citywide --output bend_citywide_network.geojson
```

### 5. Free Address & Intersection Geocoding
Geocodes addresses or street corners using Nominatim without Google Maps billing (cached on disk automatically):
```bash
python main.py geocode "Franklin Ave and 3rd St, Bend, OR"
```

---

## Running the Automated Test Suite
```bash
python -m pytest tests -v
```
All 69 unit tests run offline in `< 30s` using cached fixtures and spatial mocks.
