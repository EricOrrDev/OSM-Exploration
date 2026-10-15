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

```
[ Overpass API / Offline Fixture ]
               │
               ▼
      [ OpenSidewalks Parser ]  ──> Extracts Crosswalks, Curb Cuts, Sidewalks, Signals
               │
               ▼
    [ Pedestrian Network Graph ]
               │
               ▼
 [ Blind Safety Cost Function ]  ──> 50% discount for APS signals; 400% penalty for unmarked crossings
               │
               ▼
[ Accessible Dijkstra Router ]  ──> Finds safest accessible corridor (not just shortest vehicle path)
               │
               ▼
  [ Screen-Reader Audio Guidance ]  ──> Generates tactile announcements and auditory crossing alerts
```

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
  Speaker: "Follow concrete NW 3rd St Sidewalk (2.0m wide) with tactile guidance for 56 meters."
  [Haptic/Tactile Cue: Vibrates cane/wearable upon approaching truncated domes]

Step 2 [APPROACH_CURB]
  Speaker: "Approach curb edge: Step down lowered curb ramp with tactile truncated domes."
  [Haptic/Tactile Cue: Vibrates cane/wearable upon approaching truncated domes]

Step 3 [CROSS_STREET]
  Speaker: "Cross NE Franklin Ave APS Crossing (zebra pattern) for 32 meters. Accessible Pedestrian Signal active with audible locator tone. Pedestrian refuge island present in median."
  [Auditory Cue: Plays 1000 Hz pedestrian locator beep / chirp]

Step 4 [EXIT_CURB]
  Speaker: "Step up lowered curb ramp onto tactile paving to exit roadway."
  [Haptic/Tactile Cue: Vibrates cane/wearable upon approaching truncated domes]

Step 5 [WALK_SIDEWALK]
  Speaker: "Follow concrete East Corridor Sidewalk (1.8m wide) for 44 meters."

Step 6 [ARRIVE]
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
Geocodes addresses or street corners using Nominatim without Google Maps billing:
```bash
python main.py geocode "Franklin Ave and 3rd St, Bend, OR"
```

---

## Running the Automated Test Suite
```bash
python -m pytest tests -v
```
All unit tests run offline in `< 0.2s` using verified fixtures.
