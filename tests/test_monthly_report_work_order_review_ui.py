from dataclasses import replace
from io import BytesIO

from streamlit.testing.v1 import AppTest

from app import monthly_report_work_order_review_flow as flow
from test_monthly_report_work_order_review_flow import draft_source, CSV


SCRIPT = """
import streamlit as st
from app.monthly_report_work_order_review_ui import render_reviewed_rows
draft = st.session_state['draft']
draft, blocks = render_reviewed_rows(draft, {b.key:b for b in draft.blocks}, 'review-ui', st.session_state['content'])
st.session_state['draft'] = draft
"""


def app_for(monkeypatch, tmp_path, raw=CSV):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft, content = draft_source(raw)
    app = AppTest.from_string(SCRIPT, default_timeout=20)
    app.session_state["draft"] = draft
    app.session_state["content"] = content
    return app.run()


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_visible_native_controls_correct_recompute_include_and_reopen(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path)
    assert not app.exception
    assert not app.session_state["draft"].source_row_reviews
    button(app, "Review and correct imported rows").click().run()
    assert not app.exception
    assert len(app.session_state["draft"].source_row_reviews) == 1
    next(t for t in app.text_input if t.label == "Recorded status").set_value("Completed")
    button(app, "Save row correction").click().run()
    assert not app.exception
    current = app.session_state["draft"]
    bundle = flow.saved_bundle(current, current.sources[0].id, "workorders")
    assert flow.restored_group(bundle, bundle["groups"][0]).rows[0].status == "Completed"
    button(app, "Include reviewed rows in Activity").click().run()
    assert not app.exception
    accepted = app.session_state["draft"]
    block = next(b for b in accepted.blocks if b.key == "work_orders")
    assert block.extra_tables[1].rows[0][-3:] == ("2", "2", "0")
    button(app, "Include reviewed rows in Activity").click().run()
    assert app.session_state["draft"] == accepted
    reopened = AppTest.from_string(SCRIPT, default_timeout=20)
    reopened.session_state["draft"] = accepted
    reopened.session_state["content"] = app.session_state["content"]
    reopened.run()
    assert not reopened.exception
    assert next(t for t in reopened.text_input if t.label == "Recorded status").value == "Completed"


def test_visible_mapping_handles_unknown_headers_and_explicit_date_locale(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path, b"Ticket,Building,Reported,State,Type\n0003,North,09/04/2026,Closed,PM\n")
    button(app, "Review and correct imported rows").click().run()
    assert button(app, "Include reviewed rows in Activity").disabled
    next(w for w in app.selectbox if w.label == "Work-order ID column").select(0)
    next(w for w in app.selectbox if w.label == "Work date column").select(2)
    next(w for w in app.selectbox if w.label == "Numeric date order").select("MDY")
    next(w for w in app.checkbox if w.label.startswith("Rebuild this table")).check()
    button(app, "Apply source mapping").click().run()
    assert not app.exception
    assert not button(app, "Include reviewed rows in Activity").disabled
    assert next(t for t in app.text_input if t.label == "Work-order ID").value == "0003"
    assert next(t for t in app.text_input if t.label == "Work date").value == "2026-09-04"


def test_stale_native_publication_does_not_overwrite_new_report_edits(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path)
    button(app, "Review and correct imported rows").click().run()
    publish = button(app, "Include reviewed rows in Activity")
    current = app.session_state["draft"]
    newer = replace(current, blocks=tuple(replace(b, text="New manual note") if b.key=="work_orders" else b for b in current.blocks))
    app.session_state["draft"] = newer
    publish.click().run()
    assert not app.exception
    assert any("report table changed" in item.value for item in app.warning)
    assert app.session_state["draft"] == newer


def test_real_monthly_source_manager_reaches_review_and_retains_corrected_rows(monkeypatch, tmp_path):
    from test_monthly_report_ui import monthly
    from app import monthly_report_upload_ui as ui, monthly_report_ai as ai
    app = monthly(monkeypatch, tmp_path)
    raw = CSV.replace(b"North", b"Demo North").replace(b"South", b"Demo North")
    stream = BytesIO(raw)
    stream.name = "review-source.csv"
    original = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label,*args,**kwargs:
        [stream] if label == "Add source files" else original(label,*args,**kwargs))
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "")
    app.run()
    assert not app.exception
    button(app, "Review and correct imported rows").click().run()
    assert not app.exception
    next(t for t in app.text_input if t.label=="Recorded status").set_value("Completed")
    button(app,"Save row correction").click().run()
    assert not app.exception
    drafts=[v for k,v in app.session_state.filtered_state.items() if k.endswith("_draft") and hasattr(v,"blocks")]
    assert any(d.source_row_reviews for d in drafts)
    next(w for w in app.checkbox if w.label == "Include Work Orders in this report").check().run()
    button(app,"Include reviewed rows in Activity").click().run()
    assert not app.exception
    app.run()
    drafts=[v for k,v in app.session_state.filtered_state.items() if k.endswith("_draft") and hasattr(v,"blocks")]
    assert any(any(b.key=="work_orders" and any(t.rows and t.rows[0][-3:]==("2","2","0") for t in b.extra_tables) for b in d.blocks) for d in drafts), ([b for d in drafts for b in d.blocks if b.key == "work_orders"], [w.value for w in app.warning], [i.value for i in app.info])

