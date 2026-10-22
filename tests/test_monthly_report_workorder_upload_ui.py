"""A supported WO CSV produces editable metrics without overwriting manual text."""
from io import BytesIO
from dataclasses import replace
import pytest

from app import monthly_report_ai as ai, monthly_report_upload_ui as ui
from test_monthly_report_ui import monthly

CSV = (b"Work Order,Date,Status,Facility,Asset\n"
       b"WO-TEST-1001,2026-09-03,Completed,Demo North,PUMP-TEST-02\n"
       b"WO-TEST-1002,2026-09-20,Completed,Demo North,AHU-TEST-07\n"
       b"WO-TEST-1003,2026-09-24,Open,Demo North,VAV-TEST-03\n")


def _upload(monkeypatch, raw=CSV):
    stream = BytesIO(raw)
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
    assert any("3 work orders · 2 completed · 1 open" in info.value for info in app.info)
    assert any("Uploaded rows only." in info.value for info in app.info)
    assert any("66.7%" in info.value for info in app.info)
    assert sum(b.label == "Add totals to summary" for b in app.button) == 1
    before = next(w for w in app.text_area if w.label == "Activity summary").value
    assert "3 total" not in before  # reviewed proposal, not silent accepted work
    next(b for b in app.button if b.label == "Add totals to summary").click().run()
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
    next(b for b in app.button if b.label == "Add totals to summary").click().run()
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
    first = next(b for b in app.button if b.label == "Add totals to summary")
    first.click().run()
    assert not app.exception
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    assert editor.value.count("3 total, 2 completed, 1 open") == 1
    assert "Synthetic initial activity." in editor.value
    app.run()
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    assert editor.value.count("3 total, 2 completed, 1 open") == 1
    assert not any(b.label == "Add totals to summary" for b in app.button)


def test_detail_disclosure_contains_every_counted_row_without_changing_the_summary(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    before = next(w for w in app.text_area if w.label == "Activity summary").value
    raw = b"Work Order,Date,Status,Facility\n" + b"".join(
        f"SYNTHETIC-{i:03},2026-09-15,{'Completed' if i <= 50 else 'Open'},Demo North\n".encode()
        for i in range(1, 61))
    _upload(monkeypatch, raw)
    app.run()
    assert not app.exception
    assert any("60 work orders · 50 completed · 10 open (83.3% completed). Uploaded rows only."
               in info.value for info in app.info)
    details = [table.value for table in app.dataframe
               if list(table.value.columns) == ["Work order", "Date", "Status"]
               and len(table.value) == 60]
    assert len(details) == 1
    assert details[0].iloc[-1].tolist() == ["SYNTHETIC-060", "2026-09-15", "Open"]
    assert any("all 60 counted work orders" in c.value for c in app.caption)
    assert next(w for w in app.text_area if w.label == "Activity summary").value == before


@pytest.mark.parametrize("manual", ["Manual correction entered before accepting totals.", "", "  Deliberate wording.\n\n"])
def test_totals_clicked_with_delivered_text_keep_exact_edit_and_add_once(
        monkeypatch, tmp_path, manual):
    app = monthly(monkeypatch, tmp_path)
    _upload(monkeypatch)
    app.run()
    next(w for w in app.text_area if w.label == "Activity summary").set_value(manual)
    next(b for b in app.button if b.label == "Add totals to summary").click().run()
    assert not app.exception
    text = next(w for w in app.text_area if w.label == "Activity summary").value
    assert text.startswith(manual + "\n\n" if manual else "September 2026")
    assert "Synthetic initial activity." not in text
    assert text.count("3 total, 2 completed, 1 open") == 1
    assert not any("report changed after you reviewed" in w.value for w in app.warning)
    assert not any(b.label == "Apply interrupted edit" for b in app.button)
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == text


def test_totals_from_an_older_report_do_not_overwrite_an_unrelated_update(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    _upload(monkeypatch)
    app.run()
    accept = next(b for b in app.button if b.label == "Add totals to summary")
    key, draft = next((k, v) for k, v in app.session_state.filtered_state.items()
                      if k.endswith("_draft") and hasattr(v, "blocks"))
    newer = "A separately recovered update must be reviewed first."
    app.session_state[key] = replace(draft, blocks=tuple(
        replace(block, text=newer) if block.key == "activity_summary" else block
        for block in draft.blocks))
    accept.click().run()
    assert not app.exception
    assert next(w.value for w in app.text_area if w.label == "Activity summary") == newer
    assert any("report changed after you reviewed" in w.value for w in app.warning)
    next(b for b in app.button if b.label == "Add totals to summary").click().run()
    assert not app.exception
    text = next(w.value for w in app.text_area if w.label == "Activity summary")
    assert text.startswith(newer + "\n\n")
    assert text.count("3 total, 2 completed, 1 open") == 1
