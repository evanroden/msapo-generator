"""Optional photo editing keeps other pictures ready and removes in one action."""
from streamlit.testing.v1 import AppTest

from app.monthly_report_asset_review import pending_asset_indexes


SCRIPT = '''
from dataclasses import replace
from io import BytesIO
from PIL import Image
import streamlit as st
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod, ResolvedBlock
from app.monthly_report_ui import _field
from app.monthly_report_visual_ui import edit_photos
if "photos_draft" not in st.session_state:
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    block = approve_all_assets(ResolvedBlock("improvements", "Last month", asset_hashes=("one.png", "two.png"), asset_captions=("First photo", "Second photo")))
    st.session_state.photos_draft = replace(draft, blocks=(block,))
assets = {}
for name, color in (("one.png", "blue"), ("two.png", "green")):
    image = BytesIO()
    Image.new("RGB", (20, 20), color).save(image, "PNG")
    assets[name] = image.getvalue()
draft = st.session_state.photos_draft
block = edit_photos(draft, draft.blocks[0], "photos", assets, _field)
st.session_state.photos_draft = replace(draft, blocks=(block,))
'''


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_reviewed_photos_show_ready_until_edit_and_caption_change_is_local():
    app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    assert not app.text_area and not app.checkbox and not app.select_slider
    assert not pending_asset_indexes(app.session_state.photos_draft.blocks[0])
    button(app, "Edit photos or captions").click().run()
    assert len(app.text_area) == 2
    app.text_area[0].set_value("A corrected first caption").run()
    assert not app.exception
    block = app.session_state.photos_draft.blocks[0]
    assert block.asset_captions == ("A corrected first caption", "Second photo")
    assert pending_asset_indexes(block) == (0,)
    assert not app.checkbox
    button(app, "Remove photo").click().run()
    block = app.session_state.photos_draft.blocks[0]
    assert block.asset_hashes == ("two.png",)
    assert block.asset_captions == ("Second photo",)
    assert not pending_asset_indexes(block)
    assert not app.exception


def test_layout_change_preserves_review_and_unchanged_caption_edits_are_noops():
    app = AppTest.from_string(SCRIPT).run()
    button(app, "Edit photos or captions").click().run()
    app.select_slider[0].set_value(3).run()
    assert app.session_state.photos_draft.blocks[0].photos_per_page == 3
    assert not pending_asset_indexes(app.session_state.photos_draft.blocks[0])
    app.text_area[0].set_value("First photo").run()
    assert not pending_asset_indexes(app.session_state.photos_draft.blocks[0])
    button(app, "Done editing photos").click().run()
    assert not app.text_area and not app.select_slider
    assert not app.exception
