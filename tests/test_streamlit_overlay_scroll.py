"""Exact native hook: queued old scroll versus real movement after opening."""
from pathlib import Path
import subprocess

import pytest
import streamlit

from scripts.streamlit_overlay_resize import OVERLAY_BUNDLE, repair_overlay


@pytest.mark.parametrize("scenario", ["ancestor", "document", "window", "later-scroll",
    "later-document-scroll", "input-and-unrelated", "closed", "cleanup", "fallback"])
def test_native_overlay_scroll_dismissal_preserves_first_open_and_real_close(tmp_path, scenario):
    source = Path(streamlit.__file__).parent / "static/static/js" / OVERLAY_BUNDLE
    repaired = tmp_path / "repaired.js"
    repaired.write_bytes(repair_overlay(source.read_bytes()))
    result = subprocess.run(["node", str(Path(__file__).with_name("overlay_scroll_test.cjs")),
                             str(source), str(repaired), scenario], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
