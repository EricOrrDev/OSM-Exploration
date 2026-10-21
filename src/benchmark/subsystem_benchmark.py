"""Subsystem Performance Benchmark & Latency Budget Evaluator."""

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from ..config import PRESETS
from ..clients.overpass_client import OverpassClient
from ..parser.osm_parser import OSMParser
from ..routing.pedestrian_graph import PedestrianGraph, RoutingPreference
from ..routing.guidance import AudioGuidanceGenerator
from ..export.geojson_exporter import GeoJSONExporter


@dataclass
class SubsystemBudget:
    name: str
    target_budget_s: float
    description: str


# Generous allowable latency budgets per subsystem
DEFAULT_BUDGETS: Dict[str, SubsystemBudget] = {
    "fetch_warm_cache": SubsystemBudget(
        name="Disk Cache I/O (Overpass/Nominatim)",
        target_budget_s=0.050,  # 50ms
        description="Reading cached OSM/Nominatim JSON from local disk",
    ),
    "osm_parsing": SubsystemBudget(
        name="OSM Parsing (OSMParser)",
        target_budget_s=0.100,  # 100ms
        description="Parsing raw JSON into PedestrianNetwork models",
    ),
    "graph_build": SubsystemBudget(
        name="Graph Construction & GIS Conflation",
        target_budget_s=2.000,  # 2000ms
        description="Graph edges, spatial indexing, GeoPackage conflation, and gap bridging",
    ),
    "routing_balanced": SubsystemBudget(
        name="Dijkstra Routing (Balanced)",
        target_budget_s=0.050,  # 50ms
        description="Pathfinding with accessibility multipliers across corridor",
    ),
    "routing_fewer_turns": SubsystemBudget(
        name="Dijkstra Routing (Fewer Turns)",
        target_budget_s=0.050,  # 50ms
        description="Pathfinding with cognitive turn penalties and curve costs",
    ),
    "audio_guidance": SubsystemBudget(
        name="Audio Guidance Generation",
        target_budget_s=2.500,  # 2500ms
        description="15° quantization, clock mapping, intersection classifier, and button cues",
    ),
    "map_export": SubsystemBudget(
        name="Map & Data Export (HTML/GeoJSON/GPKG)",
        target_budget_s=1.000,  # 1000ms
        description="Exporting GeoJSON, OGC GeoPackage, and interactive Leaflet HTML",
    ),
    "end_to_end_pipeline": SubsystemBudget(
        name="Full End-to-End Navigation Pipeline",
        target_budget_s=4.000,  # 4000ms
        description="Complete execution from data to audio guidance and map export",
    ),
}


class SubsystemBenchmark:
    """Profiles and validates subsystem execution latencies against generous allowable budgets."""

    def __init__(self, budgets: Optional[Dict[str, SubsystemBudget]] = None):
        self.budgets = budgets or DEFAULT_BUDGETS

    def run_benchmark(self, preset_name: str = "osu-to-safeway") -> Dict[str, Any]:
        """Execute all subsystems and record execution latencies."""
        preset = PRESETS.get(preset_name, PRESETS["osu-to-safeway"])
        bbox = preset["bbox"]
        start_pt = preset["start"]
        end_pt = preset["end"]
        fixture_name = preset.get("fixture")

        results: Dict[str, Dict[str, Any]] = {}
        t_pipeline_start = time.perf_counter()

        # 1. Warm Cache / Fixture Fetch
        client = OverpassClient()
        t0 = time.perf_counter()
        raw = client.fetch_pedestrian_data(bbox, fixture_name=fixture_name, offline=True)
        t_fetch = time.perf_counter() - t0
        results["fetch_warm_cache"] = self._record("fetch_warm_cache", t_fetch)

        # 2. OSM Parsing
        parser = OSMParser()
        t0 = time.perf_counter()
        network = parser.parse(raw)
        t_parse = time.perf_counter() - t0
        results["osm_parsing"] = self._record("osm_parsing", t_parse)

        # 3. Graph Construction & Spatial Conflation
        t0 = time.perf_counter()
        graph = PedestrianGraph(network)
        t_graph = time.perf_counter() - t0
        results["graph_build"] = self._record("graph_build", t_graph)

        start_node = graph.find_nearest_node(start_pt)
        end_node = graph.find_nearest_node(end_pt)
        assert start_node and end_node, "Failed to resolve route start/end nodes"

        # 4. Dijkstra Routing (Balanced)
        t0 = time.perf_counter()
        route_balanced = graph.route(start_node, end_node, preference=RoutingPreference.BALANCED)
        t_route_bal = time.perf_counter() - t0
        results["routing_balanced"] = self._record("routing_balanced", t_route_bal)

        # 5. Dijkstra Routing (Fewer Turns)
        t0 = time.perf_counter()
        route_fewer = graph.route(start_node, end_node, preference=RoutingPreference.FEWER_TURNS)
        t_route_fewer = time.perf_counter() - t0
        results["routing_fewer_turns"] = self._record("routing_fewer_turns", t_route_fewer)

        # 6. Audio Guidance Generation
        guidance_gen = AudioGuidanceGenerator(network)
        t0 = time.perf_counter()
        instructions = guidance_gen.generate_instructions(route_balanced)
        t_guidance = time.perf_counter() - t0
        results["audio_guidance"] = self._record("audio_guidance", t_guidance)

        # 7. Map & Data Export
        tmp_dir = Path("output") / ".benchmarks"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        GeoJSONExporter.export_route_to_geojson(route_balanced, network, instructions, tmp_dir / "bench.geojson")
        GeoJSONExporter.export_route_to_gpkg(route_balanced, network, instructions, tmp_dir / "bench.gpkg")
        GeoJSONExporter.export_route_to_html(route_balanced, network, instructions, tmp_dir / "bench.html")
        t_export = time.perf_counter() - t0
        results["map_export"] = self._record("map_export", t_export)

        # 8. Full Pipeline End-to-End
        t_pipeline = time.perf_counter() - t_pipeline_start
        results["end_to_end_pipeline"] = self._record("end_to_end_pipeline", t_pipeline)

        return results

    def _record(self, key: str, actual_s: float) -> Dict[str, Any]:
        budget = self.budgets[key]
        passed = actual_s <= budget.target_budget_s
        margin_pct = ((budget.target_budget_s - actual_s) / budget.target_budget_s) * 100
        return {
            "key": key,
            "name": budget.name,
            "actual_s": round(actual_s, 4),
            "budget_s": budget.target_budget_s,
            "passed": passed,
            "margin_pct": round(margin_pct, 1),
            "description": budget.description,
        }

    def print_summary(self, results: Dict[str, Dict[str, Any]]) -> bool:
        """Render a formatted benchmark table."""
        all_passed = True
        print("\n" + "=" * 82)
        print("PEDESTRIAN ACCESSIBILITY ENGINE - SUBSYSTEM LATENCY BENCHMARK")
        print("=" * 82)
        print(f"{'Subsystem':<36} | {'Actual':<9} | {'Budget':<8} | {'Margin':<8} | {'Status'}")
        print("-" * 82)

        for key, res in results.items():
            if key == "end_to_end_pipeline":
                print("-" * 82)
            passed = res["passed"]
            if not passed:
                all_passed = False
            status = "[PASS]" if passed else "[FAIL]"
            print(
                f"{res['name']:<36} | {res['actual_s']:>6.3f}s  | {res['budget_s']:>6.3f}s | {res['margin_pct']:>6.1f}% | {status}"
            )

        print("=" * 82)
        if all_passed:
            print("ALL SUBSYSTEMS SATISFIED PERFORMANCE LATENCY BUDGETS.")
        else:
            print("[WARNING] ONE OR MORE SUBSYSTEMS EXCEEDED ALLOWABLE LATENCY BUDGETS.")
        print("=" * 82 + "\n")
        return all_passed
