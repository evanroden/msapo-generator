"""Cross-adapter Activity acceptance with invented source bytes only.

Refs #277, #476, #479, #480, #481, #717, #270.
This test runs on an isolated report store; no external reader, OCR, or live writes.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pymupdf
import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_work_order_review_flow as flow
from app.monthly_report_docx import generate_report
from app.monthly_report_source_scope import correct_scope
from test_monthly_report_work_order_review_flow import CSV, PERIOD, PROFILE, draft_source
from test_monthly_report_work_order_pdf_review import _mixed_pdf
from test_monthly_report_work_order_docx_review import _normal_document
from conftest import requires_libreoffice


def _store(draft, content):
    bundle = flow.prepare_bundle(draft, content)
    return flow.store_bundle(draft, bundle), bundle


def _publish(draft, bundle):
    block = next(item for item in draft.blocks if item.key == "work_orders")
    return flow.publish_bundle(
        draft, bundle, expected_revision=flow.revision(bundle),
        expected_block=block.fingerprint,
    )


def _scoped(content):
    return replace(content, source=correct_scope(
        content.source, PROFILE, ("north", "south")))


@requires_libreoffice
def test_three_formats_with_conflicting_orders_scan_and_manual_corrections(
        tmp_path, monkeypatch):
    """A failed source never erases a good sibling, review, or final document."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    from app import pdf_converter
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pdf_converter, "PDF_BACKEND", "libreoffice")

    draft, csv = draft_source()
    csv = _scoped(csv)
    pdf_bytes = _mixed_pdf(scanned=True)
    pdf, _ = sources.ingest(PROFILE, "synthetic-two-page-and-scan.pdf", pdf_bytes)
    pdf = _scoped(pdf)
    document = _normal_document()
    stream = BytesIO()
    document.save(stream)
    word_bytes = stream.getvalue()
    word, _ = sources.ingest(PROFILE, "synthetic-native-table.docx", word_bytes)
    word = _scoped(word)
    draft = replace(
        draft,
        sources=(csv.source, pdf.source, word.source),
        sections=tuple(section for section in draft.sections
                       if section.key == "activity"),
    )

    # A reviewed CSV row stays included even when a later PDF scan is rejected.
    draft, csv_review = _store(draft, csv)
    draft = _publish(draft, csv_review)
    csv_published = flow.saved_bundle(draft, csv.source.id, "workorders")
    assert csv_published is not None
    original_manual = next(b for b in draft.blocks
                           if b.key == "activity_summary").text

    draft, pdf_review = _store(draft, pdf)
    assert len(pdf_review["groups"]) == 3
    with pytest.raises(ValueError, match="unsupported"):
        _publish(draft, pdf_review)
    # An image-only page requires an explicit omission, not imaginary OCR.
    pdf_review = flow.group_decisions(pdf_review, 2, omitted=True)
    draft = flow.store_bundle(draft, pdf_review,
                              expected_revision=flow.revision(
                                  flow.saved_bundle(draft, pdf.source.id, "workorders")))
    with pytest.raises(ValueError, match="Another included source"):
        _publish(draft, pdf_review)

    # Only the two truly duplicated PDF rows are omitted; the safe remainder
    # retains physical source pages, original IDs, and native table identity.
    for row in flow.restored_group(pdf_review, pdf_review["groups"][0]).rows:
        if row.work_order in {"0001", "0002"}:
            pdf_review = flow.change_row(pdf_review, 0, row.key, {}, excluded=True)
    draft = flow.store_bundle(draft, pdf_review,
                              expected_revision=flow.revision(
                                  flow.saved_bundle(draft, pdf.source.id, "workorders")))
    draft = _publish(draft, pdf_review)
    assert flow.saved_bundle(draft, csv.source.id, "workorders") == csv_published

    # Native Word title bands, repeat headers, and unrelated contact tables
    # cannot create another work-order or leak an unrelated contact.
    draft, word_review = _store(draft, word)
    draft = _publish(draft, word_review)
    block = next(b for b in draft.blocks if b.key == "work_orders")
    samples = [table for table in block.extra_tables
               if table.columns and table.columns[0] == "Work order"]
    assert len(samples) == 4  # CSV, both PDF text pages, native Word.
    ids = [row[0] for table in samples for row in table.rows]
    assert set(ids) == {"0001", "0002", "0003", "0099", "0004",
                        "0005", "0006", "000071", "000072"}
    assert len(ids) == len(set(ids)) == 9
    assert next(b for b in draft.blocks if b.key == "activity_summary").text == original_manual

    # Persist the combined accepted report and prove later re-entry does not
    # substitute a parser's old proposal for the explicit reviewed rows.
    library.save_profile(PROFILE, expected_revision=0,
                         actor="Synthetic Editor", confirmed=True)
    library.save_snapshot(draft, expected_revision=0)
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    assert reopened.fingerprint == draft.fingerprint
    assert len(reopened.source_row_reviews) == 3
    assert flow.saved_bundle(reopened, csv.source.id, "workorders") == csv_published
    assert _publish(reopened, flow.saved_bundle(reopened, word.source.id, "workorders")) == reopened

    output = generate_report(reopened, acknowledged_fingerprint=reopened.fingerprint)
    assert output.docx and output.pdf and not output.pdf_error
    report = Document(BytesIO(output.docx))
    exported = [tuple(tuple(c.text for c in row.cells) for row in t.rows)
                for t in report.tables]
    printed = [table for table in exported if table[0][0] == "Work order"]
    assert len(printed) == 4
    printed_ids = [row[0] for table in printed for row in table[1:]]
    assert printed_ids == ids
    with pymupdf.open(stream=output.pdf, filetype="pdf") as rendered:
        rendered_text = "\n".join(page.get_text() for page in rendered)
    for identity in ids:
        assert rendered_text.count(identity) == 1, identity
    assert "Synthetic User" not in rendered_text  # DOCX's unrelated contact.
    assert "Keep my authored wording." in rendered_text
    for content, raw in ((csv, CSV), (pdf, pdf_bytes), (word, word_bytes)):
        assert sources.source_bytes(PROFILE, content.source) == raw
