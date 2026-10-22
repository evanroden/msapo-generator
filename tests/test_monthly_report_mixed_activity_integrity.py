"""Mixed source intake keeps safe work and excludes unrouted/contact material.

Real synthetic PDF/CSV bytes use the product importer. External reading is
explicitly mocked, including its payload and reservation boundary.
"""
from concurrent.futures import Future
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

from app import monthly_report_sources as sources
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
from app.monthly_report_structured_uploads import native_update, reader_batches, reader_update
from conftest import requires_libreoffice


SAFE_WORK = 'Vendor inspected pump DP-42 and verified the discharge check valve would not close.'
FOREIGN_WORK = 'Replaced the reserve pump coupling at FOREIGN_CONTEXT_CANARY.'


def pdf_bytes(text):
    with fitz.open() as pdf:
        page = pdf.new_page(width=900, height=600)
        page.insert_textbox(fitz.Rect(35, 35, 860, 560), text, fontsize=11)
        return pdf.tobytes()


def synthetic_sources(monkeypatch, tmp_path, *, site_heading='Building'):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    originals = {
        'synthetic-service.pdf': pdf_bytes(SAFE_WORK),
        'synthetic-site-log.csv': (
            f'{site_heading},Work Performed,Service Date\n'
            f'Unmapped East,{FOREIGN_WORK},2026-09-12\n').encode(),
    }
    contents, messages = sources.ingest_batch(profile, tuple(originals.items()))
    assert not messages
    assert len(contents) == 2
    assert {content.source.sha256 for content in contents} == {sha256(raw).hexdigest() for raw in originals.values()}
    return profile, contents, originals


@pytest.mark.parametrize('site_heading', ['Building', 'Location', 'Site', 'Client'])
def test_one_unrouted_csv_cannot_discard_safe_sibling_reader_results(monkeypatch, tmp_path, site_heading):
    _, contents, _ = synthetic_sources(monkeypatch, tmp_path, site_heading=site_heading)
    manual = ResolvedBlock('activity_summary', 'This month', text='Human maintenance scope remains unchanged.')
    result, pages = reader_update(contents, 'activity_summary', {'items': [
        {'source': contents[0].source.id, 'page': 1, 'text': SAFE_WORK, 'row': []},
        {'source': contents[1].source.id, 'page': 1, 'text': FOREIGN_WORK, 'row': []},
    ]}, manual)
    assert result.text == manual.text + '\n\n' + SAFE_WORK
    assert 'FOREIGN_CONTEXT_CANARY' not in result.text
    assert len(result.references) == 1 and result.references[0].startswith(contents[0].source.id + ':')
    assert not pages
    assert reader_update(contents, 'activity_summary', {'items': [
        {'source': contents[0].source.id, 'page': 1, 'text': SAFE_WORK, 'row': []},
    ]}, result)[0] == result


def test_unrouted_csv_is_removed_before_reader_payload_or_image_reservation(monkeypatch, tmp_path):
    profile, contents, _ = synthetic_sources(monkeypatch, tmp_path)
    from app import monthly_report_structured_uploads as structured
    reserved = []
    original = structured.reserve_bulk_image
    def record(profile, digest, raw):
        reserved.append(digest)
        return original(profile, digest, raw)
    monkeypatch.setattr(structured, 'reserve_bulk_image', record)
    payloads = reader_batches(profile, contents, 'activity_summary')
    payload_text = '\n'.join(block.get('text', '') for payload in payloads for block in payload)
    assert contents[0].source.id in payload_text
    assert contents[1].source.id not in payload_text
    assert 'FOREIGN_CONTEXT_CANARY' not in payload_text
    assert contents[1].source.sha256 not in reserved
    assert reader_batches(profile, (contents[1],), 'activity_summary') == ()


@pytest.mark.parametrize('pass_kind', ['native', 'reader'])
@pytest.mark.parametrize('detail', [
    'call Synthetic Technician at 202-555-0176 or service.person@example.invalid with questions',
    'Phone: (202) 555-0176; Email: service.person@example.invalid',
    'call Synthetic Technician at 2025550176',
])
def test_extracted_contacts_are_excluded_without_losing_work_or_negative_tails(monkeypatch, tmp_path, pass_kind, detail):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    text = 'Technician inspected the tower basin; ' + detail + '; the fan did not start.'
    content, _ = sources.ingest(synthetic_profiles()[0], 'synthetic-contact-service.pdf', pdf_bytes(text))
    if pass_kind == 'native':
        result = native_update((content,), 'activity_summary')
    else:
        result, _ = reader_update((content,), 'activity_summary', {'items': [
            {'source': content.source.id, 'page': 1, 'text': text, 'row': []}]})
    assert '202-555-0176' not in result.text
    assert '(202) 555-0176' not in result.text
    assert '2025550176' not in result.text
    assert 'service.person@example.invalid' not in result.text
    assert 'Technician inspected the tower basin' in result.text
    assert 'the fan did not start.' in result.text


def test_operating_identifiers_and_deliberate_human_wording_are_not_contact_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    text = ('Inspected asset serial 2025550176 on 2026-09-12; recorded 128 psi, '
            '27% valve travel and 1.5 hours. Inspected work order 202-555-0198. '
            'Contact relay CR-42 remains locked out.')
    content, _ = sources.ingest(synthetic_profiles()[0], 'synthetic-operating-controls.pdf', pdf_bytes(text))
    manual = ResolvedBlock('activity_summary', 'This month', text='Human-authored note: call 202-555-0176 after the agreed review.')
    native = native_update((content,), 'activity_summary', manual)
    assert manual.text in native.text
    assert ' '.join(text.split()) in ' '.join(native.text.split())
    result, _ = reader_update((content,), 'activity_summary', {'items': [
        {'source': content.source.id, 'page': 1, 'text': text, 'row': []}]}, native)
    assert result.text == native.text


@pytest.mark.parametrize('mixed', [True, False])
def test_guided_mixed_upload_is_processed_and_reading_cannot_retry_an_unrouted_csv(monkeypatch, tmp_path, mixed):
    import streamlit as st
    from app import monthly_report_ai as ai, receipt_jobs
    from app import monthly_report_active_work as active_work
    from app.monthly_report_model import ReportPeriod
    from test_monthly_report_activity_intake_commit import setup_app, editor, draft, activity, TOKEN
    app, profile = setup_app(monkeypatch, tmp_path)
    # Explicit source types preserve this Activity-routing test under the
    # general intake; ambiguous Reference-only files are covered separately.
    originals = {
        'synthetic-cmms-site-log.csv': b'Building,Work Performed,Service Date\nUnmapped East,Replaced reserve pump coupling,2026-10-12\n',
    }
    if mixed:
        originals['synthetic-maintenance report.pdf'] = pdf_bytes(SAFE_WORK)
    original_uploader = st.file_uploader
    def upload(label, *args, **kwargs):
        if label == 'Add source files':
            values = []
            for name, raw in originals.items():
                stream = BytesIO(raw); stream.name = name; values.append(stream)
            return values
        return original_uploader(label, *args, **kwargs)
    monkeypatch.setattr(st, 'file_uploader', upload)
    calls, reservations = [], []
    monkeypatch.setattr(ai, 'ANTHROPIC_API_KEY', 'synthetic-key-not-used')
    monkeypatch.setattr(ai, 'reserve_call', lambda *a: reservations.append(a))
    def request_json(payload):
        calls.append(payload)
        texts = '\n'.join(block.get('text', '') for block in payload)
        items = []
        for name, raw in originals.items():
            identity = sha256(raw).hexdigest()
            if 'SOURCE ' + identity + ' PAGE 1' in texts:
                items.append({'source': identity, 'page': 1, 'row': [],
                    'text': SAFE_WORK if name.endswith('.pdf') else 'Replaced reserve pump coupling'})
        return {'items': items}
    monkeypatch.setattr(ai, 'request_json', request_json)
    def finish(prepare, worker):
        future = Future()
        try:
            future.set_result(worker(prepare()))
        except Exception as exc:
            future.set_exception(exc)
        return future
    monkeypatch.setattr(receipt_jobs, 'start_receipt', finish)
    editor(app).set_value('Human text delivered with these files.').run()
    assert not app.exception
    expected_ids = {sha256(raw).hexdigest() for raw in originals.values()}
    assert {source.id for source in draft(app).sources} == expected_ids, 'Both real uploads must be processed.'
    native_ids = set().union(*(set(value) for key, value in app.session_state.filtered_state.items()
                            if key.endswith('_native_ids')))
    assert expected_ids <= native_ids
    assert not calls and not reservations, 'Upload alone cannot start paid reading.'
    notices = '\n'.join(item.value for item in (*app.warning, *app.info, *app.caption))
    assert 'synthetic-cmms-site-log.csv' in notices and 'not sent to the Activity reader' in notices
    assert 'reserve pump coupling' not in activity(app).text
    if mixed:
        next(button for button in app.button if button.label == 'Read selected files').click().run()
        app.run()
        assert not app.exception
        assert len(calls) == len(reservations) == 1
        assert not any(button.label.startswith('Retry reading') for button in app.button)
        assert SAFE_WORK in activity(app).text
    else:
        assert not any(button.label in {'Read selected files', 'Retry reading uploaded files'} for button in app.button)
    for _ in range(2):
        app.run()
        assert not app.exception
    assert len(calls) == (1 if mixed else 0)
    journal = active_work.load(TOKEN, profile.contract, profile.key, ReportPeriod(2026, 10))
    assert journal and next(block for block in journal.draft.blocks if block.key == 'activity_summary') == activity(app)


@requires_libreoffice
def test_contact_filtered_activity_persists_and_prints_without_contact_values(monkeypatch, tmp_path):
    from app import monthly_report_library as library
    from app.monthly_report_docx import generate_report
    from app.monthly_report_model import BlockSpec, ReportDraft, ReportPeriod, SectionSpec
    from app.monthly_report_source_details import correct_source_details
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    original = pdf_bytes('Vendor inspected fan EF-73; call Synthetic Tech at 202-555-0176 or '
        'service.person@example.invalid with questions; the fan did not start.')
    content, _ = sources.ingest(profile, 'synthetic-contact-service.pdf', original)
    reviewed = correct_source_details(content.source, profile, None, profile.facilities[0].key)
    content = replace(content, source=reviewed)
    block = native_update((content,), 'activity_summary')
    section = SectionSpec('activity', '2', 'Monthly Activity Summary', (BlockSpec('activity_summary', 'rich_text'),))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Reviewer', (section,),
                        (block,), sources=(reviewed,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    restored = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert restored.draft == draft and restored.revision == saved.revision
    package = generate_report(restored.draft, acknowledged_fingerprint=restored.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    assert sources.source_bytes(profile, reviewed) == original
    output = Path(os.environ.get('INDEPENDENT_OUTPUT', str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'contact_filtered_activity.docx').write_bytes(package.docx)
    (output / 'contact_filtered_activity.pdf').write_bytes(package.pdf)
    (output / 'contact_filtered_activity.json').write_text(json.dumps({
        'tested_revision': os.environ.get('MSAPO_SHA', 'unrecorded'),
        'source_sha256': sha256(original).hexdigest(), 'draft_fingerprint': restored.draft.fingerprint,
        'saved_revision': restored.revision,
        'docx_bytes': len(package.docx), 'docx_sha256': sha256(package.docx).hexdigest(),
        'pdf_bytes': len(package.pdf), 'pdf_sha256': sha256(package.pdf).hexdigest(),
    }, indent=2) + '\n')
    document = Document(BytesIO(package.docx))
    text = '\n'.join(paragraph.text for paragraph in document.paragraphs)
    assert 'inspected fan EF-73' in text and text.count('the fan did not start.') == 1
    with ZipFile(BytesIO(package.docx)) as package_parts:
        parts = b'\n'.join(package_parts.read(name) for name in package_parts.namelist()
                           if name.endswith(('.xml', '.rels')))
    assert b'202-555-0176' not in parts and b'service.person@example.invalid' not in parts
    with fitz.open(stream=package.pdf, filetype='pdf') as pdf:
        text = ' '.join(' '.join(page.get_text().split()) for page in pdf)
        for index, page in enumerate(pdf, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output / f'contact_filtered_activity_page_{index}.png')
    assert 'inspected fan EF-73' in text and text.count('the fan did not start.') == 1
    assert '202-555-0176' not in text and 'service.person@example.invalid' not in text
