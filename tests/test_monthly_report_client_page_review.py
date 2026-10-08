from streamlit.testing.v1 import AppTest


SCRIPT = '''
from dataclasses import replace
from io import BytesIO
from PIL import Image
import streamlit as st
from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod, ResolvedBlock, default_sections
from app.monthly_report_editor import review_client_images
if "draft" not in st.session_state:
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    block = ResolvedBlock("vendor_reports", "This month", asset_hashes=("one.png", "two.png"),
                          asset_captions=("First caption", "Second caption"), references=("source:1:hash", "source:2:hash"))
    st.session_state.draft = replace(draft, sections=(default_sections()[4],), blocks=(block,))
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


def test_every_page_is_individually_confirmed_and_content_changes_invalidate():
    app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    assert not app.selectbox and not app.checkbox
    button(app, "This page is ready to include").click().run()
    assert not app.session_state.draft.blocks[0].client_reviewed_fingerprint
    assert button(app, "This page is ready to include").disabled
    button(app, "Next page").click().run()
    assert not button(app, "This page is ready to include").disabled
    button(app, "This page is ready to include").click().run()
    block = app.session_state.draft.blocks[0]
    assert block.client_reviewed_fingerprint == block.fingerprint
    button(app, "Change caption").click().run()
    assert not app.session_state.draft.blocks[0].client_reviewed_fingerprint
    assert not button(app, "This page is ready to include").disabled
    assert not app.exception


def test_remove_page_keeps_caption_source_alignment_and_hides_single_page_navigation():
    app = AppTest.from_string(SCRIPT).run()
    original = app.session_state.draft
    button(app, "This page is ready to include").click().run()
    button(app, "Next page").click().run()
    button(app, "Remove this page from report").click().run()
    block = app.session_state.draft.blocks[0]
    assert block.asset_hashes == ("one.png",)
    assert block.asset_captions == ("First caption",)
    assert block.references == ("source:1:hash",)
    assert block.client_reviewed_fingerprint == block.fingerprint
    assert not any(w.label in ("Previous page", "Next page") for w in app.button)
    assert len(original.blocks[0].asset_hashes) == 2
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
    button(app, "Remove this page from report").click().run()
    button(app, "Rebuild original library block").click().run()
    assert not app.session_state.draft.blocks[0].asset_hashes
    assert len(app.session_state.original.blocks[0].asset_hashes) == 2
    assert not app.exception
