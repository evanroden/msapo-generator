"""Source labels must not turn explicitly non-PM work into preventive work."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest

from app import monthly_report_library as library
from app.monthly_report_docx import _build_docx
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportTable, ResolvedBlock, SectionSpec,
    synthetic_profiles,
)
from app.monthly_report_source_table_labels import table_task_label
from tests.test_work_order_imported_rows import launch, current, edit, native_rows


NON_PM = (
    "Non-PM count", "Non PM count", "NonPM count", "non preventive maintenance",
    "Nonpreventive maintenance count", "Non-preventive maintenance",
    "NON\u2011PM", "non\u2013preventive maintenance", "non\u2014PM count",
)


def source_table(heading):
    return ReportTable(("Facility", heading), (("Demo North", "0"), ("Demo South", "")),
                       "synthetic:non-pm-source")


@pytest.mark.parametrize("heading", NON_PM)
def test_explicitly_non_pm_schema_keeps_neutral_source_label(heading):
    table = source_table(heading)
    assert table_task_label(table, "work_orders") == "Work-order source table · 2 source rows"
    assert table_task_label(table, "work_orders", position=1, total=2) == (
        "Work-order source table · source 2 of 2 · 2 source rows")
    assert table.columns == ("Facility", heading)
    assert table.rows == (("Demo North", "0"), ("Demo South", ""))


@pytest.mark.parametrize("heading", (
    "PM", "PM count", "Preventive maintenance count", "PM/non-PM", "Non-PM / PM",
    "Non-PM and preventive maintenance count", "Nonstandard PM count",
))
def test_positive_pm_evidence_and_mixed_schemas_keep_established_label(heading):
    assert table_task_label(source_table(heading), "work_orders") == (
        "Preventive maintenance summary · 2 source rows")


@pytest.mark.parametrize("heading", ("Equipment", "RPM", "Department", "non-PM equipment"))
def test_incidental_text_does_not_acquire_a_preventive_label(heading):
    assert table_task_label(source_table(heading), "work_orders") == (
        "Work-order source table · 2 source rows")


def test_explicit_record_and_annual_schema_labels_keep_precedence():
    record = ReportTable(("WO #", "Non-PM count"), (("DEMO-A", "0"),))
    assert table_task_label(record, "work_orders") == "Work-order records · 1 source row"
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    annual = ReportTable(("Non-PM", *months), (("Demo", *("0" for _ in months)),))
    assert table_task_label(annual, "work_orders") == "Annual work-order summary · 1 source row"
    assert table_task_label(source_table("Non-PM count"), "service_calls") == (
        "Service-call records · 2 source rows")


@pytest.mark.parametrize("heading", ("Non-PM count", "Non-preventive maintenance"))
def test_native_editor_label_rerun_edits_and_word_keep_source_cells(heading):
    table = source_table(heading)
    app = launch(table)
    expected = "Work-order source table · 2 source rows"
    assert expected in [item.value for item in app.text]
    assert current(app) == table
    app.run()
    assert not app.exception
    assert current(app) == table
    edit(app, edited={0: {heading: "3"}})
    changed = replace(table, rows=(("Demo North", "3"), ("Demo South", "")))
    assert current(app) == changed
    assert expected in [item.value for item in app.text]
    app.session_state["show"] = False
    app.run()
    app.session_state["show"] = True
    app.run()
    assert not app.exception
    assert current(app) == changed
    assert expected in [item.value for item in app.text]
    assert native_rows(changed) == (changed.columns, *changed.rows)


def test_saved_reopened_source_table_and_word_remain_literal(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    table = source_table("Non-PM count")
    block = ResolvedBlock("work_orders", "This month", extra_tables=(table,),
                          references=("synthetic:non-pm-source",))
    section = SectionSpec("activity", "2", "Activity", (BlockSpec("work_orders", "rich_text"),))
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10),
                        "Synthetic reviewer", (section,), (block,), synthetic=True)
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic reviewer")
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened == saved
    assert table_task_label(reopened.draft.blocks[0].extra_tables[0], "work_orders") == (
        "Work-order source table · 2 source rows")
    output = Document(BytesIO(_build_docx(reopened.draft)))
    assert any(tuple(tuple(cell.text for cell in row.cells) for row in result.rows) == (
        table.columns, *table.rows) for result in output.tables)
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key, draft.period, 1) == saved

