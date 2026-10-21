# Pedestrian Accessibility, Safety Weights & Audio Guidance Engine

A comprehensive technical reference for the accessibility-weighted pathfinding, hazard metric scoring, turn quantization, clock-face orientation, and audio guidance generation systems in `OSMExploration`.

---

## 1. System Architecture

The pedestrian routing and guidance pipeline converts raw OpenStreetMap (OSM) spatial geometry into accessible, tactile-aware navigation instructions calibrated for blind and visually impaired pedestrians:

```mermaid
flowchart TD
    subgraph Data ["1. Data Ingestion & Models"]
        osm["OSM Pedestrian Data<br/>(Sidewalks, Crosswalks, Curb Cuts)"] --> parser["OSMParser"]
        parser --> models["Pedestrian Models<br/>(CrosswalkFeature, SidewalkFeature, KerbFeature)"]
    end

    subgraph Weights ["2. Centralized Weights (Single Source of Truth)"]
        sw["safety_weights.py<br/>(DEFAULT_SAFETY_WEIGHTS)"]
        models -.->|delegates hazard metric| sw
    end

    subgraph Routing ["3. Accessibility Pathfinding"]
        models --> graph["PedestrianGraph<br/>(Dijkstra Pathfinding)"]
        sw -->|multipliers & turn penalties| graph
        pref["Routing Preference<br/>(BALANCED vs FEWER_TURNS)"] --> graph
        graph --> route["RouteResult<br/>(Edges, Nodes, Safety Rating)"]
    end

    subgraph Guidance ["4. Audio Guidance Generation"]
        route --> audio["AudioGuidanceGenerator"]
        verb["GuidanceVerbiageConfig<br/>(DEGREES vs CLOCK, SWEEP vs CURVING)"] --> audio
        audio --> inst["Turn-by-Turn Audio Instructions<br/>(15° Quantization / Clock Face / Sweeps)"]
    end
```

---

## 2. Centralized Weights Architecture

All safety weights, routing cost multipliers, hazard penalties, and verbiage templates are centralized in [`src/models/safety_weights.py`](file:///C:/Code/Capstone/OSMExploration/src/models/safety_weights.py) and exposed directly at the top of [`src/models/pedestrian.py`](file:///C:/Code/Capstone/OSMExploration/src/models/pedestrian.py):

```python
from src.models.pedestrian import (
    HAZARD_WEIGHTS,
    SAFETY_WEIGHTS,
    VERBIAGE_CONFIG,
    configure_hazard_weights,
    configure_guidance_verbiage,
)
```

Modifying `HAZARD_WEIGHTS` or using `configure_hazard_weights(...)` propagates immediately across feature models, graph edge weights, and route rating calculations without divergence or circular import issues.

---

## 3. Hazard Metric Scoring Model

The hazard metric evaluates situational crossing danger on a normalized scale from **$0.0$ (Safe / Low Risk)** to **$1.0$ (Severe Hazard)**.

### Mathematical Formulation
$$\text{Hazard} = \max\left(0.0, \min\left(1.0, H_{\text{base}} + \sum P_i - \sum D_j\right)\right)$$

Where $H_{\text{base}} = 0.40$ is the baseline roadway crossing exposure, $P_i$ are situational hazard penalties, and $D_j$ are safety mitigation discounts.

### Hazard Penalties & Mitigation Discounts
| Parameter | Default | Category | Impact & Mobility Rationale |
| :--- | :--- | :--- | :--- |
| `base_crossing_hazard` | `0.40` | Baseline | Initial exposure risk for crossing any roadway |
| `roundabout_penalty` | `0.60` | Penalty | **Extreme hazard**: Free-flowing vehicular traffic continuously enters and exits without traffic signals. Driven to $1.0$ ($> 5\times$ normal intersection). |
| `unmarked_crossing_penalty` | `0.40` | Penalty | **Severe hazard**: Crossing multi-lane roadway without markings or yield control |
| `missing_aps_penalty` | `0.15` | Penalty | Visual signal exists but lacks audible locator chirps or vibrotactile walk phases |
| `multilane_penalty` | `0.15` | Penalty | Crossing $> 2$ vehicular lanes of active traffic |
| `missing_signals_penalty` | `0.10` | Penalty | Intersection lacks visual traffic signals |
| `missing_tactile_penalty` | `0.10` | Penalty | Roadway curb transition lacks truncated dome warning surfaces |
| `missing_refuge_penalty` | `0.10` | Penalty | Multi-lane crossing lacks a protected center median refuge island |
| `aps_discount` | `0.25` | Discount | Accessible Pedestrian Signal provides clear audible and vibrotactile confirmation |
| `signals_discount` | `0.15` | Discount | Visual traffic signals bring vehicular traffic to a stop |
| `marked_discount` | `0.15` | Discount | High-visibility ladder or zebra pavement markings |
| `refuge_discount` | `0.15` | Discount | Center median refuge island splits crossing exposure into two shorter legs |
| `tactile_discount` | `0.10` | Discount | Truncated domes confirm boundary between sidewalk and active road |

### Feature Model Integration
Each feature model exposes a live property delegating to the centralized weights engine:
- `CrosswalkFeature.hazard_metric`: Calculates situational hazard for street crossings.
- `SidewalkFeature.hazard_metric`: Evaluates surface smoothness, unpaved terrain, and longitudinal slope.
- `KerbFeature.hazard_metric`: Evaluates curb transition step-free accessibility and tactile paving.

---

## 4. Routing Multipliers & Roundabout Hazard Modeling

Dijkstra's pathfinding calculates edge weight as:
$$\text{Effective Weight} = \text{Haversine Distance (m)} \times \prod \text{Multipliers}$$

### Crosswalk Routing Multipliers
| Multiplier | Value | Description |
| :--- | :--- | :--- |
| `roundabout_hazard` | **`5.5`** | **$> 5.0\times$ penalty**: Severely penalizes roundabout slip lanes. Based on mentor evaluation, roundabouts lack vehicular stop control and make vehicle acoustic detection extremely difficult for blind pedestrians. |
| `unmarked_crossing` | `4.0` | Severe penalty avoiding unmarked street crossings |
| `aps_signals` | `0.50` | $50\%$ priority discount for crosswalks equipped with audible signals |
| `preferred_corridor` | `0.70` | $30\%$ priority discount for municipal ADA safe corridors |
| `standard_signals` | `0.75` | $25\%$ discount for traffic signals stopping vehicular traffic |
| `refuge_island` | `0.80` | $20\%$ discount for mid-crossing refuge protection |
| `tactile_paving` | `0.85` | $15\%$ discount for curb ramps equipped with truncated domes |
| `marked_crossing` | `0.90` | $10\%$ discount for painted zebra/ladder crosswalks |

---

## 5. Navigation Preference: "Fewer Turns" Mode

Blind pedestrians expend significant mental effort aligning headings, scanning shorelines with a white cane, and processing spoken auditory prompts. Navigating winding paths with numerous gentle curves causes **cognitive fatigue** and **information overload**.

To address this, pathfinding supports the `FEWER_TURNS` routing preference:

```python
from src.routing.pedestrian_graph import PedestrianGraph, RoutingPreference

route = graph.route(start_node, end_node, preference=RoutingPreference.FEWER_TURNS)
```

### Turn Penalty Mechanics in Dijkstra Search
1. **Balanced Mode (`RoutingPreference.BALANCED`)**:
   - Turn cost is proportional to angle: $\text{Cost} = \text{base\_turn\_penalty} \times \left(\frac{\Delta\theta}{90^\circ}\right)$.
   - Focuses primarily on physical safety and shortest accessible path.
2. **Fewer-Turns Mode (`RoutingPreference.FEWER_TURNS`)**:
   - **Fixed Turn Penalty**: Adds a **$25.0\text{ m}$ fixed virtual penalty** for every turn $\ge 15^\circ$.
   - **Amplified Turn Multiplier**: Multiplies turn angle cost by **$3.0\times$**.
   - **Curve Fatigue Penalty**: Adds a **$15.0\text{ m}$ virtual penalty** for curving micro-segments and consecutive heading shifts.
3. **Behavioral Outcome**:
   - A straight route with **one sharp $90^\circ$ turn** is chosen over a meandering route with $4$ gentle $20^\circ$ curves, even if the winding route is physically $8\text{ meters}$ shorter.

---

## 6. Direction Announcements: 15° Quantization & Clock Face Mode

### 15-Degree Quantization
In accordance with orientation & mobility research, turn announcements in degrees are never spoken with artificial precision (such as *"Turn 73 degrees left"*). All angles are quantized strictly to the nearest **$15^\circ$ increment**:

$$\text{Quantized Angle} = \left\lfloor \frac{|\Delta\theta|}{15} + 0.5 \right\rfloor \times 15$$

Possible announced angles: $15^\circ, 30^\circ, 45^\circ, 60^\circ, 75^\circ, 90^\circ, 105^\circ, 120^\circ, 135^\circ, 150^\circ, 165^\circ, 180^\circ$.

### Clock Directions Mode
Users can configure the engine to output clock face directions instead of degree bearings:
- **12 o'clock**: Straight ahead ($0^\circ$)
- **1 o'clock**: $+30^\circ$ right
- **2 o'clock**: $+60^\circ$ right
- **3 o'clock**: $+90^\circ$ right
- **6 o'clock**: $180^\circ$ reverse / turnaround
- **9 o'clock**: $-90^\circ$ left
- **10 o'clock**: $-60^\circ$ left
- **11 o'clock**: $-30^\circ$ left

#### Half-Hourly Granularity
Because $15^\circ$ equals exactly 30 minutes on a 12-hour clock face ($360^\circ / 24\text{ half-hours} = 15^\circ/\text{step}$), the engine supports half-hour precision:
- $+15^\circ \to$ **12:30**
- $+45^\circ \to$ **1:30**
- $-15^\circ \to$ **11:30**
- $-45^\circ \to$ **10:30**

### Switching Direction Mode
```python
from src.models.pedestrian import DirectionMode, ClockGranularity, configure_guidance_verbiage

# Activate standard hourly clock directions:
configure_guidance_verbiage(
    direction_mode=DirectionMode.CLOCK,
    clock_granularity=ClockGranularity.HOURLY,
)

# Output: "Turn to 9 o'clock, then follow Century Sidewalk for 110 meters."
```

---

## 7. Curve Announcements: "Sweep Left" & "Sweep Right"

Consecutive short sidewalk micro-edges turning in the same direction are batched into a single arc step to eliminate redundant instructions.

### Curve Verbiage Presets
1. **`CurveVerbiagePreset.SWEEP` (Default)**:
   - Spoken: *"Sweep right for 14 meters."* / *"Sweep left for 19 meters."*
2. **`CurveVerbiagePreset.CURVING`**:
   - Spoken: *"Follow the curving sidewalk to the right for 14 meters."*
3. **`CurveVerbiagePreset.BEAR`**:
   - Spoken: *"Bear right for 14 meters."*
4. **`CurveVerbiagePreset.CUSTOM`**:
   - Accepts any template string supporting `{direction}`, `{distance}`, and `{name}`:
   ```python
   configure_guidance_verbiage(
       curve_preset=CurveVerbiagePreset.CUSTOM,
       curve_template="Sidewalk curves gently to the {direction} along {name} for {distance:.0f} meters.",
   )
   ```

---

## 8. Code Examples & Usage

### Example 1: Route with "Fewer Turns" and Clock Guidance
```python
from src.parser.osm_parser import OSMParser
from src.routing.pedestrian_graph import PedestrianGraph, RoutingPreference
from src.routing.guidance import AudioGuidanceGenerator
from src.models.pedestrian import DirectionMode, configure_guidance_verbiage

# 1. Parse network and build graph
network = OSMParser().parse(osm_raw_data)
graph = PedestrianGraph(network)

# 2. Select FEWER_TURNS routing preference
route = graph.route(start_node, end_node, preference=RoutingPreference.FEWER_TURNS)

# 3. Configure clock directions
configure_guidance_verbiage(direction_mode=DirectionMode.CLOCK)

# 4. Generate audio instructions
generator = AudioGuidanceGenerator(network)
instructions = generator.generate_instructions(route)

for step in instructions:
    print(f"[{step['action']}] {step['spoken_instruction']}")
```

### Example 2: Adjusting Roundabout Hazard in One Place
```python
from src.models.pedestrian import configure_hazard_weights, HAZARD_WEIGHTS

# Adjust roundabout penalty to 0.75 for extra conservative navigation
configure_hazard_weights(roundabout_penalty=0.75)
assert HAZARD_WEIGHTS.roundabout_penalty == 0.75
```
