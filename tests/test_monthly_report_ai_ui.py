from concurrent.futures import Future

from app import monthly_report_ai_ui as ui
from app.monthly_report_checks import preflight
from test_monthly_report_ui import monthly, step
from test_monthly_report_upload_ui import upload, button


def test_read_draft_review_preserves_existing_work_and_invalidates(monkeypatch, tmp_path):
    def start(prepare, read):
        payload = prepare()
        future = Future()
        if "Extract up to 100" in payload[0]["text"]:
            future.set_result({"facts": [{"page": 1, "kind": "action", "text": "Inspected the synthetic pump.",
                                         "quote": "Inspected the synthetic pump."}]})
        else:
            import json
            value = json.loads(payload[0]["text"].split("\n")[-1])
            future.set_result({"paragraphs": [{"text": "Inspected the synthetic pump.", "fact_ids": [value["facts"][0]["id"]]}]})
        return future
    monkeypatch.setattr(ui, "start_receipt", start)
    app = monthly(monkeypatch, tmp_path)
    step(app, 2)
    upload(monkeypatch, "synthetic.txt", b"Service date: 2026-09-03\nInspected the synthetic pump.")
    app.run()
    button(app, "Read monthly files").click().run()
    button(app, "Find work, findings and follow-ups").click().run()
    assert not app.exception
    next(w for w in app.checkbox if w.label == "Use these facts as evidence for suggestions").check().run()
    button(app, "Keep these facts").click().run()
    button(app, "Suggest wording / redraft").click().run()
    assert not app.exception
    assert button(app, "Use checked wording in this report").disabled
    next(w for w in app.checkbox if w.label == "I checked paragraph 1 against its source").check().run()
    button(app, "Use checked wording in this report").click().run()
    assert not app.exception
    key = next(k for k, v in app.session_state.filtered_state.items() if k.startswith("report_guided_") and k.endswith("_draft") and hasattr(v, "sources"))
    text = next(b.text for b in app.session_state[key].blocks if b.key=="activity_summary")
    assert "Synthetic initial activity." in text and "Inspected the synthetic pump." in text
    key = next(k for k, v in app.session_state.filtered_state.items() if k.startswith("report_guided_") and k.endswith("_draft") and hasattr(v, "sources"))
    assert not any(c.code == "ai_evidence" for c in preflight(app.session_state[key]))
    next(w for w in app.text_area if w.label == "Findings").set_value("Corrected finding.").run()
    assert any(c.code in ("ai_evidence","review") for c in preflight(app.session_state[key]))
    next(w for w in app.text_area if w.label=="Report paragraph 1").set_value("Inspected 800 synthetic pumps.").run()
    assert any(c.code=="ai_number" for c in preflight(app.session_state[key]))


def test_copilot_originals_and_unmatched_lines_are_retained(tmp_path, monkeypatch):
    from app import monthly_report_library as library
    from app.monthly_report_model import ReportPeriod
    from app.monthly_report_sources import source_bytes
    from app.contracts import RRH_CONTRACT
    app = monthly(monkeypatch, tmp_path)
    step(app, 2)
    notes = "Chatty introduction\n1. WORK COMPLETED\n09/03 Inspected a synthetic pump [email from vendor, 09/03]\n4. QUOTES\n09/04 Price $50 [email from vendor, 09/04]"
    next(w for w in app.text_area if w.label == "Paste Copilot's response").set_value(notes).run()
    assert any("1 priced lines" in w.value for w in app.caption)
    button(app, "Use these notes as evidence").click().run()
    assert not app.exception
    key = next(k for k, v in app.session_state.filtered_state.items() if k.startswith("report_guided_") and k.endswith("_draft") and hasattr(v, "sources"))
    source = app.session_state[key].sources[0]
    assert len(source.facts) == 1
    assert source_bytes(app.session_state[key].profile, source).decode() == notes
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    next(w for w in app.checkbox if w.label == "Save this draft for others on this report to continue").check().run()
    button(app, "Save progress").click().run()
    saved = library.load_snapshot(RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9))
    assert saved.draft.sources[0].facts
