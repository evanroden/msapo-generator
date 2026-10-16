"""Run the display-only native-commit race regression on the locked application JS."""
from pathlib import Path
import subprocess


def test_native_commit_preview_race_contract():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", "--test", "tests/preview_commit_gate_test.cjs"],
                            cwd=root, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
