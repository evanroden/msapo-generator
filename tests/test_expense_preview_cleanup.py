"""Removing a receipt retires only its now-unusable derived preview work.

Real private PreviewStore files/rasters are inspected. Callback tests model
retained Streamlit closures; the full-editor test uses AppTest, not a browser.
"""
from datetime import date
from hashlib import sha256
from types import SimpleNamespace

import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import expense_ui, reference_preview
from app.monthly_report_preview_store import PreviewStore
from app.receipt_analyzer import ReceiptAnalysis


def pdf_bytes(label):
    with fitz.open() as document:
        page = document.new_page(width=300, height=400)
        page.insert_text((20, 40), 'Synthetic receipt ' + label)
        return document.tobytes()


@pytest.fixture
def preview_model(monkeypatch):
    store, state, fragments, views = PreviewStore(), {}, [], []
    monkeypatch.setattr(reference_preview, 'STORE', store)
    monkeypatch.setattr(reference_preview.st, 'session_state', state)
    monkeypatch.setattr(reference_preview.st, 'fragment', lambda function: fragments.append(function) or function)
    monkeypatch.setattr(reference_preview, 'render_view', lambda **kwargs: views.append(kwargs))
    state['expense_report_memory_context'] = 'synthetic-expense-A'
    state['expense_receipt_files'] = []
    def render(raw, scope='synthetic-expense-A', key=None):
        digest = sha256(raw).hexdigest()
        key = key or 'expense_receipt_' + digest[:12]
        reference_preview.render_reference(key=key, owner_scope=scope,
                                           title='Synthetic receipt', raw=raw, filename='synthetic.pdf')
        owner = reference_preview._owner(scope)
        return SimpleNamespace(raw=raw, digest=digest, key=key, scope=scope, owner=owner,
                               entry=owner['entries'][key], surface=fragments[-1], view=views[-1])
    def request(target, *, generation=None):
        state['workspace_reference_' + target.key] = {'viewport': {
            'visible': True, 'pages': [0], 'dpi': 96,
            'generation': generation or target.view['generation'],
        }}
        target.view['on_change']()
    def materialize(target):
        request(target)
        target.surface()
        assert target.entry['ticket'] and store.available(target.owner['owner'], target.entry['ticket'])
        return store._files[target.entry['ticket'].key].path
    yield SimpleNamespace(store=store, state=state, render=render, request=request,
                          materialize=materialize, views=views)
    store.close()


def test_receipt_removal_deletes_its_pdf_rasters_and_invalid_packet_only(preview_model):
    harness = preview_model
    first, second = pdf_bytes('first'), pdf_bytes('second')
    harness.state['expense_receipt_files'] = [('first.pdf', first, 'application/pdf'),
                                              ('second.pdf', second, 'application/pdf')]
    removed = harness.render(first)
    kept = harness.render(second)
    independent = harness.render(first, scope='synthetic-expense-B')
    old_packet = harness.render(pdf_bytes('old packet containing first receipt'), key='expense_packet')
    paths = [harness.materialize(target) for target in (removed, kept, independent, old_packet)]
    assert harness.store.stats()['raster_entries'] == 4
    expense_ui._remove_receipt_from_draft(removed.digest)
    assert removed.key not in removed.owner['entries']
    assert old_packet.key not in old_packet.owner['entries']
    assert not paths[0].exists() and not paths[3].exists()
    for target, path in ((kept, paths[1]), (independent, paths[2])):
        assert path.read_bytes() == target.raw
        assert harness.store.available(target.owner['owner'], target.entry['ticket'])
    ticket = removed.entry['ticket']
    assert not harness.store.available(removed.owner['owner'], ticket)
    assert harness.store.pages(removed.owner['owner'], ticket, (0,), dpi=96) is None
    assert harness.store.stats()['pdf_entries'] == harness.store.stats()['raster_entries'] == 2
    assert harness.state['expense_receipt_files'] == [('second.pdf', second, 'application/pdf')]


def test_removed_receipt_callbacks_and_same_byte_readd_cannot_revive_old_view(preview_model):
    harness = preview_model
    raw = pdf_bytes('readded unchanged original')
    harness.state['expense_receipt_files'] = [('same.pdf', raw, 'application/pdf')]
    removed = harness.render(raw)
    old_path = harness.materialize(removed)
    expense_ui._remove_receipt_from_draft(removed.digest)
    count = len(harness.views)
    harness.request(removed)
    removed.surface()
    assert len(harness.views) == count and not old_path.exists()
    assert harness.store.stats()['pdf_entries'] == 0
    harness.state['expense_receipt_files'] = [('same.pdf', raw, 'application/pdf')]
    readded = harness.render(raw)
    assert readded.owner is removed.owner and readded.entry is not removed.entry
    assert readded.view['generation'] != removed.view['generation']
    harness.request(readded, generation=removed.view['generation'])
    readded.surface()
    assert 'view' not in readded.entry and harness.store.stats()['pdf_entries'] == 0
    new_path = harness.materialize(readded)
    assert new_path.read_bytes() == raw and new_path != old_path


def test_receipt_removed_while_preview_finishes_discards_the_late_ticket(preview_model, monkeypatch):
    harness = preview_model
    raw = pdf_bytes('late preview')
    harness.state['expense_receipt_files'] = [('late.pdf', raw, 'application/pdf')]
    target = harness.render(raw)
    harness.request(target)
    actual_put = harness.store.put
    late = []
    def put_and_remove(*args, **kwargs):
        ticket = actual_put(*args, **kwargs)
        late.append(ticket)
        expense_ui._remove_receipt_from_draft(target.digest)
        return ticket
    monkeypatch.setattr(harness.store, 'put', put_and_remove)
    target.surface()
    assert len(late) == 1 and not harness.store.available(target.owner['owner'], late[0])
    assert target.key not in target.owner['entries']
    assert harness.store.stats()['pdf_entries'] == harness.store.stats()['raster_entries'] == 0


def test_stale_receipt_fingerprint_cannot_discard_replacement_under_the_same_display_key(preview_model):
    harness = preview_model
    original, replacement = pdf_bytes('original identity'), pdf_bytes('replacement identity')
    harness.state['expense_receipt_files'] = [('old.pdf', original, 'application/pdf'),
                                              ('new.pdf', replacement, 'application/pdf')]
    previous = harness.render(original)
    harness.materialize(previous)
    current = harness.render(replacement, key=previous.key)
    path = harness.materialize(current)
    expense_ui._remove_receipt_from_draft(previous.digest)
    assert current.owner['entries'][current.key] is current.entry
    assert path.read_bytes() == replacement
    assert harness.store.available(current.owner['owner'], current.entry['ticket'])


def test_reconciled_removed_inventory_cleans_only_absent_receipt_previews(preview_model):
    harness = preview_model
    first, second = harness.render(pdf_bytes('removed by inventory')), harness.render(pdf_bytes('retained inventory'))
    first_path, second_path = harness.materialize(first), harness.materialize(second)
    harness.state['expense_active_receipt_ids'] = {first.digest, second.digest}
    harness.state['expense_receipt_files'] = [('kept.pdf', second.raw, 'application/pdf')]
    expense_ui._clear_removed_receipts({second.digest})
    assert not first_path.exists() and first.key not in first.owner['entries']
    assert second_path.read_bytes() == second.raw and second.key in second.owner['entries']
    assert harness.state['expense_active_receipt_ids'] == {second.digest}


def test_actual_expense_remove_keeps_other_preview_original_fields_and_split_state(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(expense_ui, 'start_receipt', lambda *a, **k: pytest.fail('No reader call is authorized.'))
    monkeypatch.setattr(expense_ui, 'account_director', lambda _: ('Synthetic Director', 'director@example.invalid'))
    monkeypatch.setattr(expense_ui, 'director_config_problems', lambda _: [])
    store = PreviewStore()
    monkeypatch.setattr(reference_preview, 'STORE', store)
    raw_a, raw_b = pdf_bytes('A'), pdf_bytes('B')
    ids = tuple(sha256(raw).hexdigest() for raw in (raw_a, raw_b))
    app = AppTest.from_string('''
import streamlit as st
from app.expense_ui import render_expense_workflow, preserve_expense_draft_state
render_expense_workflow('synthetic-expense-browser', 'America/New_York')
preserve_expense_draft_state()
''', default_timeout=30)
    app.session_state['expense_account'] = 'Rochester Regional Health'
    app.session_state['expense_receipt_files'] = [('A.pdf', raw_a, 'application/pdf'), ('B.pdf', raw_b, 'application/pdf')]
    for digest in ids:
        app.session_state['expense_receipt_analysis_' + digest] = ReceiptAnalysis(
            merchant_name='Synthetic Supplies', transaction_date=date(2026, 8, 12),
            total_amount='35.00', suggested_description='Synthetic business supplies', confidence='high')
    try:
        app.run()
        assert not app.exception
        owner = next(iter(app.session_state['_workspace_reference_owners'].values()))
        for entry in owner['entries'].values():
            entry['view'] = {'visible': True, 'pages': (0,), 'dpi': 96}
        app.run()
        assert not app.exception
        old = owner['entries']['expense_receipt_' + ids[0][:12]]
        kept = owner['entries']['expense_receipt_' + ids[1][:12]]
        old_path = store._files[old['ticket'].key].path
        kept_path = store._files[kept['ticket'].key].path
        next(widget for widget in app.toggle if widget.key == 'expense_split_' + ids[1][:12]).set_value(True).run()
        next(widget for widget in app.text_input if widget.key == 'expense_amount_' + ids[1][:12] + '_line_2').set_value('12.00').run()
        next(button for button in app.button if button.key == 'expense_remove_receipt_' + ids[0][:12]).click().run()
        assert not app.exception
        assert not old_path.exists() and not store.available(owner['owner'], old['ticket'])
        assert kept_path.read_bytes() == raw_b and store.available(owner['owner'], kept['ticket'])
        assert app.session_state['expense_receipt_files'] == [('B.pdf', raw_b, 'application/pdf')]
        assert next(widget for widget in app.text_input if widget.key == 'expense_amount_' + ids[1][:12] + '_line_2').value == '12.00'
        app.run()
        assert not app.exception and store.stats()['pdf_entries'] == 1
    finally:
        store.close()
