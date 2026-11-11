"""Reopen valid AR corrections, but never replay another period or source."""
from dataclasses import asdict, replace

from streamlit.testing.v1 import AppTest

from app.monthly_report_library import draft_from_dict
from app.monthly_report_model import ReportPeriod
from app.monthly_report_receivable_intake import check_review_binding, prepare_review
from app.monthly_report_receivable_ui import saved_review_for_editor, reviewed_editor_defaults
from test_monthly_report_receivable_intake import fixture


def saved(monkeypatch):
    draft, content, review, edits, _ = fixture(monkeypatch)
    edits[review.rows[0].reference] = {"credit_amount": "40", "balance": "360"}
    edits[review.rows[2].reference] = {"due_date": "2026-10-07"}
    report, block = prepare_review(draft, content, 1, as_of="2026-10-28",
                                   edited=edits, source_kind="vendor_invoice", confirmed=True)
    return draft_from_dict(asdict(report)), content, review, edits


def test_saved_invoice_corrections_restore_without_changing_original_cells(monkeypatch, tmp_path):
    from app.monthly_report_library import save_snapshot, load_snapshot
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    report, content, review, original = saved(monkeypatch)
    saved_snapshot = save_snapshot(report, expected_revision=0, entered_editor="Synthetic reviewer")
    restored = load_snapshot(report.profile.contract, report.profile.key, report.period)
    assert restored.draft == report and restored.revision == saved_snapshot.revision
    report = restored.draft
    receipt = saved_review_for_editor(report, report.blocks[0], content, 1, review)
    assert receipt is not None
    assert (receipt["as_of"], receipt["source_kind"]) == ("2026-10-28", "vendor_invoice")
    rows = reviewed_editor_defaults(review, receipt)
    assert rows[0]["credit_amount"] == "40" and rows[0]["balance"] == "360"
    assert rows[2]["due_date"] == "2026-10-07"
    assert review.rows[0].cells[7:9] == ("50", "350")
    assert check_review_binding(report) is None
    corrected = {}
    for row, displayed in zip(review.rows, rows):
        fields = {column.candidate_role: row.cells[column.index] for column in review.columns
                  if column.candidate_role and column.candidate_role != "aging_bucket"}
        corrected[row.reference] = {role: value for role, value in displayed.items()
                                    if role != "Source row" and value != fields.get(role, "")}
    assert corrected == original
    updated, _ = prepare_review(report, content, 1, as_of=receipt["as_of"],
                                edited=corrected, source_kind=receipt["source_kind"], confirmed=True)
    assert check_review_binding(updated) is None and updated.blocks[0].rows == report.blocks[0].rows


def test_invalid_receipt_or_new_scope_never_restores_saved_values(monkeypatch):
    report, content, review, _ = saved(monkeypatch)
    original = report.blocks[0]
    assert saved_review_for_editor(report, original, content, 1, review)
    assert saved_review_for_editor(replace(report, period=ReportPeriod(2026, 11)),
                                   original, content, 1, review) is None
    changed_source = replace(report, sources=(replace(report.sources[0], sha256="a" * 64),))
    assert saved_review_for_editor(changed_source, original, content, 1, review) is None
    changed_block = replace(original, rows=(("Demo North", "changed", "Open"), *original.rows[1:]))
    assert saved_review_for_editor(report, changed_block, content, 1, review) is None
    assert saved_review_for_editor(report, original, content, 2, review) is None
    assert saved_review_for_editor(report, original, content, 1,
                                   replace(review, fingerprint="b" * 64)) is None
    assert reviewed_editor_defaults(review, None)[0]["balance"] == "350"


APP = """
import streamlit as st
from app.monthly_report_receivable_ui import render_receivable_intake
draft = st.session_state["report"]
blocks = {block.key: block for block in draft.blocks}
draft, blocks = render_receivable_intake(draft, blocks, "synthetic_ar")
st.session_state["report"] = draft
"""


def test_native_form_reloads_asof_and_row_values_but_new_month_resets(monkeypatch):
    from app import monthly_report_receivable_ui as ui
    report, content, review, _ = saved(monkeypatch)
    captured = []
    def editor(rows, **kwargs):
        captured.append((rows, kwargs.get("key")))
        return rows
    monkeypatch.setattr(ui.st, "data_editor", editor)
    app = AppTest.from_string(APP)
    app.session_state["report"] = report
    app.session_state["synthetic_ar_evidence"] = (content,)
    app.run()
    assert not app.exception
    assert next(item for item in app.text_input if item.label.startswith("Aging as of")).value == "2026-10-28"
    assert next(item for item in app.selectbox if item.label == "Exact source category").value == "vendor_invoice"
    assert captured[-1][0][0]["balance"] == "360"
    assert captured[-1][0][2]["due_date"] == "2026-10-07"
    old_key = captured[-1][1]

    next_month = replace(report, period=ReportPeriod(2026, 11))
    app2 = AppTest.from_string(APP)
    app2.session_state["report"] = next_month
    app2.session_state["synthetic_ar_evidence"] = (content,)
    app2.run()
    assert not app2.exception
    assert next(item for item in app2.text_input if item.label.startswith("Aging as of")).value == ""
    assert captured[-1][0][0]["balance"] == "350"
    assert captured[-1][1] != old_key
    assert app2.warning
