"""Real synthetic source preparation and native AppTest photo-upload controls."""
from dataclasses import replace
from datetime import date
from io import BytesIO

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources, monthly_report_visual_ui as visual
from app.monthly_report_asset_review import asset_context
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections, synthetic_profiles
from app.monthly_report_source_details import correct_source_details
from app.monthly_report_source_retirement import retire_contributions


APP = '''
from dataclasses import replace
import streamlit as st
from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod
from app.monthly_report_ui import _field
from app.monthly_report_visual_ui import edit_photos
snapshot=library.load_snapshot(CONTRACT, PROFILE, ReportPeriod(2026,10))
draft=st.session_state.setdefault('working',snapshot.draft)
assets=st.session_state.setdefault('assets',{})
block=next(item for item in draft.blocks if item.key=='improvements')
updated=edit_photos(draft,block,'synthetic_photo_edit',assets,_field,show_preview=False)
draft=replace(draft,blocks=(updated,))
st.session_state['working']=draft
if st.session_state.pop('synthetic_photo_edit_period_editor_refresh',False):
    st.rerun()
if st.button('Save synthetic report'):
    library.save_snapshot(draft,expected_revision=snapshot.revision,assets=tuple(assets.items()),entered_editor='Synthetic Reviewer')
'''


@pytest.mark.parametrize("ambiguous", (False, True))
def test_native_human_photo_add_preserves_equal_source_page_then_retirement(monkeypatch, tmp_path, ambiguous):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    profile = synthetic_profiles()[0]
    image = BytesIO()
    Image.new("RGB", (80, 120), (50, 95, 145)).save(image, "PNG")
    raw = image.getvalue()
    content, _ = sources.ingest(profile, "synthetic-owned-page.png", raw)
    source = correct_source_details(content.source, profile, date(2026, 10, 8), "north")
    source = replace(source, selected_pages=(1,), captions=((1, "Imported sample page"),))
    source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    content = replace(content, source=source)
    imported, = sources.prepare_pages(profile, (content,), ((source.id, "improvements"),))
    if ambiguous:
        # A legacy image map may contain multiple candidate source pages. A
        # missing unique page identity does not establish human ownership.
        multiple = (*imported.references, sources.source_reference(source, 2))
        values = dict(references=multiple,
                      asset_provenance=((imported.asset_hashes[0], multiple),))
        if hasattr(imported, "asset_instances"):
            values["asset_instances"] = ()
        imported = replace(imported, **values)
    normalized = normalize_report_image(raw, ".png")
    assert imported.asset_hashes == (library.asset_reference(normalized.data, normalized.extension),)
    draft = ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic Reviewer", default_sections(),
                        (imported,), sources=(source,))
    library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    native_uploader = visual.st.file_uploader
    upload = BytesIO(raw)
    upload.name, upload.size = "synthetic-human-photo.png", len(raw)
    monkeypatch.setattr(visual.st, "file_uploader", lambda label, *a, **kw:
        [upload] if label == "Progress photos" else native_uploader(label, *a, **kw))
    script = APP.replace("CONTRACT", repr(profile.contract)).replace("PROFILE", repr(profile.key))
    app = AppTest.from_string(script).run()
    next(button for button in app.button if button.label == "Add these photos").click().run()
    assert not app.exception
    current = app.session_state["working"].blocks[0]
    assert current.asset_hashes == (*imported.asset_hashes, *imported.asset_hashes), "Explicit human Add must preserve both independently owned occurrences."
    assert asset_context(current, 0) == asset_context(imported, 0)
    assert asset_context(current, 1) == ()
    # Same selected human file remains idempotent when Add is repeated.
    next(button for button in app.button if button.label == "Add these photos").click().run()
    assert len(app.session_state["working"].blocks[0].asset_hashes) == 2
    next(button for button in app.button if button.label == "Save synthetic report").click().run()
    assert not app.exception
    saved = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert saved.revision == 2
    assert saved.draft.blocks[0] == app.session_state["working"].blocks[0]
    fresh = AppTest.from_string(script).run()
    assert not fresh.exception
    remaining = retire_contributions(fresh.session_state["working"].blocks[0], (imported,))
    assert remaining.asset_hashes == imported.asset_hashes
    assert remaining.asset_captions == ("",)
    assert not asset_context(remaining, 0)
    assert sources.source_bytes(profile, source) == raw

