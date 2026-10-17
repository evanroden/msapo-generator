"""Actual locked callbacks and cross-observer depth model, not a browser pass."""
from hashlib import sha256
from pathlib import Path
import json
import subprocess

import pytest
import streamlit

from scripts import patch_streamlit_frontend as compat
from scripts.streamlit_floating_resize import FLOATING_BUNDLE, repair_floating


def test_actual_resize_callback_preserves_native_paths_and_lifetime(tmp_path):
    original = Path(streamlit.__file__).parent / "static/static/js" / FLOATING_BUNDLE
    repaired = tmp_path / "repaired.js"
    repaired.write_bytes(repair_floating(original.read_bytes()))
    result = subprocess.run(["node", str(Path(__file__).with_name("floating_resize_test.cjs")),
                             str(original), str(repaired)], check=True, capture_output=True, text=True, timeout=10)
    assert "lifetime cancellation passed" in result.stdout


def test_cross_observer_width_feedback_and_five_negative_controls():
    from scripts.qa_native_owner_source_model import extracts
    static = Path(streamlit.__file__).parent / "static"
    sources, members = compat._locked_sources(static / "static/js")
    previous = compat._publication(sources, members, False, floating_resize=False, queued_scroll=False)
    manifest = {"selected_production": {"scalar_date": False, "generation": previous.generation},
                "assets": {previous.names[name]: {"input_sha256": sha256(previous.payloads[name]).hexdigest()}
                           for name in (compat.OVERLAY_BUNDLE, compat.VIRTUALIZER_BUNDLE)}}
    manifest["assets"][FLOATING_BUNDLE] = {"input_sha256": compat.FLOATING_SHA256}
    values, _ = extracts(static, manifest)
    result = subprocess.run(["node", str(Path(__file__).with_name("native_owner_depth_model.cjs")), json.dumps(values)],
                            check=True, capture_output=True, text=True, timeout=10)
    cases = json.loads(result.stdout)["cases"]
    assert cases["currentCycleWidthCommit"]["skipErrorCondition"]
    assert not cases["repairedCurrentCycle"]["skipErrorCondition"]
    assert cases["repairedCurrentCycle"]["popupAfterDelayedCommit"] == 653.5


def test_unknown_floating_source_is_never_modified():
    with pytest.raises(RuntimeError, match="Unexpected locked Floating"):
        repair_floating(b"unknown native source")
