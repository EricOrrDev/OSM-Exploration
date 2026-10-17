"""Spatial conflation and geospatial data registry package."""

from .gpkg_registry import GeoPackageRegistry, LayerRole, SpatialFeature
from .semantic_classifier import (
    DisambiguationResult,
    SemanticCrossingType,
    SemanticRoadClassifier,
)

__all__ = [
    "GeoPackageRegistry",
    "LayerRole",
    "SpatialFeature",
    "SemanticCrossingType",
    "DisambiguationResult",
    "SemanticRoadClassifier",
]
