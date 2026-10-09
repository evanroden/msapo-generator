import threading
import time

import pytest
from lxml import etree as E

from app import monthly_report_cover_metrics as metrics
from app import monthly_report_render_jobs as jobs


def source_root():
    ns = ' '.join(f'xmlns:{key}="{value}"' for key, value in metrics.NS.items())
    paragraphs = ''.join(f'<w:p><w:pPr><w:spacing w:line="360" w:lineRule="auto"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial Narrow"/><w:b/><w:sz w:val="{size}"/></w:rPr><w:t>{text}</w:t></w:r></w:p>' for size, text in [(56, 'Synthetic Site'), (48, 'Monthly Review')])
    return E.fromstring(f'<w:document {ns}><w:body><w:p><w:r><w:drawing><wp:anchor wp14:anchorId="A1234567"><wp:positionV relativeFrom="page"><wp:posOffset>2000000</wp:posOffset></wp:positionV><wp:extent cx="6000000" cy="1100000"/><wps:wsp><wps:txbx><w:txbxContent>{paragraphs}</w:txbxContent></wps:txbx><wps:bodyPr lIns="0" tIns="0" rIns="0" bIns="0"><a:noAutofit/></wps:bodyPr></wps:wsp></wp:anchor></w:drawing></w:r></w:p><w:sectPr/></w:body></w:document>')


def test_independent_measured_parameters_and_strict_application():
    root = source_root()
    item = metrics.candidates(root)[0]
    record = metrics.solve(item, [191.16, 235.44], [195.5, 250.35], [195.5, 239.3], 293)
    assert record['line'] == 296
    assert record['y_delta'] == -4.34
    assert metrics.apply_cover_metrics(root, [record])
    assert root.find('.//wp:posOffset', metrics.NS).text == str(2000000 - round(4.34 * 12700))
    assert not metrics.apply_cover_metrics(root, [record])  # Never cumulative.
    changed = source_root()
    changed.find('.//wp:extent', metrics.NS).set('cy', '2000000')
    assert not metrics.apply_cover_metrics(changed, [record])


def test_text_edit_does_not_change_font_geometry_signature():
    root = source_root()
    before = metrics.candidates(root)[0]['signature']
    root.find('.//w:t', metrics.NS).text = 'Renamed Site'
    assert metrics.candidates(root)[0]['signature'] == before


@pytest.mark.parametrize('change', [{'y_delta': float('nan')}, {'y_delta': 21}, {'line': True}, {'anchor': '../bad'}, {'extra': 1}])
def test_invalid_records_rejected(change):
    record = {'anchor': 'A1234567', 'signature': 'a' * 64, 'line': 296, 'y_delta': -4.34, **change}
    with pytest.raises(ValueError):
        metrics.validate_records([record])


def test_serialization_is_bounded_and_preserves_backend_seam(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    entered, release = threading.Event(), threading.Event()
    def backend(path):
        entered.set(); release.wait(2)
        return path
    monkeypatch.setattr(jobs.pdf_converter, 'convert_to_pdf', backend)
    worker = threading.Thread(target=lambda: jobs.convert_to_pdf('first'))
    worker.start(); assert entered.wait(1)
    started = time.monotonic()
    with pytest.raises(jobs.RenderBusy):
        jobs.convert_to_pdf('preview', wait_seconds=0)
    assert time.monotonic() - started < .1
    release.set(); worker.join(2)
    assert jobs.convert_to_pdf('next') == 'next'


def test_v3_identity_is_unchanged_by_v4_metrics():
    import hashlib
    import json

    from app.monthly_report_render_profile import identity, validate_profile
    old = {'version': 3, 'cover_zero_origin': True, 'divider_wrap_none': False, 'divider_white_text': True}
    assert validate_profile(old) == old
    payload = {'source_sha256': 'a' * 64, 'companion_sha256': 'b' * 64, 'render_profile': old}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert identity('a' * 64, 'b' * 64, old) == expected


def test_v4_records_are_defensively_copied_and_strict():
    from app.monthly_report_render_profile import DEFAULT, validate_profile
    record = {'anchor': 'A1234567', 'signature': 'a' * 64, 'line': 296, 'y_delta': -4.34}
    source = {**DEFAULT, 'cover_metrics': [record]}
    checked = validate_profile(source)
    checked['cover_metrics'][0]['line'] = 300
    assert record['line'] == 296
    for bad in (None, {}, [dict(record, line=1)], [record, record]):
        with pytest.raises(ValueError):
            validate_profile({**DEFAULT, 'cover_metrics': bad})


def test_cross_process_conversion_slot_contention(tmp_path, monkeypatch):
    import os
    import select
    import subprocess
    import sys

    if os.name == 'nt':
        pytest.skip('POSIX process-lock control')
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    script = '''from app.monthly_report_render_jobs import conversion_slot
import sys
with conversion_slot(wait_seconds=0):
 print('locked', flush=True)
 sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 5)[0]
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(jobs.RenderBusy), jobs.conversion_slot(wait_seconds=.1):
            pytest.fail('Cross-process lock was not held.')
    finally:
        child.communicate('\n', timeout=10)
    assert child.returncode == 0
    with jobs.conversion_slot(wait_seconds=0):
        pass


@pytest.mark.parametrize('clipped,native', [(False, False), (True, False), (False, True)])
def test_calibration_requires_verified_full_visible_lines(tmp_path, monkeypatch, clipped, native):
    from io import BytesIO
    from zipfile import ZipFile

    from app import (
        monthly_report_native_package,
        monthly_report_render_compat,
        monthly_report_render_profile,
    )
    raw = BytesIO()
    with ZipFile(raw, 'w') as archive:
        archive.writestr('word/document.xml', E.tostring(source_root()))
    monkeypatch.setattr(monthly_report_native_package, 'passive_docx', lambda source: raw.getvalue())
    monkeypatch.setattr(monthly_report_render_compat, 'rendering_docx', lambda raw, profile: raw)
    calls, generated = [], {}
    texts = metrics.candidates(source_root())[0]['texts']
    target = [195.5, 250.35] if native else [191.16, 235.44]
    def evidence(baselines, height=22):
        return {'pages': 1, 'cover_lines': [{'text': text, 'baseline': y, 'ink_height': height, 'ink_area': 100} for text, y in zip(texts, baselines)]}
    def inspect(path, **kwargs):
        return evidence(target) if path == 'reference' else generated[path]
    def convert(path, **kwargs):
        with ZipFile(path) as archive:
            root = E.fromstring(archive.read('word/document.xml'))
        item = metrics.candidates(root)[0]
        delta = (item['geometry'][0] - 2000000) / 12700
        baselines = [195.5 + delta, 250.35 + (item['line'] - 360) * .165 + delta]
        output = tmp_path / f'proof-{len(calls)}.pdf'; output.write_bytes(b'pdf')
        generated[output] = evidence(baselines, 8 if clipped and delta else 22)
        calls.append(item['line'])
        return output
    monkeypatch.setattr(monthly_report_render_profile, 'inspect_companion', inspect)
    monkeypatch.setattr(jobs, 'convert_to_pdf', convert)
    records, audit = metrics.calibrate_cover_metrics('source', 'reference', monthly_report_render_profile.DEFAULT)
    if native:
        assert not records and audit['status'] == 'native-baselines-match' and len(calls) == 1
    elif clipped:
        assert not records and 'visible-ink' in audit['reason'] and len(calls) == 3
    else:
        assert records[0]['line'] == 296 and audit['visible_ink_verified'] and len(calls) == 3
    assert not list(tmp_path.glob('proof-*.pdf'))
