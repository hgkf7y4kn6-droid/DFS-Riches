"""Runs the lineup builder's JavaScript rules (static/lineups.js) under Node."""
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_fit_checker_rules():
    script = Path(__file__).parent / "js" / "lineups_fit.test.js"
    result = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "fit tests passed" in result.stdout
