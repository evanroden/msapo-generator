"""Synthetic Section 10 AR intake: source identity, aging and price exclusions."""
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json

import pytest
from docx import Document
from tests.conftest import requires_libreoffice

from app import monthly_report_sources as source_api
from app.monthly_report_receivable_intake import (
    _digest, _money, check_review_binding, decoded, editable_rows,
    inspect_content, prepare_review,
)
from app.monthly_report_checks import preflight
from app.monthly_report_content_policy import contains_price, table_has_pricing
from app.monthly_report_financial_policy import (
    FinancialScope, MonetaryEvidence, SourceFinancialReview, financial_permission,
)
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, Facility, ReportDraft, ReportPeriod, ReportProfile,
    ReportSource, ResolvedBlock, SectionSpec,
)


COLS = ("Invoice #", "Facility", "Status", "Invoice Date", "Due Date",
        "Invoice Amount", "Payment Amount", "Credit Amount", "Balance Due",
        "Customer Account")
DATA = (
    ("INV-101", "Demo North", "Partially paid", "2026-10-01", "2026-10-02",
     "500", "100", "50", "350", "A"),
    ("INV-102", "Demo South", "Credit", "", "",
     "", "", "25", "-25", "B"),
    ("INV-103", "Demo North", "Open", "03/04/2026", "03/05/2026",
     "250", "", "", "250", "C"),
)


def fixture(monkeypatch, rows=DATA, *, filename="synthetic-invoices.csv"):
    from csv import writer
    from io import StringIO
    buffer = StringIO()
    out = writer(buffer)
    out.writerow(COLS)
    out.writerows(rows)
    raw = buffer.getvalue().encode()
    digest = sha256(raw).hexdigest()
    source = ReportSource(digest, filename, digest, ".csv",
                          facility="Demo North", service_date="2026-10-01",
                          selected_pages=(1,), page_texts=(buffer.getvalue(),))
    tables = source_api._spreadsheet(raw, ".csv")
    from app.monthly_report_sources import SourceContent
    content = SourceContent(source, tables)
    sections = (SectionSpec("accounts_receivable", "10", "Accounts Receivables",
                (BlockSpec("accounts_receivable", "table", columns=(
                    ColumnSpec("facility", "Facility"), ColumnSpec("item", "Item"),
                    ColumnSpec("status", "Status"))),
                 BlockSpec("accounts_receivable_notes", "rich_text"))),)
    profile = ReportProfile("Synthetic contract", "synthetic-sites", "Demo sites",
                            (Facility("north", "Demo North"), Facility("south", "Demo South")),
                            "multi_site")
    draft = ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic editor", sections, (),
                        sources=(source,))
    def verified(profile, original):
        assert original == source and sha256(raw).hexdigest() == source.sha256
        return raw
    monkeypatch.setattr(source_api, "source_bytes", verified)
    review = inspect_content(draft, content, 1)
    edits = {row.reference: {} for row in review.rows}
    return draft, content, review, edits, raw


def prepared(monkeypatch, rows=DATA, **kwargs):
    draft, content, review, edits, raw = fixture(monkeypatch, rows, **kwargs)
    updated, block = prepare_review(draft, content, 1,
                                    as_of="2026-10-28", edited=edits,
                                    source_kind="vendor_invoice", confirmed=True)
    return updated, block, draft, content, raw


def test_review_preserves_source_amounts_partials_credits_and_unknown_dates(monkeypatch):
    report, block, before, content, raw = prepared(monkeypatch)
    assert len(block.rows) == 3
    assert tuple(len(row) for row in block.rows) == (3, 3, 3)
    assert "Partially paid" in block.rows[0][2]
    assert "1–30 days" in block.rows[0][2]
    assert "aging as of 2026-10-28" in block.rows[0][2]
    assert "Credit — not aged" in block.rows[1][2]
    assert "unknown date" in block.rows[1][1]
    assert "date needs review" in block.rows[2][1]
    assert "due date needs review" in block.rows[2][2]
    assert "Unknown aging" in block.rows[2][2]
    assert all(not contains_price(cell) for row in block.rows for cell in row)
    assert not table_has_pricing(("Facility", "Item", "Status"), block.rows)
    receipt = decoded(report.source_row_reviews[-1])
    assert [entry["reference"] for entry in receipt["rows"]] == [
        "ar-source:" + content.source.id + ":table:1:row:" + str(n)
        for n in range(1, 4)
    ]
    assert receipt["rows"][0]["source_amounts"] == {
        "invoice_amount": "500", "payment_amount": "100",
        "credit_amount": "50", "balance": "350"}
    assert receipt["rows"][1]["source_amounts"]["credit_amount"] == "25"
    assert receipt["rows"][2]["due_date_raw"] == "03/05/2026"
    assert report.sources == before.sources
    assert content.tables == source_api._spreadsheet(raw, ".csv")
    assert check_review_binding(report) is None
    assert report.source_row_reviews == (report.source_row_reviews[0],)


def test_date_bucket_boundaries_and_unknown_balance(monkeypatch):
    rows = (
        ("INV-A", "Demo North", "Open", "2026-10-01", "2026-10-28", "", "", "", "", "A"),
        ("INV-B", "Demo North", "Open", "2026-10-01", "2026-10-27", "", "", "", "", "B"),
        ("INV-C", "Demo North", "Open", "2026-09-13", "2026-09-13", "", "", "", "", "C"),
        ("INV-D", "Demo North", "Open", "2026-08-14", "2026-08-14", "", "", "", "", "D"),
        ("INV-E", "Demo North", "Partially paid", "2026-01-01", "2026-01-01", "", "5", "", "", "E"),
    )
    report, _, _, _, _ = prepared(monkeypatch, rows)
    assert ["Current", "1–30 days", "31–60 days", "61–90 days", "91+ days"] == [
        next(v for v in ("Current", "1–30 days", "31–60 days", "61–90 days", "91+ days")
             if v in row[2])
        for row in report.blocks[0].rows]
    assert "outstanding balance unknown" in report.blocks[0].rows[-1][2]


@pytest.mark.parametrize("change", (
    "wrong-scope", "missing-source", "source-content", "wrong-row",
    "deleted-receipt", "forged-receipt", "changed-source-details",
))
def test_source_receipt_cannot_be_reused_for_a_different_invoice(monkeypatch, change):
    report, block, _, _, _ = prepared(monkeypatch)
    if change == "wrong-scope":
        report = replace(report, period=ReportPeriod(2026, 9))
    elif change == "missing-source":
        report = replace(report, sources=())
    elif change == "source-content":
        report = replace(report, sources=(replace(report.sources[0], sha256="b" * 64),))
    elif change == "wrong-row":
        changed = replace(block, rows=(("Demo North", "Invoice CHANGED", "Open"), *block.rows[1:]))
        report = replace(report, blocks=(changed,))
    elif change == "deleted-receipt":
        report = replace(report, source_row_reviews=())
    elif change == "changed-source-details":
        report = replace(report, sources=(replace(report.sources[0], service_date="2026-10-20"),))
    else:
        record = json.loads(report.source_row_reviews[0])
        record["output_rows"][0][2] = "Paid"
        tampered = json.dumps(record, sort_keys=True, separators=(",", ":"))
        new_block = replace(block,
            rows=tuple(tuple(row) for row in record["output_rows"]),
            references=tuple("receivable:v1:" + _digest(record) if r.startswith("receivable:v1:") else r
                             for r in block.references))
        report = replace(report, blocks=(new_block,), source_row_reviews=(tampered,))
    assert check_review_binding(report) is not None
    assert any(c.code == "receivable_source" and c.blocking for c in preflight(report))


def test_manual_row_corrections_preserve_original_and_reject_duplicate_or_ambiguous_site(monkeypatch):
    draft, content, review, edits, _ = fixture(monkeypatch)
    edits[review.rows[2].reference] = {"due_date": "2026-10-07"}
    revised, _ = prepare_review(draft, content, 1,
                                 as_of="2026-10-28", edited=edits,
                                 source_kind="customer_invoice", confirmed=True)
    original = decoded(revised.source_row_reviews[0])["rows"][2]
    assert original["cells"][4] == "03/05/2026"
    assert original["corrections"] == {"due_date": "2026-10-07"}
    assert "1–30 days" in revised.blocks[0].rows[2][2]
    assert check_review_binding(revised) is None
    duplicates = dict(edits)
    duplicates[review.rows[1].reference] = {
        "invoice_id": "INV-101", "site": "Demo North", "customer_id": "A"}
    with pytest.raises(ValueError, match="same site"):
        prepare_review(draft, content, 1, as_of="2026-10-28",
                       edited=duplicates, source_kind="customer_invoice", confirmed=True)
    bad = dict(edits)
    bad[review.rows[1].reference] = {"site": "Other client"}
    with pytest.raises(ValueError, match="foreign"):
        prepare_review(draft, content, 1, as_of="2026-10-28",
                       edited=bad, source_kind="customer_invoice", confirmed=True)


def test_missing_asof_missing_columns_and_inconsistent_partial_balance_fail_closed(monkeypatch):
    draft, content, review, edits, _ = fixture(monkeypatch)
    with pytest.raises(ValueError, match="as-of"):
        prepare_review(draft, content, 1, as_of="", edited=edits,
                       source_kind="vendor_invoice", confirmed=True)
    mismatch = dict(edits)
    mismatch[review.rows[0].reference] = {"balance": "400"}
    with pytest.raises(ValueError, match="disagree"):
        prepare_review(draft, content, 1, as_of="2026-10-28", edited=mismatch,
                       source_kind="vendor_invoice", confirmed=True)
    with pytest.raises(ValueError, match="Confirm"):
        prepare_review(draft, content, 1, as_of="2026-10-28", edited=edits,
                       source_kind="vendor_invoice", confirmed=False)


def test_reopen_preserves_valid_source_row_receipt_and_client_status(monkeypatch):
    report, block, _, _, _ = prepared(monkeypatch)
    from app.monthly_report_library import draft_from_dict
    restored = draft_from_dict(asdict(report))
    assert restored == report
    assert decoded(restored.source_row_reviews[0])["source_kind"] == "vendor_invoice"
    assert check_review_binding(restored) is None
    assert restored.blocks[0].rows == block.rows


def test_vendor_invoice_amounts_never_enter_client_word_output(monkeypatch):
    report, block, _, _, _ = prepared(monkeypatch)
    from app.monthly_report_docx import assemble_docx
    generated = assemble_docx(report, acknowledged_fingerprint=report.fingerprint)
    docx = Document(BytesIO(generated))
    cells = " ".join(cell.text for table in docx.tables for row in table.rows
                     for cell in row.cells)
    words = " ".join(p.text for p in docx.paragraphs) + " " + cells
    assert "Invoice INV-101" in words and "Partially paid" in words
    assert "350" not in words and "500" not in words
    assert "$" not in words
    assert not any(c.blocking for c in preflight(report))


@requires_libreoffice
def test_saved_status_only_ar_word_and_real_pdf_exclude_invoice_amounts(monkeypatch, tmp_path):
    """Output acceptance: status and aging dates survive, monetary inputs do not."""
    from app.monthly_report_docx import generate_report
    from app.monthly_report_library import load_snapshot, save_snapshot
    from zipfile import ZipFile
    from lxml import etree
    import pymupdf as fitz
    import re

    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    report, block, _, _, original_bytes = prepared(monkeypatch)
    saved = save_snapshot(report, expected_revision=0, entered_editor='Synthetic reviewer')
    reopened = load_snapshot(report.profile.contract, report.profile.key, report.period)
    assert reopened.revision == saved.revision
    assert reopened.draft == report
    assert check_review_binding(reopened.draft) is None
    assert len(original_bytes) > 0

    package = generate_report(reopened.draft,
                              acknowledged_fingerprint=reopened.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    with ZipFile(BytesIO(package.docx)) as archive:
        visible = []
        for name in archive.namelist():
            if name.startswith('word/') and name.endswith('.xml'):
                root = etree.fromstring(archive.read(name))
                visible.extend(node.text or '' for node in root.iter()
                               if node.tag.endswith('}t'))
        word_text = ' '.join(visible)
    rendered = []
    with fitz.open(stream=package.pdf, filetype='pdf') as pages:
        assert len(pages) >= 1
        pdf_text = ' '.join(page.get_text() for page in pages)
        for page in pages:
            image = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            assert image.width > 0 and image.height > 0
            rendered.append(image.tobytes('png'))
    from pathlib import Path
    import os
    artifact_root = os.environ.get('FINANCIAL_OUTPUT') or os.environ.get('INDEPENDENT_OUTPUT')
    if artifact_root:
        target = Path(artifact_root) / 'receivables'
        target.mkdir(parents=True, exist_ok=True)
        (target / 'status-only.docx').write_bytes(package.docx)
        (target / 'status-only.pdf').write_bytes(package.pdf)
        for number, raw_png in enumerate(rendered, 1):
            (target / f'page-{number:02}.png').write_bytes(raw_png)
        manifest = {
            'kind': 'synthetic source-bound nonfinancial AR status acceptance',
            'source_sha256': sha256(original_bytes).hexdigest(),
            'report_fingerprint': reopened.draft.fingerprint,
            'snapshot_revision': reopened.revision,
            'docx_sha256': sha256(package.docx).hexdigest(),
            'pdf_sha256': sha256(package.pdf).hexdigest(),
            'page_count': len(rendered),
            'expected_client_content': 'invoice identity, status and dated aging only; no monetary figures',
        }
        (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for text in (word_text, pdf_text):
        text = ' '.join(text.split())  # Word/PDF may wrap the same cell differently.
        assert 'Invoice INV-101' in text
        assert 'Partially paid' in text
        assert 'aging as of 2026-10-28' in text
        assert 'Credit' in text
        assert 'due date needs review' in text
        assert not re.search(r'(?<!\d)(?:500|350|250|100|25)(?!\d)', text)
        assert '$' not in text
        assert not re.search(r'(?i)invoice amount|aged dollar total|complete ar aging statement', text)
    assert reopened.draft.blocks[0].rows == block.rows


def test_same_filename_different_source_bytes_do_not_replay(monkeypatch):
    report, _, _, _, _ = prepared(monkeypatch, filename="same-name.csv")
    other = replace(report.sources[0], id="c" * 64, sha256="c" * 64)
    report = replace(report, sources=(other,))
    assert check_review_binding(report) is not None


@pytest.mark.parametrize("bad_block", ("table", "narrative", "caption"))
def test_other_sections_keep_strict_price_rejection(monkeypatch, bad_block):
    report, _, _, _, _ = prepared(monkeypatch)
    from app.monthly_report_model import ColumnSpec
    extra = SectionSpec("maintenance", "5", "Synthetic maintenance", (
        BlockSpec("vendor_reports", "table", columns=(
            ColumnSpec("facility", "Facility"), ColumnSpec("item", "Item"),
            ColumnSpec("status", "Status"))),))
    if bad_block == "table":
        suspicious = ResolvedBlock("vendor_reports", "This month",
                                   rows=(("Demo North", "Vendor invoice total", "$125"),))
    elif bad_block == "narrative":
        suspicious = ResolvedBlock("vendor_reports", "This month",
                                   text="Vendor invoice total $125")
    else:
        suspicious = ResolvedBlock("vendor_reports", "This month",
                                   text="Photo caption: vendor invoice total $125")
    extended = replace(report, sections=(*report.sections, extra),
                       blocks=(*report.blocks, suspicious))
    assert any(check.blocking and check.code == "pricing" for check in preflight(extended))
    from app.monthly_report_docx import assemble_docx
    with pytest.raises(ValueError):
        assemble_docx(extended, acknowledged_fingerprint=extended.fingerprint)


def test_vendor_amount_policy_is_not_a_hidden_contract_exception():
    scope = FinancialScope("Synthetic contract", "north")
    review = SourceFinancialReview("source-A", "a" * 64, scope, "vendor_invoice", "internal")
    locator = "accounts_receivable:row:1"
    content = sha256(b"synthetic vendor amount").hexdigest()
    evidence = (MonetaryEvidence(review.source_id, review.fingerprint, locator, content,
                                 "vendor_invoice_total"),)
    decision = financial_permission(
        purpose="monthly_export", scope=scope, locator=locator,
        content_sha256=content, evidence=evidence, reviews=(review,),
        current_sources=((review.source_id, review.source_sha256),))
    assert not decision.allowed
    assert "Vendor-invoice totals" in decision.reason


@pytest.mark.parametrize("value", ("", "Unknown", "N/A", "not available", "—", "pending"))
def test_unknown_money_is_explicitly_not_zero(value):
    assert _money(value) is None
    assert _money("0") == 0


def test_mismatched_original_asof_and_days_past_due_are_never_inferred(monkeypatch):
    from app.monthly_report_receivable_intake import _review_row
    from app.monthly_report_receivable_schema import ReceivableColumn
    from datetime import date
    draft, content, review, edits, raw = fixture(monkeypatch)
    source_row = review.rows[0]
    from dataclasses import replace as update
    source_role = ReceivableColumn(len(source_row.cells), "Days past due",
                                   "days_past_due", False)
    extra = update(review, columns=(*review.columns, source_role),
                   rows=(update(source_row, cells=(*source_row.cells, "250")),))
    with pytest.raises(ValueError, match="past due"):
        _review_row(draft, extra, extra.rows[0], {}, date(2026, 10, 28))
    source_role = ReceivableColumn(len(source_row.cells), "Aging as of",
                                   "as_of_date", False)
    extra = update(review, columns=(*review.columns, source_role),
                   rows=(update(source_row, cells=(*source_row.cells, "2026-09-30")),))
    with pytest.raises(ValueError, match="as-of date"):
        _review_row(draft, extra, extra.rows[0], {}, date(2026, 10, 28))


def test_currency_formatted_xlsx_amounts_are_read_without_retyping():
    from decimal import Decimal
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(["Invoice #", "Invoice Amount"])
    cases = (('"$"#,##0.00', 500), ("[$USD-409]#,##0.00", 1234.5), ("$#,##0.00", -12.25),
             ("#,##0.00 [$€-407]", 99.5), ("$#,##0.000", 1.125))
    for number, (number_format, value) in enumerate(cases, 1):
        sheet.append([f"SYN-{number}", value])
        sheet.cell(row=number + 1, column=2).number_format = number_format
    raw = BytesIO()
    book.save(raw)
    amounts = [row[1] for row in source_api._spreadsheet(raw.getvalue(), ".xlsx")[0].rows]
    assert amounts[:3] == ["500 $", "1234.5 USD", "-12.25 $"]
    assert [_money(value) for value in amounts[:3]] == [Decimal("500"), Decimal("1234.5"), Decimal("-12.25")]
    # Another currency, or more precision than cents, still needs a correction.
    for value in amounts[3:]:
        with pytest.raises(ValueError, match="explicit numeric correction"):
            _money(value)
