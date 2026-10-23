"""Synthetic controls for cover defaults, without borrowing another site's photo.

These controls distinguish a configured, exact-site standing photograph from
the separate company/client logo catalog. They do not establish production
configuration or browser/PDF acceptance.
"""

from dataclasses import replace
from io import BytesIO

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_guided import _initial_draft
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_setup import new_month_draft
from app.monthly_report_start import design_seed, read_starting_state
from test_monthly_report_ui import ROOT, choose_report


def _picture(size=(400, 300), color="navy"):
    stream = BytesIO()
    Image.new("RGBA", size, color).save(stream, "PNG")
    raw = stream.getvalue()
    return library.asset_reference(raw, "png"), raw


def _cover(draft):
    return next(block for block in draft.blocks if block.key == "cover_photo")


def _standing_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = replace(synthetic_profiles()[0], contract=RRH_CONTRACT,
                      key="synthetic-default-cover")
    state = library.save_profile(profile, expected_revision=0,
                                 actor="Synthetic Editor", confirmed=True)
    reference, raw = _picture()
    photograph = ResolvedBlock("cover_photo", "Library", asset_hashes=(reference,))
    state = library.replace_block(profile.contract, profile.key, "cover_photo", photograph,
                                  assets=((reference, raw),), expected_revision=state.revision,
                                  actor="Synthetic Editor", confirmed=True, label="Cover photo")
    return state, state.block("cover_photo"), raw


def test_exact_site_standing_photo_loads_on_first_guided_render_without_import(monkeypatch, tmp_path):
    state, photograph, raw = _standing_profile(monkeypatch, tmp_path)
    from app import monthly_report_section_preview_ui
    monkeypatch.setattr(monthly_report_section_preview_ui, "render_section_preview", lambda *a, **kw: None)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, state.profile.facilities[0].title)
    assert not app.exception
    draft = next(value for key, value in app.session_state.filtered_state.items()
                 if key.startswith("report_guided_") and key.endswith("_draft")
                 and isinstance(value, ReportDraft))
    assert _cover(draft).asset_hashes == photograph.asset_hashes
    assert _cover(draft).source == photograph.source
    assert _cover(draft).references == photograph.references
    assert library.read_asset(state.profile.contract, state.profile.key,
                              photograph.asset_hashes[0]) == raw
    assert library.load_imported_draft(state.profile.contract, state.profile.key) is None


@pytest.mark.parametrize("source", ["Library", "Replace once", "Omit"])
def test_saved_same_site_cover_choice_survives_reporting_gap_without_upload(monkeypatch, tmp_path, source):
    state, photograph, raw = _standing_profile(monkeypatch, tmp_path)
    august = _initial_draft(state, ReportPeriod(2026, 8), "Synthetic Editor")
    august = replace(august, blocks=tuple(replace(block, source=source) if block.key == "cover_photo"
                                          else block for block in august.blocks))
    library.save_snapshot(august, expected_revision=0, entered_editor="Synthetic Editor")
    imported, _, prior = read_starting_state(state.profile.contract, state.profile.key,
                                            ReportPeriod(2026, 10))
    assert imported is None and prior == august
    october = new_month_draft(prior, ReportPeriod(2026, 10))
    assert _cover(october).asset_hashes == photograph.asset_hashes
    assert _cover(october).source == source
    assert library.read_asset(state.profile.contract, state.profile.key,
                              photograph.asset_hashes[0]) == raw


def test_other_site_design_does_not_borrow_configured_photo(monkeypatch, tmp_path):
    state, photograph, _ = _standing_profile(monkeypatch, tmp_path)
    other = replace(synthetic_profiles()[1], contract=state.profile.contract,
                    key="synthetic-other-site-cover")
    draft, assets = design_seed(other, ReportPeriod(2026, 10), "Synthetic Editor", state)
    assert not _cover(draft).asset_hashes
    assert photograph.asset_hashes[0] not in assets
    assert draft.profile.facilities == other.facilities


def test_fresh_design_automatically_uses_exact_logo_catalog_but_not_photo(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    logos, assets = [], {}
    for key, contracts, color in (("enfra", (), "green"),
                                   ("synthetic-client", (profile.contract,), "blue")):
        reference, raw = _picture((240, 80), color)
        assets[reference] = raw
        logos.append(branding.BrandLogo(key, "Synthetic " + key, contracts, reference,
                                       "https://example.invalid/brand", "https://example.invalid/brand.png",
                                       "2026-10-21"))
    branding.save_branding(tuple(logos), assets, expected_revision=0,
                           actor="Synthetic Editor", confirmed=True)
    draft, selected_assets = design_seed(profile, ReportPeriod(2026, 10), "Synthetic Editor")
    included = {block.key: block for block in draft.blocks if block.asset_hashes}
    assert set(included) == {"brand_logo", "client_logo"}
    assert included["brand_logo"].asset_hashes == (logos[0].asset,)
    assert included["client_logo"].asset_hashes == (logos[1].asset,)
    assert selected_assets == assets
    assert not _cover(draft).asset_hashes
