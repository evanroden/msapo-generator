"""Malformed saved page identities remain correctable without authorizing output."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from docx import Document
from docx.shared import Inches
import pytest

from app import monthly_report_library as library
from app.monthly_report_asset_layout import (
    document_page_indexes, photo_preview_references, picture_runs,
)
from app.monthly_report_asset_review import (
    approve_all_assets, pending_asset_indexes, refresh_asset_source_context,
)
from app.monthly_report_checks import preflight
from app.monthly_report_correction_targets import resolve_target
from app.monthly_report_docx import _build_docx, assemble_docx, estimate_bytes, outline
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_preview import section_preview_fingerprint
from tests.test_monthly_report_asset_layout import payload
from tests.test_monthly_report_native_layout import draft as report


BAD_PAGES = ("²", "①", "١", "１", "0", "-1", "+1", "1.0", "1234567", "9" * 5000)
BAD_IDS = ("superscript", "circled", "arabic-indic", "fullwidth", "zero",
           "negative", "signed", "decimal", "overlong", "oversized")


def sample(page, *, approved=False):
    block, source, assets = payload()
    reference = f"{source.id}:{page}:{source.fingerprint}"
    block = replace(block, references=(reference,),
        asset_provenance=tuple((asset, (reference,) if index == 1 else ())
                               for index, asset in enumerate(block.asset_hashes)))
    if approved:
        block = approve_all_assets(block)
    draft = report(block)
    return replace(draft, profile=replace(draft.profile, template="enfra_builtin:monthly"),
                   sources=(source,)), assets


@pytest.mark.parametrize("page", BAD_PAGES, ids=BAD_IDS)
def test_invalid_page_identity_keeps_preview_layout_and_explicit_review_gate(page):
    draft, assets = sample(page, approved=True)
    before = draft.fingerprint
    block, = draft.blocks
    assert document_page_indexes(block, draft.sources) == set()
    assert tuple(picture_runs(block, draft.sources)) == ((False, (0, 1, 2)),)
    assert photo_preview_references(draft) == set(block.asset_hashes)
    assert estimate_bytes(draft, assets.__getitem__) > 0
    assert outline(draft)[0][2] > 0

    # A saved approval is not authority for malformed source provenance.
    assert 1 in pending_asset_indexes(block, draft.sources)
    checks = preflight(draft)
    review = next(check for check in checks if check.code == "client_pages")
    assert review.blocking
    assert any(resolve_target(draft, target) == (block, 1, None)
               for target in review.targets)
    with pytest.raises(ValueError, match="Check .*picture"):
        assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint,
                      asset_loader=assets.__getitem__)
    assert draft.fingerprint == before
    assert draft.blocks[0].references == block.references
    assert all(sha256(raw).hexdigest() + ".png" == asset for asset, raw in assets.items())


@pytest.mark.parametrize("page", ("²", "9" * 5000), ids=("superscript", "oversized"))
def test_public_preflight_returns_picture_correction_instead_of_numeral_exception(page):
    draft, _ = sample(page, approved=True)
    checks = preflight(draft)
    review = next(check for check in checks if check.code == "client_pages")
    assert review.blocking
    assert any(resolve_target(draft, target) == (draft.blocks[0], 1, None)
               for target in review.targets)


@pytest.mark.parametrize("page", ("1", "01", "000001"))
def test_valid_and_padded_page_layout_remains_separate_from_photos(page):
    draft, assets = sample(page)
    block, = draft.blocks
    assert document_page_indexes(block, draft.sources) == {1}
    assert tuple(picture_runs(block, draft.sources)) == (
        (False, (0,)), (True, (1,)), (False, (2,)))
    assert photo_preview_references(draft) == {block.asset_hashes[0], block.asset_hashes[2]}
    assert any(check.blocking for check in preflight(draft) if check.code == "client_pages")
    assert estimate_bytes(draft, assets.__getitem__) > 0
    reviewed = approve_all_assets(refresh_asset_source_context(block, draft.sources))
    approved = replace(draft, blocks=(reviewed,))
    assert not pending_asset_indexes(reviewed, draft.sources)
    assert not any(check.code == "client_pages" for check in preflight(approved))
    assert document_page_indexes(reviewed, draft.sources) == {1}
    assert approved.blocks[0].references == block.references


@pytest.mark.parametrize("change", ("missing", "stale", "duplicate_source", "unselected"))
def test_existing_invalid_source_authority_never_becomes_document_layout(change):
    draft, _ = sample("1")
    source, = draft.sources
    if change == "missing":
        draft = replace(draft, sources=())
    elif change == "stale":
        draft = replace(draft, sources=(replace(source, service_date="2026-10-01"),))
    elif change == "duplicate_source":
        draft = replace(draft, sources=(source, source))
    else:
        draft = replace(draft, sources=(replace(source, selected_pages=()),))
    assert document_page_indexes(draft.blocks[0], draft.sources) == set()
    assert any(check.blocking for check in preflight(draft))
    if change == "missing":
        assert any(check.code == "client_source_missing" for check in preflight(draft))


@pytest.mark.parametrize("page", ("²", "9" * 5000, "000001"), ids=("superscript", "oversized", "padded"))
def test_storage_preview_identity_retains_unchanged_report(tmp_path, monkeypatch, page):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft, _ = sample(page)
    before = draft.fingerprint
    assert len(section_preview_fingerprint(draft, "activity")) == 64
    assert draft.fingerprint == before


@pytest.mark.parametrize("page", ("²", "9" * 5000), ids=("superscript", "oversized"))
def test_storage_generic_and_native_word_keep_original_pictures_and_captions(tmp_path, monkeypatch, page):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft, assets = sample(page)
    block, = draft.blocks
    before = draft.fingerprint
    # Layout-only assembly supports the unfinished editing preview. The public
    # final assembler remains blocked above; this does not approve these pages.
    generic = Document(BytesIO(_build_docx(draft, asset_loader=assets.__getitem__)))
    assert generic.inline_shapes
    assert block.references[0] not in "\n".join(p.text for p in generic.paragraphs)

    native = Document()
    native.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    native.add_paragraph("Improvement Highlights and Pics")
    native.add_picture(BytesIO(next(iter(assets.values()))), width=Inches(6), height=Inches(1.8))
    native.add_picture(BytesIO(next(iter(assets.values()))), width=Inches(4), height=Inches(2))
    path = tmp_path / "synthetic-native-layout.docx"
    native.save(path)
    original = path.read_bytes()
    output = Document(BytesIO(build_native_docx(draft, path, asset_loader=assets.__getitem__)))
    assert len(output.inline_shapes) == 3
    output_assets = [sha256(output.part.related_parts[
        shape._inline.graphic.graphicData.pic.blipFill.blip.embed].blob).hexdigest() + ".png"
        for shape in output.inline_shapes]
    assert output_assets == list(block.asset_hashes)
    assert [p.text for p in output.paragraphs if p.text in block.asset_captions] == list(block.asset_captions)
    assert path.read_bytes() == original
    assert draft.fingerprint == before


def test_saved_reopened_bad_identity_keeps_evidence_and_historical_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft, assets = sample("²", approved=True)
    before = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by,
                                   assets=tuple(assets.items()))
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened == before
    assert {asset: library.read_asset(draft.profile.contract, draft.profile.key, asset)
            for asset in assets} == assets
    assert any(check.code == "client_pages" and check.blocking for check in preflight(reopened.draft))
    assert section_preview_fingerprint(reopened.draft, "activity")
    corrected, _ = sample("1")
    library.save_snapshot(corrected, expected_revision=1, entered_editor=draft.prepared_by)
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key, draft.period, 1) == before
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft == corrected
    assert {asset: library.read_asset(draft.profile.contract, draft.profile.key, asset)
            for asset in assets} == assets

