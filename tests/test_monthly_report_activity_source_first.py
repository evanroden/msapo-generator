"""Source-first Activity copy and editable table identities, using synthetic data."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportTable, ResolvedBlock
from app.monthly_report_source_table_labels import table_task_label


def test_labels_are_source_grounded_and_never_infer_a_contact_or_completed_job():
    ordinary = ReportTable(("WO #", "Finish Date", "Status"),
                           (("DEMO-01", "2026-09-02", "Open"),), "synthetic:work")
    annual = ReportTable(("Category", "Site", "Metric", "Unit", "Jan", "Feb", "Mar",
                          "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
                         (("PM", "Demo North", "Completed", "count",
                           "0", "", "1", "", "", "", "", "", "", "", "", ""),), "synthetic:year")
    assert table_task_label(ordinary, "work_orders") == "Work-order records · 1 source row"
    assert table_task_label(annual, "work_orders") == "Annual work-order summary · 1 source row"
    assert table_task_label(ordinary, "work_orders", position=1, total=3).endswith("source 2 of 3 · 1 source row")
    assert table_task_label(ordinary, "service_calls").startswith("Service-call records")
    unknown = ReportTable(("Private **name**", "Price $300"),
                          (("Synthetic Private Note", "400"),), "synthetic:raw")
    label = table_task_label(unknown, "activity_summary")
    assert label == "Imported source table · 1 source row"
    assert all(token not in label for token in ("Private", "$300", "400", "Synthetic"))
    assert table_task_label(replace(ordinary, rows=()), "work_orders").endswith("0 source rows")


def test_activity_has_a_direct_shared_uploader_with_distinct_work_and_vendor_tasks(monkeypatch, tmp_path):
    from test_monthly_report_upload_ui import app_with_library, current_draft
    app, _ = app_with_library(monkeypatch, tmp_path)
    assert not app.exception
    # The same uploader, already opened for the first file, accepts both jobs.
    assert len([widget for widget in app.get("file_uploader")
                if widget.label == "Add source files"]) == 1
    explanations = [caption.value for caption in app.caption]
    assert any("Work-order export (CSV/XLSX)" in value
               and "Vendor service report (PDF/DOCX)" in value for value in explanations)
    before = current_draft(app)
    app.run()
    assert not app.exception
    assert current_draft(app) == before
    assert len([widget for widget in app.get("file_uploader")
                if widget.label == "Add source files"]) == 1
    assert not any(widget.label == "Read monthly files" for widget in app.button)


def test_imported_tables_display_schema_based_titles_without_table_number_controls():
    from test_work_order_imported_rows import APP
    first = ReportTable(("WO #", "Finish Date", "Status"),
                        (("DEMO-A", "2026-09-02", "Open"),), "synthetic:first")
    second = ReportTable(("Facility", "PM count"),
                         (("Demo North", "0"), ("Demo South", "")), "synthetic:second")
    app = AppTest.from_string(APP, default_timeout=30)
    original = ResolvedBlock("work_orders", "Last month",
                             extra_tables=(first, second),
                             references=("synthetic:report",))
    app.session_state["block"] = original
    app.run()
    assert not app.exception
    visible = [x.value for x in app.text]
    assert "Work-order records · source 1 of 2 · 1 source row" in visible
    assert "Work-order source table · source 2 of 2 · 2 source rows" in visible
    assert not any(x in {"Table 1", "Table 2"} for x in visible)
    assert app.session_state["block"] == original
    keys = [key for key, value in app.session_state.filtered_state.items()
            if "row_probe_edit_work_orders_imported_1_" in key
            and isinstance(value, dict) and "edited_rows" in value]
    assert len(keys) == 1
    app.session_state[keys[0]] = {"edited_rows": {0: {"PM count": "3"}},
                                  "added_rows": [], "deleted_rows": []}
    app.run()
    assert not app.exception
    changed = app.session_state["block"]
    assert changed.extra_tables[0] == first
    assert changed.extra_tables[1].rows == (("Demo North", "3"), ("Demo South", ""))
    assert changed.extra_tables[1].columns == second.columns
    assert changed.extra_tables[1].reference == second.reference


def test_starting_report_review_names_work_order_data_but_keeps_exact_table_cells():
    from app.monthly_report_import import ImportItem
    from app.monthly_report_model import ReportPeriod
    from app.monthly_report_sections import ImportSection
    from pathlib import Path
    script = """
import streamlit as st
from pathlib import Path
from app.monthly_report_import import ImportItem
from app.monthly_report_model import ReportPeriod
from app.monthly_report_sections import ImportSection
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field
item = ImportItem("table", "table", "word/document.xml", 1, 1, "activity",
                  suggested_slot="work_orders", rows=(
                    ("WO #", "Finish Date", "Status"),
                    ("DEMO-200", "2026-09-07", "Open"),
                    ("DEMO-201", "", "Pending")))
plans = st.session_state.setdefault("plans", {})
_section_card(ImportSection("activity", "Monthly Activity Summary", (item,)),
              Path("synthetic.docx"), None, ReportPeriod(2026, 9),
              "source_first", _field, plans, True)
"""
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    next(widget for widget in app.radio
         if "Edit text or change pictures" in widget.options).set_value(
             "Edit text or change pictures").run()
    assert not app.exception
    assert any("Work-order records · 2 source rows" == text.value for text in app.text)
    reviewed = app.session_state["plans"]["activity"]["tables"]["table"]
    assert reviewed.columns == ("WO #", "Finish Date", "Status")
    assert reviewed.rows == (("DEMO-200", "2026-09-07", "Open"),
                            ("DEMO-201", "", "Pending"))
    app.run()
    assert app.session_state["plans"]["activity"]["tables"]["table"] == reviewed
