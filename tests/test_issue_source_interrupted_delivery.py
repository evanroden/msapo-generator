"""Synthetic native issue receipts: a render is not canonical acknowledgement.

The pre-enqueue case interrupts Streamlit after native callback registration,
not only after the row renderer returns. Neither case uses the frontend Tab
helper: the second delivery is a legitimate explicit source selection.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, ReportSource, synthetic_profiles
from app.monthly_report_sources import source_reference


SCRIPT = '''
import streamlit as st
from unittest.mock import patch
from streamlit.delta_generator import DeltaGenerator
from app.monthly_report_followups import render_followups
from app import monthly_report_issues as issues
from app.monthly_report_ui import _field
original_enqueue = DeltaGenerator._enqueue
def enqueue(self, delta_type, *args, **kwargs):
    if delta_type == 'multiselect' and st.session_state.pop('interrupt_enqueue', False):
        st.stop()
    return original_enqueue(self, delta_type, *args, **kwargs)
with patch.object(DeltaGenerator, '_enqueue', enqueue):
    result = render_followups(st.session_state['draft'], 'delivery', _field, category='issue')
if st.session_state.pop('interrupt_once', False):
    st.session_state['interrupted_result'] = result
    st.stop()
st.session_state['draft'] = result
if hasattr(issues, 'acknowledge_issue_controls'):
    issues.acknowledge_issue_controls(result, 'delivery')
'''


def workspace(draft=None):
    source = ReportSource('independent', 'synthetic-evidence.txt', 'b' * 64, '.txt',
                          page_texts=('First inspection.', 'Second inspection.', 'Third inspection.'))
    item = ReportFollowUp('row-one', 'issue', 'Inspect intake damper.', '2026-10',
                          references=('missing:original:page',))
    if draft is None:
        draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10), 'Synthetic editor',
            (), (), sources=(source,), follow_ups=(item,), synthetic=True)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['draft'] = draft
    app.run()
    assert not app.exception
    return app, source


def picker(app):
    return next(w for w in app.multiselect if w.label == 'Supporting source pages')


def selected(app):
    return app.session_state['draft'].follow_ups[0].references


def source_packet(widget_id, refs):
    states = WidgetStates()
    widget = states.widgets.add()
    widget.id = widget_id
    widget.string_array_value.data.extend(refs)
    return states


@pytest.mark.parametrize('interrupt', [None, 'interrupt_once', 'interrupt_enqueue'])
def test_legitimate_second_selection_retains_both_links_without_native_reset(interrupt):
    app, source = workspace()
    before = app.session_state['draft']
    a, b = (source_reference(source, n) for n in (1, 2))
    native_id = picker(app).id
    if interrupt:
        app.session_state[interrupt] = True
    picker(app).set_value([a]).run()
    assert not app.exception
    if interrupt:
        assert app.session_state['draft'] == before
    app._run(source_packet(native_id, [a, b]))
    assert not app.exception
    assert selected(app) == (a, b, 'missing:original:page')
    assert picker(app).value == [a, b]
    assert picker(app).id == native_id
    assert not picker(app).proto.set_value, 'No server-authored empty reset may erase native links.'
    assert not any('_pending_issue_delivery_' in key for key in app.session_state.filtered_state)


def test_repeated_interruption_aba_and_explicit_clear_are_deliberate_selections():
    app, source = workspace()
    before = app.session_state['draft']
    a, b, c = [source_reference(source, n) for n in (1, 2, 3)]
    native_id = picker(app).id
    for refs in ([a], [a, b], [a], [a, b, c], []):
        app.session_state['interrupt_once'] = True
        picker(app).set_value(refs).run()
        assert not app.exception
        assert app.session_state['draft'] == before
        assert app.session_state['interrupted_result'].follow_ups[0].references == (*refs, 'missing:original:page')
        assert picker(app).id == native_id
    app.run()
    assert selected(app) == ('missing:original:page',)
    assert picker(app).value == []
    assert not any('_pending_issue_delivery_' in key for key in app.session_state.filtered_state)


def test_interrupted_selection_then_unlink_and_next_selection():
    app, source = workspace()
    a, b = [source_reference(source, n) for n in (1, 2)]
    app.session_state['interrupt_once'] = True
    picker(app).set_value([a]).run()
    next(w for w in app.checkbox if w.label == 'Remove unavailable source links').check().run()
    assert not app.exception and selected(app) == (a,)
    picker(app).set_value([a, b]).run()
    assert not app.exception and selected(app) == (a, b)
    assert not any('Earlier issue edit' in w.label for w in app.expander)


@pytest.mark.parametrize('replacement', ['row', 'period', 'profile', 'editor', 'source', 'source_order', 'row_key'])
def test_pending_selection_never_replays_into_replaced_scope(replacement):
    app, source = workspace()
    before = app.session_state['draft']
    a = source_reference(source, 1)
    app.session_state['interrupt_once'] = True
    picker(app).set_value([a]).run()
    if replacement == 'row':
        before = replace(before, follow_ups=(replace(before.follow_ups[0], text='Independent newer finding.'),))
    elif replacement == 'period':
        before = replace(before, period=ReportPeriod(2026, 11))
    elif replacement == 'profile':
        before = replace(before, profile=replace(before.profile, title='Independent report profile'))
    elif replacement == 'editor':
        app.session_state['delivery_rich_text_epoch'] = 'replacement-editor'
    elif replacement == 'source':
        before = replace(before, sources=(replace(source, page_texts=('Changed page.',)),))
    elif replacement == 'source_order':
        before = replace(before, sources=(replace(source, id='other'), source))
    else:
        before = replace(before, follow_ups=(replace(before.follow_ups[0], key='different-row'),))
    app.session_state['draft'] = before
    app.run()
    assert not app.exception and app.session_state['draft'] == before
    assert picker(app).value == []
    assert any('synthetic-evidence.txt · page 1' in w.proto.code_text for w in app.get('code'))


def test_conflicting_links_remain_recoverable_after_new_deliberate_edit():
    app, source = workspace()
    before = app.session_state['draft']
    app.session_state['interrupt_once'] = True
    picker(app).set_value([source_reference(source, 1)]).run()
    app.session_state['draft'] = replace(before, follow_ups=(replace(before.follow_ups[0], text='Independent finding.'),))
    app.run()
    next(w for w in app.text_area if w.label == 'Issue description').set_value('Fresh deliberate correction.').run()
    app.run()
    assert not app.exception
    assert app.session_state['draft'].follow_ups[0].text == 'Fresh deliberate correction.'
    assert selected(app) == ('missing:original:page',)
    earlier = [w.proto.code_text for w in app.get('code') if 'Inspect intake damper.' in w.proto.code_text]
    assert len(earlier) == 1 and 'synthetic-evidence.txt · page 1' in earlier[0]


def test_acknowledged_receipt_and_retired_callback_cannot_replay_after_aba():
    app, source = workspace()
    before = app.session_state['draft']
    key = picker(app).key
    registration = deepcopy(app.session_state[key + '_delivery'])
    app.session_state['interrupt_once'] = True
    picker(app).set_value([source_reference(source, 1)]).run()
    receipt = deepcopy(app.session_state[key + '_change'])
    app.run()  # Actual canonical assignment retires the matching pending edit.
    app.session_state['draft'] = before
    app.session_state[key + '_change'] = receipt
    app.run()
    assert not app.exception and app.session_state['draft'] == before
    # The retired callback itself is also rejected even with identical content.
    from app.monthly_report_issues import _issue_changed
    from unittest.mock import patch
    state = dict(app.session_state.filtered_state)
    state[key] = [source_reference(source, 2)]
    with patch('streamlit.session_state', state):
        _issue_changed(key, registration['before'], registration['identity'], registration['token'])
    assert key + '_change' not in state


def test_source_and_description_status_co_delivery_survive_early_interruption():
    app, source = workspace()
    a, b = [source_reference(source, n) for n in (1, 2)]
    native_id = picker(app).id
    next(w for w in app.text_area if w.label == 'Issue description').set_value('Delivered description.')
    next(w for w in app.selectbox if w.label == 'Issue status').set_value('updated')
    app.session_state['interrupt_enqueue'] = True
    picker(app).set_value([a]).run()
    app._run(source_packet(native_id, [a, b]))
    assert not app.exception
    item = app.session_state['draft'].follow_ups[0]
    assert (item.text, item.status, item.references) == ('Delivered description.', 'updated', (a, b, 'missing:original:page'))


def test_unrelated_canonical_changes_and_other_rows_are_preserved():
    app, source = workspace()
    before = app.session_state['draft']
    other = replace(before.follow_ups[0], key='row-two', text='Other independently edited issue.')
    app.session_state['draft'] = replace(before, follow_ups=(*before.follow_ups, other))
    app.run()
    app.session_state['interrupt_once'] = True
    picker(app).set_value([source_reference(source, 1)]).run()
    canonical = app.session_state['draft']
    app.session_state['draft'] = replace(canonical, prepared_by='A different deliberate editor')
    app.run()
    assert not app.exception
    draft = app.session_state['draft']
    assert draft.prepared_by == 'A different deliberate editor'
    assert draft.follow_ups[1] == other
    assert draft.follow_ups[0].references[0] == source_reference(source, 1)


def test_reload_and_competing_saves_keep_optimistic_revision_guards(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app, source = workspace()
    a, b = [source_reference(source, n) for n in (1, 2)]
    app.session_state['interrupt_once'] = True
    picker(app).set_value([a]).run()
    picker(app).set_value([a, b]).run()
    draft = app.session_state['draft']
    library.save_profile(draft.profile, expected_revision=0, actor='Synthetic editor', confirmed=True)
    first = library.save_snapshot(draft, expected_revision=0, entered_editor='Synthetic editor')
    loaded = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.draft.follow_ups == draft.follow_ups
    resumed, _ = workspace(loaded.draft)
    assert selected(resumed) == (a, b, 'missing:original:page')
    assert picker(resumed).value == [a, b]
    assert not any('_pending_issue_delivery_' in key for key in resumed.session_state.filtered_state)
    def save(editor):
        try:
            return library.save_snapshot(replace(draft, prepared_by=editor),
                expected_revision=first.revision, entered_editor=editor).revision
        except library.RevisionConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ['Synthetic writer one', 'Synthetic writer two']))
    assert sorted(results, key=str) == [first.revision + 1, 'conflict']
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft.follow_ups == draft.follow_ups


def test_source_delivery_with_deferred_clear_is_acknowledged_only_after_assignment():
    script = SCRIPT.replace("category='issue')", "category='issue', defer_issue_actions=True)")
    script = script.replace("st.session_state['draft'] = result", "result = issues.apply_issue_action(result, 'delivery')\nst.session_state['draft'] = result")
    app, source = workspace()
    # Reuse only the synthetic canonical draft in a normal ordered-caller scaffold.
    ordered = AppTest.from_string(script, default_timeout=30)
    ordered.session_state['draft'] = app.session_state['draft']
    ordered.run()
    picker(ordered).set_value([source_reference(source, 1)])
    next(w for w in ordered.button if w.label == 'Clear issues from this report').click().run()
    assert not ordered.exception
    item = ordered.session_state['draft'].follow_ups[0]
    assert not item.included and item.references[0] == source_reference(source, 1)
    assert not any('_pending_issue_delivery_' in key for key in ordered.session_state.filtered_state)
