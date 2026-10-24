"""Unit tests for NavigationEngine CLI help and sub-command routing."""

import subprocess
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_cli_help_flags():
    """Verify that -h, --help, and -help exit cleanly with status 0."""
    for flag in ["-h", "--help", "-help"]:
        res = subprocess.run(
            [sys.executable, "main.py", flag],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "NavigationEngine" in res.stdout
        assert "Common Examples:" in res.stdout
        assert "test-presets" in res.stdout
        assert "gui" in res.stdout


def test_cli_help_subcommand():
    """Verify that 'main.py help' and 'main.py help route' display valid documentation."""
    # General help
    res1 = subprocess.run(
        [sys.executable, "main.py", "help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert res1.returncode == 0
    assert "NavigationEngine" in res1.stdout

    # Subcommand specific help
    res2 = subprocess.run(
        [sys.executable, "main.py", "help", "route"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert res2.returncode == 0
    assert "usage: main.py route" in res2.stdout
    assert "--preset" in res2.stdout

    # Subcommand specific help for test-presets
    res3 = subprocess.run(
        [sys.executable, "main.py", "help", "test-presets"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert res3.returncode == 0
    assert "test-presets" in res3.stdout
    assert "--preference" in res3.stdout
