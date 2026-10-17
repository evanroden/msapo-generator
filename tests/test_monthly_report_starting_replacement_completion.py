"""Named uploads retain their own scope through reruns and the real save gate."""
from io import BytesIO

from PIL import Image
import pytest

from app import monthly_report_library as library
from app import monthly_report_section_ui as ui
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_model import synthetic_profiles
from tests.test_monthly_report_start_import import save_start, start_app
from tests.test_monthly_report_starting_review_recovery import (
    continue_button,
    drawing_report,
)


@pytest.mark.parametrize("section,label", [
    ("cover", "New cover photograph"),
    ("proposals", "Updated price-free proposal image"),
])
def test_named_upload_survives_reruns_without_certifying_a_different_role(
        monkeypatch, tmp_path, section, label):
    path, _ = drawing_report(tmp_path, section)
    original = path.read_bytes()
    raw = BytesIO()
    Image.new("RGB", (610, 410), "green").save(raw, "PNG")
    upload = BytesIO(raw.getvalue())
    upload.name = "synthetic-clear-replacement.png"
    upload.size = len(raw.getvalue())
    real = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda name, *a, **kw:
                        upload if name == label else real(name, *a, **kw))

    app = start_app(monkeypatch, tmp_path, path)
    assert continue_button(app).disabled
    action = next(r for r in app.radio if r.label == "What would you like to do?")
    action.set_value("Edit text or change pictures").run()
    assert not app.exception
    if section == "cover":
        # An optional photograph cannot replace the unrelated VML drawing in
        # this actual inspected source. Existing-report cover-design recovery
        # has its separate complete save/original-retention regression.
        for _ in range(2):
            assert continue_button(app).disabled
            assert any("new cover photograph changes only the photograph" in e.value for e in app.error)
            plans = next(value for key, value in app.session_state.filtered_state.items()
                         if key.endswith("_section_plans"))
            assert {slot for slot, _ in plans["cover"]["new_assets"]} == {"cover_photo"}
            assert not library.list_profiles(synthetic_profiles()[0].contract)
            assert path.read_bytes() == original
            app.run()
        return
    assert not continue_button(app).disabled
    app.run()
    assert not app.exception
    assert not continue_button(app).disabled
    assert not library.list_profiles(synthetic_profiles()[0].contract)

    # Only this explicit save may write the chosen replacement. The original
    # remains an independent unchanged file, not a rewritten recovery artifact.
    draft = save_start(app)
    assert draft is not None
    assert path.read_bytes() == original
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original
    replacement = normalize_report_image(raw.getvalue(), ".png", line_art=False)
    reference = library.asset_reference(replacement.data, replacement.extension)
    assert any(reference in block.asset_hashes for block in draft.blocks)
    assert library.read_asset(draft.profile.contract, draft.profile.key, reference) == replacement.data
