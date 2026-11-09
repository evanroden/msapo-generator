"""Untrusted saved logo titles render literally in the Monthly report offer.

A logo's display name is not Markdown or a link. The saved title, contract,
source URLs, byte-verified PNG, and report-only replacement stay unchanged.
The native UI is exercised without any external URL or paid calls.
"""
from io import BytesIO

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding
from app import monthly_report_library as library
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
from app.monthly_report_ui_text import literal


APP = """
import streamlit as st
from app.monthly_report_branding_ui import offer_logo

assets = st.session_state.setdefault("result_assets", {})
block = st.session_state.setdefault("result_block", st.session_state["initial_block"])
result = offer_logo(block, st.session_state["contract"], "test_logo_title", assets,
                    scope=("synthetic", "2026-09"))
st.session_state["result_block"] = result
"""


def install(monkeypatch, tmp_path, title):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    output = BytesIO()
    Image.new("RGB", (180, 72), (50, 100, 130)).save(output, format="PNG")
    raw = output.getvalue()
    ref = library.asset_reference(raw, "png")
    logo = branding.BrandLogo(
        "synthetic_client", title, (profile.contract,), ref,
        "https://example.invalid/brand", "https://example.invalid/image.png",
        "2026-10-07",
    )
    saved = branding.save_branding(
        (logo,), {ref: raw}, expected_revision=0,
        actor="Synthetic Reviewer", confirmed=True,
    )
    app = AppTest.from_string(APP, default_timeout=20)
    app.session_state["contract"] = profile.contract
    app.session_state["initial_block"] = ResolvedBlock("client_logo", "Omit")
    app.run()
    assert not app.exception
    return app, saved, logo, raw


@pytest.mark.parametrize("title", (
    "[Synthetic](https://example.invalid) **Client**",
    "www.example.invalid [Asset](https://example.invalid/a)",
    "**Important** _synthetic_ report logo",
    "contact@example.invalid",
    "Normal synthetic company logo",
))
def test_saved_logo_offer_escapes_gfm_markup_and_autolinks_without_rewriting_data(
        monkeypatch, tmp_path, title):
    app, saved, logo, raw = install(monkeypatch, tmp_path, title)
    expected = ("Available: " + literal(title)
                + " · official source checked 2026-10-07")
    assert [c.value for c in app.caption if c.value.startswith("Available: ")] == [expected]
    assert branding.load_branding() == saved
    assert branding.find_logo(logo.contracts[0]) == logo
    assert branding.read_logo(logo) == raw
    assert app.session_state["result_block"] == ResolvedBlock("client_logo", "Omit")
    assert app.session_state["result_assets"] == {}
    assert sum(b.label == "Add this logo to this report" for b in app.button) == 1

    # Passive reentry cannot use a logo, create a false approval or alter the
    # exact saved description, origin URLs, image bytes or history.
    app.run()
    assert not app.exception
    assert [c.value for c in app.caption if c.value.startswith("Available: ")] == [expected]
    assert branding.load_branding() == saved
    assert app.session_state["result_block"].source == "Omit"

    next(b for b in app.button if b.label == "Add this logo to this report").click().run()
    assert not app.exception
    actual = app.session_state["result_block"]
    assert actual.source == "Replace once"
    assert actual.asset_hashes == (logo.asset,)
    assert actual.asset_captions == ()
    assert actual.references == ()
    assert app.session_state["result_assets"] == {logo.asset: raw}
    assert branding.load_branding() == saved
    assert branding.read_logo(logo) == raw
    app.run()
    assert app.session_state["result_block"] == actual
    assert not any(b.label == "Add this logo to this report" for b in app.button)


def test_existing_explicit_report_logo_is_not_replaced_by_passive_display(
        monkeypatch, tmp_path):
    app, saved, logo, raw = install(monkeypatch, tmp_path,
        "[Verified](https://example.invalid) **Title**")
    prior = ResolvedBlock("client_logo", "This month",
                          asset_hashes=("synthetic-other.png",),
                          asset_captions=("Retain report-only caption",),
                          references=("synthetic-source",))
    app.session_state["result_block"] = prior
    app.run()
    assert not app.exception
    assert app.session_state["result_block"] == prior
    assert branding.load_branding() == saved
    assert "Use this logo in this report" in [b.label for b in app.button]
    # Moving focus/reading the candidate does not overwrite an authored block.
    app.run()
    assert app.session_state["result_block"] == prior


def test_logo_branding_admin_keeps_title_as_native_text_not_a_generated_link(
        monkeypatch, tmp_path):
    app, saved, logo, _ = install(monkeypatch, tmp_path,
        "[Untrusted](https://example.invalid) **synthetic**")
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_branding_ui import render_branding

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

render_branding(field)
""").run()
    assert not app.exception
    # The selector/dataframe are native text widgets; they must not change
    # stored names merely to make presentation safe.
    assert any(select.label == "Logo to inspect" for select in app.selectbox)
    assert branding.load_branding() == saved
