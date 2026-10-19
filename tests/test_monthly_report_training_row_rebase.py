"""Training edits rebase across independent rows, never a replaced incarnation.

AppTest delivers native widget protocols. A second AppTest represents an
independent session; its returned current block is the explicit upstream
state in the first editor. This does not claim a production two-tab journey.
"""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

from docx import Document
import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_model import ReportTable
from app.monthly_report_training import EVENT_REF, add_event, load_training
from conftest import requires_libreoffice
from test_monthly_report_training_retention import APP, NOTE, current, training, widget
from test_monthly_report_training_sessions_ui import action, fill_session, rows


def healthy(app):
    assert not app.exception
    assert not app.error
    return app


def events(app):
    return next(table for table in current(app).extra_tables if table.reference == EVENT_REF)


def set_events(app, table):
    block = current(app)
    app.session_state['blocks'] = {block.key: replace(block, extra_tables=tuple(
        table if old.reference == EVENT_REF else old for old in block.extra_tables))}


def populated(training):
    app, draft, *_ = training
    table = events(app)
    for title, day in [('Synthetic electrical refresher', 9), ('Synthetic fire response', 22)]:
        table = add_event(table, title=title, when=date(2026, 9, day), mode='Virtual',
                          participants=['Synthetic Hospital Tech'], hours='1', period=draft.period)
    set_events(app, table)
    healthy(app.run())
    return app


def second_session(training, first):
    _, draft, *_ = training
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state['draft'] = replace(draft, blocks=(current(first),))
    app.session_state['blocks'] = {current(first).key: current(first)}
    return healthy(app.run())


def begin_edit(app):
    action(app, 'Edit session', 'Synthetic fire response').click().run()
    healthy(app)
    widget(app, 'text_input', 'Training topic').set_value('Synthetic fire response; corrected muster point')
    widget(app, 'text_input', 'Hours (optional)').set_value('')
    return widget(app, 'text_input', 'Training topic').proto.id


@pytest.mark.parametrize('change', ['remove', 'add', 'reorder', 'unchanged'])
def test_unrelated_session_changes_do_not_strand_a_delivered_edit(training, change):
    app = populated(training)
    before = events(app)
    native_id = begin_edit(app)
    if change == 'remove':
        action(app, 'Remove', 'Accepted safety event').click().run()
        healthy(app)
        assert len(rows(app)) == 2
    elif change == 'add':
        other = second_session(training, app)
        fill_session(other, title='Separate chemical handling session')
        widget(other, 'button', 'Add completed training').click().run()
        healthy(other)
        set_events(app, events(other))
    elif change == 'reorder':
        # A current canonical reordering carries its row metadata with each
        # row. There is no UI order control in the current session cards.
        table = events(app)
        changes = {'rows': tuple(reversed(table.rows))}
        if hasattr(table, 'row_tokens'):
            changes['row_tokens'] = tuple(reversed(table.row_tokens))
        set_events(app, replace(table, **changes))
    if change == 'remove':
        assert widget(app, 'text_input', 'Training topic').proto.id == native_id
        assert widget(app, 'text_input', 'Training topic').value.endswith('corrected muster point')
    widget(app, 'button', 'Save session').click().run()
    healthy(app)
    updated = events(app)
    target = [row for row in updated.rows if row[0].endswith('corrected muster point')]
    assert target == [('Synthetic fire response; corrected muster point', '2026-09-22',
                       'Virtual', 'Synthetic Hospital Tech', '')]
    assert not any(row[0] == 'Synthetic fire response' for row in updated.rows)
    assert ('Accepted safety event' not in {row[0] for row in updated.rows}) == (change == 'remove')
    assert ('Separate chemical handling session' in {row[0] for row in updated.rows}) == (change == 'add')
    assert before.rows[1] in updated.rows
    assert current(app).text == NOTE
    assert load_training(training[1].profile.contract) == training[4]
    healthy(app.run())
    assert events(app) == updated


@pytest.mark.parametrize('change', ['edit', 'delete', 'delete_recreate'])
def test_same_row_change_or_recreation_keeps_a_real_conflict(training, change):
    app = populated(training)
    other = second_session(training, app)
    native_id = begin_edit(app)
    if change == 'edit':
        action(other, 'Edit session', 'Synthetic fire response').click().run()
        widget(other, 'text_input', 'Training topic').set_value('Newer acknowledged fire response')
        widget(other, 'button', 'Save session').click().run()
    else:
        action(other, 'Remove', 'Synthetic fire response').click().run()
        if change == 'delete_recreate':
            fill_session(other, title='Synthetic fire response', when=date(2026, 9, 22))
            widget(other, 'selectbox', 'Method').set_value('Virtual')
            widget(other, 'button', 'Add completed training').click().run()
    healthy(other)
    newer = events(other)
    set_events(app, newer)
    for _ in range(3):
        widget(app, 'button', 'Save session').click().run()
        healthy(app)
        assert events(app) == newer
        assert widget(app, 'text_input', 'Training topic').proto.id == native_id
        assert widget(app, 'text_input', 'Training topic').value.endswith('corrected muster point')
        assert any('entered details are kept' in message.value for message in app.warning)
    widget(app, 'button', 'Cancel editing').click().run()
    healthy(app)
    assert events(app) == newer
    assert widget(app, 'text_input', 'Training topic').value == ''


def test_rebase_retries_local_validation_without_forgetting_its_original_row(training):
    app = populated(training)
    begin_edit(app)
    widget(app, 'text_input', 'Hours (optional)').set_value('unknown')
    action(app, 'Remove', 'Accepted safety event').click().run()
    widget(app, 'button', 'Save session').click().run()
    assert not app.exception
    assert any('positive hours' in message.value for message in app.error)
    assert not any(row[0].endswith('corrected muster point') for row in rows(app))
    widget(app, 'text_input', 'Hours (optional)').set_value('')
    widget(app, 'button', 'Save session').click().run()
    healthy(app)
    assert any(row[0].endswith('corrected muster point') for row in rows(app))


def test_changed_session_schema_cannot_rebind_an_existing_edit(training):
    app = populated(training)
    begin_edit(app)
    table = events(app)
    newer = replace(table, columns=('Training', 'Date', 'Hours', 'Participants', 'Format'))
    set_events(app, newer)
    widget(app, 'button', 'Save session').click().run()
    healthy(app)
    assert events(app) == newer
    assert widget(app, 'text_input', 'Training topic').value.endswith('corrected muster point')
    assert app.warning


@pytest.mark.parametrize('intervening_add', [False, True])
def test_deleted_edit_becomes_new_only_after_current_explicit_form_submission(training, intervening_add):
    app = populated(training)
    original = events(app)
    begin_edit(app)
    action(app, 'Remove', 'Synthetic fire response').click().run()
    widget(app, 'button', 'Save session').click().run()
    healthy(app)
    assert len(rows(app)) == 2
    if intervening_add:
        newer = add_event(events(app), title='Separate current addition', when=date(2026, 9, 26),
                          mode='In person', participants=['Synthetic Hospital Tech'], hours='',
                          period=training[1].period)
        set_events(app, newer)
        widget(app, 'button', 'Add as new session').click().run()
        healthy(app)
        assert events(app) == newer, 'A new-row choice still requires its exact displayed revision.'
        assert app.warning
    widget(app, 'button', 'Add as new session').click().run()
    healthy(app)
    accepted = events(app)
    assert len(rows(app)) == (4 if intervening_add else 3)
    assert len([row for row in rows(app) if row[0].endswith('corrected muster point')]) == 1
    assert not any(row[0] == 'Synthetic fire response' for row in rows(app))
    assert original.row_tokens[-1] not in accepted.row_tokens
    healthy(app.run())
    assert events(app) == accepted


def test_legacy_browsing_does_not_migrate_or_save_but_explicit_mutation_preserves_identity(training):
    app = populated(training)
    old = events(app)
    legacy = ReportTable(old.columns, old.rows, old.reference)
    set_events(app, legacy)
    before = current(app)
    for _ in range(2):
        healthy(app.run())
        assert current(app) == before
        assert current(app).fingerprint == before.fingerprint
    assert load_training(training[1].profile.contract) == training[4]
    begin_edit(app)
    assert current(app) == before, 'Opening Edit is not a business mutation.'
    action(app, 'Remove', 'Accepted safety event').click().run()
    widget(app, 'button', 'Save session').click().run()
    healthy(app)
    assert any(row[0].endswith('corrected muster point') for row in rows(app))
    assert len(events(app).row_tokens) == len(events(app).rows)


def test_row_incarnations_round_trip_without_changing_plain_table_fingerprints(training):
    app = populated(training)
    original = current(app)
    table = events(app)
    assert len(set(table.row_tokens)) == len(table.rows)
    assert library.block_from_dict(asdict(original)) == original
    plain = replace(original, extra_tables=tuple(ReportTable(t.columns, t.rows, t.reference)
                     for t in original.extra_tables))
    encoded = asdict(plain)
    assert all('row_tokens' not in t for t in encoded['extra_tables'])
    assert library.block_from_dict(encoded).fingerprint == plain.fingerprint


def test_last_session_removal_is_acknowledged_when_the_empty_table_is_omitted(training):
    app, *_ = training
    old_token = events(app).row_tokens[0]
    action(app, 'Remove', 'Accepted safety event').click().run()
    healthy(app.run())
    assert rows(app) == ()
    assert not app.warning
    assert not widget(app, 'button', 'Add completed training').disabled
    fill_session(app, title='Accepted safety event', when=date(2026, 9, 1), hours='0.75')
    widget(app, 'button', 'Add completed training').click().run()
    healthy(app.run())
    assert len(rows(app)) == 1
    assert events(app).row_tokens[0] != old_token


@requires_libreoffice
def test_rebased_session_survives_save_reload_and_prints_once(training, tmp_path):
    from app.monthly_report_docx import generate_report
    app = populated(training)
    begin_edit(app)
    action(app, 'Remove', 'Accepted safety event').click().run()
    widget(app, 'button', 'Save session').click().run()
    healthy(app)
    block = current(app)
    draft = replace(training[1], blocks=(block,), sections=tuple(
        section for section in training[1].sections if section.key == 'training'))
    saved = library.save_snapshot(draft, expected_revision=training[5].revision,
                                  entered_editor=draft.prepared_by)
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened.draft == draft and reopened.revision == saved.revision
    app2 = AppTest.from_string(APP, default_timeout=30)
    app2.session_state['draft'] = reopened.draft
    app2.session_state['blocks'] = {block.key: reopened.draft.blocks[0]}
    healthy(app2.run())
    assert current(app2) == block
    package = generate_report(reopened.draft, acknowledged_fingerprint=reopened.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    output = Path(os.environ.get('INDEPENDENT_OUTPUT', str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'rebased_training.docx').write_bytes(package.docx)
    (output / 'rebased_training.pdf').write_bytes(package.pdf)
    (output / 'rebased_training.json').write_text(json.dumps({
        'tested_revision': os.environ.get('MSAPO_SHA', 'unrecorded'),
        'draft_fingerprint': reopened.draft.fingerprint, 'saved_revision': reopened.revision,
        'docx_bytes': len(package.docx), 'docx_sha256': sha256(package.docx).hexdigest(),
        'pdf_bytes': len(package.pdf), 'pdf_sha256': sha256(package.pdf).hexdigest(),
    }, indent=2) + '\n')
    expected = 'Synthetic fire response; corrected muster point'
    document = Document(BytesIO(package.docx))
    text = '\n'.join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert text.count(expected) == 1
    assert 'Accepted safety event' not in text
    with fitz.open(stream=package.pdf, filetype='pdf') as pdf:
        text = ' '.join(' '.join(page.get_text().split()) for page in pdf)
        for index, page in enumerate(pdf, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f'rebased_training_page_{index}.png')
    assert text.count(expected) == 1
    assert 'Accepted safety event' not in text
