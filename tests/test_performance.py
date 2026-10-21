"""Unit and integration performance testing suite with allowable latency budgets.

Validates that all critical subsystems (parsing, spatial graph construction, Dijkstra routing,
audio guidance generation, and map export) execute within generous allowable latencies to prevent
performance regressions.
"""

from pathlib import Path
import time
import pytest

from src.benchmark.subsystem_benchmark import DEFAULT_BUDGETS, SubsystemBenchmark
from src.config import PRESETS
from src.clients.overpass_client import OverpassClient
from src.parser.osm_parser import OSMParser
from src.routing.pedestrian_graph import PedestrianGraph, RoutingPreference
from src.routing.guidance import AudioGuidanceGenerator
from src.export.geojson_exporter import GeoJSONExporter


@pytest.fixture(scope="module")
def benchmark_data():
    """Loads parsed network and graph for isolated subsystem latency evaluations."""
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient()
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset.get("fixture"), offline=True)
    parser = OSMParser()
    network = parser.parse(raw)
    graph = PedestrianGraph(network)
    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    return {
        "raw": raw,
        "network": network,
        "graph": graph,
        "start_node": start_node,
        "end_node": end_node,
    }


def test_parsing_latency_budget(benchmark_data):
    """Verify OSMParser processes raw network JSON within 100ms budget."""
    budget = DEFAULT_BUDGETS["osm_parsing"].target_budget_s
    parser = OSMParser()

    t0 = time.perf_counter()
    network = parser.parse(benchmark_data["raw"])
    elapsed = time.perf_counter() - t0

    assert len(network.raw_nodes) > 0
    assert elapsed < budget, f"Parsing took {elapsed:.4f}s, exceeding budget {budget}s"


def test_graph_construction_latency_budget(benchmark_data):
    """Verify graph construction with GIS conflation finishes within 2.0s budget."""
    budget = DEFAULT_BUDGETS["graph_build"].target_budget_s

    t0 = time.perf_counter()
    graph = PedestrianGraph(benchmark_data["network"])
    elapsed = time.perf_counter() - t0

    assert len(graph.adj) > 0
    assert elapsed < budget, f"Graph construction took {elapsed:.4f}s, exceeding budget {budget}s"


def test_dijkstra_balanced_routing_latency_budget(benchmark_data):
    """Verify Dijkstra pathfinding (Balanced) executes within 50ms budget."""
    budget = DEFAULT_BUDGETS["routing_balanced"].target_budget_s
    graph = benchmark_data["graph"]
    start = benchmark_data["start_node"]
    end = benchmark_data["end_node"]

    t0 = time.perf_counter()
    route = graph.route(start, end, preference=RoutingPreference.BALANCED)
    elapsed = time.perf_counter() - t0

    assert route is not None
    assert route.total_distance_m > 0
    assert elapsed < budget, f"Balanced routing took {elapsed:.4f}s, exceeding budget {budget}s"


def test_dijkstra_fewer_turns_routing_latency_budget(benchmark_data):
    """Verify Dijkstra pathfinding with turn penalties (Fewer Turns) executes within 50ms budget."""
    budget = DEFAULT_BUDGETS["routing_fewer_turns"].target_budget_s
    graph = benchmark_data["graph"]
    start = benchmark_data["start_node"]
    end = benchmark_data["end_node"]

    t0 = time.perf_counter()
    route = graph.route(start, end, preference=RoutingPreference.FEWER_TURNS)
    elapsed = time.perf_counter() - t0

    assert route is not None
    assert elapsed < budget, f"Fewer-turns routing took {elapsed:.4f}s, exceeding budget {budget}s"


def test_audio_guidance_generation_latency_budget(benchmark_data):
    """Verify audio guidance generation with topology classification finishes within 2.5s budget."""
    budget = DEFAULT_BUDGETS["audio_guidance"].target_budget_s
    graph = benchmark_data["graph"]
    network = benchmark_data["network"]
    route = graph.route(benchmark_data["start_node"], benchmark_data["end_node"])
    generator = AudioGuidanceGenerator(network)

    t0 = time.perf_counter()
    instructions = generator.generate_instructions(route)
    elapsed = time.perf_counter() - t0

    assert len(instructions) > 0
    assert elapsed < budget, f"Audio guidance took {elapsed:.4f}s, exceeding budget {budget}s"


def test_map_export_latency_budget(benchmark_data, tmp_path):
    """Verify GeoJSON, GeoPackage, and HTML map generation finishes within 1.0s budget."""
    budget = DEFAULT_BUDGETS["map_export"].target_budget_s
    graph = benchmark_data["graph"]
    network = benchmark_data["network"]
    route = graph.route(benchmark_data["start_node"], benchmark_data["end_node"])
    instructions = AudioGuidanceGenerator(network).generate_instructions(route)

    t0 = time.perf_counter()
    GeoJSONExporter.export_route_to_geojson(route, network, instructions, tmp_path / "route.geojson")
    GeoJSONExporter.export_route_to_gpkg(route, network, instructions, tmp_path / "route.gpkg")
    GeoJSONExporter.export_route_to_html(route, network, instructions, tmp_path / "route.html")
    elapsed = time.perf_counter() - t0

    assert (tmp_path / "route.html").exists()
    assert elapsed < budget, f"Map export took {elapsed:.4f}s, exceeding budget {budget}s"


def test_end_to_end_subsystem_benchmark_suite():
    """Verify entire subsystem suite passes all latency budgets simultaneously."""
    bench = SubsystemBenchmark()
    results = bench.run_benchmark(preset_name="osu-to-safeway")
    all_passed = bench.print_summary(results)

    for key, res in results.items():
        assert res["passed"], (
            f"Subsystem '{res['name']}' exceeded budget: {res['actual_s']:.4f}s > {res['budget_s']:.4f}s"
        )
    assert all_passed is True
