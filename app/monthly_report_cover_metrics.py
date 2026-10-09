"""Measured cover textbox corrections for disposable PDF rendering copies.

No font, wording, or downloadable DOCX changes. A record is usable only while
its original textbox geometry and paragraph font metrics still match.
"""
import hashlib
import json
import math
import re
import subprocess
from copy import copy, deepcopy
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree as E

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
      'wp14': 'http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing',
      'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
      'wps': 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'v': 'urn:schemas-microsoft-com:vml',
      'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006'}
W = '{' + NS['w'] + '}'


def validate_records(records):
    if not isinstance(records, list) or len(records) > 3:
        raise ValueError('Unsupported saved cover typography measurements.')
    seen = set()
    for record in records:
        if (not isinstance(record, dict) or set(record) != {'anchor', 'signature', 'line', 'y_delta'}
                or not isinstance(record['anchor'], str) or not re.fullmatch(r'[0-9A-F]{8}', record['anchor'])
                or record['anchor'] in seen or not isinstance(record['signature'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', record['signature'])
                or type(record['line']) is not int or not 180 <= record['line'] <= 720
                or type(record['y_delta']) not in (int, float) or not math.isfinite(record['y_delta'])
                or abs(record['y_delta']) > 20):
            raise ValueError('Unsupported saved cover typography measurements.')
        seen.add(record['anchor'])
    return [dict(record) for record in records]


def _cover(root):
    body = root.find('w:body', NS)
    if body is None:
        return []
    result = []
    for node in body:
        result.append(node)
        if node.tag == W + 'sectPr' or node.find('.//w:sectPr', NS) is not None:
            break
        if len(result) > 8:
            return []
    return result


def candidates(root):
    result = []
    for node in _cover(root):
        for anchor in node.findall('.//wp:anchor', NS):
            try:
                aid = anchor.get('{' + NS['wp14'] + '}anchorId', '')
                box = anchor.find('.//w:txbxContent', NS)
                bodypr = anchor.find('.//wps:bodyPr', NS)
                pos = anchor.find('wp:positionV', NS)
                extent = anchor.find('wp:extent', NS)
                if (not re.fullmatch(r'[0-9A-F]{8}', aid) or box is None or bodypr is None
                        or pos is None or pos.get('relativeFrom') != 'page' or extent is None
                        or bodypr.get('anchor', 't') != 't'
                        or any(bodypr.get(key) != '0' for key in ('lIns', 'tIns', 'rIns', 'bIns'))
                        or bodypr.find('a:noAutofit', NS) is None
                        or len(box) != 2 or any(p.tag != W + 'p' for p in box)):
                    continue
                texts, metrics, lines = [], [], []
                for paragraph in box:
                    spacing = paragraph.find('w:pPr/w:spacing', NS)
                    runs = paragraph.findall('w:r', NS)
                    if (spacing is None or spacing.get(W + 'lineRule') != 'auto' or not runs
                            or any(child.tag not in {W + 'pPr', W + 'r'} for child in paragraph)):
                        raise ValueError
                    run_metrics = []
                    for run in runs:
                        props = run.find('w:rPr', NS)
                        if props is None or any(child.tag not in {W + 'rPr', W + 't'} for child in run):
                            raise ValueError
                        fonts, size = props.find('w:rFonts', NS), props.find('w:sz', NS)
                        if fonts is None or fonts.get(W + 'ascii') != 'Arial Narrow' or size is None:
                            raise ValueError
                        run_metrics.append((fonts.get(W + 'ascii'), int(size.get(W + 'val')), props.find('w:b', NS) is not None))
                    if len(set(run_metrics)) != 1:
                        raise ValueError
                    texts.append(' '.join(''.join(paragraph.xpath('.//w:t/text()', namespaces=NS)).split()))
                    metrics.append((run_metrics[0], sorted(spacing.attrib.items())))
                    lines.append(int(spacing.get(W + 'line')))
                if len(set(lines)) != 1 or not 240 <= lines[0] <= 600 or not all(texts):
                    continue
                geometry = [int(pos.find('wp:posOffset', NS).text), int(extent.get('cx')), int(extent.get('cy'))]
                signature = hashlib.sha256(json.dumps([geometry, metrics], sort_keys=True).encode()).hexdigest()
                result.append({'anchor': aid, 'signature': signature, 'texts': texts,
                               'line': lines[0], 'geometry': geometry, 'element': anchor})
            except (ValueError, TypeError, AttributeError):
                continue
    return result if len(result) <= 3 else []


def apply_cover_metrics(root, records):
    records = validate_records(records)
    available = candidates(root)
    changed = False
    for record in records:
        matches = [item for item in available if item['anchor'] == record['anchor'] and item['signature'] == record['signature']]
        if len(matches) != 1:
            continue
        item = matches[0]
        if not .65 <= record['line'] / item['line'] <= 1.35:
            continue
        anchor = item['element']
        offset = anchor.find('wp:positionV/wp:posOffset', NS)
        offset.text = str(int(offset.text) + round(record['y_delta'] * 12700))
        for spacing in anchor.findall('.//w:txbxContent/w:p/w:pPr/w:spacing', NS):
            spacing.set(W + 'line', str(record['line']))
        # Word's alternate VML representation must agree with DrawingML.
        alternate = next((parent for parent in anchor.iterancestors() if parent.tag == '{' + NS['mc'] + '}AlternateContent'), None)
        if alternate is not None:
            for shape in alternate.findall('.//mc:Fallback//v:shape', NS):
                if shape.get('{' + NS['w14'] + '}anchorId') != record['anchor']:
                    continue
                style = shape.get('style', '')
                match = re.search(r'(?<![-\w])margin-top:([-\d.]+)pt', style)
                if match:
                    replacement = f'margin-top:{float(match.group(1)) + record["y_delta"]:.6f}pt'
                    shape.set('style', style[:match.start()] + replacement + style[match.end():])
                for spacing in shape.findall('.//w:txbxContent/w:p/w:pPr/w:spacing', NS):
                    spacing.set(W + 'line', str(record['line']))
        changed = True
    return changed


def cover_package(raw):
    """Keep first-section semantics and dependencies while dropping later pages."""
    with ZipFile(BytesIO(raw)) as archive:
        root = E.fromstring(archive.read('word/document.xml'), E.XMLParser(resolve_entities=False, no_network=True))
        nodes = _cover(root)
        if not nodes:
            raise ValueError('No bounded first cover section was found.')
        end = nodes[-1] if nodes[-1].tag == W + 'sectPr' else nodes[-1].find('.//w:sectPr', NS)
        if end is None:
            raise ValueError('No first cover section boundary was found.')
        final = deepcopy(end)
        end.getparent().remove(end)
        body = root.find('w:body', NS)
        for node in list(body):
            body.remove(node)
        for node in nodes:
            if node.tag != W + 'sectPr':
                body.append(node)
        body.append(final)
        output = BytesIO()
        with ZipFile(output, 'w', ZIP_DEFLATED) as target:
            for info in archive.infolist():
                target.writestr(copy(info), E.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                                if info.filename == 'word/document.xml' else archive.read(info.filename))
        return output.getvalue()


def solve(item, reference, baseline, trial, trial_line):
    """Infer translation and line advance independently from measured origins."""
    if any(len(points) != 2 or any(not math.isfinite(p) for p in points) for points in (reference, baseline, trial)):
        raise ValueError('Incomplete cover baseline measurements.')
    slope = ((trial[1] - trial[0]) - (baseline[1] - baseline[0])) / (trial_line - item['line'])
    if not .02 <= slope <= .5 or abs(trial[0] - baseline[0]) > .2:
        raise ValueError('Cover line spacing does not have a stable measured response.')
    line = round(item['line'] + ((reference[1] - reference[0]) - (baseline[1] - baseline[0])) / slope)
    record = {'anchor': item['anchor'], 'signature': item['signature'], 'line': line,
              'y_delta': round(reference[0] - baseline[0], 4)}
    validate_records([record])
    return record


def pdf_cover_lines(page, queries):
    """Small text/ink measurements; called only inside the bounded PDF worker."""
    import pymupdf as fitz
    if not isinstance(queries, list) or len(queries) > 6 or any(not isinstance(q, str) or len(q) > 400 for q in queries):
        raise ValueError('Invalid cover line queries.')
    if not queries:
        return []
    lines = []
    for block in page.get_text('dict', flags=fitz.TEXT_PRESERVE_WHITESPACE)['blocks']:
        for line in block.get('lines', []):
            spans = line['spans']
            text = ' '.join(''.join(span['text'] for span in spans).split())
            if text not in queries or not spans or line.get('dir') != (1.0, 0.0):
                continue
            if len({round(span['origin'][1], 2) for span in spans}) != 1:
                continue
            bbox = fitz.Rect(line['bbox']) & page.rect
            if not 0 < bbox.width * bbox.height < 50_000:
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=bbox, colorspace=fitz.csGRAY, alpha=False)
            points = [(i % pix.width, i // pix.width) for i, value in enumerate(pix.samples) if value < 100]
            if not points:
                continue
            rows = [point[1] for point in points]
            lines.append({'text': text, 'baseline': spans[0]['origin'][1], 'bbox': list(bbox),
                          'ink_height': (max(rows) - min(rows) + 1) / 2, 'ink_area': len(points) / 4})
    return lines


def _matched_lines(evidence, texts):
    result = []
    for text in texts:
        matches = [line for line in evidence.get('cover_lines', []) if line['text'] == text]
        if len(matches) != 1:
            raise ValueError('Cover line is missing, wrapped, or ambiguous.')
        result.append(matches[0])
    return result


def _patch_package(raw, records):
    with ZipFile(BytesIO(raw)) as archive:
        root = E.fromstring(archive.read('word/document.xml'), E.XMLParser(resolve_entities=False, no_network=True))
        if records and not apply_cover_metrics(root, records):
            raise ValueError('Cover metrics no longer match their source.')
        result = BytesIO()
        with ZipFile(result, 'w', ZIP_DEFLATED) as target:
            for info in archive.infolist():
                target.writestr(copy(info), E.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                                if info.filename == 'word/document.xml' else archive.read(info.filename))
        return result.getvalue()


def calibrate_cover_metrics(source, companion, profile):
    """One owner-install calibration, at most three serialized cover renders."""
    import tempfile
    from pathlib import Path
    from uuid import uuid4

    from app import pdf_converter
    from app.monthly_report_native_package import passive_docx
    from app.monthly_report_render_compat import rendering_docx
    from app.monthly_report_render_jobs import convert_to_pdf
    from app.monthly_report_render_profile import inspect_companion

    audit = {'status': 'unsupported-cover'}
    records = []
    try:
        raw = cover_package(passive_docx(source))
        with ZipFile(BytesIO(raw)) as archive:
            items = candidates(E.fromstring(archive.read('word/document.xml')))
        # Keep one calibration bounded and reject overlapping/ambiguous boxes.
        if len(items) != 1:
            return records, audit
        item = items[0]
        queries = item['texts']
        reference = _matched_lines(inspect_companion(companion, cover_queries=queries), queries)
        with tempfile.TemporaryDirectory(prefix='monthly-cover-calibration-') as folder:
            def measure(patches):
                stem = 'cover-calibration-' + uuid4().hex
                path = Path(folder) / (stem + '.docx')
                actual = None
                expected = pdf_converter.OUTPUT_DIR / (stem + '.pdf')
                try:
                    path.write_bytes(rendering_docx(_patch_package(raw, patches), profile=profile))
                    actual = convert_to_pdf(path, wait_seconds=130)
                    observed = inspect_companion(actual, cover_queries=queries)
                    if observed['pages'] != 1:
                        raise ValueError('Cover calibration did not retain exactly one page.')
                    return _matched_lines(observed, queries)
                finally:
                    for output in {actual, expected} - {None}:
                        output.unlink(missing_ok=True)
            baseline = measure([])
            target = [line['baseline'] for line in reference]
            original = [line['baseline'] for line in baseline]
            if max(abs(a - b) for a, b in zip(target, original)) <= .2:
                return [], {'status': 'native-baselines-match'}
            trial_line = round(item['line'] * .8)
            trial_record = {'anchor': item['anchor'], 'signature': item['signature'], 'line': trial_line, 'y_delta': 0}
            trial = measure([trial_record])
            record = solve(item, target, original, [line['baseline'] for line in trial], trial_line)
            final = measure([record])
            errors = [abs(a - b['baseline']) for a, b in zip(target, final)]
            if max(errors) > .25:
                raise ValueError('Corrected cover baselines failed the quarter-point verification tolerance.')
            for expected, observed in zip(reference, final):
                if (observed['ink_height'] < expected['ink_height'] - 1.5
                        or not .65 <= observed['ink_area'] / expected['ink_area'] <= 1.4):
                    raise ValueError('Corrected cover lettering failed the visible-ink clipping check.')
            records = [record]
            audit = {'status': 'verified', 'baseline_errors_points': [round(value, 4) for value in errors],
                     'tolerance_points': .25, 'visible_ink_verified': True}
    except (ValueError, OSError, subprocess.TimeoutExpired, pdf_converter.PDFConversionError) as exc:
        audit = {'status': 'preserve-native', 'reason': str(exc)[:300]}
    return records, audit
