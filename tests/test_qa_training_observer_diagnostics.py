"""The local-only passive diagnostic must preserve the native observer API."""
from pathlib import Path
import subprocess


def test_native_observer_contract_and_bounded_local_only_capture():
    script = Path(__file__).with_name("qa_training_observer_diagnostics_test.cjs")
    result = subprocess.run(["node", str(script)], check=True, capture_output=True, text=True)
    assert "same-turn delivery, unchanged errors, bounds and isolation passed" in result.stdout
