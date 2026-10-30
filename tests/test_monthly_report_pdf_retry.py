"""PDF retry converts the exact completed native DOCX without assembly or saving."""
from dataclasses import replace
from contextlib import contextmanager

import pytest
from docx import Document
from io import BytesIO

from app import monthly_report_docx as module, monthly_report_render_jobs as jobs
from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026,9))
    word = Document()
    word.add_paragraph('Synthetic original editable Word bytes')
    stream = BytesIO()
    word.save(stream)
    raw = module.canonical_docx(stream.getvalue())
    package = module.ReportPackage(raw, None, 'original.docx', 'original.pdf', draft.fingerprint, 'Prior PDF failed')
    monkeypatch.setattr(module, 'assemble_docx', lambda *a, **kw: pytest.fail('Retry must not assemble Word again'))
    monkeypatch.setattr(module, 'rendering_docx', lambda raw, **kw: raw)
    return draft, package


def test_retry_converts_same_bytes_in_foreground_slot_and_keeps_native_identity(monkeypatch, tmp_path):
    draft, package = setup(monkeypatch, tmp_path)
    observations = []
    original_slot = jobs.work_slot
    @contextmanager
    def slot(**kwargs):
        observations.append(('slot', kwargs))
        with original_slot(**kwargs):
            yield
    monkeypatch.setattr(jobs, 'work_slot', slot)
    target = tmp_path/'converted.pdf'
    def convert(path, **kwargs):
        observations.append(('convert', path.read_bytes(), kwargs))
        target.write_bytes(b'%PDF-synthetic')
        return target
    monkeypatch.setattr(jobs, 'convert_to_pdf', convert)
    result = module.retry_report_pdf(draft, package)
    assert result == replace(package, pdf=b'%PDF-synthetic', pdf_error='')
    assert observations == [('slot', {}), ('convert', package.docx, {'wait_seconds':130, 'lossless_images':True})]
    assert not target.exists()
    assert module.retry_report_pdf(draft, result) is result
    assert len(observations) == 2


def test_changed_draft_rejects_before_work_or_conversion(monkeypatch, tmp_path):
    draft, package = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(jobs, 'work_slot', lambda **kw: pytest.fail('Stale retry cannot acquire work'))
    with pytest.raises(ValueError, match='earlier draft'):
        module.retry_report_pdf(replace(draft, prepared_by='Different editor'), package)


@pytest.mark.parametrize('kind', ['busy', 'invalid'])
def test_failed_retry_keeps_word_and_releases_admission(monkeypatch, tmp_path, kind):
    draft, package = setup(monkeypatch, tmp_path)
    target = tmp_path/'bad.pdf'
    def convert(path, **kwargs):
        if kind == 'busy':
            raise jobs.RenderBusy('Synthetic office is busy')
        target.write_bytes(b'not a pdf')
        return target
    monkeypatch.setattr(jobs, 'convert_to_pdf', convert)
    result = module.retry_report_pdf(draft, package)
    assert result.docx == package.docx and result.fingerprint == package.fingerprint
    assert result.docx_name == 'original.docx' and result.pdf_name == 'original.pdf'
    assert result.pdf is None and 'DOCX is ready' in result.pdf_error
    assert not target.exists()
    with jobs.work_slot(preview=True):
        pass
