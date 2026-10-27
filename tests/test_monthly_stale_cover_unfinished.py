"""A stale cover is not evidence that undated draft edits are historical."""
from test_monthly_report_start_import import report_file, PERIOD
import pytest
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_start_import import analyze_starting_report, automatic_section_plans, build_starting_import
from app.monthly_report_import import inspect_docx


def test_stale_cover_preserves_undated_unfinished_prose_for_period_review(tmp_path):
    path = report_file(tmp_path, month="July 2026", activity=("Inspected the newly installed air handler.",), photo=True, table=True)
    inspection = inspect_docx(path)
    analysis = analyze_starting_report(inspection, synthetic_profiles()[0], PERIOD)
    plans = automatic_section_plans(inspection, analysis)
    item = next(i for i in inspection.items if "newly installed" in i.text)
    assert item.id in analysis.uncertain_items
    assert item.id not in analysis.older_items
    plan = next(p for p in plans.values() if item.id in p["selected"])
    assert not plan["approved"]
    assert any("month" in q.lower() for q in plan["questions"])
    assert plan["texts"][item.id] == item.text
    with pytest.raises(ValueError, match="remaining starting-report questions"):
        build_starting_import(path, inspection, plans.values())
    plan["approved"] = True  # Explicit section review, never inferred from cover.
    plan["questions"] = ()
    mapped, _ = build_starting_import(path, inspection, plans.values())
    assert "newly installed air handler" in next(b.text for b in mapped.blocks if b.key == "activity_summary")


def test_period_review_requires_explicit_confirmation_bound_to_text_and_month():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_section_ui import _approve_plan
text = st.text_input("Work", value="Inspected air handler")
month = st.text_input("Month", value="September 2026")
old = st.session_state.get("plans", {}).get("activity", {})
plan = {"key": "activity", "period_review_items": ("one",), "period_review_label": month,
        "texts": {"one": text}, "new_assets": [], "preserved_assets": []}
plans = {}
def field(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return key
_approve_plan(plan, "test", field, old, plans, [])
st.session_state["plans"] = plans
""").run()
    assert not app.session_state["plans"]["activity"]["approved"]
    app.checkbox[0].check().run()
    assert app.session_state["plans"]["activity"]["approved"]
    app.text_input[0].set_value("Different work").run()
    assert not app.session_state["plans"]["activity"]["approved"]
    app.checkbox[0].check().run()
    app.text_input[1].set_value("October 2026").run()
    assert not app.session_state["plans"]["activity"]["approved"]


def test_upload_period_review_then_durable_reopen_keeps_unfinished_prose(monkeypatch, tmp_path):
    from test_monthly_report_start_import import start_app, save_start
    from app import monthly_report_library as library
    path = report_file(tmp_path, month="July 2026", activity=("Inspected the newly installed air handler.", "Repaired the second pump."))
    app = start_app(monkeypatch, tmp_path, path)
    proceed = lambda: next(b for b in app.button if b.label == "Continue to this month’s updates")
    assert proceed().disabled
    confirm = next(c for c in app.checkbox if c.label == "This work belongs in September 2026")
    confirm.check().run()
    assert not app.exception
    assert not proceed().disabled
    draft = save_start(app)
    assert "newly installed air handler" in next(b.text for b in draft.blocks if b.key == "activity_summary")
    assert "Repaired the second pump." in next(b.text for b in draft.blocks if b.key == "activity_summary")
    snapshot = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened.draft == snapshot.draft


def test_period_review_preserves_all_retained_paragraphs_and_edits_not_explicit_old_work(monkeypatch, tmp_path):
    from test_monthly_report_start_import import start_app, save_start
    from app import monthly_report_library as library
    paragraphs = ("July 2026: Old completed pump repair.", "Inspected the air handler.", "Repaired the second pump.")
    path = report_file(tmp_path, month="July 2026", activity=paragraphs)
    app = start_app(monkeypatch, tmp_path, path)
    radio = next(r for r in app.radio if r.label == "What would you like to do?")
    radio.set_value("Edit text or change pictures").run()
    editor = next(t for t in app.text_area if "Inspected the air handler." in t.value)
    expected = "Inspected the air handler.\n\nRepaired the second pump."
    assert editor.value == expected
    edited = expected + "\n\nReviewed and corrected."
    editor.set_value(edited).run()
    next(c for c in app.checkbox if c.label == "This work belongs in September 2026").check().run()
    assert next(t for t in app.text_area if "Inspected the air handler." in t.value).value == edited
    draft = save_start(app)
    assert next(b.text for b in draft.blocks if b.key == "activity_summary") == edited
    library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert next(b.text for b in reopened.draft.blocks if b.key == "activity_summary") == edited
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == path.read_bytes()


@pytest.mark.parametrize("plain", ((), ("Inspected the second pump.",)))
def test_stale_cover_priced_work_remains_editable_until_price_removed(monkeypatch, tmp_path, plain):
    from test_monthly_report_start_import import start_app, save_start
    paragraphs = ("July 2026: Explicitly old work.", "Repaired the air handler for $500.", *plain)
    path = report_file(tmp_path, month="July 2026", activity=paragraphs)
    app = start_app(monkeypatch, tmp_path, path)
    next(r for r in app.radio if r.label == "What would you like to do?").set_value("Edit text or change pictures").run()
    editor = next(t for t in app.text_area if t.label == "Work completed this month")
    expected = "\n\n".join(paragraphs[1:])
    assert editor.value == expected
    next(c for c in app.checkbox if c.label == "This work belongs in September 2026").check().run()
    assert next(b for b in app.button if b.label == "Continue to this month’s updates").disabled
    clean = expected.replace(" for $500", "")
    editor = next(t for t in app.text_area if t.label == "Work completed this month")
    editor.set_value(clean).run()
    next(c for c in app.checkbox if c.label == "This work belongs in September 2026").check().run()
    draft = save_start(app)
    assert next(b.text for b in draft.blocks if b.key == "activity_summary") == clean


def test_confirmed_period_review_remains_reachable_and_edit_requires_reconfirmation(monkeypatch, tmp_path):
    from test_monthly_report_start_import import start_app, save_start
    path = report_file(tmp_path, month="July 2026", activity=("Inspected the air handler.", "Repaired the second pump."))
    app = start_app(monkeypatch, tmp_path, path)
    next(r for r in app.radio if r.label == "What would you like to do?").set_value("Edit text or change pictures").run()
    confirm = lambda: next(c for c in app.checkbox if c.label == "This work belongs in September 2026")
    proceed = lambda: next(b for b in app.button if b.label == "Continue to this month’s updates")
    confirm().check().run()
    app.run()  # Approval must not remove the only route back to this text.
    assert not proceed().disabled
    # AppTest delivers expander state; hosted browsers click its real summary.
    card_key = next(k for k in app.session_state.filtered_state if k.endswith("_section_activity_open"))
    app.session_state[card_key] = False
    app.run()
    assert not any(t.label == "Work completed this month" for t in app.text_area)
    assert not proceed().disabled
    app.session_state[card_key] = True
    app.run()
    editor = next(t for t in app.text_area if t.label == "Work completed this month")
    changed = editor.value + "\n\nCorrected after review."
    editor.set_value(changed).run()
    assert not confirm().value
    assert proceed().disabled
    confirm().check().run()
    draft = save_start(app)
    assert next(b.text for b in draft.blocks if b.key == "activity_summary") == changed
    assert not app.exception


def test_import_text_native_default_matches_retained_edits_and_explicit_clear(monkeypatch, tmp_path):
    from test_monthly_report_start_import import start_app
    paragraphs = ("Inspected the air handler.", "Repaired the second pump.")
    app = start_app(monkeypatch, tmp_path, report_file(tmp_path, month="July 2026", activity=paragraphs))
    next(r for r in app.radio if r.label == "What would you like to do?").set_value("Edit text or change pictures").run()
    area = lambda: next(t for t in app.text_area if t.label == "Work completed this month")
    identity = area().proto.id
    assert area().proto.default == "\n\n".join(paragraphs)
    for wording in ("Synthetic revised work.", "", "Restored explicit work."):
        area().set_value(wording).run()
        assert area().value == wording
        assert area().proto.default == wording, "Session state alone does not hydrate a native remount."
        assert area().proto.id == identity
        key = next(k for k in app.session_state.filtered_state if k.endswith("_section_activity_open"))
        app.session_state[key] = False
        app.run()
        app.session_state[key] = True
        app.run()
        assert area().value == wording
        assert area().proto.default == wording
        assert area().proto.id == identity


def test_native_import_default_does_not_reuse_another_source_or_target_month(monkeypatch, tmp_path):
    from io import BytesIO
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_section_ui as ui
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'store'))
    uploads = []
    for name, wording in (('one', 'First unfinished inspection.'), ('two', 'Second unfinished repair.')):
        folder = tmp_path / name
        folder.mkdir()
        path = report_file(folder, month='July 2026', activity=(wording,))
        upload = BytesIO(path.read_bytes())
        upload.name, upload.size = path.name, len(upload.getvalue())
        uploads.append(upload)
    current = [uploads[0]]
    real = ui.st.file_uploader
    monkeypatch.setattr(ui.st, 'file_uploader', lambda label, *a, **k: current[0] if label == 'Starting report' else real(label, *a, **k))
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_model import synthetic_profiles, ReportPeriod
from app.monthly_report_ui import _field
month=st.selectbox("Target month", [9,10])
p=synthetic_profiles()[0]
render_section_setup(p.contract,ReportPeriod(2026,month),"Synthetic Editor",_field,identity=p)
''', default_timeout=30).run()
    def edit():
        next(r for r in app.radio if r.label == 'What would you like to do?').set_value('Edit text or change pictures').run()
        return next(t for t in app.text_area if t.label == 'Work completed this month')
    edit().set_value('First-month private correction.').run()
    next(c for c in app.checkbox if c.label == 'This work belongs in September 2026').check().run()
    app.selectbox[0].set_value(10).run()
    assert edit().proto.default == 'First unfinished inspection.'
    assert not next(c for c in app.checkbox if c.label == 'This work belongs in October 2026').value
    current[0] = uploads[1]
    app.run()
    assert edit().proto.default == 'Second unfinished repair.'
    assert not next(c for c in app.checkbox if c.label == 'This work belongs in October 2026').value
    assert not app.exception
