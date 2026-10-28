"""Native image review retains its caption, controls and owner across reruns."""
import subprocess
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_caption_adapter_is_owned_by_the_same_native_image_after_rerun():
    app = AppTest.from_file(str(ROOT / "tests/fixtures/workspaces/import_picture_alt_app.py")).run()
    assert not app.exception
    before = [entry.proto.json for entry in app.get("bidi_component")]
    assert len(before) == 2 and all("monthly_import_picture_" in value for value in before)
    assert len(app.get("image")) == 3
    app.button[0].click().run()
    assert not app.exception
    assert [entry.proto.json for entry in app.get("bidi_component")] == before
    assert len(app.get("image")) == 3


def test_display_only_description_adapter():
    result = subprocess.run(["node", "--test", "tests/import_picture_accessibility_test.cjs"],
                            cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
