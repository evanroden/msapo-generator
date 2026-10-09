"""Reviewed shared artwork is reusable; unknown or changed artwork stays gated."""

from dataclasses import replace
from io import BytesIO

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding, monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_asset_review import pending_asset_indexes
from app.monthly_report_model import ResolvedBlock, ReportPeriod, synthetic_profiles
from app.monthly_report_setup import new_month_draft
from app.monthly_report_start import design_seed


@pytest.fixture
def shared_logos(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    logos, assets = [], {}
    for key, color, contracts in (("client", "blue", (profile.contract,)), ("enfra", "green", ())):
        image = BytesIO()
        Image.new("RGB", (240, 80), color).save(image, "PNG")
        raw = image.getvalue()
        ref = library.asset_reference(raw, "png")
        assets[ref] = raw
        logos.append(branding.BrandLogo(key, "Synthetic " + key, contracts, ref,
                                       "https://example.invalid/brand", "https://example.invalid/logo.png",
                                       "2026-10-07"))
    branding.save_branding(tuple(logos), assets, expected_revision=0,
                          actor="Synthetic Reviewer", confirmed=True)
    return profile, tuple(logos), assets


def client_page_checks(draft):
    return {check.block_key for check in preflight(draft) if check.code == "client_pages"}


def test_shared_defaults_are_reviewed_and_carry_to_next_month_without_artwork_review(shared_logos):
    profile, logos, assets = shared_logos
    draft, loaded = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Editor")
    assert loaded == assets
    for key in ("client_logo", "brand_logo"):
        block = next(b for b in draft.blocks if b.key == key)
        assert block.client_reviewed_fingerprint == block.fingerprint
    assert not client_page_checks(draft)
    next_month = new_month_draft(draft, ReportPeriod(2026, 10))
    assert not client_page_checks(next_month)


def test_shared_defaults_do_not_review_pinned_custom_artwork_or_new_cover_photo(shared_logos):
    profile, logos, _ = shared_logos
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Editor")
    # Even identical image bytes in a previously pinned, unreviewed block are
    # not silently accepted by the empty-logo default path.
    custom = ResolvedBlock("client_logo", "Replace once", asset_hashes=(logos[0].asset,))
    photo = ResolvedBlock("cover_photo", "Replace once", asset_hashes=("unknown.png",))
    draft = replace(draft, blocks=tuple(custom if b.key == custom.key else photo if b.key == photo.key else b
                                       for b in draft.blocks))
    result = branding.apply_defaults(draft, {})
    assert next(b for b in result.blocks if b.key == "client_logo") == custom
    assert client_page_checks(result) == {"client_logo", "cover_photo"}


def test_explicit_shared_logo_choice_reuses_review_but_later_custom_replacement_needs_review(shared_logos):
    profile, logos, assets = shared_logos
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_branding_ui import offer_logo
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
block = st.session_state.setdefault("block", ResolvedBlock("client_logo", "Replace once", asset_hashes=("custom.png",)))
assets = st.session_state.setdefault("assets", {})
st.session_state["block"] = offer_logo(block, synthetic_profiles()[0].contract, "reuse", assets)
''').run()
    assert not app.exception
    assert not app.session_state["block"].client_reviewed_fingerprint
    next(button for button in app.button if button.label == "Use this logo in this report").click().run()
    assert not app.exception
    block = app.session_state["block"]
    assert block.asset_hashes == (logos[0].asset,)
    assert app.session_state["assets"][logos[0].asset] == assets[logos[0].asset]
    assert block.client_reviewed_fingerprint == block.fingerprint
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Editor")
    changed = replace(block, asset_hashes=("new-custom.png",))
    draft = replace(draft, blocks=tuple(changed if b.key == changed.key else b for b in draft.blocks))
    assert client_page_checks(draft) == {"client_logo"}


def test_shared_defaults_validate_saved_bytes_before_reusing_review(shared_logos):
    profile, logos, _ = shared_logos
    path = library._root() / "branding" / "assets" / logos[0].asset
    path.unlink()  # Stored objects are read-only; simulate a corrupt replacement.
    path.write_bytes(b"changed artwork")
    with pytest.raises(ValueError, match="fingerprint"):
        design_seed(profile, ReportPeriod(2026, 9), "Synthetic Editor")


def test_shared_logo_replacement_drops_old_per_picture_metadata(shared_logos):
    _, logos, _ = shared_logos
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_branding_ui import offer_logo
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
original = approve_all_assets(ResolvedBlock("client_logo", "Library", asset_hashes=("old-custom.png",), references=("old-origin",)))
block = st.session_state.setdefault("block", original)
st.session_state["block"] = offer_logo(block, synthetic_profiles()[0].contract, "reviewed-replacement", {})
''').run()
    assert not app.exception
    next(button for button in app.button if button.label == "Use this logo in this report").click().run()
    assert not app.exception
    assert app.session_state["block"].asset_hashes == (logos[0].asset,)
    assert not pending_asset_indexes(app.session_state["block"])
