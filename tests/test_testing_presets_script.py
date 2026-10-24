"""Unit tests for the testing presets batch execution suite."""

from pathlib import Path
import pytest

from scripts.run_testing_presets import TESTING_PRESET_KEYS, run_testing_presets
from src.routing.pedestrian_graph import RoutingPreference


def test_testing_presets_keys():
    """Verify that all 7 primary archetypes and corridor presets are included."""
    assert len(TESTING_PRESET_KEYS) == 7
    assert "century-chandler" in TESTING_PRESET_KEYS
    assert "3rd-revere" in TESTING_PRESET_KEYS
    assert "colorado-straight" in TESTING_PRESET_KEYS
    assert "columbia-bridge" in TESTING_PRESET_KEYS
    assert "hwy20-jamison" in TESTING_PRESET_KEYS
    assert "powers-hwy97" in TESTING_PRESET_KEYS
    assert "osu-to-safeway" in TESTING_PRESET_KEYS


def test_run_testing_presets_batch(tmp_path):
    """Verify batch runner generates artifacts and valid result records."""
    results = run_testing_presets(
        output_dir=tmp_path,
        offline=True,
        open_browser=False,
        preference=RoutingPreference.BALANCED,
    )

    assert len(results) == 7
    for r in results:
        assert r["status"] == "SUCCESS"
        assert r["distance_m"] > 0
        assert r["effective_cost"] > 0
        assert r["num_steps"] > 0
        assert (tmp_path / r["html_file"]).exists()

    hub_file = tmp_path / "test_presets_hub.html"
    assert hub_file.exists()
    hub_content = hub_file.read_text(encoding="utf-8")
    assert "Accessible Navigation — Testing Presets Hub" in hub_content
    assert "Roundabout" in hub_content
    assert "Refuge Island" in hub_content
