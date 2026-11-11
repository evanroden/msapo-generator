"""Synthetic issue evidence rendered as ordered, individually owned Word/PDF pages.

All originals remain immutable; deliberately omitted issues and old references
are absent from output, and the gallery never approves pages by selection.
"""
from dataclasses import asdict, replace
from io import BytesIO
import json
import shutil

from docx import Document
import pymupdf as fitz
import pytest

from app import monthly_report_designs as designs
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_docx import _build_docx, _convert_report_pdf
from app.monthly_report_issue_evidence_render import (
    append_issue_evidence, selected_issue_pages)
from app.monthly_report_model import ReportFollowUp, synthetic_profiles
from tests.test_monthly_issue_page_gallery import synthetic_pdf
from tests.test_monthly_report_issue_cards import draft_for


def _reviewed(source, numbers):
    return replace(source, client_page_reviews=tuple(
        (n, page_fingerprint(source, n)) for n in numbers),
        captions=tuple((n, f"Reviewed caption for {source.filename}, sheet {n}")
                       for n in numbers))


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    originals = {"alpha.pdf": synthetic_pdf("A", pages=5),
                 "beta.pdf": synthetic_pdf("B", pages=3, rotated=True)}
    alpha, _ = sources.ingest(profile, "alpha.pdf", originals["alpha.pdf"])
    beta, _ = sources.ingest(profile, "beta.pdf", originals["beta.pdf"])
    a = _reviewed(alpha.source, (1, 3, 5))
    b = _reviewed(beta.source, (1, 2, 3))
    pump = ReportFollowUp("pump", "issue", "Synthetic pump incident", "2026-09",
        update="Synthetic survey.", references=tuple(sources.source_reference(a, i) for i in (1, 3, 5)))
    valve = ReportFollowUp("valve", "issue", "Synthetic valve incident", "2026-09",
        update="Synthetic inspection.", references=tuple(sources.source_reference(b, i) for i in (1, 2, 3)))
    draft = replace(draft_for(""), sources=(a, b), follow_ups=(pump, valve))
    monkeypatch.setattr(designs, "source_for", lambda _profile: None)
    return draft, originals


def _paragraphs(payload):
    doc = Document(BytesIO(payload))
    return doc, "\n".join(p.text for p in doc.paragraphs)


def test_fallback_docx_emits_first_middle_last_for_two_issues_once_and_in_order(monkeypatch, tmp_path):
    draft, originals = _setup(monkeypatch, tmp_path)
    chosen = selected_issue_pages(draft)
    assert [(issue.key, source.filename, number) for issue, source, number, _ in chosen] == [
        ("pump", "alpha.pdf", 1), ("pump", "alpha.pdf", 3), ("pump", "alpha.pdf", 5),
        ("valve", "beta.pdf", 1), ("valve", "beta.pdf", 2), ("valve", "beta.pdf", 3)]
    data = _build_docx(draft)
    doc, text = _paragraphs(data)
    assert len(doc.inline_shapes) == 6
    expected = [f"Reviewed caption for {file}, sheet {number}" for file, number in
                [("alpha.pdf", 1), ("alpha.pdf", 3), ("alpha.pdf", 5),
                 ("beta.pdf", 1), ("beta.pdf", 2), ("beta.pdf", 3)]]
    assert all(text.count(caption) == 1 for caption in expected)
    offsets = [text.index(caption) for caption in expected]
    assert offsets == sorted(offsets)
    assert text.index("Evidence for issue: Synthetic pump") < offsets[0]
    assert offsets[2] < text.index("Evidence for issue: Synthetic valve") < offsets[3]
    assert all(sources.source_bytes(draft.profile, source) == originals[source.filename]
               for source in draft.sources)


def test_persistence_omit_reorder_replace_and_stale_links_dont_move_between_issues(monkeypatch, tmp_path):
    draft, originals = _setup(monkeypatch, tmp_path)
    draft = replace(draft, follow_ups=(
        replace(draft.follow_ups[0], references=(
            *draft.follow_ups[0].references, draft.follow_ups[0].references[1])),
        draft.follow_ups[1]))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Reviewer")
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened.revision == saved.revision
    assert reopened.draft == draft
    assert len(selected_issue_pages(reopened.draft)) == 6
    assert len(_paragraphs(_build_docx(reopened.draft))[0].inline_shapes) == 6

    excluded = replace(reopened.draft, follow_ups=(
        replace(draft.follow_ups[0], included=False), draft.follow_ups[1]))
    omit_doc, omit_text = _paragraphs(_build_docx(excluded))
    assert len(omit_doc.inline_shapes) == 3
    assert "Evidence for issue: Synthetic pump" not in omit_text
    assert "Evidence for issue: Synthetic valve" in omit_text
    assert len(selected_issue_pages(excluded)) == 3

    reordered = replace(draft, sources=tuple(reversed(draft.sources)),
                        follow_ups=tuple(reversed(draft.follow_ups)))
    assert [(issue.key, source.filename, page) for issue, source, page, _ in
            selected_issue_pages(reordered)][:3] == [
                ("valve", "beta.pdf", 1), ("valve", "beta.pdf", 2), ("valve", "beta.pdf", 3)]
    assert len(_paragraphs(_build_docx(reordered))[0].inline_shapes) == 6

    changed = replace(draft.sources[0], filename="replaced.pdf", sha256="f" * 64)
    stale = replace(draft, sources=(changed, draft.sources[1]))
    with pytest.raises(ValueError, match="changed|unavailable"):
        selected_issue_pages(stale)
    remaining = replace(stale, follow_ups=(replace(draft.follow_ups[0], references=()), draft.follow_ups[1]))
    assert [(issue.key, source.filename) for issue, source, _, _ in selected_issue_pages(remaining)] == [
        ("valve", "beta.pdf")] * 3
    assert sources.source_bytes(draft.profile, draft.sources[0]) == originals["alpha.pdf"]
    assert sources.source_bytes(draft.profile, draft.sources[1]) == originals["beta.pdf"]


def test_missing_original_unreviewed_page_and_price_caption_refuse_without_loss(monkeypatch, tmp_path):
    draft, originals = _setup(monkeypatch, tmp_path)
    first, second = draft.sources
    not_reviewed = replace(first, client_page_reviews=())
    bad = replace(draft, sources=(not_reviewed, second),
        follow_ups=(replace(draft.follow_ups[0], references=(
            sources.source_reference(not_reviewed, 1),)), draft.follow_ups[1]))
    with pytest.raises(ValueError, match="Review page"):
        selected_issue_pages(bad)

    priced = replace(first, captions=tuple((n, "$1,200 unit price" if n == 1 else caption)
                                          for n, caption in first.captions))
    bad = replace(draft, sources=(priced, second),
        follow_ups=(replace(draft.follow_ups[0], references=(
            sources.source_reference(priced, 1),)), draft.follow_ups[1]))
    with pytest.raises(ValueError, match="Review page"):
        selected_issue_pages(bad)
    sources._path(draft.profile, first.sha256, first.suffix).unlink()
    with pytest.raises(ValueError, match="unavailable"):
        _build_docx(draft)
    assert sources.source_bytes(draft.profile, second) == originals["beta.pdf"]


def test_native_anchor_insert_does_not_reassign_water_or_omit_issues(monkeypatch, tmp_path):
    draft, _ = _setup(monkeypatch, tmp_path)
    document = Document()
    document.add_paragraph("Native Issues heading")
    water = document.add_paragraph("Native Water section untouched")
    emitted = append_issue_evidence(document, draft, before=water._p)
    assert len(emitted) == 6
    assert [issue for issue, _ in emitted] == ["pump"] * 3 + ["valve"] * 3
    doc, text = _paragraphs(_save_for_test(document))
    assert len(doc.inline_shapes) == 6
    assert text.index("Native Issues heading") < text.index("Evidence for issue: Synthetic pump")
    assert text.index("Reviewed caption for beta.pdf, sheet 3") < text.index("Native Water section untouched")


def _save_for_test(document):
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


@pytest.mark.skipif(not (shutil.which("libreoffice") or shutil.which("soffice")),
                    reason="LibreOffice is required for actual PDF conversion")
def test_actual_pdf_has_ordered_evidence_pages_without_loss(monkeypatch, tmp_path):
    draft, originals = _setup(monkeypatch, tmp_path)
    word = _build_docx(draft)
    pdf, error = _convert_report_pdf(draft, word)
    assert not error and pdf is not None and pdf.startswith(b"%PDF-")
    with fitz.open(stream=pdf, filetype="pdf") as opened:
        full_text = "\n".join(page.get_text() for page in opened)
        expected = [f"Reviewed caption for {file}, sheet {page}" for file, page in (
            ("alpha.pdf", 1), ("alpha.pdf", 3), ("alpha.pdf", 5),
            ("beta.pdf", 1), ("beta.pdf", 2), ("beta.pdf", 3))]
        assert all(full_text.count(label) == 1 for label in expected)
        assert [full_text.index(label) for label in expected] == sorted(full_text.index(label) for label in expected)
        assert sum(len(page.get_images(full=True)) for page in opened) >= 6
    assert all(sources.source_bytes(draft.profile, s) == originals[s.filename] for s in draft.sources)
