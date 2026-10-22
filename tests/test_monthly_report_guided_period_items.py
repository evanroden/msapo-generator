"""Item decisions use the one canonical Activity editor and durable draft."""
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportPeriod
from app.monthly_report_checks import preflight
from app.monthly_report_period_items import HISTORICAL, exclusions

OLD = 'August 16 2026: inspected the synthetic pump.'
CURRENT = 'September 18 2026: corrected the synthetic valve.'
APP = '''
import streamlit as st
from dataclasses import replace
from app.monthly_report_guided import _edit_content, _refresh_period_editors_after_commit
from app.monthly_report_model import BlockSpec, ResolvedBlock, ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field
base=synthetic_draft(synthetic_profiles()[0],ReportPeriod(2026,9))
block=st.session_state.setdefault('canonical',ResolvedBlock('activity_summary','This month',text='August 16 2026: inspected the synthetic pump.\\nSeptember 18 2026: corrected the synthetic valve.'))
draft=replace(base,blocks=(block,))
result=_edit_content(BlockSpec('activity_summary','rich_text'),block,None,'period_probe',{},_field,draft)
st.session_state['result']=result
if st.session_state.get('commit_enabled',True):
    st.session_state['canonical']=result
    _refresh_period_editors_after_commit('period_probe')
'''


def editor(app):
    return next(item for item in app.text_area if item.label == 'Activity summary')


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def test_exclude_restore_and_historical_keep_one_current_editor_without_resurrection():
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert sum('id="report-editor-activity_summary"' in item.value for item in app.markdown) == 1
    assert any('#report-editor-activity_summary' in item.value for item in app.markdown)
    click(app, 'Leave out')
    assert len(app.text_area) == 1
    assert editor(app).value == app.session_state['canonical'].text == CURRENT
    for _ in range(2):
        app.run()
        assert editor(app).value == CURRENT
    click(app, 'Restore this wording')
    assert OLD in editor(app).value
    click(app, 'Keep as history')
    assert HISTORICAL + OLD in editor(app).value
    assert editor(app).value == app.session_state['canonical'].text
    app.run()
    assert not any(b.label == 'Keep as history' for b in app.button)
    # A substantive wording/date correction invalidates only this exact choice.
    editor(app).set_value(editor(app).value.replace('inspected', 'rechecked')).run()
    assert any(b.label == 'Keep as history' for b in app.button)


def test_repeat_import_and_old_widget_receipt_cannot_restore_excluded_wording():
    app = AppTest.from_string(APP).run()
    original_key = editor(app).key
    editor(app).set_value(OLD + '\n' + CURRENT + '\nManual correction retained.').run()
    old_receipt = dict(app.session_state[original_key + '_explicitly_edited'])
    click(app, 'Leave out')
    canonical = app.session_state['canonical']
    assert OLD not in canonical.text and 'Manual correction retained.' in canonical.text
    # Repeat source material retaining report decisions, including a late old
    # textarea callback. The exact omission persists and sibling text survives.
    app.session_state['canonical'] = replace(canonical, text=OLD + '\n' + canonical.text)
    app.session_state[original_key + '_explicitly_edited'] = old_receipt
    app.run()
    assert not app.exception
    assert editor(app).value == app.session_state['canonical'].text == canonical.text
    assert exclusions(app.session_state['canonical'], ReportPeriod(2026,9))
    click(app, 'Restore this wording')
    assert editor(app).value.count(OLD) == 1
    editor(app).set_value('September 16 2026: manually corrected current work.').run()
    app.run()
    assert editor(app).value == app.session_state['canonical'].text == 'September 16 2026: manually corrected current work.'
    assert not any(b.label == 'Keep as history' for b in app.button)


def test_interrupted_decision_replays_exact_baseline_but_not_newer_report():
    app = AppTest.from_string(APP).run()
    app.session_state['commit_enabled'] = False
    click(app, 'Leave out')
    assert OLD in app.session_state['canonical'].text
    assert OLD not in app.session_state['result'].text
    app.session_state['commit_enabled'] = True
    app.run()
    assert not app.exception and editor(app).value == CURRENT
    click(app, 'Restore this wording')
    app.session_state['commit_enabled'] = False
    click(app, 'Leave out')
    newer = replace(app.session_state['canonical'], text='September 21 2026: a newer manual correction.')
    app.session_state['canonical'] = newer
    app.session_state['commit_enabled'] = True
    app.run()
    assert not app.exception and editor(app).value == newer.text
    assert app.session_state['canonical'] == newer


def test_full_guided_durable_recovery_and_docx_exclude_receipt_payload(monkeypatch, tmp_path):
    from test_monthly_report_qa_ui import visit, ACTOR_COOKIE
    from app import monthly_report_testing as qa, monthly_report_qa_fixture as fixture
    from app import monthly_report_active_work as active
    from app.monthly_report_docx import assemble_docx
    app = visit(monkeypatch, tmp_path)
    click(app, 'Load known-value report')
    priced = 'August 20 2026: quoted synthetic repair cost $987654.'
    editor(app).set_value(priced + '\n' + CURRENT).run()
    click(app, 'Leave out')
    assert editor(app).value == CURRENT
    with qa.isolated(ACTOR_COOKIE):
        journal = active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        block = next(block for block in journal.draft.blocks if block.key == 'activity_summary')
        assert block.text == CURRENT
        receipt = next(ref for ref in block.references if ref.startswith('period-item:v1:'))
        raw = assemble_docx(journal.draft, acknowledged_fingerprint=journal.draft.fingerprint)
    with ZipFile(BytesIO(raw)) as package:
        contents = b'\n'.join(package.read(name) for name in package.namelist())
    assert priced.encode() not in contents and receipt.encode() not in contents
    assert receipt.split(':',2)[2].encode() not in contents
    assert b'987654' not in contents
    reopened = visit(monkeypatch, tmp_path)
    assert editor(reopened).value == CURRENT
    click(reopened, 'Restore this wording')
    assert priced in editor(reopened).value
    with qa.isolated(ACTOR_COOKIE):
        journal = active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    assert any(check.blocking and check.code == 'pricing' for check in preflight(journal.draft))


def test_interrupted_manual_edit_and_omission_reconciliation_survive_together():
    app = AppTest.from_string(APP).run()
    click(app, 'Leave out')
    canonical = app.session_state['canonical']
    app.session_state['canonical'] = replace(canonical, text=OLD + '\n' + CURRENT)
    app.session_state['commit_enabled'] = False
    app.run()
    # Its still-mounted callback describes the imported baseline. A newer
    # exclusion transition must retain this interrupted wording for review.
    manual = OLD + '\n' + CURRENT + '\nCurrent manual sibling edit.'
    editor(app).set_value(manual).run()
    app.session_state['commit_enabled'] = True
    app.run()
    assert not app.exception and OLD not in editor(app).value
    assert any(b.label == 'Apply interrupted edit' for b in app.button)
    # Explicit recovery is a valid manual edit against the current baseline.
    # Reconciliation removes only the excluded line; an interrupted full commit
    # must preserve the sibling edit together with the omission decision.
    app.session_state['commit_enabled'] = False
    click(app, 'Apply interrupted edit')
    assert app.session_state['canonical'].text == CURRENT
    assert app.session_state['result'].text == CURRENT + '\nCurrent manual sibling edit.'
    app.session_state['commit_enabled'] = True
    app.run()
    assert not app.exception
    assert editor(app).value == app.session_state['canonical'].text == CURRENT + '\nCurrent manual sibling edit.'
