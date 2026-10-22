"""Exact PR273 review regressions, using real files and the ordinary editor.

Reader results are separately modeled. AppTest delivers native widget messages
but does not establish browser delivery timing or caret continuity.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from zipfile import ZipFile

from docx import Document
import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from conftest import requires_libreoffice
from test_monthly_report_mixed_activity_integrity import pdf_bytes


STATUS = 'Pending — call 202-555-0176 or tech@example.invalid'
SERIAL = 'SN-202-555-0176'
CSV = ('Vendor,Event date,Work performed,Status\n'
       'Synthetic Mechanical,2026-09-16,Inspected fan,' + STATUS + '\n').encode()


def ingest(monkeypatch, tmp_path, name, raw):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, name, raw)
    assert sources.source_bytes(profile, content.source) == raw
    assert content.source.sha256 == sha256(raw).hexdigest()
    return profile, content


def test_csv_status_excludes_contacts_but_keeps_the_status_and_action(monkeypatch, tmp_path):
    _, content = ingest(monkeypatch, tmp_path, 'synthetic-status.csv', CSV)
    result = structured.native_update((content,), 'activity_summary')
    assert 'Inspected fan' in result.text and '(Status: Pending' in result.text
    assert '202-555-0176' not in result.text and 'tech@example.invalid' not in result.text
    assert '2026-09-16' in result.text and 'Synthetic Mechanical' in result.text
    assert result.references == (sources.source_reference(content.source, 1),)
    assert structured.native_update((content,), 'activity_summary', result) == result


@pytest.mark.parametrize('path', ['native', 'reader'])
@pytest.mark.parametrize('identity', [
    'asset serial SN-202-555-0176', 'asset number AHU-202-555-0198',
    'work order CMMS-WO-202-555-0122',
])
def test_prefixed_technical_identifier_survives_beside_a_real_contact(monkeypatch, tmp_path, path, identity):
    text = ('Inspected ' + identity + '; call 202-555-0138 or technician@example.invalid; '
            'the fan did not start after 1.5 hours at 128 psi.')
    _, content = ingest(monkeypatch, tmp_path, 'synthetic-identifiers.pdf', pdf_bytes(text))
    if path == 'native':
        result = structured.native_update((content,), 'activity_summary')
    else:
        result, _ = structured.reader_update((content,), 'activity_summary', {'items': [
            {'source': content.source.id, 'page': 1, 'text': text, 'row': []}]})
    assert identity in result.text
    assert '202-555-0138' not in result.text and 'technician@example.invalid' not in result.text
    assert 'did not start after 1.5 hours at 128 psi.' in result.text


def test_separate_price_line_does_not_absorb_adjacent_unpunctuated_tagged_work(monkeypatch, tmp_path):
    event = ('Inspected pump bearings\nFee $500\n'
             'Calibrated the temperature sensor and confirmed it\nwould not stabilize')
    raw = ('2026-09-16 | WO-7 | Vendor service\n' + event).encode()
    _, content = ingest(monkeypatch, tmp_path, 'synthetic-adjacent-price.txt', raw)
    result = structured.native_update((content,), 'activity_summary')
    assert 'Inspected pump bearings' in result.text
    assert 'Calibrated the temperature sensor and confirmed it would not stabilize' in result.text
    assert 'Fee' not in result.text and '$500' not in result.text
    assert len(result.text.split('\n\n')) == 2


def test_full_page_pricing_guard_is_unchanged_for_unstructured_pdf(monkeypatch, tmp_path):
    _, content = ingest(monkeypatch, tmp_path, 'synthetic-pricing-page.pdf',
                        pdf_bytes('Inspected pump bearings\nFee $500'))
    assert not structured.native_update((content,), 'activity_summary').text


def test_real_wrapped_negative_and_nonmoney_cost_wording_remain_grounded(monkeypatch, tmp_path):
    text = ('Inspected the cost control relay and confirmed it\n'
            'did not start\n\n- Replaced the intake filter\n- Inspected a second pump')
    _, content = ingest(monkeypatch, tmp_path, 'synthetic-controls.txt', text.encode())
    result = structured.native_update((content,), 'activity_summary')
    assert result.text.split('\n\n') == [
        'Inspected the cost control relay and confirmed it did not start',
        '- Replaced the intake filter', '- Inspected a second pump']


def workorder_app(monkeypatch, tmp_path):
    import streamlit as st
    from test_monthly_report_activity_intake_commit import setup_app, draft
    app, profile = setup_app(monkeypatch, tmp_path)
    raw = (b'Work Order,Date,Status,Facility\n'
           b'SYNTHETIC-WO-1,2026-10-03,Completed,Synthetic West\n'
           b'SYNTHETIC-WO-2,2026-10-12,Open,Synthetic West\n')
    original = st.file_uploader
    def upload(label, *args, **kwargs):
        if label == 'Add source files':
            stream = BytesIO(raw); stream.name = 'synthetic-workorders.csv'
            return [stream]
        return original(label, *args, **kwargs)
    monkeypatch.setattr(st, 'file_uploader', upload)
    app.run()
    assert not app.exception
    assert {source.id for source in draft(app).sources} == {sha256(raw).hexdigest()}, 'The uploader must process the actual file.'
    assert any(button.label == 'Add totals to summary' and not button.disabled for button in app.button)
    return app, profile, original


@pytest.mark.parametrize('precommitted', [False, True])
def test_accepted_totals_acknowledge_the_manual_edit_and_survive_recovery_reload(monkeypatch, tmp_path, precommitted):
    import streamlit as st
    from app import monthly_report_active_work as active_work
    from test_monthly_report_activity_intake_commit import APP, TOKEN, editor, activity
    app, profile, original_uploader = workorder_app(monkeypatch, tmp_path)
    manual = 'Operator verified the actuator remains locked out.'
    editor(app).set_value(manual)
    if precommitted:
        app.run()
    identity = editor(app).proto.id
    next(button for button in app.button if button.label == 'Add totals to summary').click().run()
    assert not app.exception
    assert activity(app).text.startswith(manual + '\n\n')
    assert activity(app).text.count('2 total, 1 completed, 1 open') == 1
    assert not any('earlier edit was interrupted' in message.value for message in app.warning)
    assert not any(button.label == 'Apply interrupted edit' for button in app.button)
    assert editor(app).proto.id == identity and editor(app).value == activity(app).text
    expected = activity(app)
    journal = active_work.load(TOKEN, profile.contract, profile.key, ReportPeriod(2026, 10))
    assert journal and next(block for block in journal.draft.blocks if block.key == 'activity_summary') == expected
    app.run()
    assert not app.exception and activity(app) == expected
    monkeypatch.setattr(st, 'file_uploader', original_uploader)
    resumed = AppTest.from_string(APP, default_timeout=45).run()
    assert not resumed.exception and activity(resumed) == expected
    assert not any(button.label == 'Apply interrupted edit' for button in resumed.button)


def test_prior_report_incarnation_cannot_accept_same_source_totals(monkeypatch, tmp_path):
    from test_monthly_report_activity_intake_commit import activity
    app, _, _ = workorder_app(monkeypatch, tmp_path)
    before = activity(app)
    add = next(button for button in app.button if button.label == 'Add totals to summary')
    epoch = next(key for key in app.session_state.filtered_state if key.endswith('_rich_text_epoch'))
    # Model a delayed action while a new report incarnation has the same
    # profile/month/source and identical wording. This is not a browser reset.
    app.session_state[epoch] = 'new-synthetic-report-incarnation'
    add.click().run()
    assert not app.exception
    assert activity(app) == before
    assert any('report changed after you reviewed' in warning.value for warning in app.warning)


@requires_libreoffice
def test_reviewed_activity_import_save_and_output_keep_scope_without_contact_leak(monkeypatch, tmp_path):
    from app import monthly_report_library as library
    from app.monthly_report_docx import generate_report
    from app.monthly_report_model import BlockSpec, ReportDraft, SectionSpec
    from app.monthly_report_source_details import correct_source_details
    profile, csv = ingest(monkeypatch, tmp_path, 'synthetic-status.csv', CSV)
    raw = ('2026-09-16 | WO-8 | Vendor service\nInspected asset serial ' + SERIAL +
           '\nFee $500\nCalibrated sensor ST-11 and confirmed it\nwould not stabilize').encode()
    _, tagged = ingest(monkeypatch, tmp_path, 'synthetic-pricing-tail.txt', raw)
    contents = tuple(replace(content, source=correct_source_details(content.source, profile, None,
                     profile.facilities[0].key)) for content in (csv, tagged))
    block = structured.native_update(contents, 'activity_summary')
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Reviewer',
        (SectionSpec('activity', '2', 'Monthly Activity Summary', (BlockSpec('activity_summary', 'rich_text'),)),),
        (block,), sources=tuple(content.source for content in contents))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    restored = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert restored.draft == draft and restored.revision == saved.revision
    package = generate_report(restored.draft, acknowledged_fingerprint=restored.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    output = Path(os.environ.get('INDEPENDENT_OUTPUT', str(tmp_path)))
    output.mkdir(exist_ok=True, parents=True)
    (output / 'reviewed_activity.docx').write_bytes(package.docx)
    (output / 'reviewed_activity.pdf').write_bytes(package.pdf)
    with fitz.open(stream=package.pdf, filetype='pdf') as pdf:
        pdf_text = ' '.join(' '.join(page.get_text().split()) for page in pdf)
        for index, page in enumerate(pdf, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f'reviewed_activity_page_{index}.png')
    (output / 'reviewed_activity.json').write_text(json.dumps({
        'tested_revision': os.environ.get('MSAPO_SHA', 'unrecorded'),
        'source_sha256': [content.source.sha256 for content in contents],
        'saved_revision': saved.revision, 'draft_fingerprint': restored.draft.fingerprint,
        'docx_bytes': len(package.docx), 'docx_sha256': sha256(package.docx).hexdigest(),
        'pdf_bytes': len(package.pdf), 'pdf_sha256': sha256(package.pdf).hexdigest(),
    }, indent=2) + '\n')
    docx_text = '\n'.join(paragraph.text for paragraph in Document(BytesIO(package.docx)).paragraphs)
    with ZipFile(BytesIO(package.docx)) as package_parts:
        xml = '\n'.join(package_parts.read(name).decode('utf8', errors='ignore')
                        for name in package_parts.namelist() if name.endswith('.xml'))
    for rendered in (docx_text, pdf_text, xml):
        assert '202-555-0176' not in rendered.replace(SERIAL, '')
        assert 'tech@example.invalid' not in rendered and '$500' not in rendered
        assert SERIAL in rendered and 'would not stabilize' in rendered
        assert 'Inspected fan' in rendered and 'Pending' in rendered
