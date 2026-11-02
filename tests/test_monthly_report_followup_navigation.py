"""Exact follow-up targets and native capture-before-pagination routing."""
from dataclasses import replace
import pytest
from streamlit.testing.v1 import AppTest
from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, default_sections, synthetic_profiles
from app.monthly_report_followups import problems, problem_details
from app.monthly_report_followup_navigation import followup_target, resolve_followup


def fixture(category='issue'):
    items = tuple(ReportFollowUp(f'{category}-{n}', category, f'Inspect item {n}', '2026-09',
        status='pending' if category == 'proposal' else 'ongoing') for n in range(30))
    items = (*items[:-1], replace(items[-1], text=''))
    return ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10), 'Synthetic Editor',
                       default_sections(), (), follow_ups=items)


@pytest.mark.parametrize('category', ['issue','proposal'])
def test_structured_problem_api_preserves_all_messages_and_exact_occurrence(category):
    draft = fixture(category)
    item = draft.follow_ups[-1]
    assert problems(item, draft) == tuple(p.message for p in problem_details(item,draft))
    target = followup_target(draft,item,'description')
    assert resolve_followup(draft,target) == item
    for changed in (replace(item,key='other'), replace(item,text='Now corrected'), replace(item,included=False)):
        assert resolve_followup(replace(draft, follow_ups=(*draft.follow_ups[:-1],changed)), target) is None
    assert resolve_followup(replace(draft,follow_ups=(*draft.follow_ups,item)),target) is None
    assert resolve_followup(replace(draft,follow_ups=draft.follow_ups[:-1]),target) is None
    assert resolve_followup(replace(draft,period=ReportPeriod(2026,11)),target) is None
    assert resolve_followup(replace(draft,sections=()),target) is None


SCRIPT = '''
import streamlit as st
from app.monthly_report_followups import render_followups
from app.monthly_report_issues import acknowledge_issue_controls
from app.monthly_report_ui import _field, preserve_report_draft_state, restore_report_draft_state
from app.monthly_report_checks import preflight
from app.monthly_report_followup_navigation import render_links, NOTICE
restore_report_draft_state()
st.session_state['review_pages_draft'] = render_followups(st.session_state['review_pages_draft'],
    'review_pages', _field, category=st.session_state['category'])
acknowledge_issue_controls(st.session_state['review_pages_draft'], 'review_pages')
from app.monthly_report_issues import _action_scope
st.session_state['last_scope'] = _action_scope(st.session_state['review_pages_draft'], 'review_pages')
for check in preflight(st.session_state['review_pages_draft']):
    render_links(check, st.session_state['review_pages_draft'], 'review_pages')
notice = st.session_state.pop('review_pages_followup_navigation_notice', None)
if notice: st.warning(notice)
preserve_report_draft_state()
'''


def workspace(category):
    app = AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state['category'] = category
    app.session_state['review_pages_draft'] = fixture(category)
    app.run()
    if category == 'proposal':
        next(b for b in app.button if b.label == 'Update proposal').click().run()
    assert not app.exception
    return app


def correction(app):
    return next(b for b in app.button if b.label.endswith('· description'))


def page(app,category):
    return next(w for w in app.selectbox if w.label == ('Issue page' if category == 'issue' else 'Proposal page'))


def text_field(app,category):
    return next(w for w in app.text_area if w.label == ('Issue description' if category == 'issue' else 'Proposal scope'))


@pytest.mark.parametrize('category',['issue','proposal'])
def test_unblurred_native_edit_survives_warning_jump_and_repeated_rerender(category):
    app = workspace(category)
    before = app.session_state.review_pages_draft
    text_field(app,category).set_value('An unblurred old-page edit')
    correction(app).click().run()
    assert not app.exception
    after = app.session_state.review_pages_draft
    assert after.follow_ups[0].text == 'An unblurred old-page edit'
    assert after.follow_ups[-1] == before.follow_ups[-1]
    assert page(app,category).value == 2
    markup='\n'.join(m.value for m in app.markdown)
    assert 'enfra-page-correction-request' in markup
    for _ in range(2):
        app.run()
        assert not app.exception
        assert app.session_state.review_pages_draft == after
        assert 'enfra-page-correction-request' not in '\n'.join(m.value for m in app.markdown)
    # An ordinary native pagination change must still preserve its old input.
    index = 25 if category == 'issue' else 29  # Only the targeted proposal is editing.
    text_field(app,category).set_value('An unblurred second-page edit')
    page(app,category).set_value(1).run()
    assert app.session_state.review_pages_draft.follow_ups[index].text == 'An unblurred second-page edit'


@pytest.mark.parametrize('category',['issue','proposal'])
@pytest.mark.parametrize('change',['revision','removed','omitted','scope','duplicate'])
def test_held_warning_never_mutates_replacement_or_selects_sibling(category,change):
    app=workspace(category)
    old=app.session_state.review_pages_draft
    if change == 'scope':
        app.session_state.review_pages_rich_text_epoch='new incarnation'
        new=old
    elif change == 'removed': new=replace(old,follow_ups=old.follow_ups[:-1])
    elif change == 'duplicate': new=replace(old,follow_ups=(*old.follow_ups,old.follow_ups[-1]))
    else:
        item=replace(old.follow_ups[-1], **({'text':'Replacement'} if change=='revision' else {'included':False}))
        new=replace(old,follow_ups=(*old.follow_ups[:-1],item))
    app.session_state.review_pages_draft=new
    correction(app).click().run()
    assert not app.exception
    assert page(app,category).value == 1
    assert 'enfra-page-correction-request' not in '\n'.join(m.value for m in app.markdown)
    assert any('changed or is unavailable' in w.value for w in app.warning)
    if change != 'duplicate': assert app.session_state.review_pages_draft == new


@pytest.mark.parametrize('category',['issue','proposal'])
def test_target_own_unblurred_edit_invalidates_old_warning_without_losing_input(category):
    app=workspace(category)
    correction(app).click().run()
    target_key = 'review_pages_' + ('issue_issue-29_text' if category=='issue' else 'follow_proposal-29_compact_text')
    target=next(w for w in app.text_area if w.key == target_key)
    target.set_value('Exact target corrected during the click')
    correction(app).click().run()
    assert not app.exception
    assert app.session_state.review_pages_draft.follow_ups[-1].text == 'Exact target corrected during the click'
    assert any('changed or is unavailable' in w.value for w in app.warning)
    assert 'enfra-page-correction-request' not in '\n'.join(m.value for m in app.markdown)
    assert not app.session_state.review_pages_draft.follow_ups[-1].reviewed_fingerprint


@pytest.mark.parametrize('category,reason',[('issue','evidence'),('issue','sources'),
    ('issue','period'),('proposal','sources'),('proposal','decision')])
def test_specific_problem_routes_to_existing_native_field_without_approval(category,reason):
    app=workspace(category)
    old=app.session_state.review_pages_draft
    item=replace(old.follow_ups[-1],text='Target description',status='updated',update='Older update',
                 update_period='2026-09') if category=='issue' else replace(old.follow_ups[-1],text='Target proposal')
    if reason=='sources': item=replace(item,references=('missing:1:bytes',))
    app.session_state.review_pages_draft=replace(old,follow_ups=(*old.follow_ups[:-1],item))
    app.run()
    label={'evidence':'evidence','sources':'source links','period':'update month','decision':'decision'}[reason]
    next(b for b in app.button if b.label.endswith('· '+label)).click().run()
    assert not app.exception
    assert app.session_state.review_pages_draft.follow_ups[-1] == item
    markup='\n'.join(m.value for m in app.markdown)
    assert 'enfra-page-correction-request' in markup
    suffix={'evidence':'_note','sources':'_remove_missing_','period':'_period_confirm_','decision':'_status'}[reason]
    import re
    key=re.search(r'data-field-key="([^"]+)"',markup).group(1)
    assert suffix in key
    widgets=list(app.text_area)+list(app.checkbox)+list(app.radio)+list(app.button)
    assert len([w for w in widgets if w.key==key]) == 1
    if reason == "period":
        native = next(w for w in app.button if w.key == key)
        assert native.label == "Confirm update for October 2026"
        assert not native.disabled
        assert 'data-field-kind="button"' in markup
        assert not app.session_state.review_pages_draft.follow_ups[-1].reviewed_fingerprint


@pytest.mark.parametrize('category',['issue','proposal'])
def test_repeated_warning_callbacks_are_navigation_only(category):
    app=workspace(category)
    before=app.session_state.review_pages_draft
    for _ in range(3):
        correction(app).click().run()
        assert not app.exception
        assert app.session_state.review_pages_draft == before
        assert page(app,category).value==2
    app.run()
    assert 'enfra-page-correction-request' not in '\n'.join(m.value for m in app.markdown)


@pytest.mark.parametrize('category',['issue','proposal'])
@pytest.mark.parametrize('change',['scope','revision','removed','malformed_nonce'])
def test_queued_request_revalidates_after_capture_before_any_page_selection(category,change):
    app=workspace(category)
    draft=app.session_state.review_pages_draft
    app.session_state.review_pages_followup_navigation_pending={
        'target':followup_target(draft,draft.follow_ups[-1],'description'),
        'scope':app.session_state.last_scope,
        'nonce':None if change=='malformed_nonce' else 'one-shot-synthetic-request'}
    if change=='scope': app.session_state.review_pages_rich_text_epoch='newer incarnation'
    if change=='revision':
        app.session_state.review_pages_draft=replace(draft,follow_ups=(*draft.follow_ups[:-1],replace(draft.follow_ups[-1],text='Newer value')))
    if change=='removed': app.session_state.review_pages_draft=replace(draft,follow_ups=draft.follow_ups[:-1])
    app.run()
    assert not app.exception
    assert page(app,category).value==1
    assert 'enfra-page-correction-request' not in '\n'.join(m.value for m in app.markdown)
    assert any('changed or is unavailable' in w.value for w in app.warning)
    assert 'review_pages_followup_navigation_pending' not in app.session_state.filtered_state
