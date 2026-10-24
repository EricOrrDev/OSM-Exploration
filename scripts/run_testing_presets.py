"""Testing Presets Suite: Batch runner and benchmark catalog for all archetype corridors.

Runs all 7 primary testing presets (Roundabout, 4-Way Stop, Straight Sidewalk, Bridge,
Mid-Block Crosswalk, Refuge Island, and Campus Corridor), saves their interactive HTML
stepper maps to output/, prints a formatted terminal comparison table, and generates an
interactive test hub catalog (output/test_presets_hub.html).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import webbrowser

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure RouteVisualizer is in sys.path
RV_PATH = PROJECT_ROOT.parent / "RouteVisualizer" / "src"
if RV_PATH.is_dir() and str(RV_PATH) not in sys.path:
    sys.path.insert(0, str(RV_PATH))

from src.config import CARTO_API_KEY, PRESETS
from src.clients.overpass_client import OverpassClient
from src.parser.osm_parser import OSMParser
from src.routing.pedestrian_graph import PedestrianGraph, RoutingPreference
from src.routing.guidance import AudioGuidanceGenerator
from src.export.geojson_exporter import GeoJSONExporter

# The 7 primary testing presets covering all prototype archetypes & corridor
TESTING_PRESET_KEYS = [
    "century-chandler",   # Roundabout
    "3rd-revere",         # 4-Way Signalized / Stop
    "colorado-straight",  # Straight Sidewalk Corridor
    "columbia-bridge",    # Bridge Crossing
    "hwy20-jamison",      # Mid-Block Crosswalk
    "powers-hwy97",       # Refuge Island Crossing
    "osu-to-safeway",     # Full Campus to Grocery Corridor
]


def run_testing_presets(
    output_dir: Optional[Path] = None,
    offline: bool = True,
    open_browser: bool = False,
    preference: RoutingPreference = RoutingPreference.BALANCED,
) -> List[Dict[str, Any]]:
    """Execute all testing presets in batch and generate artifacts."""
    if output_dir is None:
        # Default to root Capstone/output or NavigationEngine/output
        root_output = PROJECT_ROOT.parent / "output"
        output_dir = root_output if root_output.parent.is_dir() else (PROJECT_ROOT / "output")

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = OverpassClient()
    parser = OSMParser()
    results: List[Dict[str, Any]] = []

    print("\n" + "=" * 110)
    print("RUNNING ALL ACCESSIBLE NAVIGATION TESTING PRESETS (7 ARCHETYPES)")
    print(f"Output Directory: {output_dir}")
    print(f"Routing Preference: {preference.value.upper()}")
    print("=" * 110)

    for key in TESTING_PRESET_KEYS:
        if key not in PRESETS:
            continue
        cfg = PRESETS[key]
        name = cfg.get("name", key)
        archetype = cfg.get("archetype", "corridor")
        t0 = time.perf_counter()

        try:
            # 1. Fetch / Load fixture
            raw_data = client.fetch_pedestrian_data(
                bbox=cfg["bbox"],
                fixture_name=cfg.get("fixture"),
                offline=offline,
            )

            # 2. Parse Network
            network = parser.parse(raw_data)

            # 3. Construct Graph
            graph = PedestrianGraph(network)
            start_node = graph.find_nearest_node(cfg["start"])
            end_node = graph.find_nearest_node(cfg["end"])

            # 4. Compute Route
            route = graph.route(start_node, end_node, preference=preference)
            if not route:
                raise ValueError("Graph router could not find a path between endpoints.")

            # 5. Generate Audio Guidance
            guidance = AudioGuidanceGenerator(network)
            instructions = guidance.generate_instructions(route)

            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            # 6. Check for detected anomalies
            anomalies = [inst for inst in instructions if inst.get("data_anomaly")]

            # 7. Export Artifacts
            html_filename = f"{key}_map.html"
            geojson_filename = f"{key}_route.geojson"
            gpkg_filename = f"{key}_route.gpkg"

            html_path = output_dir / html_filename
            geojson_path = output_dir / geojson_filename
            gpkg_path = output_dir / gpkg_filename

            GeoJSONExporter.export_route_to_geojson(route, network, instructions, geojson_path)
            GeoJSONExporter.export_interactive_html(
                route=route,
                network=network,
                instructions=instructions,
                output_path=html_path,
                title=f"{name} ({archetype.replace('_', ' ').title()})",
                carto_api_key=CARTO_API_KEY,
            )
            GeoJSONExporter.export_route_to_gpkg(route, network, instructions, gpkg_path)

            record = {
                "key": key,
                "name": name,
                "archetype": archetype,
                "distance_m": route.total_distance_m,
                "effective_cost": route.total_effective_cost,
                "safety_rating": route.accessibility_rating,
                "num_steps": len(instructions),
                "num_anomalies": len(anomalies),
                "latency_ms": elapsed_ms,
                "html_file": html_filename,
                "html_path": str(html_path),
                "status": "SUCCESS",
            }
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            record = {
                "key": key,
                "name": name,
                "archetype": archetype,
                "distance_m": 0.0,
                "effective_cost": 0.0,
                "safety_rating": "N/A",
                "num_steps": 0,
                "num_anomalies": 0,
                "latency_ms": elapsed_ms,
                "html_file": "",
                "html_path": "",
                "status": f"FAILED: {e}",
            }

        results.append(record)

    # Print Terminal Summary Table
    _print_terminal_table(results)

    # Generate HTML Hub Catalog
    hub_path = output_dir / "test_presets_hub.html"
    _generate_hub_html(results, hub_path)
    print(f"\n[Generated Testing Hub Catalog] -> {hub_path}")

    if open_browser and hub_path.is_file():
        webbrowser.open(hub_path.as_uri())

    return results


def _print_terminal_table(results: List[Dict[str, Any]]) -> None:
    """Print clean ASCII comparison table for the presets."""
    header = f"{'Preset Key':<19} {'Archetype':<15} {'Distance':<10} {'Eff. Cost':<11} {'Rating':<18} {'Steps':<7} {'Anomalies':<11} {'Latency':<9} {'Status'}"
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        dist_str = f"{r['distance_m']:.1f} m" if r["status"] == "SUCCESS" else "-"
        cost_str = f"{r['effective_cost']:.1f}" if r["status"] == "SUCCESS" else "-"
        # Shorten rating label for compact display
        rating_short = r["safety_rating"].split("(")[0].strip() if r["status"] == "SUCCESS" else "-"
        steps_str = str(r["num_steps"]) if r["status"] == "SUCCESS" else "-"
        anom_str = str(r["num_anomalies"]) if r["num_anomalies"] > 0 else "None"
        lat_str = f"{r['latency_ms']:.1f} ms"

        print(
            f"{r['key']:<19} {r['archetype'].replace('_', ' ').title():<15} {dist_str:<10} {cost_str:<11} "
            f"{rating_short:<18} {steps_str:<7} {anom_str:<11} {lat_str:<9} {r['status']}"
        )
    print("-" * len(header))


def _generate_hub_html(results: List[Dict[str, Any]], hub_path: Path) -> None:
    """Build high-contrast interactive HTML testing hub catalog linking all maps."""
    cards_html = []
    for r in results:
        status_color = "#10b981" if r["status"] == "SUCCESS" else "#ef4444"
        rating_color = "#38bdf8"
        if "caution" in r["safety_rating"].lower():
            rating_color = "#f87171"
        elif "moderate" in r["safety_rating"].lower():
            rating_color = "#fbbf24"

        anom_badge = (
            f'<span class="badge badge-warning">⚠️ {r["num_anomalies"]} Anomaly Flagged</span>'
            if r["num_anomalies"] > 0
            else '<span class="badge badge-neutral">✓ Clean Conflation</span>'
        )

        card = f"""
        <div class="preset-card">
          <div class="preset-header">
            <div>
              <span class="archetype-badge">{r['archetype'].replace('_', ' ').upper()}</span>
              <h3 class="preset-title">{r['name']}</h3>
            </div>
            <span class="status-indicator" style="background:{status_color};"></span>
          </div>
          <div class="preset-stats">
            <div class="stat-item">
              <span class="stat-label">Physical Distance</span>
              <span class="stat-val">{r['distance_m']:.1f} m</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Effective Safety Cost</span>
              <span class="stat-val">{r['effective_cost']:.1f}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Guidance Steps</span>
              <span class="stat-val">{r['num_steps']} cues</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Pipeline Latency</span>
              <span class="stat-val">{r['latency_ms']:.1f} ms</span>
            </div>
          </div>
          <div class="preset-rating" style="color:{rating_color};">
            🛡️ <strong>{r['safety_rating']}</strong>
          </div>
          <div class="preset-footer">
            {anom_badge}
            <a href="{r['html_file']}" target="_blank" class="launch-btn">🚀 Open Stepper Map & Audio ▶</a>
          </div>
        </div>
        """
        cards_html.append(card)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Accessible Navigation - Testing Presets Hub</title>
  <style>
    body {{
      margin: 0;
      padding: 32px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #090d16;
      color: #f8fafc;
    }}
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    header {{
      margin-bottom: 28px;
      padding-bottom: 20px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.12);
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 16px;
    }}
    h1 {{
      margin: 0 0 8px 0;
      font-size: 28px;
      color: #38bdf8;
      letter-spacing: -0.5px;
    }}
    .subtitle {{
      color: #94a3b8;
      margin: 0;
      font-size: 15px;
    }}
    .meta-tag {{
      background: rgba(255, 255, 255, 0.08);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 13px;
      color: #cbd5e1;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 20px;
    }}
    .preset-card {{
      background: #0f172a;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 14px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      transition: transform 0.2s, border-color 0.2s;
    }}
    .preset-card:hover {{
      transform: translateY(-2px);
      border-color: #38bdf8;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.5);
    }}
    .preset-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
    }}
    .archetype-badge {{
      display: inline-block;
      background: #0369a1;
      color: #ffffff;
      font-size: 11px;
      font-weight: 800;
      padding: 3px 8px;
      border-radius: 6px;
      margin-bottom: 6px;
    }}
    .preset-title {{
      margin: 0;
      font-size: 17px;
      font-weight: 700;
      line-height: 1.35;
      color: #ffffff;
    }}
    .status-indicator {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
      box-shadow: 0 0 8px currentColor;
      flex-shrink: 0;
      margin-top: 4px;
    }}
    .preset-stats {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      background: rgba(255, 255, 255, 0.03);
      padding: 12px;
      border-radius: 10px;
      border: 1px solid rgba(255, 255, 255, 0.05);
    }}
    .stat-item {{
      display: flex;
      flex-direction: column;
      gap: 2px;
    }}
    .stat-label {{
      font-size: 11px;
      color: #94a3b8;
      text-transform: uppercase;
      font-weight: 600;
    }}
    .stat-val {{
      font-size: 14px;
      font-weight: 700;
      color: #f1f5f9;
    }}
    .preset-rating {{
      font-size: 13px;
    }}
    .preset-footer {{
      margin-top: auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      padding-top: 10px;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .badge {{
      font-size: 12px;
      font-weight: 600;
      padding: 4px 8px;
      border-radius: 6px;
    }}
    .badge-warning {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.4); }}
    .badge-neutral {{ background: rgba(16, 185, 129, 0.15); color: #6ee7b7; }}
    .launch-btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #0284c7;
      color: #ffffff;
      text-decoration: none;
      font-size: 12px;
      font-weight: 700;
      padding: 8px 12px;
      border-radius: 8px;
      transition: background 0.15s;
    }}
    .launch-btn:hover {{
      background: #0369a1;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Accessible Navigation — Testing Presets Hub</h1>
        <p class="subtitle">Benchmark testbed across prototype archetypes & corridors</p>
      </div>
      <div class="meta-tag">Generated: {now_str}</div>
    </header>

    <div class="grid">
      {''.join(cards_html)}
    </div>
  </div>
</body>
</html>"""

    hub_path.write_text(html_content, encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run all navigation testing presets in batch.")
    parser.add_argument("--open", action="store_true", help="Open testing hub catalog in browser.")
    parser.add_argument("--offline", action="store_true", default=True, help="Use cached offline fixtures.")
    parser.add_argument(
        "--preference",
        choices=["balanced", "fewer_turns", "shortest"],
        default="balanced",
        help="Routing preference mode.",
    )
    args = parser.parse_args()
    pref_enum = RoutingPreference(args.preference)
    run_testing_presets(open_browser=args.open, offline=args.offline, preference=pref_enum)
