"""CLI entrypoint for OpenStreetMap Pedestrian Accessibility & Routing Engine."""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    BEND_CITY_BBOX,
    BEND_CITY_CACHE_FILE,
    DEFAULT_BBOX,
    DEFAULT_END,
    DEFAULT_START,
    PRESETS,
)
from src.clients.overpass_client import OverpassClient
from src.clients.nominatim_client import NominatimClient
from src.parser.osm_parser import OSMParser
from src.routing.pedestrian_graph import PedestrianGraph
from src.routing.guidance import AudioGuidanceGenerator
from src.benchmark.coverage_analyzer import CoverageAnalyzer
from src.export.geojson_exporter import GeoJSONExporter


def run_fetch(args: argparse.Namespace) -> None:
    """Fetch and parse pedestrian network from OpenStreetMap."""
    client = OverpassClient()
    parser = OSMParser()

    if getattr(args, "citywide", False):
        print("=" * 75)
        print("FETCHING FULL CITYWIDE PEDESTRIAN INFRASTRUCTURE (BEND, OREGON)")
        print(f"Bounding Box: {BEND_CITY_BBOX}")
        print("=" * 75)
        raw = client.fetch_citywide_pedestrian_data(
            bbox=BEND_CITY_BBOX,
            rows=args.rows,
            cols=args.cols,
            force_refresh=args.force_refresh,
        )
    else:
        bbox = (args.south, args.west, args.north, args.east)
        print("=" * 75)
        print(f"FETCHING OPENSTREETMAP PEDESTRIAN INFRASTRUCTURE (BBox: {bbox})")
        print("=" * 75)
        raw = client.fetch_pedestrian_data(bbox)

    network = parser.parse(raw)

    print(f"\n[Parsed Pedestrian Network Summary]")
    print(f"  Total Indexed Nodes:        {len(network.raw_nodes)}")
    print(f"  Sidewalk Segments:          {len(network.sidewalks)}")
    print(f"  Crosswalk Corridors:        {len(network.crosswalks)}")
    print(f"  Curb Ramps (Kerb Nodes):    {len(network.kerbs)}")

    print("\n[Sample Crosswalks with Accessibility Tags]")
    for i, cw in enumerate(list(network.crosswalks.values())[:3], 1):
        print(f"  {i}. ID={cw.id} | Name={cw.name or 'Unnamed'} | Type={cw.crossing_type}")
        print(f"     Markings: {cw.markings} | Traffic Signals: {cw.has_signals}")
        print(f"     Audible Signal (APS): {cw.has_audible_signals} | Vibrotactile: {cw.has_vibrotactile}")
        print(f"     Tactile Warning Domes: {cw.has_tactile_paving} | Refuge Island: {cw.has_refuge_island}")
        print(f"     Blind Pedestrian Safety Score: {cw.safety_score:.2f} / 1.00")

    print("\n[Sample Curb Ramps / Transitions]")
    for i, kb in enumerate(list(network.kerbs.values())[:3], 1):
        print(f"  {i}. ID={kb.id} | Coord={kb.coordinate} | Type={kb.kerb_type}")
        print(f"     Step-free: {kb.is_step_free} | Tactile Paving: {kb.has_tactile_paving}")


def run_route(args: argparse.Namespace) -> None:
    """Compute accessibility-weighted route and screen-reader guidance."""
    print("=" * 75)
    print("COMPUTING BLIND-ACCESSIBLE PEDESTRIAN ROUTE & AUDIO GUIDANCE")
    print("=" * 75)

    preset_name = getattr(args, "preset", None)
    if preset_name and preset_name in PRESETS:
        preset = PRESETS[preset_name]
        print(f"Loading Preset Corridor: {preset['name']}")
        start_pt = preset["start"]
        end_pt = preset["end"]
        bbox = preset["bbox"]
        fixture_name = preset.get("fixture")
    else:
        start_pt = (args.start_lat, args.start_lon)
        end_pt = (args.end_lat, args.end_lon)
        bbox = DEFAULT_BBOX
        fixture_name = None

    client = OverpassClient()
    raw = client.fetch_pedestrian_data(bbox, fixture_name=fixture_name)
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)

    start_node = graph.find_nearest_node(start_pt)
    end_node = graph.find_nearest_node(end_pt)

    if not start_node or not end_node:
        print("[ERROR] Could not find nearest pedestrian network nodes.")
        return

    print(f"\nStart Coord: {start_pt} -> Nearest Node: {start_node}")
    print(f"End Coord:   {end_pt} -> Nearest Node: {end_node}")

    route = graph.route(start_node, end_node)
    if not route:
        print("[ERROR] No connected pedestrian path found between points.")
        return

    print(f"\n[Route Metrics]")
    print(f"  Physical Walking Distance:  {route.total_distance_m} meters (~{(route.total_distance_m / 1000 * 0.621371):.2f} miles)")
    print(f"  Accessibility Cost Score:   {route.total_effective_cost} (Lower = safer route)")
    print(f"  Safety Rating:              {route.accessibility_rating}")
    print(f"  Total Path Nodes Traversed: {len(route.node_path)} nodes")

    # Export route to GeoJSON if requested
    export_path = getattr(args, "export_geojson", None)
    if export_path:
        out_f = Path(export_path)
        GeoJSONExporter.export_route_to_geojson(route, network, out_f)
        print(f"  Exported Route GeoJSON:     {out_f.resolve()}")

    # Generate Audio Guidance
    guidance_gen = AudioGuidanceGenerator(network)
    instructions = guidance_gen.generate_instructions(route)

    print("\n" + "=" * 75)
    print(f"SCREEN-READER AUDIO GUIDANCE ({len(instructions)} INSTRUCTIONS)")
    print("=" * 75)
    for inst in instructions:
        action_badge = f"[{inst['action']}]"
        print(f"\nStep {inst['step']} {action_badge}")
        print(f"  Speaker: \"{inst['spoken_instruction']}\"")
        if inst.get("tactile_cue"):
            print("  [Haptic/Tactile Cue: Vibrates cane/wearable upon approaching truncated domes]")
        if inst.get("has_aps"):
            print("  [Auditory Cue: Plays 1000 Hz pedestrian locator beep / chirp]")
        if inst.get("road_crossed"):
            print(f"  [Crossing Street: {inst['road_crossed']}]")
        if inst.get("intersection_type"):
            print(f"  [Intersection Typology: {inst['intersection_type']} | Corridor: {inst.get('corridor_street', 'unknown')}]")
        if inst.get("relative_button_direction"):
            print(f"  [Signal Push-Button: Located {inst['relative_button_direction']} of traveler]")


def run_coverage(args: argparse.Namespace) -> None:
    """Analyze OSM tag completeness and benchmark against local municipal GIS."""
    client = OverpassClient()
    parser = OSMParser()

    is_citywide = getattr(args, "citywide", False) or BEND_CITY_CACHE_FILE.exists()
    if is_citywide:
        print("=" * 75)
        print("RUNNING CITYWIDE ACCESSIBILITY BENCHMARK (BEND, OREGON)")
        print("Loading full citywide dataset from cache / Overpass...")
        print("=" * 75)
        raw = client.fetch_citywide_pedestrian_data(BEND_CITY_BBOX)
    else:
        raw = client.fetch_pedestrian_data(DEFAULT_BBOX)

    network = parser.parse(raw)
    analyzer = CoverageAnalyzer()
    osm_stats = analyzer.analyze_network_completeness(network)
    muni_stats = analyzer.fetch_municipal_ground_truth()

    print(analyzer.format_coverage_table(osm_stats, muni_stats, is_citywide=is_citywide))


def run_export(args: argparse.Namespace) -> None:
    """Export parsed network and calculated route to GeoJSON."""
    out_path = Path(args.output) if args.output else (PROJECT_ROOT / "osm_pedestrian_network.geojson")
    client = OverpassClient()
    parser = OSMParser()

    is_citywide = getattr(args, "citywide", False)
    if is_citywide:
        raw = client.fetch_citywide_pedestrian_data(BEND_CITY_BBOX)
    else:
        raw = client.fetch_pedestrian_data(DEFAULT_BBOX)

    network = parser.parse(raw)
    GeoJSONExporter.export_network_to_geojson(network, output_path=out_path)
    print(f"\n[OK] Exported {network.total_features} pedestrian features to GeoJSON:")
    print(f"     Path: {out_path.resolve()}")


def run_geocode(args: argparse.Namespace) -> None:
    """Geocode query using free OpenStreetMap Nominatim."""
    client = NominatimClient()
    results = client.geocode(args.query)
    print(f"\nGeocoding Results for: '{args.query}'")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r.get('display_name')}")
        print(f"     Coordinates: ({r.get('lat')}, {r.get('lon')}) | Type: {r.get('type')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenStreetMap Pedestrian Accessibility & Navigation Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Fetch
    fetch_p = subparsers.add_parser("fetch", help="Fetch & parse OSM pedestrian network")
    fetch_p.add_argument("--citywide", action="store_true", help="Download and merge complete pedestrian network for Bend, OR")
    fetch_p.add_argument("--rows", type=int, default=2, help="Grid rows for spatial tiling")
    fetch_p.add_argument("--cols", type=int, default=2, help="Grid cols for spatial tiling")
    fetch_p.add_argument("--force-refresh", action="store_true", help="Force re-download even if city cache exists")
    fetch_p.add_argument("--south", type=float, default=DEFAULT_BBOX[0])
    fetch_p.add_argument("--west", type=float, default=DEFAULT_BBOX[1])
    fetch_p.add_argument("--north", type=float, default=DEFAULT_BBOX[2])
    fetch_p.add_argument("--east", type=float, default=DEFAULT_BBOX[3])

    # Route
    route_p = subparsers.add_parser("route", help="Compute accessible pedestrian path & audio guidance")
    route_p.add_argument("--preset", type=str, choices=list(PRESETS.keys()), default=None, help="Named corridor preset (e.g. osu-to-safeway)")
    route_p.add_argument("--start-lat", type=float, default=DEFAULT_START[0])
    route_p.add_argument("--start-lon", type=float, default=DEFAULT_START[1])
    route_p.add_argument("--end-lat", type=float, default=DEFAULT_END[0])
    route_p.add_argument("--end-lon", type=float, default=DEFAULT_END[1])
    route_p.add_argument("--export-geojson", type=str, default=None, help="Path to export calculated route as GeoJSON")

    # Coverage
    cov_p = subparsers.add_parser("coverage", help="Benchmark OSM tag completeness against municipal GIS")
    cov_p.add_argument("--citywide", action="store_true", help="Run full citywide benchmark for Bend, OR")

    # Export
    export_p = subparsers.add_parser("export-geojson", help="Export pedestrian network to GeoJSON")
    export_p.add_argument("--citywide", action="store_true", help="Export full citywide pedestrian network")
    export_p.add_argument("--output", type=str, default=None)

    # Geocode
    geo_p = subparsers.add_parser("geocode", help="Geocode address using free Nominatim")
    geo_p.add_argument("query", type=str, help="Search query")

    args = parser.parse_args()

    if args.command == "fetch":
        run_fetch(args)
    elif args.command == "route":
        run_route(args)
    elif args.command == "coverage":
        run_coverage(args)
    elif args.command == "export-geojson":
        run_export(args)
    elif args.command == "geocode":
        run_geocode(args)
    else:
        # Default: run route
        run_route(args)


if __name__ == "__main__":
    main()
