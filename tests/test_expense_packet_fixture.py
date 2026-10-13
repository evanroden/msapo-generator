"""Real production Expense packet fixture gate; synthetic inputs, local Calc only."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import tempfile

import fitz
from openpyxl import load_workbook
import requests
from streamlit.testing.v1 import AppTest

from app import expense_report, expense_ui, receipt_jobs, reference_preview
from tests.conftest import requires_libreoffice

FIXTURE = Path(__file__).parent / 'fixtures' / 'workspaces' / 'expense_app.py'


def restore_fixture_overrides(monkeypatch):
    # The fixture runs in its own server in browser CI. AppTest shares this
    # process, so restore its explicit external-action sentinels after the test.
    for module, names in (
        (expense_ui, ('start_receipt', 'prepare_receipt_content', 'analyze_prepared_receipt',
                      '_render_ios_mail_share', '_IOS_MAIL_SHARE_COMPONENT',
                      'build_expense_package', 'account_director', 'director_config_problems')),
        (receipt_jobs, ('start_receipt',)),
        (reference_preview, ('render_view',)),
        (expense_report, ('PDF_BACKEND',)),
        (requests.sessions.Session, ('request',)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, getattr(module, name))


def test_expense_fixture_fails_closed_without_its_marked_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = AppTest.from_file(FIXTURE).run()
    assert len(app.exception) == 1
    assert 'marked disposable expense test directory' in app.exception[0].message
    assert not app.text_input


@requires_libreoffice
def test_expense_fixture_generates_actual_split_receipt_workbook_and_pdf(monkeypatch):
    restore_fixture_overrides(monkeypatch)
    with tempfile.TemporaryDirectory(prefix='expense-adaptive-synthetic-') as directory:
        root = Path(directory)
        (root / '.synthetic-expense-fixture').write_text('synthetic-only')
        monkeypatch.setenv('EPC_DATA_DIR', directory)
        app = AppTest.from_file(FIXTURE, default_timeout=150).run()
        assert not app.exception
        assert app.session_state.filtered_state.get('_fixture_generation_count', 0) == 0
        originals = [(name, sha256(raw).hexdigest()) for name, raw, _mime in
                     app.session_state['expense_receipt_files']]
        next(toggle for toggle in app.toggle if toggle.label.startswith('Split this receipt')).set_value(True).run()
        amounts = [field for field in app.text_input if field.label == 'Reimbursable amount *']
        amounts[0].set_value('13.25')
        amounts[1].set_value('11.25')
        descriptions = [field for field in app.text_input if field.label == 'Description / business purpose *']
        descriptions[0].set_value('Unblurred synthetic expense correction')
        descriptions[1].set_value('Synthetic split second reimbursement line')
        app.run()
        next(box for box in app.checkbox if box.label.startswith('I confirm this generated')).set_value(True).run()
        generate = next(button for button in app.button if button.key == 'generate_expense_package')
        assert not generate.disabled
        generate.click().run()
        assert not app.exception
        assert not app.error
        assert app.session_state['_fixture_generation_count'] == 1
        package = app.session_state['expense_generated_package']
        record = app.session_state['_fixture_generated_evidence']
        assert record['builder'] == 'app.expense_report.build_expense_package'
        assert record['total'] == '49.00'
        assert record['receipt_count'] == 2
        assert record['line_count'] == 3
        assert record['receipt_image_count'] == 4
        assert record['receipt_hashes'] == [digest for _name, digest in originals]
        for _name, digest in originals:
            assert sha256((root / 'evidence' / ('original-' + digest + '.pdf')).read_bytes()).hexdigest() == digest
        assert record['pages'] == 5
        workbook = load_workbook(BytesIO(package.workbook_bytes), data_only=False)
        form = workbook['EXPENSE REIMBURSEMENT']
        assert [form[f'H{row}'].value for row in (24, 25, 26)] == [13.25, 11.25, 24.5]
        assert form['C25'].value == 'Synthetic split second reimbursement line'
        assert form['Q60'].value == '=H18+H39+H59'
        with fitz.open(stream=package.pdf_bytes, filetype='pdf') as document:
            assert len(document) == 5
            assert 'REIMBURSEMENT OF EXPENSES' in document[0].get_text()
            assert 'Synthetic Employee' in document[0].get_text()
            assert '49.00' in document[0].get_text()
            assert all('Receipt 1 of 2' in document[index].get_text() for index in (1, 2))
            assert all('Receipt 2 of 2' in document[index].get_text() for index in (3, 4))
        receipt = json.loads(next((root / 'evidence').glob('*.json')).read_text())
        assert receipt == record
        assert (root / 'evidence' / (record['output_sha256'] + '.pdf')).read_bytes() == package.pdf_bytes
        assert (root / 'evidence' / (record['output_sha256'] + '.xlsx')).read_bytes() == package.workbook_bytes
        app.run()
        assert app.session_state['_fixture_generation_count'] == 1
        assert originals == [(name, sha256(raw).hexdigest()) for name, raw, _mime in
                             app.session_state['expense_receipt_files']]
        next(field for field in app.text_input if field.label == 'Reimbursable amount *').set_value('12.25').run()
        assert not app.exception
        assert app.session_state['_fixture_generation_count'] == 1
        assert not any(button.label == 'Download combined PDF packet' for button in app.get('download_button'))
