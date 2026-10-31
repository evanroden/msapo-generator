"""The resource probe observes the real converter without dropping its options."""
import ast
from hashlib import sha256
from io import BytesIO
import json
import logging
from pathlib import Path
import random

from docx import Document
from docx.shared import Inches
from PIL import Image
import pymupdf
import pytest

from app import pdf_converter, monthly_report_render_jobs
from conftest import requires_libreoffice


def observed_converter(original):
    """Execute the actual nested driver function, not a test reimplementation."""
    source = Path(__file__).resolve().parents[1] / 'scripts/qa_monthly_report_resources.py'
    module = ast.parse(source.read_text())
    main = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    functions = [node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'observed_converter']
    assert len(functions) == 1
    namespace = {'original_converter': original, 'logging': logging}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['observed_converter']


@pytest.mark.parametrize('options', [{}, {'lossless_images': False}, {'lossless_images': True}])
def test_actual_probe_forwards_each_supplied_option_once_without_defaults(options):
    calls = []
    result = object()
    def backend(path, **kwargs):
        calls.append((path, kwargs))
        return result
    source = Path('untouched.docx')
    assert observed_converter(backend)(source, **options) is result
    assert calls == [(source, options)]


@pytest.mark.parametrize('options', [{}, {'lossless_images': True}])
def test_probe_preserves_exact_failure_and_logs_once_without_retry(options, caplog):
    calls = []
    failure = pdf_converter.PDFConversionTimeout('synthetic original worker timeout')
    def backend(path, **kwargs):
        calls.append((path, kwargs))
        raise failure
    source = Path('unchanged.docx')
    with pytest.raises(pdf_converter.PDFConversionTimeout) as raised:
        observed_converter(backend)(source, **options)
    assert raised.value is failure
    assert calls == [(source, options)]
    messages = [record for record in caplog.records if record.message == 'Synthetic resource probe converter failure']
    assert len(messages) == 1 and messages[0].exc_info[1] is failure


def test_probe_cannot_silently_drop_unknown_backend_option(caplog):
    calls = []
    def strict_backend(path, *, lossless_images=False):
        calls.append(path)
    with pytest.raises(TypeError, match='unknown_option'):
        observed_converter(strict_backend)(Path('unchanged.docx'), unknown_option=True)
    assert calls == []
    assert len([record for record in caplog.records if record.message == 'Synthetic resource probe converter failure']) == 1


@requires_libreoffice
def test_real_worker_receives_lossless_through_actual_resource_probe(monkeypatch, tmp_path, record_property):
    from app import office_process
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    monkeypatch.setattr(pdf_converter, 'PDF_BACKEND', 'libreoffice')
    original = pdf_converter._BACKENDS['libreoffice']
    monkeypatch.setitem(pdf_converter._BACKENDS, 'libreoffice', observed_converter(original))
    worker = office_process.run_office
    calls = []
    def record_worker(command, *, timeout):
        calls.append((command, timeout))
        return worker(command, timeout=timeout)
    monkeypatch.setattr(office_process, 'run_office', record_worker)
    image = Image.frombytes('RGB', (320, 180), random.Random(125).randbytes(320 * 180 * 3))
    data = BytesIO()
    image.save(data, 'PNG')
    document = Document()
    document.add_picture(BytesIO(data.getvalue()), width=Inches(2))
    path = tmp_path / 'synthetic.docx'
    document.save(path)
    before = path.read_bytes()
    output = monthly_report_render_jobs.convert_to_pdf(path, wait_seconds=130, lossless_images=True)
    try:
        assert len(calls) == 1
        command, timeout = calls[0]
        assert timeout == 120
        option = command[command.index('--convert-to') + 1]
        prefix, filter_name, settings = option.split(':', 2)
        assert (prefix, filter_name) == ('pdf', 'writer_pdf_Export')
        assert json.loads(settings) == {'UseLosslessCompression': {'type': 'boolean', 'value': 'true'},
                                        'ReduceImageResolution': {'type': 'boolean', 'value': 'false'}}
        assert command[-1] == str(path.resolve())
        with pymupdf.open(output) as pdf:
            infos = [info for page in pdf for info in page.get_image_info(xrefs=True)]
            assert len(infos) == 1
            resource = pdf.extract_image(infos[0]['xref'])
            actual = Image.open(BytesIO(resource['image'])).convert('RGB')
            assert resource['smask'] == 0
            assert actual.size == image.size and actual.tobytes() == image.tobytes()
        assert path.read_bytes() == before
        record_property('real_worker', json.dumps({'calls': len(calls), 'timeout': timeout,
            'dimensions': image.size, 'rgb_sha256': sha256(actual.tobytes()).hexdigest(),
            'pdf_bytes': output.stat().st_size, 'options': json.loads(settings)}))
    finally:
        output.unlink(missing_ok=True)
    assert not list(tmp_path.glob('.office-*'))
