from dataclasses import asdict, replace
from io import BytesIO
import json
from zipfile import ZipFile

from PIL import Image
import pytest

from app import monthly_report_branding as branding, monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_start import design_seed, save_design_start


def collection(color="green"):
    stream = BytesIO()
    Image.new("RGBA", (240, 80), color).save(stream, "PNG")
    raw = stream.getvalue()
    ref = library.asset_reference(raw, "png")
    logo = branding.BrandLogo("synthetic", "Synthetic client", (synthetic_profiles()[0].contract,), ref,
                             "https://example.invalid/brand", "https://example.invalid/logo.png", "2026-10-07")
    return (logo,), {ref: raw}


def bundle(logos, assets, extra=None):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema": 1, "logos": [asdict(v) for v in logos]}))
        for ref, raw in assets.items():
            archive.writestr("assets/" + ref, raw)
        if extra:
            archive.writestr(*extra)
    return stream.getvalue()


def test_bundle_validation_and_explicit_sources():
    logos, assets = collection()
    assert branding.inspect_bundle(bundle(logos, assets)) == (logos, assets)
    for extra in [("../outside.png", b"x"), ("script.svg", b"<svg/>"), ("assets/unlisted.png", b"x")]:
        with pytest.raises(ValueError, match="Only the listed"):
            branding.inspect_bundle(bundle(logos, assets, extra))
    with pytest.raises(ValueError, match="fingerprint"):
        branding.inspect_bundle(bundle(logos, {logos[0].asset: b"changed"}))
    with pytest.raises(ValueError, match="unique contract"):
        branding.inspect_bundle(bundle((*logos, replace(logos[0], key="duplicate")), assets))
    for bad in [replace(logos[0], source_url="file:///etc/passwd"), replace(logos[0], asset_url="https://user:password@example.invalid/a"), replace(logos[0], checked_on="yesterday")]:
        with pytest.raises(ValueError):
            branding.inspect_bundle(bundle((bad,), assets))


def test_oversized_or_non_png_image_is_rejected():
    logos, _ = collection()
    for size, fmt in [((2401, 2), "PNG"), ((5, 5), "JPEG")]:
        stream = BytesIO()
        Image.new("RGB", size).save(stream, fmt)
        ref = library.asset_reference(stream.getvalue(), "png")
        with pytest.raises(ValueError, match="PNG images"):
            branding.inspect_bundle(bundle((replace(logos[0], asset=ref),), {ref: stream.getvalue()}))


def test_versioned_branding_pins_saved_report_and_restores_without_erasing_history(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    logos, assets = collection()
    with pytest.raises(ValueError):
        branding.save_branding(logos, assets, expected_revision=0, actor="Synthetic Editor", confirmed=False)
    saved = branding.save_branding(logos, assets, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    assert saved.revision == 1 and branding.find_logo(logos[0].contracts[0]) == logos[0]
    draft, draft_assets = design_seed(synthetic_profiles()[0], ReportPeriod(2026, 9), "Synthetic Editor")
    logo = next(b for b in draft.blocks if b.key == "client_logo")
    assert logo.asset_hashes == (logos[0].asset,)
    save_design_start(draft, draft_assets, actor="Synthetic Editor", confirmed=True)
    updated, new_assets = collection("blue")
    branding.save_branding(updated, new_assets, expected_revision=1, actor="Synthetic Next Editor", confirmed=True)
    assert branding.apply_defaults(draft, {}).blocks == draft.blocks
    assert library.load_imported_draft(draft.profile.contract, draft.profile.key) == draft
    assert library.read_asset(draft.profile.contract, draft.profile.key, logo.asset_hashes[0]) == assets[logos[0].asset]
    with pytest.raises(library.RevisionConflict):
        branding.save_branding(logos, assets, expected_revision=1, actor="Synthetic Editor", confirmed=True)
    restored = branding.restore_branding(1, expected_revision=2, actor="Synthetic Editor", confirmed=True)
    assert restored.revision == 3 and restored.action == "restore:1"
    assert branding.load_branding(2).logos == updated
    assert branding.read_logo(restored.logos[0]) == assets[logos[0].asset]
    assert (tmp_path / "monthly_reports" / "branding" / "history" / "00000003.json").exists()


def test_empty_brand_and_client_defaults_and_explicit_omit(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    logos, assets = collection()
    brand = replace(logos[0], key="enfra", contracts=(), title="Synthetic report brand")
    branding.save_branding((*logos, brand), assets, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    draft, images = design_seed(synthetic_profiles()[0], ReportPeriod(2026, 9), "Synthetic Editor")
    assert {b.key for b in draft.blocks if b.asset_hashes} == {"client_logo", "brand_logo"}
    omitted = replace(draft, blocks=tuple(replace(b, source="Omit", asset_hashes=()) if b.key == "client_logo" else b for b in draft.blocks))
    assert branding.apply_defaults(omitted, images) == omitted


def test_section_choices_are_specific_and_cover_every_section():
    from app.monthly_report_model import default_sections
    from app.monthly_report_section_help import SECTION_HELP, section_help
    assert {s.key for s in default_sections()} <= SECTION_HELP.keys()
    assert len({v.edit for v in SECTION_HELP.values()}) == len(SECTION_HELP)
    assert "readings" in section_help("water").guidance
    assert "reporting lines" in section_help("organization").guidance
    assert "price" in section_help("proposals").guidance
