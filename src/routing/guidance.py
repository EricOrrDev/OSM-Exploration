"""Auditory and tactile navigation guidance generator for blind pedestrians.

Coordinates StepQualitiesExtractor (raw semantic feature extraction) and
GuidanceTextPreparer (user-tunable text formatting, paces, and verbosity filtering).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.pedestrian import PedestrianNetwork
from ..models.qualities import NavigationStepQualities
from .button_detector import ButtonDetector
from .intersection_classifier import IntersectionClassifier
from .pedestrian_graph import RouteResult
from .safety_weights import (
    DEFAULT_SAFETY_WEIGHTS,
    DEFAULT_VERBIAGE_CONFIG,
    CurveVerbiagePreset,
    DirectionMode,
    DistanceUnit,
    GuidanceVerbiageConfig,
    SafetyWeightsConfig,
)
from .step_qualities import StepQualitiesExtractor
from .text_preparer import GuidanceTextPreparer, TextPreparationConfig, VerbosityLevel


class AudioGuidanceGenerator:
    """Formats route steps into explicit, tactile-aware spoken instructions."""

    def __init__(
        self,
        network: PedestrianNetwork,
        classifier: Optional[IntersectionClassifier] = None,
        button_detector: Optional[ButtonDetector] = None,
        map_data_dir: Optional[Path] = None,
        weights: Optional[SafetyWeightsConfig] = None,
        verbiage_config: Optional[GuidanceVerbiageConfig] = None,
        text_preparer: Optional[GuidanceTextPreparer] = None,
        prep_config: Optional[TextPreparationConfig] = None,
    ):
        self.network = network
        self.classifier = classifier or IntersectionClassifier(network, map_data_dir=map_data_dir)
        self.button_detector = button_detector or ButtonDetector(network)
        self.weights = weights or DEFAULT_SAFETY_WEIGHTS
        self.verbiage = verbiage_config or self.weights.verbiage or DEFAULT_VERBIAGE_CONFIG
        self.extractor = StepQualitiesExtractor(
            network=self.network,
            classifier=self.classifier,
            button_detector=self.button_detector,
            map_data_dir=map_data_dir,
            weights=self.weights,
        )
        self.prep_config = prep_config or TextPreparationConfig(
            direction_mode=self.verbiage.direction_mode,
            clock_granularity=self.verbiage.clock_granularity,
            curve_preset=self.verbiage.curve_preset,
            distance_unit=self.verbiage.distance_unit,
            stride_length_m=self.verbiage.stride_length_m,
            pace_margin=self.verbiage.pace_margin,
            pace_unit_noun=self.verbiage.pace_unit_noun,
        )
        self.preparer = text_preparer or GuidanceTextPreparer(self.prep_config)

    def extract_step_qualities(self, route: RouteResult) -> List[NavigationStepQualities]:
        """Extract comprehensive raw semantic qualities for each route step prior to text preparation."""
        return self.extractor.extract_qualities(route)

    def generate_instructions(
        self,
        route: RouteResult,
        prep_config: Optional[TextPreparationConfig] = None,
    ) -> List[Dict[str, Any]]:
        """Generate auditory instructions for each segment and transition along the route."""
        if prep_config is not None:
            cfg = prep_config
        else:
            cfg = self.prep_config
            if self.verbiage:
                cfg.direction_mode = self.verbiage.direction_mode
                cfg.clock_granularity = self.verbiage.clock_granularity
                cfg.curve_preset = self.verbiage.curve_preset
                cfg.curve_template = self.verbiage.curve_template
                cfg.distance_unit = self.verbiage.distance_unit
                cfg.stride_length_m = self.verbiage.stride_length_m
                cfg.pace_margin = self.verbiage.pace_margin
                cfg.pace_unit_noun = self.verbiage.pace_unit_noun

        qualities = self.extract_step_qualities(route)
        return self.preparer.prepare_instructions(qualities, config=cfg)
