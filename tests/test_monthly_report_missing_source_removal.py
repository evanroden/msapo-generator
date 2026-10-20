"""Independent synthetic AppTest regression; no production edits or browser claim."""
from dataclasses import replace
import pytest
from streamlit.testing.v1 import AppTest
from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, ReportSource, synthetic_profiles
from app.monthly_report_sources import source_reference

SCRIPT = '''
import streamlit as st
from app.monthly_report_followups import render_followups
from app.monthly_report_ui import _field
st.session_state['runs'] = st.session_state.get('runs', 0) + 1
st.session_state['draft'] = render_followups(st.session_state['draft'], 'independent', _field, category=st.session_state['category'])
'''
LABEL='Remove unavailable source links'
WARNINGS=('A supporting source changed or is missing.', 'Some saved source links are unavailable. Replace them with current evidence, or explicitly remove them.')

def app_for(category, with_source=True):
    source=ReportSource('synthetic', 'synthetic-evidence.pdf', 'a'*64, '.pdf', page_texts=('Synthetic first page.','Synthetic second page.'))
    refs=(source_reference(source,1), 'missing:first:old', 'missing:second:old') if with_source else ('missing:first:old','missing:second:old')
    item=ReportFollowUp('one', category, 'Synthetic one.', '2026-09', status='updated' if category=='issue' else 'pending', update='Original update.', evidence_note='Original evidence.', references=refs)
    other=ReportFollowUp('two',category,'Synthetic two.','2026-09',references=(source_reference(source,2),) if with_source else ())
    draft=ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,10),'Synthetic Editor',(),(),sources=(source,) if with_source else (),follow_ups=(item,other),synthetic=True)
    app=AppTest.from_string(SCRIPT,default_timeout=15)
    app.session_state['draft']=draft
    app.session_state['category']=category
    app.run()
    assert not app.exception
    return app

def remove(app):
    return next(w for w in app.checkbox if w.label==LABEL)

@pytest.mark.parametrize('category',['issue','proposal'])
@pytest.mark.parametrize('with_source',[True,False])
def test_one_removal_rerun_hides_warning_and_preserves_delivered_edits(category,with_source):
    app=app_for(category,with_source)
    before=app.session_state['draft']; checkbox=remove(app); old_id=checkbox.id; old_key=checkbox.key
    assert not checkbox.value
    for _ in range(2):
        app.run()
        assert app.session_state['draft']==before
        assert remove(app).id==old_id and remove(app).key==old_key and not remove(app).value
        assert any(w.value in WARNINGS for w in app.warning)
    update_label='Issue update' if category=='issue' else 'What changed this month?'
    next(w for w in app.text_area if w.label==update_label).set_value('Delivered together with removal.')
    next(w for w in app.text_area if w.label=='Evidence or explanation for the status').set_value('Preserve this evidence note.')
    runs=app.session_state['runs']
    remove(app).check().run()
    assert not app.exception
    after=app.session_state['draft']
    assert app.session_state['runs']==runs+1
    assert remove(app).id==old_id and remove(app).key==old_key and remove(app).value
    assert after.follow_ups[0].references==before.follow_ups[0].references[:1] if with_source else not after.follow_ups[0].references
    assert after.follow_ups[0].update=='Delivered together with removal.'
    assert after.follow_ups[0].evidence_note=='Preserve this evidence note.'
    assert after.follow_ups[1]==before.follow_ups[1]
    assert after.sources==before.sources and after.blocks==before.blocks
    assert not any(w.value in WARNINGS for w in app.warning)
    app.run()
    assert app.session_state['draft']==after
    assert not any(w.label==LABEL for w in app.checkbox)

@pytest.mark.parametrize('category',['issue','proposal'])
def test_new_missing_set_requires_separate_explicit_removal(category):
    app=app_for(category)
    old_key=remove(app).key
    remove(app).check().run()
    app.run()
    draft=app.session_state['draft']
    item=replace(draft.follow_ups[0], references=(*draft.follow_ups[0].references,'missing:new:revision'))
    app.session_state['draft']=replace(draft,follow_ups=(item,draft.follow_ups[1]))
    app.run()
    assert not app.exception
    assert remove(app).key!=old_key and not remove(app).value
    assert app.session_state['draft'].follow_ups[0].references==item.references
    assert any(w.value in WARNINGS for w in app.warning)

@pytest.mark.parametrize('category',['issue','proposal'])
def test_removal_does_not_hide_another_items_missing_evidence(category):
    app=app_for(category)
    draft=app.session_state['draft']
    second=replace(draft.follow_ups[1],references=(*draft.follow_ups[1].references,'missing:other:item'))
    app.session_state['draft']=replace(draft,follow_ups=(draft.follow_ups[0],second))
    app.run()
    assert sum(w.value in WARNINGS for w in app.warning)==2
    checkboxes=[w for w in app.checkbox if w.label==LABEL]
    assert len(checkboxes)==2
    checkboxes[0].check().run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups[1]==second
    assert not [w for w in app.checkbox if w.label==LABEL][1].value
    assert sum(w.value in WARNINGS for w in app.warning)==1


def test_removal_persists_current_evidence_on_first_full_workflow_rerun(monkeypatch, tmp_path):
    """Use the real editor, widget mirrors and recovery journal, without a second rerun."""
    from test_monthly_report_qa_ui import visit, ACTOR_COOKIE
    from app import monthly_report_testing as qa, monthly_report_qa_fixture as fixture
    from app import monthly_report_library as library
    from app.monthly_report_active_work import load
    from app.monthly_report_checks import preflight

    app = visit(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Replay synthetic source files").click().run()
    with qa.isolated(ACTOR_COOKIE):
        original = next(s for s in library.load_snapshot(
            fixture.CONTRACT, fixture.profile().key, fixture.PERIOD).draft.sources
            if s.filename == "synthetic-activity.txt")
    next(w for w in app.multiselect if w.label == "Source sites" and original.id in w.key).set_value(["qa-north"])
    next(b for b in app.button if b.label == "Use these source details" and original.id in b.key).click().run()
    with qa.isolated(ACTOR_COOKIE):
        source = next(s for s in load(ACTOR_COOKIE, fixture.CONTRACT,
            fixture.profile().key, fixture.PERIOD).draft.sources if s.id == original.id)
    reference = source_reference(source, 1)
    next(w for w in app.multiselect if w.label == "Supporting source pages").set_value([reference]).run()
    checkbox = remove(app)
    native_id = checkbox.id
    with qa.isolated(ACTOR_COOKIE):
        before = load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD).draft.fingerprint
    checkbox.check().run()
    assert not app.exception
    with qa.isolated(ACTOR_COOKIE):
        draft = load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD).draft
    assert draft.follow_ups[0].references == (reference,)
    assert draft.fingerprint != before
    assert not any(check.blocking for check in preflight(draft))
    assert next(w for w in app.multiselect if w.label == "Supporting source pages").value == [reference]
    assert remove(app).id == native_id and remove(app).value is True
    assert any(w.value == "QA working report SHA256: " + draft.fingerprint for w in app.caption)
    assert any(w.value == "QA durable report SHA256: " + draft.fingerprint for w in app.caption)
    assert not any(w.value in WARNINGS for w in app.warning)

    # A genuinely new session must recover only the exact retained evidence.
    reopened = visit(monkeypatch, tmp_path)
    assert not reopened.exception
    assert next(w for w in reopened.multiselect if w.label == "Supporting source pages").value == [reference]
    assert not any(w.value in WARNINGS for w in reopened.warning)
    assert any(w.value == "QA durable report SHA256: " + draft.fingerprint for w in reopened.caption)
