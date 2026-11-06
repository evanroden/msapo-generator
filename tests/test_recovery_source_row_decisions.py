"""Recovery comparisons disclose private source-review work before a copy choice."""
from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active, monthly_report_library as library
from app import monthly_report_sources as sources, monthly_report_training_review_flow as training
from app import monthly_report_work_order_review_flow as orders
from app.monthly_report_compare_ui import compare_drafts
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from test_monthly_report_work_order_review_flow import draft_source, stored
from test_training_review_flow import report
from test_training_review_ui import click, open_app, widget


CSV = b'Topic,Date,Method,Participants,Hours,Status\nPrivate subject,2026-09-12,Virtual,Private learner,1,Completed\n'


@pytest.fixture
def portable(monkeypatch, tmp_path):
    # Supply the temporary original/cache destination and byte writer. Repeated
    # Training source reads use the same real CSV parser without Linux storage.
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    monkeypatch.setattr(sources, '_path', lambda profile, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, '_atomic_write', write)
    monkeypatch.setattr(training, 'source_content', lambda draft, source:
        sources.SourceContent(source, sources._spreadsheet(sources.source_bytes(draft.profile, source), '.csv')))


def copies():
    app = open_app(report(CSV))
    click(app, 'Review this Training table')
    saved = app.session_state['draft']
    widget(app, 'text_input', 'Hours').set_value('3')
    click(app, 'Save Training row review')
    return saved, app.session_state['draft']


def display(working, saved):
    changes = compare_drafts(working, saved)
    assert len(changes) == 1
    change, = changes
    assert 'review' in change.title.casefold()
    return change.saved + '\n' + change.working


def rows_in_word(draft, path, *, public=False):
    app = open_app(draft)
    click(app, 'Include reviewed Training rows')
    template = Document()
    template.add_heading('11 Training Summary', 1)
    template.add_paragraph('Session')
    template.add_table(rows=2, cols=5)
    template.save(path)
    build = build_native_docx if public else _build_native_docx
    doc = Document(BytesIO(build(app.session_state['draft'], path, section_key='training')))
    return [[c.text for c in r.cells] for table in doc.tables for r in table.rows]


def test_actual_training_decisions_affect_future_word_and_are_disclosed(portable, tmp_path):
    saved, working = copies()
    assert saved.fingerprint != working.fingerprint
    assert saved.blocks == working.blocks and saved.sources == working.sources
    assert rows_in_word(saved, tmp_path / 'template.docx')[-1][-1] == '1'
    assert rows_in_word(working, tmp_path / 'template.docx')[-1][-1] == '3'
    shown = display(working, saved)
    assert 'Training' in shown and 'Hours' in shown
    assert all(x not in shown for x in ('Private subject', 'Private learner', saved.sources[0].id, '"record"'))
    assert sources.source_bytes(saved.profile, saved.sources[0]) == CSV


@pytest.mark.parametrize('older', (False, True))
def test_actual_recovery_comparison_discloses_decision_before_choice(portable, monkeypatch, older):
    saved, working = copies()
    snapshot = library.SavedReport(saved, '2026-09-15T12:00:00Z', 8)
    script = '''
import streamlit as st
from app.monthly_report_compare_ui import render_conflict_comparison
from app.monthly_report_active_conflict_ui import render_older_draft_conflict
if st.session_state['older']:
    render_older_draft_conflict(st.session_state['active'], st.session_state['snapshot'], 'a'*32, 'review')
else:
    render_conflict_comparison(st.session_state['active'].draft, st.session_state['snapshot'])
'''
    monkeypatch.setattr(library, 'load_profile', lambda *_: SimpleNamespace(profile=working.profile))
    monkeypatch.setattr(library, 'save_snapshot', lambda *a, **k: pytest.fail('Comparison wrote shared work'))
    monkeypatch.setattr(active, 'save', lambda *a, **k: pytest.fail('Comparison wrote browser work'))
    app = AppTest.from_string(script)
    app.session_state['older'] = older
    app.session_state['active'] = active.ActiveWork(working, 3, 1, generation='b'*32)
    app.session_state['snapshot'] = snapshot
    app.run()
    if older:
        click(app, 'Review draft changes')
        assert [(b.label, b.disabled) for b in app.button] == [
            ('Continue with unfinished draft', False), ('Open saved report', False)]
    assert not app.exception
    assert not any('matches' in m.value or 'No visible' in m.value for m in app.info)
    assert 'Hours' in '\n'.join(w.value for w in app.text)
    assert app.session_state['active'].draft == working and app.session_state['snapshot'] == snapshot


@pytest.mark.parametrize(('kind', 'raw', 'field', 'edit', 'label'), [
    ('workorders', b'Work Order,Site,Date,Status,Type,Trade\n0001,North,2026-09-03,Open,PM,HVAC\n', 'status', 'Completed', 'Status'),
    ('maintenance', b'WO #,Finish Date,Area,Task,Tag,Site,Status\n0001,2026-09-03,North,Inspect pump,P-1,North,Completed\n', 'task', 'Private correction', 'Task'),
])
def test_supported_other_source_reviews_disclose_field_without_contents(portable, kind, raw, field, edit, label):
    draft, content = draft_source(raw)
    saved, bundle = stored(draft, content, kind)
    row = orders.restored_group(bundle, bundle['groups'][0]).rows[0]
    revised = orders.change_row(bundle, 0, row.key, {field: edit})
    working = orders.store_bundle(saved, revised, expected_revision=orders.revision(bundle))
    shown = display(working, saved)
    assert label in shown and all(s not in shown for s in ('Private correction', 'Inspect pump', content.source.id))


def test_added_removed_review_shows_which_source_changed(portable):
    saved, working = copies()
    empty = replace(saved, source_row_reviews=())
    assert 'Training' in display(working, empty) and 'Training' in display(empty, saved)


def test_equal_serialization_and_receipt_order_preserve_existing_behavior(portable):
    saved, working = copies()
    text, = working.source_row_reviews
    assert not compare_drafts(replace(working, source_row_reviews=(json.dumps(json.loads(text), indent=2),)), working)
    independent = report(CSV.replace(b'Private subject', b'Second subject'), 'second.csv')
    value = training.prepare_review(independent, independent.sources[0], 1)
    independent = training.store_review(independent, value)
    other = replace(working, sources=(*working.sources, *independent.sources),
                    source_row_reviews=(text, *independent.source_row_reviews))
    assert not compare_drafts(other, replace(other, source_row_reviews=other.source_row_reviews[::-1]))
    assert not compare_drafts(working, working)
    assert [c.title for c in compare_drafts(replace(working, prepared_by='Another editor'), working)] == ['Prepared by']


def test_saving_identical_training_form_fields_is_not_a_changed_decision(portable):
    app = open_app(report(CSV))
    click(app, 'Review this Training table')
    before = app.session_state['draft']
    click(app, 'Save Training row review')
    after = app.session_state['draft']
    assert before.source_row_reviews != after.source_row_reviews
    assert not compare_drafts(after, before)


def test_real_row_omission_is_distinguishable(portable):
    saved, _ = copies()
    app = open_app(saved)
    widget(app, 'checkbox', 'Omit this Training source row').check()
    click(app, 'Save Training row review')
    shown = display(app.session_state['draft'], saved)
    assert 'Row inclusion' in shown and '1 left out' in shown


def test_several_current_sources_limit_detail_and_preserve_all_receipts(portable):
    drafts = []
    for n in range(6):
        draft = report(CSV.replace(b'Private subject', ('Private subject '+str(n)).encode()), f'private-{n}.csv')
        value = training.prepare_review(draft, draft.sources[0], 1)
        drafts.append(training.store_review(draft, value))
    saved = replace(drafts[0], sources=tuple(d.sources[0] for d in drafts), source_row_reviews=())
    working = replace(saved, source_row_reviews=tuple(d.source_row_reviews[0] for d in drafts))
    shown = display(working, saved)
    assert len(shown) < 1500 and '2 additional' in shown
    assert 'private-' not in shown and 'Private subject' not in shown
    assert all(d.source_row_reviews[0] == working.source_row_reviews[i] for i,d in enumerate(drafts))


@pytest.mark.parametrize('broken', ['bad json: Private secret', '{"kind":"Private secret"}', 'x'*4_000_001],
                         ids=['older-text', 'unknown-kind', 'over-budget'])
def test_older_damaged_or_excessive_review_is_reported_without_unsafe_details(portable, broken):
    saved, _ = copies()
    shown = display(replace(saved, source_row_reviews=(broken,)), saved)
    assert len(shown) < 1500 and 'Private secret' not in shown and broken not in shown


def test_ambiguous_duplicate_identity_is_visible_and_not_collapsed(portable):
    saved, _ = copies()
    duplicated = replace(saved, source_row_reviews=saved.source_row_reviews * 2)
    with pytest.raises(ValueError, match='Multiple saved Training reviews'):
        training.saved_review(duplicated, duplicated.sources[0], 1)
    shown = display(duplicated, saved)
    assert 'Private learner' not in shown and len(shown) < 1500


def revised_work_orders():
    draft, content = draft_source()
    saved, initial = stored(draft, content)
    row = orders.restored_group(initial, initial['groups'][0]).rows[0]
    def correct(status):
        changed = orders.change_row(initial, 0, row.key, {'status': status})
        return orders.store_bundle(saved, changed, expected_revision=orders.revision(initial))
    return content, correct


def test_two_distinct_status_inputs_survive_same_normalized_result(portable):
    content, correct = revised_work_orders()
    left, right = correct('Private inspection A'), correct('Private inspection B')
    def row(draft):
        value = orders.saved_bundle(draft, content.source.id, 'workorders')
        return orders.restored_group(value, value['groups'][0]).rows[0]
    a, b = row(left), row(right)
    assert a.status == b.status == '' and a.issues == b.issues
    assert dict(a.corrections)['status'] != dict(b.corrections)['status']
    shown = display(right, left)
    assert 'Status' in shown and 'Private inspection' not in shown


def test_reordered_competing_receipts_change_the_first_selected_work_order(portable):
    content, correct = revised_work_orders()
    a, b = correct('Open'), correct('Completed')
    saved = replace(a, source_row_reviews=(*a.source_row_reviews, *b.source_row_reviews))
    working = replace(saved, source_row_reviews=saved.source_row_reviews[::-1])
    def status(draft):
        first = orders.saved_bundle(draft, content.source.id, 'workorders')
        return orders.restored_group(first, first['groups'][0]).rows[0].status
    assert status(saved) != status(working)
    assert len(display(working, saved)) < 1500


@pytest.mark.parametrize('legacy', ['PRIVATE LEGACY KEY', ['PRIVATE LEGACY KEY']])
def test_work_order_identity_ignores_training_only_legacy_extra_field(portable, legacy):
    content, correct = revised_work_orders()
    saved, working = correct('Open'), correct('Completed')
    value = json.loads(working.source_row_reviews[0])
    value['table'] = legacy
    working = replace(working, source_row_reviews=(orders.encoded(value),))
    assert orders.saved_bundle(working, content.source.id, 'workorders')['table'] == legacy
    shown = display(working, saved)
    assert 'Status' in shown and 'PRIVATE LEGACY KEY' not in shown


def test_two_corrected_hours_are_distinct_on_each_side(portable):
    saved, three = copies()
    app = open_app(saved)
    widget(app, 'text_input', 'Hours').set_value('2')
    click(app, 'Save Training row review')
    two = app.session_state['draft']
    change, = compare_drafts(three, two)
    assert 'Hours 2' in change.saved and 'Hours 3' in change.working
    assert 'Hours 3' not in change.saved and 'Hours 2' not in change.working


def test_unverified_free_text_hours_are_not_rendered(portable):
    saved, _ = copies()
    app = open_app(saved)
    widget(app, 'text_input', 'Hours').set_value('Private number 1234')
    click(app, 'Save Training row review')
    shown = display(app.session_state['draft'], saved)
    assert 'Hours' in shown and '1234' not in shown and 'Private number' not in shown


@pytest.mark.parametrize('case', ['undecided-site', 'extra-site-column', 'extra-cost-column'])
def test_numeric_hours_remain_private_outside_narrow_confirmed_event(case, portable):
    raw = CSV
    if case != 'undecided-site':
        header = b'Site' if case == 'extra-site-column' else b'Cost'
        raw = CSV.replace(b'Status\n', b'Status,'+header+b'\n').replace(b'Completed\n', b'Completed,PRIVATE SOURCE CELL\n')
    draft = report(raw)
    if case == 'undecided-site':
        draft = replace(draft, sources=(replace(draft.sources[0], scope_review=()),))
    app = open_app(draft)
    click(app, 'Review this Training table')
    saved = app.session_state['draft']
    widget(app, 'text_input', 'Hours').set_value('29')
    click(app, 'Save Training row review')
    shown = display(app.session_state['draft'], saved)
    assert 'Hours' in shown and '29' not in shown and 'PRIVATE SOURCE CELL' not in shown


def test_foreign_scope_and_untrusted_filename_stay_private(portable):
    saved, _ = copies()
    value = json.loads(saved.source_row_reviews[0])
    value.update(scope='foreign-site', filename='PRIVATE FOREIGN ORIGINAL')
    shown = display(replace(saved, source_row_reviews=(json.dumps(value),)), saved)
    assert 'PRIVATE FOREIGN ORIGINAL' not in shown and 'foreign-site' not in shown
    assert 'Private learner' not in shown and 'Hours' not in shown


def test_public_storage_recovery_history_and_word_keep_both_row_decisions(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    saved, working = copies()
    library.save_profile(saved.profile, expected_revision=0, actor='Synthetic Editor', confirmed=True)
    shared = library.save_snapshot(saved, expected_revision=0, entered_editor='Synthetic Editor')
    browser = active.save('a'*32, working, expected_revision=0, base_snapshot_revision=shared.revision)
    with pytest.raises(library.RevisionConflict):
        library.save_snapshot(working, expected_revision=0)
    reopened = active.load('a'*32, saved.profile.contract, saved.profile.key, saved.period)
    older = library.load_snapshot_version(saved.profile.contract, saved.profile.key, saved.period, shared.revision)
    assert reopened == browser and older == shared
    assert 'Hours' in display(reopened.draft, older.draft)
    assert rows_in_word(older.draft, tmp_path / 'template.docx', public=True)[-1][-1] == '1'
    assert rows_in_word(reopened.draft, tmp_path / 'template.docx', public=True)[-1][-1] == '3'
    assert sources.source_bytes(saved.profile, saved.sources[0]) == CSV
