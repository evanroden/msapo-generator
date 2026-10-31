"""Bounded integration controls for recovered generated contents.

The local/hosted renderer is not Microsoft Word acceptance. Arbitrary native
contents stay passive and retain the separate unavailable-update notice.
"""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from docx import Document
from docx.oxml.ns import qn
import pymupdf as fitz
import pytest

from app import monthly_report_docx as renderer
from app.monthly_report_contents_pagination import anchor_for, synchronize
from app.monthly_report_model import included_sections
from test_monthly_report_contents_pagination import cached_pages, current_report, image
from tests.conftest import requires_libreoffice


@requires_libreoffice
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_display_titles_keep_distinct_section_targets(tmp_path, monkeypatch, reverse):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    draft = current_report(pages=3, reverse=reverse)
    draft = replace(draft, sections=tuple(
        replace(section, title="Monthly status") if section.included else section
        for section in draft.sections))
    package = renderer.generate_report(draft, acknowledged_fingerprint=draft.fingerprint,
                                       asset_loader=image)
    assert package.pdf, package.pdf_error
    assert package.contents_notice == ""
    expected = included_sections(draft.sections)
    assert len({anchor_for(section.key) for section in expected}) == 2
    cache = cached_pages(package.docx)
    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        outlines = pdf.get_toc()
        assert [entry[1] for entry in outlines] == ["1. Monthly status", "2. Monthly status"]
        assert outlines[0][2] != outlines[1][2]
        contents = next(page for page in pdf if "Table of contents" in page.get_text())
        links = [link for link in contents.get_links() if link["kind"] == fitz.LINK_GOTO]
        assert len(links) == 4  # One title and one page-number link per section.
        for section, (_, title, page) in zip(expected, outlines):
            assert 1 <= page <= len(pdf)
            assert cache[f"PAGEREF {anchor_for(section.key)} \\h"] == str(page)
            assert title in pdf[page - 1].get_text()
            assert sum(link["page"] == page - 1 for link in links) == 2
    reopened = Document(BytesIO(package.docx))
    fields = list(reopened.element.iter(qn("w:fldSimple")))
    generated = [field for field in fields
                 if field.get(qn("w:instr"), "").strip().startswith("PAGEREF mr_contents_")]
    assert len(generated) == 2
    assert all(field.get(qn("w:dirty")) == "true" for field in generated)


@requires_libreoffice
def test_verified_word_cache_reconversion_keeps_final_page_count_and_destinations(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    draft = current_report(pages=3)
    package = renderer.generate_report(draft, acknowledged_fingerprint=draft.fingerprint,
                                       asset_loader=image)
    assert package.pdf and not package.contents_notice, package.pdf_error
    # Test-only reopening/reconversion: production still converts exactly once.
    rendered_again, error = renderer._convert_report_pdf(draft, package.docx)
    assert rendered_again, error
    with fitz.open(stream=package.pdf, filetype="pdf") as first, \
            fitz.open(stream=rendered_again, filetype="pdf") as second:
        assert len(first) == len(second)
        assert first.get_toc() == second.get_toc()
        final_heading_page = first.get_toc()[-1][2]
        assert final_heading_page == len(first)
        assert max(map(int, cached_pages(package.docx).values())) == final_heading_page
    updated, notice = synchronize(package.docx, rendered_again, included_sections(draft.sections))
    assert renderer.canonical_docx(updated) == package.docx
    assert notice == ""


@requires_libreoffice
@pytest.mark.parametrize("damage", ["duplicate-outline", "wrong-link-destination"])
def test_ambiguous_or_wrong_final_destinations_never_fill_word_cache(tmp_path, monkeypatch, damage):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    draft = current_report(pages=3)
    raw = renderer.assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint,
                                 asset_loader=image)
    pdf, error = renderer._convert_report_pdf(draft, raw)
    assert pdf, error
    with fitz.open(stream=pdf, filetype="pdf") as changed:
        if damage == "duplicate-outline":
            outlines = changed.get_toc()
            changed.set_toc([*outlines, outlines[0]])
        else:
            contents = next(page for page in changed if "Table of contents" in page.get_text())
            link = next(link for link in contents.get_links() if link["kind"] == fitz.LINK_GOTO)
            assert link["page"] > 0
            link["page"] = 0
            link["to"] = fitz.Point(0, 0)
            contents.update_link(link)
        altered = changed.tobytes()
    updated, notice = synchronize(raw, altered, included_sections(draft.sections))
    assert updated == raw
    assert "could not be verified" in notice
    assert set(cached_pages(updated).values()) == {"?"}


def test_duplicate_generated_word_target_remains_explicitly_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    draft = current_report()
    raw = renderer.assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    document = Document(BytesIO(raw))
    target = next(document.element.iter(qn("w:bookmarkStart")))
    target.addnext(deepcopy(target))
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as before, ZipFile(output, "w", ZIP_DEFLATED) as after:
        for info in before.infolist():
            after.writestr(info, document.element.xml.encode() if info.filename == "word/document.xml"
                          else before.read(info.filename))
    duplicated = output.getvalue()
    updated, notice = synchronize(duplicated, b"%PDF-not-needed", included_sections(draft.sections))
    assert updated == duplicated
    assert "could not be verified" in notice
    assert set(cached_pages(updated).values()) == {"?"}
