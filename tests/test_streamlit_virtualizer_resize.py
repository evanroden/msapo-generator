"""Actual locked virtualizer callback updates leave native resize delivery."""
from pathlib import Path
import subprocess

import pytest
import streamlit

from scripts.streamlit_virtualizer_resize import VIRTUALIZER_BUNDLE, repair_virtualizer


def test_actual_virtualizer_resize_preserves_geometry_scroll_and_cleanup(tmp_path):
    source = Path(streamlit.__file__).parent / "static/static/js" / VIRTUALIZER_BUNDLE
    repaired = tmp_path / "repaired.js"
    repaired.write_bytes(repair_virtualizer(source.read_bytes()))
    result = subprocess.run(["node", str(Path(__file__).with_name("virtualizer_resize_test.cjs")),
                             str(source), str(repaired)], check=True, capture_output=True, text=True)
    assert "actual virtual-list resize: coalescing, exact geometry, scroll and cleanup passed" in result.stdout


def test_unexpected_virtualizer_bytes_fail_without_repair():
    with pytest.raises(RuntimeError, match="Unexpected locked"):
        repair_virtualizer(b"unrecognized frontend")
