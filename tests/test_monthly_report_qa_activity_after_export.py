"""QA native Word/PDF export must not empty the mounted Activity editor.

Deployed browser live acceptance 38315296356 passed 18/18 source checks and
created real Word/PDF bytes, then its Activity textarea stayed empty.
This tests the complete Streamlit editor/export rerun, not a source-only stub.
"""

from app import monthly_report_library as library
from app.monthly_report_qa_fixture import CONTRACT, PERIOD, profile
from app.monthly_report_testing import isolated
from test_monthly_report_qa_ui import visit, ACTOR_COOKIE


SEED = "Three September work orders: 3 total, 2 completed, 1 open (66.7%)."


def _activity(app):
    return next(w for w in app.text_area if w.label == "Activity summary")


def test_qa_export_and_neutral_reruns_never_clear_hydrated_activity(monkeypatch, tmp_path):
    app = visit(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Load known-value report").click().run()
    assert not app.exception
    assert _activity(app).value == SEED

    next(b for b in app.button if b.label == "Compare fixture facts").click().run()
    assert not app.exception
    assert all(app.session_state["monthly_qa_comparison"]["checks"].values())
    assert _activity(app).value == SEED

    next(b for b in app.button if b.label == "Generate QA Word and PDF").click().run()
    assert not app.exception
    _, package = app.session_state["monthly_qa_package"]
    assert package.docx.startswith(b"PK") and package.pdf.startswith(b"%PDF-")
    assert _activity(app).value == SEED
    from hashlib import sha256
    expected_hash = "QA working Activity SHA256: " + sha256(
        SEED.encode("utf-8")).hexdigest()
    assert any(c.value == expected_hash for c in app.get("caption"))
    for _ in range(3):
        app.run()
        assert not app.exception
        assert _activity(app).value == SEED

    # The immutable snapshot must retain the same exact source wording.
    with isolated(ACTOR_COOKIE):
        stored = library.load_snapshot(CONTRACT, profile().key, PERIOD)
        assert stored is not None
        assert next(b.text for b in stored.draft.blocks
                    if b.key == "activity_summary") == SEED


def test_qa_export_does_not_turn_a_saved_activity_widget_empty_on_rerun(
        monkeypatch, tmp_path):
    app = visit(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Load known-value report").click().run()
    assert _activity(app).value == SEED
    # A temporary frontend blank mount during another long-running action
    # is not an operator's explicit deletion; prefill remains authoritative.
    editor_key = _activity(app).key
    app.session_state[editor_key] = ""
    app.run()
    assert not app.exception
    assert _activity(app).value == SEED
    next(b for b in app.button if b.label == "Generate QA Word and PDF").click().run()
    assert not app.exception
    assert _activity(app).value == SEED
