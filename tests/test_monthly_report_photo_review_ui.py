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


def test_only_changed_photo_opens_until_all_photos_are_requested():
    from dataclasses import replace

    app = AppTest.from_string(SCRIPT).run()
    original = app.session_state.photos_draft
    block = replace(original.blocks[0], asset_captions=("First photo", "Changed second caption"))
    app.session_state.photos_draft = replace(original, blocks=(block,))
    app.run()
    assert [value.value for value in app.text_area] == ["Changed second caption"]
    assert pending_asset_indexes(app.session_state.photos_draft.blocks[0]) == (1,)
    app.text_area[0].set_value("Corrected second caption").run()
    assert app.session_state.photos_draft.blocks[0].asset_captions == ("First photo", "Corrected second caption")
    assert pending_asset_indexes(app.session_state.photos_draft.blocks[0]) == (1,)
    button(app, "Edit all photos or captions").click().run()
    assert [value.value for value in app.text_area] == ["First photo", "Corrected second caption"]
    assert not app.exception


def test_guided_photos_use_full_editor_width_without_a_duplicate_thumbnail():
    script = SCRIPT.replace('assets, _field)', 'assets, _field, show_preview=False)')
    app = AppTest.from_string(script).run()
    button(app, "Edit photos or captions").click().run()
    assert len(app.text_area) == 2
    assert not app.get("image")
    assert not app.get("column")
    assert not app.exception


def test_org_position_removal_is_one_action_and_retained_reporting_lines_are_valid():
    app = AppTest.from_string('''
from dataclasses import replace
import streamlit as st
from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod, ResolvedBlock, OrgChartNode
from app.monthly_report_ui import _field
from app.monthly_report_visual_ui import edit_org_chart
if "chart_draft" not in st.session_state:
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    block = ResolvedBlock("org_chart", "Library", org_nodes=(
        OrgChartNode("lead", "Synthetic Lead", "Manager"),
        OrgChartNode("worker", "Synthetic Worker", "Technician", "lead")))
    st.session_state.chart_draft = replace(draft, blocks=(block,))
draft = st.session_state.chart_draft
changed = edit_org_chart(draft, draft.blocks[0], "chart", {}, _field, show_preview=False)
st.session_state.chart_draft = replace(draft, blocks=(changed,))
''').run()
    assert not app.checkbox and not app.get("image")
    button(app, "Remove position").click().run()
    assert not app.exception
    nodes = app.session_state.chart_draft.blocks[0].org_nodes
    assert len(nodes) == 1 and nodes[0].key == "worker" and nodes[0].reports_to == ""
