"""Exports PedestrianNetwork and RouteResults into GeoJSON, GeoPackage, and interactive HTML maps.

Delegates core serialization and map generation to the dedicated RouteVisualizer package
while maintaining full backward compatibility for existing callers and test suites.
"""

from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure RouteVisualizer is resolvable
_rv_path = str((Path(__file__).resolve().parent.parent.parent.parent / "RouteVisualizer" / "src").resolve())
if _rv_path not in sys.path and Path(_rv_path).is_dir():
    sys.path.insert(0, _rv_path)

from route_visualizer import GeoJSONBuilder, GeoPackageBuilder, RouteMapBuilder
from route_visualizer.gpkg_builder import create_gpb_point, create_gpb_linestring

from ..models.pedestrian import PedestrianNetwork
from ..routing.pedestrian_graph import RouteResult

# Aliases for backward compatibility
_create_gpb_point = create_gpb_point
_create_gpb_linestring = create_gpb_linestring


class GeoJSONExporter:
    """Converts pedestrian networks and routes into GeoJSON, GeoPackage, and interactive web maps."""

    @staticmethod
    def export_network_to_geojson(network: PedestrianNetwork, output_path: Optional[Path] = None) -> Dict[str, Any]:
        """Convert entire pedestrian network into a GeoJSON FeatureCollection."""
        return GeoJSONBuilder.build_network_geojson(network, output_path)

    @staticmethod
    def export_route_to_geojson(
        route: RouteResult,
        network: PedestrianNetwork,
        instructions: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Convert a calculated route into a detailed GeoJSON FeatureCollection."""
        return GeoJSONBuilder.build_route_geojson(route, network, instructions, output_path)

    @staticmethod
    def export_route_to_gpkg(
        route: RouteResult,
        network: PedestrianNetwork,
        instructions: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Create a valid OGC GeoPackage containing route corridor, segments, and waypoints."""
        if not output_path:
            output_path = Path("output/route.gpkg")
        geojson_data = GeoJSONBuilder.build_route_geojson(route, network, instructions)
        return GeoPackageBuilder.export(geojson_data, Path(output_path), instructions)

    @staticmethod
    def export_interactive_html(
        route: RouteResult,
        network: PedestrianNetwork,
        instructions: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[Path] = None,
        title: str = "Pedestrian Navigation Map",
        carto_api_key: str = "",
        cache_dir: Optional[Path] = None,
    ) -> str:
        """Render self-contained interactive Leaflet HTML map with navigation HUD and TTS."""
        return RouteMapBuilder.render_html(
            route=route,
            network=network,
            instructions=instructions,
            output_path=output_path,
            title=title,
            carto_api_key=carto_api_key,
            cache_dir=cache_dir,
        )

    @staticmethod
    def export_route_to_html(
        route: RouteResult,
        network: PedestrianNetwork,
        instructions: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[Path] = None,
        title: str = "Pedestrian Navigation Map",
        carto_api_key: str = "",
        cache_dir: Optional[Path] = None,
    ) -> Path:
        """Render self-contained HTML map and return output Path (backward compatibility wrapper)."""
        if not output_path:
            output_path = Path("output/map.html")
        RouteMapBuilder.render_html(
            route=route,
            network=network,
            instructions=instructions,
            output_path=Path(output_path),
            title=title,
            carto_api_key=carto_api_key,
            cache_dir=cache_dir,
        )
        return Path(output_path)
