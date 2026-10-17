"""The exact position callback moves its resize writes outside native delivery."""
from pathlib import Path
import subprocess

import pytest
import streamlit

from scripts.streamlit_overlay_resize import OVERLAY_BUNDLE, repair_overlay


def test_actual_locked_overlay_callbacks_preserve_position_and_cancel_queued_work(tmp_path):
    source = Path(streamlit.__file__).parent / "static" / "static" / "js" / OVERLAY_BUNDLE
    repaired = tmp_path / "repaired.js"
    repaired.write_bytes(repair_overlay(source.read_bytes()))
    result = subprocess.run(["node", str(Path(__file__).with_name("overlay_position_resize_test.cjs")),
                             str(source), str(repaired)], check=True, capture_output=True, text=True)
    assert "synchronous RO writes reproduced; coalescing, placement and cleanup passed" in result.stdout


def test_unexpected_overlay_bytes_cannot_be_repaired():
    with pytest.raises(RuntimeError, match="Unexpected locked"):
        repair_overlay(b"unrecognized frontend")
