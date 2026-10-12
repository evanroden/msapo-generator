"""Real imperfect PDF pages: explicit review, exclusion, and final report output.

Uses the immutable archived vendor/water evidence (never client documents).
Synthetic headless output checks are NOT authentic owner/browser acceptance.
"""
from dataclasses import replace
from io import BytesIO
from shutil import which
from zipfile import ZipFile

import fitz
import pytest
from docx import Document

from app import monthly_report_library as library
from app import monthly_report_qa_fixture as fixture
from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_fingerprint, page_allowed
from app.monthly_report_docx import generate_report
from app.monthly_report_qa_imperfect_docs import load_pack
from app.monthly_report_section_uploads import prepare_section_pages
from app.monthly_report_testing import isolated


def _read_originals():
    with ZipFile(BytesIO(load_pack())) as archive:
        return (
            archive.read("QA_Vendor_Service_MixedPages.pdf"),
            archive.read("QA_Water_Treatment_MixedPages.pdf"),
        )


def _mark_reviewed(content, wanted):
    selected = replace(
        content.source, selected_pages=wanted,
        client_page_reviews=tuple(
            (n, page_fingerprint(content.source, n)) for n in wanted),
    )
    return replace(content, source=selected)


def test_actual_imperfect_pdf_review_filters_and_idempotence(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with isolated("e" * 32):
        fixture.prepare("prefill")
        profile = fixture.profile()
        vendor_bytes, water_bytes = _read_originals()
        vendor, _ = sources.ingest(profile, "QA_Vendor_Service_MixedPages.pdf", vendor_bytes)
        water, _ = sources.ingest(profile, "QA_Water_Treatment_MixedPages.pdf", water_bytes)

        # Upload alone cannot authorize client-facing page inclusion.
        with pytest.raises(ValueError, match="Check page 1"):
            prepare_section_pages(profile, (vendor,), "improvements", {})
        for n in (2, 3, 4, 5):
            # Even a forged review receipt cannot authorize blank, legal,
            # signature-only or pricing material.
            blocked = _mark_reviewed(vendor, (n,))
            assert not page_allowed(blocked.source, n)
            with pytest.raises(ValueError, match="Check page"):
                prepare_section_pages(profile, (blocked,), "improvements", {})

        vendor = _mark_reviewed(vendor, (1,))
        water = _mark_reviewed(water, (1, 2))
        assert all(page_allowed(vendor.source, n) for n in (1,))
        assert all(page_allowed(water.source, n) for n in (1, 2))
        activity = prepare_section_pages(profile, (vendor,), "improvements", {})
        chemical = prepare_section_pages(profile, (water,), "water_reports", activity)
        assert len(activity["improvements"].asset_hashes) == 1
        assert len(chemical["water_reports"].asset_hashes) == 2
        assert tuple(activity["improvements"].references) == (
            sources.source_reference(vendor.source, 1),)
        assert tuple(chemical["water_reports"].references) == (
            sources.source_reference(water.source, 1),
            sources.source_reference(water.source, 2))
        assert "service_calls" not in activity
        assert "service_calls" not in chemical
        assert prepare_section_pages(profile, (vendor,), "improvements", activity) == {}
        assert prepare_section_pages(profile, (water,), "water_reports", chemical) == {}
        assert all(library.read_asset(profile.contract, profile.key, ref)
                   for block in (*activity.values(), *chemical.values())
                   for ref in block.asset_hashes)


@pytest.mark.skipif(which("libreoffice") is None, reason="real PDF renderer unavailable")
def test_actual_imperfect_pdf_pages_survive_word_and_pdf_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with isolated("f" * 32):
        draft = fixture.prepare("prefill")
        profile = fixture.profile()
        vendor_bytes, water_bytes = _read_originals()
        vendor, _ = sources.ingest(profile, "QA_Vendor_Service_MixedPages.pdf", vendor_bytes)
        water, _ = sources.ingest(profile, "QA_Water_Treatment_MixedPages.pdf", water_bytes)
        vendor = _mark_reviewed(vendor, (1,))
        water = _mark_reviewed(water, (1, 2))
        activity = prepare_section_pages(profile, (vendor,), "improvements", {})
        chemistry = prepare_section_pages(profile, (water,), "water_reports", activity)
        existing = tuple(b for b in draft.blocks if b.key not in {"improvements", "water_reports"})
        final = replace(draft, blocks=(*existing, *activity.values(), *chemistry.values()),
                        sources=(*draft.sources, vendor.source, water.source))
        package = generate_report(final, acknowledged_fingerprint=final.fingerprint)
        assert package.docx and package.pdf, package.pdf_error
        assert package.docx.startswith(b"PK") and package.pdf.startswith(b"%PDF-")
        refs = activity["improvements"].references + chemistry["water_reports"].references
        assert len(refs) == len(set(refs)) == 3

        word = Document(BytesIO(package.docx))
        assert word is not None
        with ZipFile(BytesIO(package.docx)) as archive:
            media = [archive.read(n) for n in archive.namelist()
                     if n.startswith("word/media/") and not n.endswith("/")]
            assert media, "Reviewed technical document pictures did not reach Word output"
            xml = b"\n".join(archive.read(n) for n in archive.namelist()
                             if n.endswith(".xml"))
            assert b"$4,875.00" not in xml
            assert b"GENERAL TERMS AND CONDITIONS" not in xml
        with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
            assert len(pdf) >= 4
            assert sum(bool(p.get_images(full=True)) for p in pdf) >= 3
            text = "\n".join(p.get_text() for p in pdf)
            assert "$4,875.00" not in text
            assert "GENERAL TERMS AND CONDITIONS" not in text
