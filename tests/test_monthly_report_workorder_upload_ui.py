"""A supported WO CSV produces editable metrics without overwriting manual text."""
from io import BytesIO
import pytest

from app import monthly_report_ai as ai, monthly_report_upload_ui as ui
from test_monthly_report_ui import monthly

CSV = (b"Work Order,Date,Status,Facility,Asset\n"
       b"WO-TEST-1001,2026-09-03,Completed,Demo North,PUMP-TEST-02\n"
       b"WO-TEST-1002,2026-09-20,Completed,Demo North,AHU-TEST-07\n"
       b"WO-TEST-1003,2026-09-24,Open,Demo North,VAV-TEST-03\n")


def _upload(monkeypatch):
    stream = BytesIO(CSV)
    stream.name = "work_orders.csv"
    original = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *args, **kwargs:
                        [stream] if label == "Add activity files (optional)"
                        else original(label, *args, **kwargs))
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "")


def test_csv_shows_grounded_totals_before_user_acceptance(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    _upload(monkeypatch)
    app.run()
    assert not app.exception
    assert any("3 total, 2 completed, 1 open" in info.value for info in app.info)
    assert any("66.7%" in info.value for info in app.info)
    assert sum(b.label == "Add these work-order totals to Activity" for b in app.button) == 1
    before = next(w for w in app.text_area if w.label == "Activity summary").value
    assert "3 total" not in before  # reviewed proposal, not silent accepted work
    next(b for b in app.button if b.label == "Add these work-order totals to Activity").click().run()
    assert not app.exception
    added = next(w for w in app.text_area if w.label == "Activity summary").value
    stored = [(key, value) for key, value in app.session_state.filtered_state.items()
              if key.endswith("_draft") and hasattr(value, "blocks")]
    persisted = [block.text for _, draft in stored for block in draft.blocks
                 if block.key == "activity_summary"]
    assert "3 total" in added and "66.7%" in added, (
        "persisted", persisted, "editor", added,
        "references", [block.references for _, draft in stored for block in draft.blocks
                       if block.key == "activity_summary"])
    assert "WO-TEST-1001" not in added  # raw source rows are not copied into narrative
    assert before in added  # earlier manual/library text remains


def test_manual_deletion_is_not_reversed_by_reader_rerun(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    _upload(monkeypatch)
    app.run()
    next(b for b in app.button if b.label == "Add these work-order totals to Activity").click().run()
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    editor.set_value("My deliberate current-month wording.").run()
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "My deliberate current-month wording.")

def test_workorder_accept_is_idempotent_and_does_not_insert_raw_csv(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    _upload(monkeypatch)
    app.run()
    first = next(b for b in app.button if b.label == "Add these work-order totals to Activity")
    first.click().run()
    assert not app.exception
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    assert editor.value.count("3 total, 2 completed, 1 open") == 1
    assert "Synthetic initial activity." in editor.value
    app.run()
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    assert editor.value.count("3 total, 2 completed, 1 open") == 1
    assert not any(b.label == "Add these work-order totals to Activity" for b in app.button)


@pytest.mark.parametrize("manual", ["Manual correction entered before accepting totals.", ""])
def test_totals_clicked_with_new_text_reject_stale_baseline_without_losing_edit(
        monkeypatch, tmp_path, manual):
    app = monthly(monkeypatch, tmp_path)
    _upload(monkeypatch)
    app.run()
    next(w for w in app.text_area if w.label == "Activity summary").set_value(manual)
    next(b for b in app.button if b.label == "Add these work-order totals to Activity").click().run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == manual
    assert any("report changed after you reviewed" in w.value for w in app.warning)
    # Re-reviewing the unchanged evidence against the now-current wording
    # remains possible and adds the totals exactly once.
    next(b for b in app.button if b.label == "Add these work-order totals to Activity").click().run()
    assert not app.exception
    text = next(w for w in app.text_area if w.label == "Activity summary").value
    assert manual in text
    assert text.count("3 total, 2 completed, 1 open") == 1
