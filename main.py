"""CLI entrypoint for NavigationEngine Pedestrian Accessibility & Routing Engine."""

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
    CARTO_API_KEY,
    DEFAULT_BBOX,
    DEFAULT_END,
    DEFAULT_START,
    PRESETS,
    PROTOTYPE_AREAS,
)
from src.clients.overpass_client import OverpassClient
from src.clients.nominatim_client import NominatimClient
from src.clients.carto_tile_cache import CartoTileCache
from src.parser.osm_parser import OSMParser
from src.routing.pedestrian_graph import PedestrianGraph
from src.routing.guidance import AudioGuidanceGenerator
from src.benchmark.coverage_analyzer import CoverageAnalyzer
from src.benchmark.subsystem_benchmark import SubsystemBenchmark
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

    offline_mode = getattr(args, "offline", False)
    client = OverpassClient()
    raw = client.fetch_pedestrian_data(bbox, fixture_name=fixture_name, offline=offline_mode)
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

    # Generate Audio Guidance
    guidance_gen = AudioGuidanceGenerator(network)
    instructions = guidance_gen.generate_instructions(route)

    # Export route map files (GeoJSON, GeoPackage, interactive HTML)
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    file_prefix = preset_name if preset_name else "route"

    geojson_path = getattr(args, "export_geojson", None) or str(out_dir / f"{file_prefix}_route.geojson")
    gpkg_path = getattr(args, "export_gpkg", None) or str(out_dir / f"{file_prefix}_route.gpkg")
    html_path = getattr(args, "export_html", None) or str(out_dir / f"{file_prefix}_map.html")

    GeoJSONExporter.export_route_to_geojson(route, network, instructions, Path(geojson_path))
    GeoJSONExporter.export_route_to_gpkg(route, network, instructions, Path(gpkg_path))
    title = f"Pedestrian Route: {preset['name']}" if preset_name else "Accessible Pedestrian Route"
    carto_key = getattr(args, "carto_key", None) or CARTO_API_KEY

    if getattr(args, "cache_tiles", False):
        print("\nCaching corridor raster basemap tiles locally on-device...")
        tile_cache = CartoTileCache(api_key=carto_key)
        tile_stats = tile_cache.cache_bbox(bbox=bbox, min_zoom=14, max_zoom=17)
        print(f"  [On-Device Cache] {tile_stats['newly_downloaded']} new, {tile_stats['already_cached']} cached ({tile_stats['total_bytes']/1024:.1f} KB)")

    GeoJSONExporter.export_route_to_html(route, network, instructions, Path(html_path), title=title, carto_api_key=carto_key)

    auth_label = "Authenticated via CARTO_API_KEY" if carto_key else "Open Access Mode"
    print(f"\n[Exported Map Layers]")
    print(f"  GeoJSON File:      {Path(geojson_path).resolve()}")
    print(f"  GeoPackage SQLite: {Path(gpkg_path).resolve()}")
    print(f"  Interactive HTML:  {Path(html_path).resolve()} ({auth_label})")

    print("\n" + "=" * 75)
    print(f"SCREEN-READER AUDIO GUIDANCE ({len(instructions)} INSTRUCTIONS)")
    print("=" * 75)
    for inst in instructions:
        action_badge = f"[{inst['action']}]"
        print(f"\nStep {inst['step']} {action_badge}")
        print(f"  Speaker: \"{inst['spoken_instruction']}\"")
        if inst.get("is_curve"):
            print(f"  [Curve Trajectory: {inst.get('turn_direction', 'unknown').capitalize()} arc (~{inst.get('turn_angle_deg', 0)}°)]")
        elif inst.get("turn_direction"):
            print(f"  [Turn Alignment: {inst.get('turn_direction', 'unknown').capitalize()} {inst.get('turn_angle_deg', 0)}°]")
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


def run_benchmark(args: argparse.Namespace) -> None:
    """Benchmark and validate subsystem latencies against allowable performance budgets."""
    preset = getattr(args, "preset", "osu-to-safeway")
    bench = SubsystemBenchmark()
    results = bench.run_benchmark(preset_name=preset)
    all_passed = bench.print_summary(results)
    if not all_passed:
        sys.exit(1)


def run_geocode(args: argparse.Namespace) -> None:
    """Geocode query using free OpenStreetMap Nominatim."""
    client = NominatimClient()
    results = client.geocode(args.query)
    print(f"\nGeocoding Results for: '{args.query}'")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r.get('display_name')}")
        print(f"     Coordinates: ({r.get('lat')}, {r.get('lon')}) | Type: {r.get('type')}")


def run_cache_tiles(args: argparse.Namespace) -> None:
    """Pre-fetch and cache CARTO raster basemap tiles locally on-device."""
    print("=" * 75)
    print("CARTO BASEMAP ON-DEVICE TILE CACHING ENGINE")
    print("=" * 75)

    if getattr(args, "area", None) and args.area in PROTOTYPE_AREAS:
        bbox = PROTOTYPE_AREAS[args.area]
        area_name = args.area
    elif getattr(args, "preset", None) and args.preset in PRESETS:
        bbox = PRESETS[args.preset]["bbox"]
        area_name = f"preset: {args.preset}"
    elif getattr(args, "bbox", None):
        bbox = tuple(args.bbox)
        area_name = "custom bounding box"
    else:
        # Default to Bend Corridor
        bbox = PROTOTYPE_AREAS["bend-corridor"]
        area_name = "bend-corridor (default)"

    carto_key = getattr(args, "carto_key", None) or CARTO_API_KEY
    tile_cache = CartoTileCache(api_key=carto_key)

    print(f"Target Area:      {area_name}")
    print(f"Bounding Box:     {bbox}")
    print(f"Zoom Levels:      {args.min_zoom} to {args.max_zoom}")
    print(f"Map Style:        {args.style}")
    print(f"Storage Dir:      {tile_cache.cache_dir / args.style}")
    auth_label = "Authenticated via CARTO_API_KEY" if tile_cache.api_key else "Open Access Mode"
    print(f"API Mode:         {auth_label}")

    print("\nDownloading and caching tiles...")
    def on_progress(current: int, total: int, status: str) -> None:
        if current % 10 == 0 or current == total:
            print(f"  [{current}/{total}] tiles processed ({status})")

    stats = tile_cache.cache_bbox(
        bbox=bbox,
        min_zoom=args.min_zoom,
        max_zoom=args.max_zoom,
        style=args.style,
        force_refresh=getattr(args, "force", False),
        progress_callback=on_progress,
    )

    print(f"\n[Tile Caching Complete]")
    print(f"  Total In-Scope:    {stats['total_tiles']} tiles")
    print(f"  Newly Downloaded:  {stats['newly_downloaded']} tiles")
    print(f"  Already Cached:    {stats['already_cached']} tiles")
    print(f"  Failed / Skipped:  {stats['failed_tiles']} tiles")
    print(f"  Storage Footprint: {stats['total_bytes'] / 1024:.1f} KB (~{stats['total_bytes'] / (1024*1024):.2f} MB)")


def run_test_presets(args: argparse.Namespace) -> None:
    """Run all 7 core prototype archetypes and corridor testing presets in batch."""
    from scripts.run_testing_presets import run_testing_presets
    from src.weights import RoutingPreference
    pref = RoutingPreference(args.preference) if hasattr(args, "preference") and args.preference else RoutingPreference.BALANCED
    out_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else None
    run_testing_presets(
        output_dir=out_dir,
        offline=getattr(args, "offline", True),
        open_browser=getattr(args, "open", False),
        preference=pref,
    )


def run_gui(args: argparse.Namespace) -> None:
    """Launch the Route Launcher GUI Dev Tool."""
    dev_tool_src = PROJECT_ROOT.parent / "NavigationDevTool" / "src"
    if str(dev_tool_src) not in sys.path and dev_tool_src.is_dir():
        sys.path.insert(0, str(dev_tool_src))
    from dev_tool.server import start_dev_server
    start_dev_server(port=args.port, open_browser=not args.no_browser)


def main() -> None:
    epilog_text = """
Common Examples:
  python main.py route --preset osu-to-safeway    # Route Tykeson Hall to Safeway
  python main.py route --preset century-chandler  # Test Roundabout prototype
  python main.py test-presets --open              # Run all 7 testing presets & open catalog
  python main.py gui                              # Launch interactive Web GUI Dev Tool
  python main.py help route                       # View options for routing
"""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="NavigationEngine: Accessible Pedestrian Routing, Audio Guidance & Spatial Conflation",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available sub-commands")

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
    route_p.add_argument("--offline", action="store_true", help="Bypass live network requests and use local offline fixtures/cache immediately")
    route_p.add_argument("--start-lat", type=float, default=DEFAULT_START[0])
    route_p.add_argument("--start-lon", type=float, default=DEFAULT_START[1])
    route_p.add_argument("--end-lat", type=float, default=DEFAULT_END[0])
    route_p.add_argument("--end-lon", type=float, default=DEFAULT_END[1])
    route_p.add_argument("--export-geojson", type=str, default=None, help="Path to export calculated route as GeoJSON")
    route_p.add_argument("--export-gpkg", type=str, default=None, help="Path to export calculated route as OGC GeoPackage SQLite (.gpkg)")
    route_p.add_argument("--export-html", type=str, default=None, help="Path to export interactive web map (.html)")
    route_p.add_argument("--carto-key", type=str, default=None, help="CARTO API key for basemap tiles (overrides CARTO_API_KEY in .env)")
    route_p.add_argument("--cache-tiles", action="store_true", help="Automatically cache corridor basemap tiles locally for offline use")

    # Cache Tiles
    cache_p = subparsers.add_parser("cache-tiles", help="Pre-download and store CARTO tiles on device")
    cache_p.add_argument("--area", type=str, choices=list(PROTOTYPE_AREAS.keys()), default=None, help="Target prototyping area")
    cache_p.add_argument("--preset", type=str, choices=list(PRESETS.keys()), default=None, help="Corridor preset to cache")
    cache_p.add_argument("--bbox", type=float, nargs=4, metavar=("SOUTH", "WEST", "NORTH", "EAST"), default=None)
    cache_p.add_argument("--min-zoom", type=int, default=14, help="Minimum slippy tile zoom level (default: 14)")
    cache_p.add_argument("--max-zoom", type=int, default=17, help="Maximum slippy tile zoom level (default: 17)")
    cache_p.add_argument("--style", type=str, default="voyager", help="CARTO raster style (voyager, dark, positron)")
    cache_p.add_argument("--force", action="store_true", help="Force re-downloading even if cached")
    cache_p.add_argument("--carto-key", type=str, default=None, help="CARTO API key")

    # Coverage
    cov_p = subparsers.add_parser("coverage", help="Benchmark OSM tag completeness against municipal GIS")
    cov_p.add_argument("--citywide", action="store_true", help="Run full citywide benchmark for Bend, OR")

    # Export
    export_p = subparsers.add_parser("export-geojson", help="Export pedestrian network to GeoJSON")
    export_p.add_argument("--citywide", action="store_true", help="Export full citywide pedestrian network")
    export_p.add_argument("--output", type=str, default=None)

    # Benchmark
    bench_p = subparsers.add_parser("benchmark", help="Measure subsystem execution latencies against allowable budgets")
    bench_p.add_argument("--preset", type=str, choices=list(PRESETS.keys()), default="osu-to-safeway", help="Preset corridor to profile")

    # Geocode
    geo_p = subparsers.add_parser("geocode", help="Geocode address using free Nominatim")
    geo_p.add_argument("query", type=str, help="Search query")

    # Test Presets
    test_p = subparsers.add_parser("test-presets", help="Run all 7 core prototype archetypes and corridor presets in batch")
    test_p.add_argument("--open", action="store_true", help="Automatically open generated testing hub catalog in browser")
    test_p.add_argument("--offline", action="store_true", default=True, help="Use cached offline fixtures (default: True)")
    test_p.add_argument("--output-dir", type=str, default=None, help="Directory to save generated maps")
    test_p.add_argument("--preference", choices=["balanced", "fewer_turns", "shortest"], default="balanced", help="Routing optimization preference")

    # GUI
    gui_p = subparsers.add_parser("gui", help="Launch interactive Route Launcher GUI Dev Tool")
    gui_p.add_argument("--port", type=int, default=8050, help="Local HTTP server port (default: 8050)")
    gui_p.add_argument("--no-browser", action="store_true", help="Do not automatically launch browser")

    # Help
    help_p = subparsers.add_parser("help", help="Show help information for a command")
    help_p.add_argument("subcommand", nargs="?", choices=["fetch", "route", "test-presets", "gui", "cache-tiles", "coverage", "export-geojson", "benchmark", "geocode"], help="Command to show detailed help for")

    subparsers_map = {
        "fetch": fetch_p,
        "route": route_p,
        "test-presets": test_p,
        "gui": gui_p,
        "cache-tiles": cache_p,
        "coverage": cov_p,
        "export-geojson": export_p,
        "benchmark": bench_p,
        "geocode": geo_p,
    }

    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()

    if args.command == "help":
        if getattr(args, "subcommand", None) and args.subcommand in subparsers_map:
            subparsers_map[args.subcommand].print_help()
        else:
            parser.print_help()
    elif args.command == "fetch":
        run_fetch(args)
    elif args.command == "route":
        run_route(args)
    elif args.command == "test-presets":
        run_test_presets(args)
    elif args.command == "gui":
        run_gui(args)
    elif args.command == "cache-tiles":
        run_cache_tiles(args)
    elif args.command == "coverage":
        run_coverage(args)
    elif args.command == "export-geojson":
        run_export(args)
    elif args.command == "benchmark":
        run_benchmark(args)
    elif args.command == "geocode":
        run_geocode(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
