"""A66: no-op preview reruns may not replace two acknowledged Monthly edits.

Synthetic AppTest exercises actual Streamlit text-area callbacks, widget identities
and the production browser-journal CAS. It is not a served native-browser test.
All document bytes are synthetic, assembled through the production DOCX path.
"""
from dataclasses import replace
from hashlib import sha256

from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import ReportPeriod, synthetic_profiles


TOKEN = "66" * 16
PERIOD = ReportPeriod(2026, 9)
PROFILE = synthetic_profiles()[0]
APP = """
import streamlit as st
from dataclasses import replace
from app import monthly_report_active_work as active
from app import monthly_report_recovery_save as recovery_save
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_save_status import SaveStatus
from app.monthly_report_ui import _field, preserve_report_draft_state, restore_report_draft_state

token = '66666666666666666666666666666666'
profile = synthetic_profiles()[0]
period = ReportPeriod(2026, 9)
prefix = 'a66_noop_monthly'
loaded = active.load(token, profile.contract, profile.key, period)
restore_report_draft_state()
st.session_state.setdefault('draft', loaded.draft if loaded else synthetic_draft(profile, period))
st.session_state.setdefault(prefix + '_revision', 0)
st.session_state.setdefault(prefix + '_active_sequence', loaded.revision if loaded else 0)
st.session_state.setdefault(prefix + '_active_generation', loaded.generation if loaded else '')
draft = st.session_state['draft']
blocks = list(draft.blocks)
for index in (0, 1):
    block = blocks[index]
    blocks[index] = _edit_content(
        BlockSpec(block.key, 'rich_text'), block, None, prefix, {}, _field)
draft = replace(draft, blocks=tuple(blocks))
st.session_state['draft'] = draft
status = SaveStatus(prefix, recovery_available=True)
scope = (profile.contract, profile.key, period.key, 'synthetic-incarnation', '')
try:
    saved = recovery_save.save(st.session_state, prefix, scope, token, draft, {})
except active.ActiveWorkConflict:
    st.session_state['save_outcome'] = 'conflict'
    status.failed()
else:
    st.session_state['save_outcome'] = 'saved'
    st.session_state['saved_revision'] = saved.revision
    st.session_state['saved_time'] = saved.updated_at
    status.browser_saved(saved.updated_at)
# This native action triggers the full-script rerun of a Preview click without
# spending on conversion. It never mutates the draft or publishes a version.
st.button('Preview current draft', key='a66_preview')
preserve_report_draft_state(finalize=True)
"""


def _editor(app, label):
    return next(item for item in app.text_area if item.label == label)


def _open(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(APP, default_timeout=30).run()
    assert not app.exception
    return app


def _text(draft, index):
    return draft.blocks[index].text


def _journal():
    saved = active.load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD)
    assert saved is not None
    return saved


def test_two_fields_survive_100_noop_preview_cycles_and_reopen_with_unchanged_docx(
        monkeypatch, tmp_path):
    app = _open(monkeypatch, tmp_path)
    old = tuple(item.proto.id for item in app.text_area)
    assert len(old) == 2
    first = "Synthetic September pump adjustment completed."
    second = "Synthetic September valve investigation remains pending."
    _editor(app, "Demo organization").set_value(first).run()
    assert not app.exception
    _editor(app, "Demo activity").set_value(second).run()
    assert not app.exception
    baseline = _journal()
    original_bytes = assemble_docx(baseline.draft)
    digest = sha256(original_bytes).hexdigest()
    assert _text(baseline.draft, 0) == first
    assert _text(baseline.draft, 1) == second
    assert app.session_state["saved_revision"] == baseline.revision
    assert app.session_state["saved_time"] == baseline.updated_at
    assert any('data-save-state="saved"' in m.value for m in app.markdown)

    for number in range(100):
        next(button for button in app.button if button.label == "Preview current draft").click().run()
        assert not app.exception, f"Preview #{number + 1} failed"
        assert tuple(item.proto.id for item in app.text_area) == old
        assert (_editor(app, "Demo organization").value,
                _editor(app, "Demo activity").value) == (first, second)
        assert (_text(app.session_state["draft"], 0),
                _text(app.session_state["draft"], 1)) == (first, second)
        assert app.session_state["saved_revision"] == baseline.revision
    again = _journal()
    assert again.revision == baseline.revision
    assert again.updated_at == baseline.updated_at
    assert again.draft == baseline.draft
    assert sha256(assemble_docx(again.draft)).hexdigest() == digest
    assert active.load(TOKEN, PROFILE.contract, "unrelated-site", PERIOD) is None
    assert active.load(TOKEN, PROFILE.contract, PROFILE.key, ReportPeriod(2026, 10)) is None

    # Fresh Streamlit session (same browser token, no old widget identity).
    reopened = _open(monkeypatch, tmp_path)
    assert (_editor(reopened, "Demo organization").value,
            _editor(reopened, "Demo activity").value) == (first, second)
    assert reopened.session_state["saved_revision"] == baseline.revision
    assert sha256(assemble_docx(_journal().draft)).hexdigest() == digest


def test_same_event_preview_cannot_overtake_delivered_second_field(
        monkeypatch, tmp_path):
    app = _open(monkeypatch, tmp_path)
    _editor(app, "Demo organization").set_value("Earlier real edit").run()
    before = _journal()
    _editor(app, "Demo activity").set_value("Later native input")
    next(button for button in app.button if button.label == "Preview current draft").click().run()
    assert not app.exception
    committed = _journal()
    assert committed.revision == before.revision + 1
    assert _text(committed.draft, 0) == "Earlier real edit"
    assert _text(committed.draft, 1) == "Later native input"
    assert app.session_state["save_outcome"] == "saved"


def test_stale_preview_and_failed_receipt_keep_both_versions_for_comparison(
        monkeypatch, tmp_path):
    app = _open(monkeypatch, tmp_path)
    _editor(app, "Demo organization").set_value("Local saved organization wording").run()
    _editor(app, "Demo activity").set_value("Local saved activity wording").run()
    prior = _journal()
    newer = replace(prior.draft, blocks=tuple(
        replace(block, text="Different tab's durable edit")
        if index == 1 else block
        for index, block in enumerate(prior.draft.blocks)))
    advanced = active.save(
        TOKEN, newer, expected_revision=prior.revision,
        expected_generation=prior.generation, base_snapshot_revision=0)
    assert advanced.revision == prior.revision + 1

    # The stale session's Preview must not adopt a newer journal receipt or
    # overwrite the other tab's durable revision even when its text is unchanged.
    next(button for button in app.button if button.label == "Preview current draft").click().run()
    assert not app.exception
    assert app.session_state["save_outcome"] == "conflict"
    assert any('data-save-state="failed"' in m.value for m in app.markdown)
    assert _text(app.session_state["draft"], 1) == "Local saved activity wording"
    assert _journal() == advanced

    # A real edit in the stale tab stays visible locally but cannot publish.
    _editor(app, "Demo organization").set_value("Newer local unsaved change").run()
    assert not app.exception
    assert app.session_state["save_outcome"] == "conflict"
    assert _text(app.session_state["draft"], 0) == "Newer local unsaved change"
    assert _journal() == advanced
    reopened = _open(monkeypatch, tmp_path)
    assert _editor(reopened, "Demo activity").value == "Different tab's durable edit"
    assert _editor(reopened, "Demo organization").value == "Local saved organization wording"
