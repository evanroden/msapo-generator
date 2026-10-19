"""Receipt corrections remain in the editor and approved USD is validated.

Analyses are controlled local reader results. AppTest ancestry is not native
compact-browser visibility; output tests use the supplied expense workbook.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

import fitz
from openpyxl import load_workbook
import pytest
from streamlit.testing.v1 import AppTest

from app import expense_report as expense
from app.receipt_analyzer import ReceiptAnalysis
from conftest import requires_libreoffice
from test_expense_report import _details, _job_allocation


SCRIPT = '''
import streamlit as st
from hashlib import sha256
from app.expense_ui import _render_receipt, preserve_expense_draft_state
from app.expense_report import validate_expense_report
from app.workspace_layout import workspace, workspace_section
from test_expense_report import _details, _job_allocation
raw = st.session_state['source_bytes']
identity = sha256(raw).hexdigest()
st.session_state.setdefault('expense_report_memory_context', 'synthetic-currency-owner')
with workspace('expense', 'synthetic-currency-owner'):
    with workspace_section('expense_receipt_' + identity[:12], 'Receipt 1'):
        items = _render_receipt(index=1, receipt_id=identity, filename='synthetic-receipt.pdf',
            file_bytes=raw, analysis=st.session_state['analysis'],
            account='Rochester Regional Health', allocation_seed=_job_allocation())
st.session_state['items'] = items
st.session_state['problems'] = validate_expense_report(_details(), items)
st.button('Synthetic generation gate', disabled=bool(st.session_state['problems']))
preserve_expense_draft_state()
'''


def receipt_bytes():
    with fitz.open() as document:
        page = document.new_page(width=300, height=400)
        page.insert_text((20, 40), 'SYNTHETIC SUPPLY RECEIPT\nEUR 70.00')
        return document.tobytes()


def make_app(monkeypatch, tmp_path, *, currency='EUR', error=False):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    raw = receipt_bytes()
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['source_bytes'] = raw
    app.session_state['analysis'] = ReceiptAnalysis(
        merchant_name='Synthetic Supplies', transaction_date=date(2026, 8, 12),
        total_amount='35.00', currency=currency, suggested_description='Synthetic business supplies',
        confidence='high')
    if error:
        app.session_state['expense_receipt_error_' + sha256(raw).hexdigest()] = 'Synthetic prior read failure'
    app.run()
    assert not app.exception
    return app


def gate(app):
    return next(button for button in app.button if button.label == 'Synthetic generation gate')


def amount(app):
    return next(widget for widget in app.text_input if widget.key.startswith('expense_amount_'))


def ancestry(app, *, kind, text):
    matches = []
    def visit(node, owners):
        proto = getattr(node, 'proto', None)
        identity = getattr(proto, 'id', '') if proto is not None else ''
        path = (*owners, identity)
        if node.type == kind and text in str(getattr(node, 'label', '') or getattr(node, 'value', '')):
            matches.append(path)
        for child in getattr(node, 'children', {}).values():
            visit(child, path)
    visit(app._tree, ())
    return matches


@pytest.mark.parametrize('kind,text', [
    ('button', 'Remove this receipt'),
    ('button', 'Try reading this receipt again'),
    ('error', 'Receipt currency appears to be'),
])
def test_receipt_corrections_are_inside_the_editor_not_compact_hidden_preview(monkeypatch, tmp_path, kind, text):
    app = make_app(monkeypatch, tmp_path, error=True)
    paths = ancestry(app, kind=kind, text=text)
    assert paths, 'The expected correction control must actually render.'
    assert all(any('epc_edit_expense_receipt_' in owner for owner in path) for path in paths)
    assert not any(any('epc_reference_expense_receipt_' in owner for owner in path) for path in paths)


@pytest.mark.parametrize('first_currency', ['', 'USD'])
def test_later_foreign_currency_cannot_silently_accept_an_earlier_automatic_amount(monkeypatch, tmp_path, first_currency):
    app = make_app(monkeypatch, tmp_path, currency=first_currency)
    assert amount(app).value == '35.00' and not gate(app).disabled
    original_widget = amount(app).proto.id
    app.session_state['analysis'] = replace(app.session_state['analysis'], currency='EUR')
    app.run()
    assert not app.exception
    assert amount(app).value == '35.00', 'Keep the entered number recoverable instead of silently deleting it.'
    assert amount(app).proto.id == original_widget, 'A reader correction must keep the existing amount editor.'
    assert gate(app).disabled
    assert any('approved U.S.-dollar' in problem for problem in app.session_state['problems'])
    with pytest.raises(expense.ExpenseReportError, match='approved U.S.-dollar'):
        expense.build_expense_workbook(_details(), app.session_state['items'])


def test_known_foreign_receipt_requires_valid_usd_and_review_but_usd_keeps_existing_rules(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path)
    assert amount(app).value == '' and gate(app).disabled
    amount(app).set_value('35.00 EUR').run()
    assert gate(app).disabled
    amount(app).set_value('35.00').run()
    assert gate(app).disabled, 'A numeric value alone cannot establish reviewed USD for a known foreign receipt.'
    confirm = next(box for box in app.checkbox if box.label.startswith('I entered the approved U.S.-dollar'))
    confirm.set_value(True).run()
    assert not app.exception and not gate(app).disabled
    accepted = app.session_state['items']
    signature = expense.expense_report_signature(_details(), accepted)
    for change in (
            {'source_currency': 'GBP'}, {'transaction_date': date(2026, 8, 13)},
            {'file_bytes': accepted[0].file_bytes + b'\n%synthetic-source-revision'},
            {'receipt_id': accepted[0].receipt_id + ':new-line'},
            {'source_receipt_id': 'different-source'}):
        changed = replace(accepted[0], **change)
        assert any('approved U.S.-dollar' in problem for problem in expense.validate_expense_report(_details(), [changed])), change
        assert expense.expense_report_signature(_details(), [changed]) != signature
    amount(app).set_value('36.00').run()
    assert gate(app).disabled
    assert expense.expense_report_signature(_details(), app.session_state['items']) != signature
    with pytest.raises(expense.ExpenseReportError, match='approved U.S.-dollar'):
        expense.build_expense_workbook(_details(), [replace(accepted[0], amount='36.00')])
    usd = make_app(monkeypatch, tmp_path / 'usd', currency='USD')
    assert not gate(usd).disabled
    assert not any(box.label.startswith('I entered the approved U.S.-dollar') for box in usd.checkbox)


@requires_libreoffice
def test_reviewed_foreign_split_prints_only_entered_usd_total_and_preserves_original(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path)
    next(widget for widget in app.toggle if widget.label.startswith('Split this receipt')).set_value(True).run()
    fields = [widget for widget in app.text_input if widget.key.startswith('expense_amount_')]
    fields[0].set_value('32.00').run()
    next(widget for widget in app.text_input if widget.key.endswith('_line_2') and widget.key.startswith('expense_amount_')).set_value('18.00').run()
    next(widget for widget in app.text_input if widget.key.endswith('_line_2') and widget.key.startswith('expense_description_')).set_value('Second synthetic business purpose').run()
    assert gate(app).disabled
    next(box for box in app.checkbox if box.label.startswith('I entered the approved U.S.-dollar')).set_value(True).run()
    assert not app.exception and not gate(app).disabled
    items = app.session_state['items']
    original = app.session_state['source_bytes']
    assert len(items) == 2 and all(item.file_bytes == original for item in items)
    package = expense.build_expense_package(_details(), items)
    assert package.pdf_bytes and not package.pdf_error
    assert package.total == Decimal('50.00') and package.receipt_count == 1
    workbook = load_workbook(BytesIO(package.workbook_bytes))
    form = workbook.worksheets[0]
    assert form['H24'].value == 32 and form['H25'].value == 18
    output = Path(os.environ.get('INDEPENDENT_OUTPUT', str(tmp_path)))
    output.mkdir(exist_ok=True, parents=True)
    (output / 'approved_usd_expense.xlsx').write_bytes(package.workbook_bytes)
    (output / 'approved_usd_expense.pdf').write_bytes(package.pdf_bytes)
    with fitz.open(stream=package.pdf_bytes, filetype='pdf') as document:
        text = ' '.join(page.get_text() for page in document)
        assert '32.00' in text and '18.00' in text and '50.00' in text
        for index, page in enumerate(document, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f'approved_usd_expense_page_{index}.png')
        pages = len(document)
    (output / 'approved_usd_expense.json').write_text(json.dumps({
        'tested_revision': os.environ.get('MSAPO_SHA', 'unrecorded'),
        'source_sha256': sha256(original).hexdigest(), 'total_usd': str(package.total),
        'workbook_bytes': len(package.workbook_bytes), 'workbook_sha256': sha256(package.workbook_bytes).hexdigest(),
        'pdf_bytes': len(package.pdf_bytes), 'pdf_sha256': sha256(package.pdf_bytes).hexdigest(),
        'pdf_pages': pages, 'template': 'Unchanged repository Employee_Reimbursement_Expense_Report_JDE_10012025.xlsx',
        'template_sha256': sha256(expense.EXPENSE_TEMPLATE_PATH.read_bytes()).hexdigest(),
    }, indent=2) + '\n')
