"""Only invented DOCX fixtures. Fake conversion is not production fidelity proof."""
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
import fitz
import pytest

from app import memory
from app import monthly_report_source_render_qa as p
from app import monthly_report_testing as qa

TOKEN = 'a' * 32
OWNER = 'b' * 32


@pytest.fixture
def source():
    document = Document()
    document.add_paragraph('Invented source: estimated cost $3200; NOT approved.')
    output = BytesIO()
    document.save(output)
    return output.getvalue()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    with qa.isolated(TOKEN):
        memory._data_dir()
        yield tmp_path


def request(raw):
    epoch = p.retire(OWNER)
    return p.new_request(OWNER, epoch, raw, upload_id='fresh-file-1', label='Synthetic original', kind='original')


def fake_render(path, directory):
    assert path.name == 'render-input.docx'
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), 'Synthetic preview only')
        output = directory / 'render-input.pdf'
        doc.save(output)
    return output, {'version': 'LibreOffice 24.2.7.2 synthetic stub, NOT render proof'}, 1


def rewrite(raw, mutate):
    with ZipFile(BytesIO(raw)) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    mutate(parts)
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as package:
        for name, data in parts.items():
            package.writestr(name, data)
    return output.getvalue()


def test_uses_real_passive_pipeline_and_distinct_immutable_receipts(isolated, source, monkeypatch):
    monkeypatch.setattr(p, '_render', fake_render)
    req = request(source)
    result = p.execute(req, source, upload_id=req.upload_id)
    assert result['status'] == 'rendered' and result['pages'] == 1
    assert result['source_sha256'] == sha256(source).hexdigest()
    assert result['render_input_sha256'] != result['source_sha256']
    assert p.artifact(req, 'source.docx') == source
    passive = p.artifact(req, 'render-input.docx')
    assert sha256(passive).hexdigest() == result['render_input_sha256']
    assert Document(BytesIO(passive)).paragraphs[0].text == Document(BytesIO(source)).paragraphs[0].text
    assert p.artifact(req, 'source-preview.pdf').startswith(b'%PDF-')
    assert json.loads(p.artifact(req, 'receipt.json')) == result
    assert not (isolated / 'monthly_reports').exists()
    assert list(p._root().rglob('*.docx'))
    assert not list(p._root().rglob('.conversion-*'))


def test_no_live_namespace_even_if_token_is_forged(tmp_path, monkeypatch, source):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    with pytest.raises(p.SourcePreviewError, match='active isolated'):
        p.retire(OWNER)
    with qa.isolated(TOKEN):  # Lease not bound yet.
        with pytest.raises(p.SourcePreviewError, match='active isolated'):
            p.retire(OWNER)
    assert not list(tmp_path.iterdir())


def test_replay_changed_upload_and_a_b_a_are_rejected(isolated, source, monkeypatch):
    monkeypatch.setattr(p, '_render', fake_render)
    req = request(source)
    with pytest.raises(p.SourcePreviewError, match='stale'):
        p.execute(req, source, upload_id='another-file')
    with pytest.raises(p.SourcePreviewError, match='stale'):
        p.execute(req, source + b'x', upload_id=req.upload_id)
    p.execute(req, source, upload_id=req.upload_id)
    with pytest.raises(p.SourcePreviewError, match='already attempted'):
        p.execute(req, source, upload_id=req.upload_id)
    p.retire(OWNER)
    with pytest.raises(p.SourcePreviewError, match='stale'):
        p.artifact(req, 'source.docx')
    fresh = request(source)
    assert fresh.epoch != req.epoch
    p.execute(fresh, source, upload_id=fresh.upload_id)
    with pytest.raises(p.SourcePreviewError, match='stale'):
        p.execute(req, source, upload_id=req.upload_id)


def test_two_sessions_and_two_browsers_cannot_reuse_results(isolated, source, monkeypatch):
    monkeypatch.setattr(p, '_render', fake_render)
    req = request(source)
    p.execute(req, source, upload_id=req.upload_id)
    p.retire('c' * 32)
    with pytest.raises(p.SourcePreviewError):
        p.artifact(replace(req, owner='c' * 32), 'source.docx')
    with qa.isolated('d' * 32):
        memory._data_dir()
        with pytest.raises(p.SourcePreviewError, match='session changed'):
            p.artifact(req, 'source.docx')
    assert p.artifact(req, 'source.docx') == source


@pytest.mark.parametrize('payload', ['macro', 'unreachable-active', 'external-image', 'external-template', 'active-shape'])
def test_active_or_external_package_never_reaches_renderer(isolated, source, monkeypatch, payload):
    called = []
    monkeypatch.setattr(p, '_render', lambda *_: called.append(True))
    def mutate(parts):
        if payload == 'macro':
            parts['[Content_Types].xml'] = parts['[Content_Types].xml'].replace(
                b'wordprocessingml.document.main+xml', b'ms-word.document.macroEnabled.main+xml')
        elif payload == 'unreachable-active':
            parts['word/vbaProject.bin'] = b'invented payload'
        elif payload == 'active-shape':
            parts['word/document.xml'] = parts['word/document.xml'].replace(b'<w:body>', b'<w:body><w:object/>')
        else:
            kind = 'image' if payload == 'external-image' else 'attachedTemplate'
            parts['word/_rels/document.xml.rels'] = parts['word/_rels/document.xml.rels'].replace(
                b'</Relationships>', f'<Relationship Id="bad" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" Target="https://invalid.example/resource" TargetMode="External"/></Relationships>'.encode())
    raw = rewrite(source, mutate)
    req = request(raw)
    result = p.execute(req, raw, upload_id=req.upload_id)
    assert result['status'] == 'failed' and result['stage'] == 'passive package validation'
    assert not called and 'pdf_sha256' not in result
    assert p.artifact(req, 'source.docx') == raw


def test_macro_in_unreachable_content_type_is_rejected(isolated, source, monkeypatch):
    monkeypatch.setattr(p, '_render', lambda *_: pytest.fail('active package reached renderer'))
    raw = rewrite(source, lambda parts: parts.update({'[Content_Types].xml': parts['[Content_Types].xml'].replace(
        b'</Types>', b'<Override PartName="/unused.bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')}))
    req = request(raw)
    assert p.execute(req, raw, upload_id=req.upload_id)['status'] == 'failed'


def test_failure_receipt_is_frozen_and_content_diagnostics_are_not_logged(isolated, source, monkeypatch, caplog):
    count = []
    def fail(*_):
        count.append(1)
        raise RuntimeError('PRIVATE SOURCE CONTENT THAT MUST NEVER BE LOGGED')
    monkeypatch.setattr(p, '_render', fail)
    req = request(source)
    result = p.execute(req, source, upload_id=req.upload_id)
    receipt = p.artifact(req, 'receipt.json')
    assert result['status'] == 'failed' and result['stage'] == 'LibreOffice conversion'
    assert 'PRIVATE SOURCE' not in receipt.decode() + caplog.text
    assert p.artifact(req, 'render-input.docx')
    with pytest.raises(p.SourcePreviewError):
        p.execute(req, source, upload_id=req.upload_id)
    assert count == [1] and p.artifact(req, 'receipt.json') == receipt
    assert not list(p._root().rglob('.conversion-*'))


def test_busy_is_one_failure_not_automatic_retry(isolated, source, monkeypatch):
    @contextmanager
    def busy(**_):
        raise p.jobs.RenderBusy('busy')
        yield
    monkeypatch.setattr(p.jobs, 'work_slot', busy)
    req = request(source)
    result = p.execute(req, source, upload_id=req.upload_id)
    assert result['status'] == 'failed' and result['stage'] == 'admission'
    assert 'busy' in result['error']
    assert not (p._folder(OWNER) / 'source.docx').exists()


def test_cancel_during_render_cannot_publish_old_result(isolated, source, monkeypatch):
    def cancel(path, directory):
        result = fake_render(path, directory)
        p.retire(OWNER)
        return result
    monkeypatch.setattr(p, '_render', cancel)
    req = request(source)
    with pytest.raises(p.SourcePreviewError, match='stale'):
        p.execute(req, source, upload_id=req.upload_id)
    assert not list(p._root().rglob('*.pdf'))
    assert not list(p._root().rglob('receipt.json'))


def test_reset_during_render_cannot_recreate_removed_namespace(isolated, source, monkeypatch):
    def reset(path, directory):
        result = fake_render(path, directory)
        qa.reset(isolated)
        return result
    monkeypatch.setattr(p, '_render', reset)
    req = request(source)
    with pytest.raises(OSError, match='reset'):
        p.execute(req, source, upload_id=req.upload_id)
    assert not any((isolated / qa._BUCKET).iterdir())


def test_byte_limit_and_storage_budget_fail_before_converter(isolated, source, monkeypatch):
    monkeypatch.setattr(p, 'MAX_BYTES', len(source) - 1)
    with pytest.raises(p.SourcePreviewError, match='32 MiB'):
        request(source)
    monkeypatch.setattr(p, 'MAX_BYTES', 32 * 1024 * 1024)
    req = request(source)
    monkeypatch.setattr(p, 'MAX_STORE_BYTES', 1)
    with pytest.raises(p.SourcePreviewError, match='storage is full'):
        p.execute(req, source, upload_id=req.upload_id)
    assert not (p._folder(OWNER) / 'attempt.json').exists()


def test_changed_artifacts_and_symlink_are_rejected(isolated, source, monkeypatch):
    monkeypatch.setattr(p, '_render', fake_render)
    req = request(source)
    p.execute(req, source, upload_id=req.upload_id)
    path = p._folder(OWNER) / 'source.docx'
    assert path.stat().st_mode & 0o222 == 0
    path.chmod(0o600)  # Simulate out-of-band disk corruption, not an app edit.
    path.write_bytes(b'changed')
    with pytest.raises(p.SourcePreviewError, match='checksum'):
        p.artifact(req, 'source.docx')
    path.unlink()
    path.symlink_to(isolated / 'not-a-source')
    with pytest.raises(p.SourcePreviewError, match='unavailable'):
        p.artifact(req, 'source.docx')
    with pytest.raises(p.SourcePreviewError, match='unavailable'):
        p.retire(OWNER)


def test_timeout_retains_first_attempt(isolated, source, monkeypatch):
    def timeout(*_):
        raise subprocess.TimeoutExpired(['office'], 120)
    monkeypatch.setattr(p, '_render', timeout)
    req = request(source)
    result = p.execute(req, source, upload_id=req.upload_id)
    assert result['status'] == 'failed' and 'timed out' in result['error']
    assert 'pdf_sha256' not in result


@pytest.mark.parametrize('result_kind', ['valid', 'failure', 'invalid', 'too-many-pages'])
def test_renderer_uses_qa_output_existing_lease_and_process_cleanup(isolated, tmp_path, monkeypatch, result_kind):
    calls = []
    monkeypatch.setattr(p.shutil, 'which', lambda _: '/usr/bin/libreoffice')
    monkeypatch.setattr(p, '_renderer', lambda _: {'version': 'LibreOffice 24.2.7.2 synthetic stub'})
    @contextmanager
    def slot(**kwargs):
        calls.append(('slot', kwargs))
        yield
    monkeypatch.setattr(p.jobs, 'conversion_slot', slot)
    directory = p._folder(OWNER) / 'bounded-job'
    directory.mkdir()
    source = p._folder(OWNER) / 'render-input.docx'
    source.write_bytes(b'synthetic stub input')
    def office(command, *, timeout):
        calls.append(('office', command, timeout))
        output = directory / 'render-input.pdf'
        if result_kind == 'invalid':
            output.write_bytes(b'not a PDF')
        elif result_kind != 'failure':
            with fitz.open() as pdf:
                for _ in range(2 if result_kind == 'too-many-pages' else 1):
                    pdf.new_page()
                pdf.save(output)
        return subprocess.CompletedProcess(command, 1 if result_kind == 'failure' else 0, 'PRIVATE SOURCE', '')
    monkeypatch.setattr(p, 'run_office', office)
    if result_kind == 'too-many-pages':
        monkeypatch.setattr(p, 'MAX_PAGES', 1)
    if result_kind == 'valid':
        result, _, pages = p._render(source, directory)
        assert result.parent == directory and pages == 1
    else:
        with pytest.raises((p.SourcePreviewError, RuntimeError)):
            p._render(source, directory)
    assert calls[0] == ('slot', {'wait_seconds': 0})
    command, timeout = calls[1][1:]
    assert timeout == 120
    assert command[:3] == [p.sys.executable, '-c', p._LIMIT_EXEC]
    assert 'RLIMIT_FSIZE' in command[2] and 'RLIMIT_AS' in command[2] and 'RLIMIT_CPU' in command[2]
    assert command[command.index('--outdir') + 1] == str(directory)
    assert str(source.resolve()) == command[-1]
    assert (directory / 'profile/user/registrymodifications.xcu').is_file()


@pytest.mark.parametrize('version', ['LibreOffice 26.8.0.0.alpha0 fake', 'LibreOffice 7.6.0.0 fake', 'not office'])
def test_non_production_renderer_rejected_before_fonts_or_conversion(monkeypatch, version):
    monkeypatch.setattr(p, 'run_office', lambda *_a, **_kw: subprocess.CompletedProcess([], 0, version, ''))
    monkeypatch.setattr(p.subprocess, 'run', lambda *_a, **_kw: pytest.fail('wrong engine continued'))
    with pytest.raises(p.SourcePreviewError, match='24.2'):
        p._renderer('/invented/libreoffice')


def test_passive_transform_inventory_is_specific(isolated, source, monkeypatch):
    monkeypatch.setattr(p, '_render', fake_render)
    req = request(source)
    receipt = p.execute(req, source, upload_id=req.upload_id)
    changes = receipt['changed_package_parts']
    assert any(row['part'] == 'docProps/core.xml' and row['render_sha256'] is None for row in changes)
    assert all(set(row) == {'part', 'source_sha256', 'render_sha256'} for row in changes)


def test_office_diagnostics_preserve_evidence_without_private_text():
    result = subprocess.CompletedProcess([], 0, 'PRIVATE SOURCE warning', 'PRIVATE PATH')
    evidence = p._diagnostics(result)
    assert evidence['stdout']['present'] and evidence['stderr']['present']
    assert evidence['stdout']['sha256'] == sha256(result.stdout.encode()).hexdigest()
    assert evidence['stderr']['decoded_capture_bytes'] == len(result.stderr)
    assert 'PRIVATE' not in json.dumps(evidence)


@pytest.mark.skipif(__import__('os').environ.get('GITHUB_ACTIONS') != 'true',
                    reason='Production 24.2 integration runs in GitHub CI; local renderer execution is unavailable here.')
def test_ci_real_24_2_source_render_and_cleanup(isolated, source):
    """Mandatory on GitHub's installed production renderer, never a mock pass."""
    req = request(source)
    result = p.execute(req, source, upload_id=req.upload_id)
    assert result['status'] == 'rendered', result
    assert result['renderer']['version'].startswith('LibreOffice 24.2.')
    assert result['renderer']['fonts'] and result['renderer']['font_inventory']
    assert 'office_diagnostics' in result['renderer']
    assert p.artifact(req, 'source.docx') == source
    passive = p.artifact(req, 'render-input.docx')
    assert sha256(passive).hexdigest() == result['render_input_sha256']
    pdf = p.artifact(req, 'source-preview.pdf')
    assert sha256(pdf).hexdigest() == result['pdf_sha256']
    with fitz.open(stream=pdf, filetype='pdf') as rendered:
        assert rendered.is_pdf and len(rendered) == result['pages'] == 1
        assert '3200' in rendered[0].get_text()  # Source inspection is NOT price approval/removal.
    assert not list(p._root().rglob('.conversion-*'))
    assert not (p.library._root() / 'render-jobs/.active-office.json').exists()
    assert not (isolated / 'monthly_reports').exists()
    p.retire(OWNER)
    assert not list(p._root().rglob('*.docx')) and not list(p._root().rglob('*.pdf'))


def test_identical_bytes_fresh_requests_are_independent_renders_not_cache_hits(isolated, source, monkeypatch):
    calls = []
    def independent(path, directory):
        calls.append(sha256(path.read_bytes()).hexdigest())
        output = directory / 'render-input.pdf'
        with fitz.open() as document:
            document.new_page().insert_text((72, 72), f'Independent synthetic render {len(calls)}')
            document.save(output)
        return output, {'version': 'LibreOffice 24.2.7.2 synthetic stub'}, 1
    monkeypatch.setattr(p, '_render', independent)
    first = request(source)
    result_a = p.execute(first, source, upload_id=first.upload_id)
    receipt_a = p.artifact(first, 'receipt.json')
    with pytest.raises(p.SourcePreviewError, match='already attempted'):
        p.execute(first, source, upload_id=first.upload_id)
    assert len(calls) == 1
    second = request(source)  # Deliberate fresh selection/attempt, same exact bytes.
    result_b = p.execute(second, source, upload_id=second.upload_id)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert first.request_id != second.request_id and first.epoch != second.epoch
    assert result_a['source_sha256'] == result_b['source_sha256']
    assert result_a['pdf_sha256'] != result_b['pdf_sha256']
    assert receipt_a != p.artifact(second, 'receipt.json')
