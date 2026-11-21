"""Synthetic canaries at the shared Monthly output boundary (Refs #458)."""
from dataclasses import replace
from hashlib import sha256

import pymupdf as fitz
import pytest

from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_checks import preflight
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_docx import assemble_docx, generate_report
from app.monthly_report_financial_policy import financial_output_gate
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock,
    SectionSpec, synthetic_profiles,
)
from app.monthly_report_preview import preview_report, section_preview_docx

CANARY = "Invoice total: $12,345.67"


def source_picture(profile, *, raster_only):
    # Construct a PDF with a real visible monetary canary. The raster variant
    # contains the same pixels but deliberately has no extractable text.
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 80), CANARY)
        image = page.get_pixmap().tobytes("png")
        raw = pdf.tobytes()
    if raster_only:
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_image(page.rect, stream=image)
            raw = pdf.tobytes()
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        page_text = pdf[0].get_text()
        assert bool(page_text.strip()) != raster_only
    digest = sha256(raw).hexdigest()
    source = ReportSource(digest, "synthetic-page.pdf", digest, ".pdf",
                          facility=profile.facilities[0].title,
                          page_texts=(page_text,), selected_pages=(1,),
                          needs_vision=(1,) if raster_only else ())
    if not raster_only:
        # A generic review receipt cannot authorize known monetary text.
        source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    reference = f"{source.id}:1:{source.fingerprint}"
    asset = sha256(image).hexdigest() + ".png"
    block = approve_all_assets(ResolvedBlock(
        "vendor_reports", "This month", asset_hashes=(asset,),
        references=(reference,), asset_provenance=((asset, (reference,)),)))
    return source, block, image


@pytest.mark.parametrize("route", ["text", "caption", "pdf_page", "source_image"])
def test_monetary_canary_blocked_before_word_pdf_and_previews(route):
    profile = synthetic_profiles()[0]
    sources = ()
    image = b""
    if route in ("pdf_page", "source_image"):
        source, block, image = source_picture(profile, raster_only=route == "source_image")
        sources = (source,)
        spec = BlockSpec(block.key, "pdf_pages")
    elif route == "caption":
        spec = BlockSpec("vendor_reports", "pdf_pages")
        block = approve_all_assets(ResolvedBlock(
            spec.key, "This month", asset_hashes=("synthetic.png",),
            asset_captions=(CANARY,)))
    else:
        spec = BlockSpec("activity_summary", "rich_text")
        block = ResolvedBlock(spec.key, "This month", text=CANARY)
    section = SectionSpec("activity", "2", "Synthetic activity", (spec,))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor",
                        (section,), (block,), sources=sources)
    assert any(c.code == "pricing" and c.blocking for c in preflight(draft))
    # A monetary block must occur before the image is assembled or PDF
    # conversion is attempted. The loader supplies only synthetic bytes.
    loader = lambda ref: image
    match = "pricing|non-financial"
    with pytest.raises(ValueError, match=match):
        assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
    with pytest.raises(ValueError, match=match):
        generate_report(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
    with pytest.raises(ValueError, match=match):
        preview_report(draft, asset_loader=loader)
    with pytest.raises(ValueError, match=match):
        section_preview_docx(draft, section.key, asset_loader=loader)


def test_generic_review_is_exact_and_does_not_authorize_changed_raster():
    profile = synthetic_profiles()[0]
    source, _, _ = source_picture(profile, raster_only=True)
    assert not financial_output_gate(source=source, page=1).allowed
    # A trusted visual review of the exact page is the existing non-financial
    # admission rule. Here we exercise binding, not claim the canary is safe.
    technical = replace(source, sha256="b" * 64, page_texts=("Synthetic diagram",))
    reviewed = replace(technical, client_page_reviews=((1, page_fingerprint(technical, 1)),))
    assert financial_output_gate(source=reviewed, page=1).allowed
    assert not financial_output_gate(source=replace(reviewed, sha256="c" * 64), page=1).allowed
    assert not financial_output_gate(text=CANARY, destination="accounts_receivable").allowed
    assert financial_output_gate(text="Status only: invoice pending").allowed
    assert financial_output_gate().allowed  # Direct photographs are unchanged.
