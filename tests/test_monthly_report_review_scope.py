from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_guided import MONTHLY_EDIT_KEYS, _standing_signature
from app.monthly_report_model import ResolvedBlock


@pytest.mark.parametrize("key", sorted(MONTHLY_EDIT_KEYS))
def test_monthly_section_edit_preserves_unrelated_site_information_review(key):
    monthly = ResolvedBlock(key, "This month", text="Previously checked monthly content")
    logo = ResolvedBlock("client_logo", "Library", asset_hashes=("approved-logo.png",))
    included = {key}

    before = _standing_signature((monthly, logo), included)
    after = _standing_signature((replace(monthly, text="Updated monthly content"), logo), included)

    assert after == before


@pytest.mark.parametrize("key", ("client_logo", "brand_logo", "cover_photo", "contact_matrix", "org_chart"))
def test_changed_site_information_still_requires_review(key):
    standing = ResolvedBlock(key, "Library", asset_hashes=("approved-content.png",))
    included = {key}

    before = _standing_signature((standing,), included)
    after = _standing_signature((replace(standing, asset_hashes=("replacement-content.png",)),), included)

    assert after != before


def test_omitted_site_information_does_not_invalidate_included_content_review():
    contacts = ResolvedBlock("contact_matrix", "Library", text="Old contact")
    assert _standing_signature((contacts,), set()) == _standing_signature(
        (replace(contacts, text="New contact"),), set()
    )


EDITOR_APP = '''
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import streamlit as st

from app.monthly_report_guided import _edit_content
from app.monthly_report_model import ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_ui import _field

key = "utility_analysis" if EDITOR_KIND == "text" else "thermal_capacity"
if "block" not in st.session_state:
    block = ResolvedBlock(
        key, "Last month",
        text="Previously reviewed utility results." if EDITOR_KIND == "text" else "",
        rows=(("Pine", "Heating", "100", "kW"),) if EDITOR_KIND == "table" else (),
        asset_hashes=("reviewed-chart.png",),
        asset_captions=("Reviewed results chart",),
    )
    st.session_state.original = replace(block, client_reviewed_fingerprint=block.fingerprint)
    st.session_state.block = st.session_state.original
image = BytesIO()
Image.new("RGB", (20, 20), "green").save(image, "PNG")
spec = next(b for s in default_sections() for b in s.blocks if b.key == key)
st.session_state.block = _edit_content(
    spec, st.session_state.block, SimpleNamespace(profile=synthetic_profiles()[0]),
    "review_scope", {"reviewed-chart.png": image.getvalue()}, _field,
)
'''


def editor_app(kind):
    return AppTest.from_string("EDITOR_KIND = " + repr(kind) + "\n" + EDITOR_APP).run()


@pytest.mark.parametrize("kind", ("text", "table"))
def test_viewing_imported_content_with_chart_preserves_source_and_approval(kind):
    app = editor_app(kind)
    assert not app.exception
    app.run()
    assert not app.exception
    assert app.session_state.block == app.session_state.original
    assert app.session_state.block.source == "Last month"
    assert app.session_state.block.client_reviewed_fingerprint == app.session_state.block.fingerprint


@pytest.mark.parametrize("kind", ("text", "table"))
def test_editing_imported_content_with_chart_invalidates_approval(kind):
    app = editor_app(kind)
    assert not app.exception
    if kind == "text":
        app.text_area[0].set_value("Updated utility results.").run()
    else:
        editor_key = next(
            key for key in app.session_state.filtered_state
            if key.startswith("review_scope_edit_thermal_capacity_table_")
            and not key.endswith(("_data", "_seed"))
        )
        # AppTest exposes data_editor edits through its widget state payload.
        app.session_state[editor_key] = {
            "edited_rows": {0: {"Capacity": 200.0}}, "added_rows": [], "deleted_rows": [],
        }
        app.run()
    assert not app.exception
    changed = app.session_state.block
    assert changed.source == "This month"
    assert changed.client_reviewed_fingerprint == ""
    assert changed.asset_hashes == app.session_state.original.asset_hashes
    if kind == "text":
        assert changed.text == "Updated utility results."
    else:
        assert float(changed.rows[0][2]) == 200
