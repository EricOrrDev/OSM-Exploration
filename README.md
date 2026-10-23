# NavigationEngine

A specialized, modular pedestrian navigation and guidance generation engine for blind and low-vision pedestrians, built on OpenStreetMap (OSM) micro-pedestrian tagging and multi-source municipal GIS conflation.

`NavigationEngine` is part of the Capstone accessibility navigation ecosystem:
- **`NavigationEngine/`**: Core pathfinding, state-space Dijkstra search with turn/curve penalties, audio guidance generation, and multi-source spatial conflation with anomaly detection.
- **[`../RouteVisualizer/`](../RouteVisualizer)**: Dedicated artifact and presentation tool rendering high-contrast interactive Leaflet HTML maps (with the `.nav-hud` stepper, Web Speech API speech synthesis, animated pulsing pedestrian avatar, and polyline tracker) and OGC GeoPackages.
- **[`../IntersectionCategorizer/`](../IntersectionCategorizer)**: GIS intersection topology and curb cut classification service.
- **[`../MapData/`](../MapData)**: Municipal GIS GeoPackages and spatial layers.
- **[`../output/`](../output)**: Centralized output destination for HTML maps, GeoJSON layers, and reports.

---

## Architecture & Subsystems

```mermaid
flowchart TD
    subgraph Data ["1. Data Ingestion & Caching"]
        api["Overpass API / Disk Cache"] --> parser["OSMParser"]
        parser --> models["Pedestrian Feature Models (Crosswalk, Sidewalk, Kerb)"]
    end

    subgraph Weights ["2. Centralized Weights Subsystem (src/weights/)"]
        sw["SafetyWeightsConfig (Single Source of Truth)"]
        sw --> hazard["Hazard Metric Calculator (0.0 to 1.0)"]
        sw --> verb["GuidanceVerbiageConfig (15° Quantization & Clock Modes)"]
        sw --> anom["AnomalyDetectionConfig (Data Conflict Tolerances)"]
    end

    subgraph Spatial ["3. Spatial Conflation & Anomaly Detector (src/spatial/)"]
        gpkg["City of Bend GeoPackages"] --> reg["GPKG Spatial Registry"]
        models --> reg
        reg --> conflict["Conflict & Anomaly Detector<br/>(Flags inconsistent markings/geometry)"]
    end

    subgraph Routing ["4. Accessible Pathfinding (src/routing/)"]
        sw --> graph["PedestrianGraph<br/>(Dijkstra search over directed state (cost, u, p))"]
        conflict -->|penalizes uncertain crossings| graph
        pref["Routing Preference (BALANCED vs FEWER_TURNS)"] --> graph
        graph --> route["RouteResult"]
    end

    subgraph Guidance ["5. Spoken Audio Guidance (src/routing/guidance.py)"]
        route --> audio["AudioGuidanceGenerator"]
        verb --> audio
        conflict -->|adds 'Elevated Caution' cues| audio
        audio --> inst["Turn-by-Turn Spoken Instructions"]
    end

    subgraph Visualizer ["6. Artifact Generation (RouteVisualizer)"]
        route --> viz["RouteVisualizer (RouteMapBuilder)"]
        inst --> viz
        viz --> html["Interactive HTML Map with HUD & TTS"]
        viz --> geojson["Styled GeoJSON"]
        viz --> gpkg_out["OGC GeoPackage (.gpkg)"]
    end
```

---

## Technical Documentation Guides

- 📖 [**Safety Weights, Hazard Metric & Guidance Guide**](docs/SAFETY_AND_ROUTING_GUIDE.md): Mathematical formulations for hazard scoring, 15° quantization, clock face directions, sweeping curves, fewer-turns pathfinding, and >5x roundabout risk modeling.
- 💾 [**Universal Offline Caching Guide**](docs/OFFLINE_CACHING_GUIDE.md): Architecture for default persistent disk caching across Nominatim, Overpass, and Carto basemap raster tiles.

---

## Key Capabilities

1. **Centralized Weights Engine (`src/weights/`)**:
   - Single source of truth for all safety multipliers, hazard metrics, cognitive turn penalties, and verbiage presets.
   - Adjust weights dynamically via `configure_hazard_weights()` or `configure_guidance_verbiage()`.
2. **Multi-Source Conflation & Anomaly Detection**:
   - Rather than assuming any single dataset is infallible "ground truth," `NavigationEngine` compares OSM features with municipal GIS inventories.
   - When sources conflict (e.g., misaligned geometry $> 6\text{ m}$, conflicting crosswalk markings, or uncertain signal hardware), the system flags the segment and injects **elevated caution cues**: *"Proceed with elevated caution: Inconsistent data between map sources for this crossing."*
3. **Orientation & Mobility Audio Guidance**:
   - Spoken angles strictly quantized to the nearest **15° increment** ($15^\circ, 30^\circ, 45^\circ, \dots, 180^\circ$).
   - User-configurable **Clock Face Mode** (e.g. *"Turn to 9 o'clock"* or *"Turn to 1:30"*).
   - Arc batching for gentle curves into sweeping instructions (*"Sweep right for 14 meters"*).
4. **Cognitive Fatigue Reduction (`RoutingPreference.FEWER_TURNS`)**:
   - Incorporates fixed turn penalties ($25\text{ m}$ for turns $\ge 15^\circ$) and curve fatigue costs into Dijkstra pathfinding, preferring 1 sharp turn over meandering winding curves.
5. **Roundabout Hazard Escalation (> 5x Normal Intersection)**:
   - Roundabout crosswalks incur a **$5.5\times$ routing multiplier** and an extreme risk penalty ($1.00$ hazard score) reflecting the danger of uncontrolled entering traffic.
6. **Integration with `RouteVisualizer`**:
   - Renders self-contained, high-contrast Leaflet HTML applications with native Web Speech API Text-to-Speech (TTS), animated pulsing pedestrian avatars, glowing polyline highlights, and keyboard navigation.

---

## CLI Usage

Run from the `NavigationEngine/` directory:

### 1. Compute Accessible Route & Spoken Guidance
```bash
# OSU-Cascades to Safeway on Century Drive (Real-World Campus Corridor)
python main.py route --preset osu-to-safeway

# Specific Prototype Archetype Presets:
python main.py route --preset century-chandler   # Roundabout
python main.py route --preset 3rd-revere         # 4-way signalized intersection
python main.py route --preset colorado-straight  # Straight sidewalk corridor
python main.py route --preset columbia-bridge    # Bridge crossing
python main.py route --preset hwy20-jamison      # Mid-block crosswalk
python main.py route --preset powers-hwy97       # Refuge island crossing
```

### 2. Run Subsystem Performance Benchmarks
```bash
python -m src.benchmark.subsystem_benchmark
```

---

## Running the Automated Test Suite

```bash
python -m pytest tests/ -v
```
All 85 tests run completely offline using cached fixtures and spatial mocks in `< 40s`.
