from streamlit.testing.v1 import AppTest


SCRIPT = '''
from dataclasses import replace
from io import BytesIO
from PIL import Image
import streamlit as st
from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod, ReportSource, ResolvedBlock, default_sections
from app.monthly_report_editor import review_client_images
if "draft" not in st.session_state:
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    source = ReportSource("source", "Synthetic service report.pdf", "synthetic-source-hash", "pdf", page_texts=("First page", "Second page"), selected_pages=(1, 2))
    block = ResolvedBlock("vendor_reports", "This month", asset_hashes=("one.png", "two.png"),
                          asset_captions=("First caption", "Second caption"), references=(f"source:1:{source.fingerprint}", f"source:2:{source.fingerprint}"))
    st.session_state.draft = replace(draft, sections=(default_sections()[4],), blocks=(block,), sources=(source,))
    st.session_state.original = st.session_state.draft
if st.button("Rebuild original library block"):
    st.session_state.draft = st.session_state.original
assets = {}
for name, color in (("one.png", "blue"), ("two.png", "green")):
    image = BytesIO()
    Image.new("RGB", (20, 20), color).save(image, "PNG")
    assets[name] = image.getvalue()
if st.button("Change caption"):
    draft = st.session_state.draft
    block = draft.blocks[0]
    st.session_state.draft = replace(draft, blocks=(replace(block, asset_captions=("Changed caption", *block.asset_captions[1:])),))
st.session_state.draft = review_client_images(st.session_state.draft, assets, "synthetic", lambda k,v: k)
'''


def button(app, label):
    return next(w for w in app.button if w.label == label)


def test_only_pending_pages_are_shown_and_caption_change_reopens_one_picture():
    from app.monthly_report_asset_review import pending_asset_indexes

    app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    assert not app.selectbox and not app.checkbox
    button(app, "This page is ready to include").click().run()
    assert pending_asset_indexes(app.session_state.draft.blocks[0]) == (1,)
    assert any(c.value == "Second caption" for c in app.caption)
    assert not any(b.label in ("Previous page", "Next page") for b in app.button)
    button(app, "This page is ready to include").click().run()
    block = app.session_state.draft.blocks[0]
    assert block.client_reviewed_fingerprint == block.fingerprint
    assert not pending_asset_indexes(block)
    assert not any(b.label == "This page is ready to include" for b in app.button)
    assert not app.get("imgs")
    button(app, "Change caption").click().run()
    assert pending_asset_indexes(app.session_state.draft.blocks[0]) == (0,)
    assert any(c.value == "Changed caption" for c in app.caption)
    assert not any(c.value == "Second caption" for c in app.caption)
    button(app, "This page is ready to include").click().run()
    assert not pending_asset_indexes(app.session_state.draft.blocks[0])
    assert not app.exception


def test_remove_page_keeps_caption_source_alignment_and_hides_single_page_navigation():
    from app.monthly_report_asset_review import pending_asset_indexes

    app = AppTest.from_string(SCRIPT).run()
    original = app.session_state.draft
    button(app, "This page is ready to include").click().run()
    button(app, "Remove this page from report").click().run()
    block = app.session_state.draft.blocks[0]
    assert block.asset_hashes == ("one.png",)
    assert block.asset_captions == ("First caption",)
    assert block.references == (original.blocks[0].references[0],)
    assert not pending_asset_indexes(block)
    assert block.client_reviewed_fingerprint == block.fingerprint
    assert not any(w.label in ("Previous page", "Next page") for w in app.button)
    assert len(original.blocks[0].asset_hashes) == 2
    button(app, "View or edit").click().run()
    assert not any(w.label == "This page is ready to include" for w in app.button)
    button(app, "Remove this page from report").click().run()
    assert not app.session_state.draft.blocks[0].asset_hashes
    assert not app.session_state.draft.blocks[0].references
    assert not app.exception


def test_removed_pages_stay_removed_when_advanced_editor_reloads_library_source():
    app = AppTest.from_string(SCRIPT).run()
    button(app, "Remove this page from report").click().run()
    assert app.session_state.draft.blocks[0].asset_hashes == ("two.png",)
    button(app, "This page is ready to include").click().run()
    button(app, "Rebuild original library block").click().run()
    block = app.session_state.draft.blocks[0]
    assert block.asset_hashes == ("two.png",)
    assert block.client_reviewed_fingerprint == block.fingerprint
    button(app, "View or edit").click().run()
    button(app, "Remove this page from report").click().run()
    button(app, "Rebuild original library block").click().run()
    assert not app.session_state.draft.blocks[0].asset_hashes
    assert len(app.session_state.original.blocks[0].asset_hashes) == 2
    assert not app.exception


def test_partial_review_is_kept_after_unrelated_text_change_and_reload():
    from dataclasses import replace
    from app.monthly_report_asset_review import pending_asset_indexes

    app = AppTest.from_string(SCRIPT).run()
    button(app, "This page is ready to include").click().run()
    draft = app.session_state.draft
    app.session_state.draft = replace(draft, blocks=(replace(draft.blocks[0], text="Updated summary"),))
    app.run()
    assert pending_asset_indexes(app.session_state.draft.blocks[0]) == (1,)
    saved = app.session_state.draft
    resumed = AppTest.from_string(SCRIPT)
    resumed.session_state.draft = saved
    resumed.run()
    assert pending_asset_indexes(resumed.session_state.draft.blocks[0]) == (1,)
    assert any(c.value == "Second caption" for c in resumed.caption)
    assert not resumed.exception


def test_unreadable_picture_cannot_be_approved(monkeypatch):
    from app import monthly_report_library as library
    from dataclasses import replace

    app = AppTest.from_string(SCRIPT).run()
    draft = app.session_state.draft
    app.session_state.draft = replace(draft, blocks=(replace(draft.blocks[0], asset_hashes=("missing.png",)),))
    def unreadable(*args):
        raise ValueError("Missing asset")
    monkeypatch.setattr(library, "read_asset", unreadable)
    app.run()
    assert button(app, "This page is ready to include").disabled
    assert any("could not be displayed" in w.value for w in app.warning)
    assert not app.exception



def test_changed_source_page_reopens_only_affected_image_despite_session_approval_cache():
    from dataclasses import replace
    from app.monthly_report_asset_review import pending_asset_indexes

    app = AppTest.from_string(SCRIPT).run()
    button(app, "This page is ready to include").click().run()
    button(app, "This page is ready to include").click().run()
    draft = app.session_state.draft
    source = replace(draft.sources[0], page_texts=("Corrected first page", "Second page"))
    app.session_state.draft = replace(draft, sources=(source,))
    app.run()
    assert not app.exception
    assert pending_asset_indexes(app.session_state.draft.blocks[0]) == (0,)
    assert any(c.value == "First caption" for c in app.caption)
    assert not any(c.value == "Second caption" for c in app.caption)
    button(app, "This page is ready to include").click().run()
    assert not pending_asset_indexes(app.session_state.draft.blocks[0], app.session_state.draft.sources)
    app.run()
    assert not any(b.label == "This page is ready to include" for b in app.button)


def test_missing_source_cannot_be_restored_by_session_approval_cache():
    from dataclasses import replace
    from app.monthly_report_asset_review import asset_fingerprint, pending_asset_indexes

    app = AppTest.from_string(SCRIPT).run()
    button(app, "This page is ready to include").click().run()
    draft = app.session_state.draft
    app.session_state.draft = replace(draft, sources=())
    app.run()
    assert pending_asset_indexes(app.session_state.draft.blocks[0]) == (0, 1)
    assert button(app, "This page is ready to include").disabled
    # Even a stale callback for the unavailable context cannot mark it ready.
    block = app.session_state.draft.blocks[0]
    app.session_state["synthetic_client_vendor_reports_approved_pictures"] = tuple(asset_fingerprint(block, i) for i in range(2))
    app.run()
    assert pending_asset_indexes(app.session_state.draft.blocks[0]) == (0, 1)
    assert button(app, "This page is ready to include").disabled
    assert not app.exception
