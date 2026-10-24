"""Unit tests for Semantic Step Qualities, GuidanceTextPreparer, and Paces Distance Formatting."""

import pytest
from src.clients.overpass_client import OverpassClient
from src.config import PRESETS
from src.models.qualities import NavigationStepQualities, StepAction
from src.parser.osm_parser import OSMParser
from src.routing.guidance import AudioGuidanceGenerator
from src.routing.pedestrian_graph import PedestrianGraph
from src.routing.step_qualities import StepQualitiesExtractor
from src.routing.text_preparer import GuidanceTextPreparer, TextPreparationConfig, VerbosityLevel
from src.weights.verbiage import DistanceUnit, GuidanceVerbiageConfig


def test_format_distance_meters():
    cfg = GuidanceVerbiageConfig(distance_unit=DistanceUnit.METERS)
    assert cfg.format_distance(1.0) == "1 meter"
    assert cfg.format_distance(0.8) == "1 meter"
    assert cfg.format_distance(15.2) == "15 meters"
    assert cfg.format_distance(156.0) == "156 meters"


def test_format_distance_paces_no_decimals():
    """Verify paces formatting never outputs decimals (e.g. 3.49 -> '3 to 4 strides')."""
    cfg = GuidanceVerbiageConfig(
        distance_unit=DistanceUnit.PACES,
        stride_length_m=0.75,
        pace_margin=0,
    )

    # 2.62m / 0.75m = 3.493 -> must be '3 to 4 strides'
    assert cfg.format_distance(2.62) == "3 to 4 strides"

    # Exact division: 15.0m / 0.75m = 20.0 -> '20 strides'
    assert cfg.format_distance(15.0) == "20 strides"

    # Exact 1 stride
    assert cfg.format_distance(0.75) == "1 stride"

    # Short distance below 1 stride
    assert cfg.format_distance(0.5) == "1 stride"

    # 10.0m / 0.75m = 13.33 -> '13 to 14 strides'
    res = cfg.format_distance(10.0)
    assert res == "13 to 14 strides"
    assert "." not in res


def test_format_distance_paces_with_margin():
    """Verify user-configured margin expands range (e.g. margin=1 turns 3 to 4 into 3 to 5 strides)."""
    cfg = GuidanceVerbiageConfig(
        distance_unit=DistanceUnit.STRIDES,
        stride_length_m=0.75,
        pace_margin=1,
    )

    # 2.62m / 0.75m = 3.49 -> margin=1 -> '3 to 5 strides'
    assert cfg.format_distance(2.62) == "3 to 5 strides"

    # 15.0m / 0.75m = 20.0 -> margin=1 -> '20 to 21 strides'
    assert cfg.format_distance(15.0) == "20 to 21 strides"

    # margin=2 -> 20 to 22 strides
    cfg_m2 = GuidanceVerbiageConfig(
        distance_unit=DistanceUnit.STRIDES,
        stride_length_m=0.75,
        pace_margin=2,
    )
    assert cfg_m2.format_distance(15.0) == "20 to 22 strides"


def test_format_distance_custom_stride_length():
    """Verify stride length adjustment adapts step counts."""
    # Shorter stride (0.50m)
    cfg_short = GuidanceVerbiageConfig(
        distance_unit=DistanceUnit.PACES,
        stride_length_m=0.50,
        pace_margin=0,
    )
    assert cfg_short.format_distance(10.0) == "20 strides"

    # Longer stride (1.00m)
    cfg_long = GuidanceVerbiageConfig(
        distance_unit=DistanceUnit.PACES,
        stride_length_m=1.00,
        pace_margin=0,
    )
    assert cfg_long.format_distance(10.0) == "10 strides"


def test_step_qualities_extraction():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])
    network = OSMParser().parse(raw)
    graph = PedestrianGraph(network)
    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)

    extractor = StepQualitiesExtractor(network)
    qualities = extractor.extract_qualities(route)

    assert len(qualities) > 10
    actions = [sq.action for sq in qualities]
    assert StepAction.APPROACH_CURB in actions
    assert StepAction.CROSS_STREET in actions
    assert StepAction.EXIT_CURB in actions
    assert StepAction.WALK_SIDEWALK in actions
    assert StepAction.ARRIVE in actions

    # Verify structured qualities on crossing steps
    crossings = [sq for sq in qualities if sq.action == StepAction.CROSS_STREET]
    assert any(c.crossing.intersection_type == "roundabout" for c in crossings)
    assert any(c.crossing.road_crossed == "SW Innovation Way" for c in crossings)
    assert any(c.crossing.has_refuge_island for c in crossings)

    # Verify dictionary serialization
    q_dict = qualities[0].to_dict()
    assert "action" in q_dict
    assert "distance_m" in q_dict
    assert "kerb" in q_dict
    assert "crossing" in q_dict


def test_text_preparer_feature_toggles_and_curbs():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])
    network = OSMParser().parse(raw)
    graph = PedestrianGraph(network)
    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)

    gen = AudioGuidanceGenerator(network)
    qualities = gen.extract_step_qualities(route)

    preparer = GuidanceTextPreparer()

    # 1. Standard mode includes curbs
    std_instructions = preparer.prepare_instructions(qualities, TextPreparationConfig(announce_curbs=True))
    assert any(i["action"] == "APPROACH_CURB" for i in std_instructions)
    assert any(i["action"] == "EXIT_CURB" for i in std_instructions)

    # 2. Turning curbs off filters them out entirely
    no_curbs_cfg = TextPreparationConfig(announce_curbs=False)
    no_curbs_instructions = preparer.prepare_instructions(qualities, no_curbs_cfg)
    assert not any(i["action"] == "APPROACH_CURB" for i in no_curbs_instructions)
    assert not any(i["action"] == "EXIT_CURB" for i in no_curbs_instructions)
    assert len(no_curbs_instructions) < len(std_instructions)

    # 3. Suppressing tactile paving descriptions
    no_tactile_cfg = TextPreparationConfig(announce_tactile=False)
    no_tactile_instructions = preparer.prepare_instructions(qualities, no_tactile_cfg)
    all_no_tactile = " ".join(i["spoken_instruction"] for i in no_tactile_instructions)
    assert "truncated domes" not in all_no_tactile
    assert "onto tactile paving" not in all_no_tactile


def test_text_preparer_verbosity_scales():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])
    network = OSMParser().parse(raw)
    graph = PedestrianGraph(network)
    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)

    gen = AudioGuidanceGenerator(network)
    qualities = gen.extract_step_qualities(route)
    preparer = GuidanceTextPreparer()

    # Minimal: curbs omitted automatically, concise guidance
    min_cfg = TextPreparationConfig(verbosity=VerbosityLevel.MINIMAL)
    min_inst = preparer.prepare_instructions(qualities, min_cfg)
    assert not any(i["action"] == "APPROACH_CURB" for i in min_inst)
    assert not any(i["action"] == "EXIT_CURB" for i in min_inst)

    # Detailed: includes full patterns and APS locator cues
    det_cfg = TextPreparationConfig(verbosity=VerbosityLevel.DETAILED)
    det_inst = preparer.prepare_instructions(qualities, det_cfg)
    det_spoken = " ".join(i["spoken_instruction"] for i in det_inst)
    assert "zebra pattern" in det_spoken


def test_text_preparer_paces_integration():
    preset = PRESETS["osu-to-safeway"]
    client = OverpassClient(mock_mode=True)
    raw = client.fetch_pedestrian_data(preset["bbox"], fixture_name=preset["fixture"])
    network = OSMParser().parse(raw)
    graph = PedestrianGraph(network)
    start_node = graph.find_nearest_node(preset["start"])
    end_node = graph.find_nearest_node(preset["end"])
    route = graph.route(start_node, end_node)

    gen = AudioGuidanceGenerator(network)
    paces_cfg = TextPreparationConfig(
        distance_unit=DistanceUnit.PACES,
        stride_length_m=0.75,
        pace_margin=1,
    )
    instructions = gen.generate_instructions(route, prep_config=paces_cfg)

    spoken_text = " ".join(inst["spoken_instruction"] for inst in instructions)
    assert "strides" in spoken_text
    assert "meters" not in spoken_text

    # Verify no decimal strides exist
    import re
    assert not re.search(r"\d+\.\d+\s+strides", spoken_text)
