"""Synthetic regression for early source-page caption length preflight.

The final Word renderers already enforce document_caption_problems; this suite
ensures the same measured rule is actionable before file generation. Photo
captions and explicitly excluded work are deliberately unaffected.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest

from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx, _build_docx
from app.monthly_report_asset_layout import document_page_indexes, document_caption_problems
from app.monthly_report_model import ResolvedBlock
from tests.test_monthly_report_asset_layout import payload
from tests.test_monthly_report_native_layout import draft


def report_with_caption(caption, *, omitted=False, remove_source=False):
    block, source, assets = payload()
    block = replace(
        block,
        asset_captions=("Ordinary photo A", caption, "Ordinary photo B"),
        source="Omit" if omitted else "This month",
    )
    active_sources = () if remove_source else (source,)
    return replace(draft(block), sources=active_sources), assets, source


def check_captions(report):
    return tuple(check for check in preflight(report)
                 if check.code == "document_caption")


@pytest.mark.parametrize("caption", (
    "Very long synthetic source finding. " * 80,
    "\n".join(("Line one", "Line two", "Line three", "Line four")),
    "W" * 500,
))
def test_oversized_standalone_pdf_page_caption_is_a_blocking_preflight_check(caption):
    report, assets, _ = report_with_caption(caption)
    block, = report.blocks
    assert document_page_indexes(block, report.sources) == {1}
    assert document_caption_problems(block, report.sources) == (1,)
    checks = check_captions(report)
    assert len(checks) == 1
    assert checks[0].blocking is True
    assert checks[0].block_key == "improvements"
    assert "picture 2" in checks[0].message
    assert "three lines" in checks[0].message
    assert "improvements" in checks[0].message
    with pytest.raises(ValueError, match="source-page caption"):
        assemble_docx(report, acknowledged_fingerprint=report.fingerprint,
                      asset_loader=assets.__getitem__)
    # Preflight rejection has no effect on report input or original asset bytes.
    assert report.blocks[0] == block
    assert assets


@pytest.mark.parametrize("caption", (
    "A brief standalone source-page finding.",
    "\n".join(("Line one", "Line two", "Line three")),
))
def test_acceptable_source_caption_does_not_acquire_new_preflight_blocker(caption):
    report, assets, _ = report_with_caption(caption)
    assert document_caption_problems(report.blocks[0], report.sources) == ()
    assert check_captions(report) == ()
    # Existing ordinary photo and price/page-approval gates remain independent.
    assert all(check.code != "document_caption" for check in preflight(report))


def test_long_ordinary_photo_caption_does_not_use_pdf_standalone_limit():
    block, source, assets = payload()
    no_document = replace(
        block,
        asset_provenance=(),
        references=(),
        asset_captions=("Long ordinary photo caption " * 80, "Keep photo B", "Photo C"),
    )
    report = replace(draft(no_document), sources=(source,))
    assert document_page_indexes(no_document, report.sources) == set()
    assert check_captions(report) == ()
    assert no_document.asset_captions[0].startswith("Long ordinary photo")


def test_an_explicitly_omitted_image_block_is_not_forced_back_into_review():
    report, _, _ = report_with_caption("Caption too long " * 150, omitted=True)
    assert check_captions(report) == ()
    assert report.blocks[0].source == "Omit"


def test_excluded_section_is_not_flagged_for_its_old_source_page_caption():
    report, _, _ = report_with_caption("Caption too long " * 150)
    removed = replace(report, sections=tuple(
        replace(section, included=False) if section.key == "activity" else section
        for section in report.sections))
    assert check_captions(removed) == ()
    assert check_captions(report)
    assert removed.blocks == report.blocks


def test_missing_or_changed_source_receipt_cannot_claim_document_caption_identity():
    report, _, original = report_with_caption("Caption too long " * 150)
    assert check_captions(report)
    missing = replace(report, sources=())
    assert check_captions(missing) == ()
    modified = replace(report, sources=(replace(original, service_date="2026-09-01"),))
    assert check_captions(modified) == ()
    # A missing source is an independent preflight source/approval issue.
    assert report.blocks[0].asset_hashes == missing.blocks[0].asset_hashes


def test_mixed_photo_document_order_reports_only_document_occurrence():
    report, _, source = report_with_caption("Too much source detail " * 120)
    block = report.blocks[0]
    assert len(block.asset_hashes) == 3
    assert document_page_indexes(block, report.sources) == {1}
    checks = check_captions(report)
    assert len(checks) == 1 and "picture 2" in checks[0].message
    # Omission of the one PDF-page image removes only that new blocker; the
    # two remaining ordinary photographs keep their caption/source identity.
    photos = replace(
        block,
        asset_hashes=(block.asset_hashes[0], block.asset_hashes[2]),
        asset_captions=(block.asset_captions[0], block.asset_captions[2]),
        asset_provenance=(),
        references=(),
    )
    changed = replace(report, blocks=(photos,))
    assert check_captions(changed) == ()
    assert photos.asset_captions == ("Ordinary photo A", "Ordinary photo B")
