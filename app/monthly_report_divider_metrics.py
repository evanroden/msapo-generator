"""Measured static divider typography, for disposable conversion copies only."""
import hashlib
import math
import re
from lxml import etree as E
from app.monthly_report_cover_metrics import NS, W


def validate_records(records):
    if not isinstance(records, list) or len(records) > 32:
        raise ValueError('Unsupported saved divider typography measurements.')
    seen = set()
    for record in records:
        if (not isinstance(record, dict) or set(record) != {'anchor', 'signature', 'line', 'y_delta', 'terminal_tracking'}
                or not isinstance(record['anchor'], str) or not re.fullmatch(r'[0-9A-F]{8}', record['anchor'])
                or record['anchor'] in seen or not isinstance(record['signature'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', record['signature'])
                or (record['line'] is not None and (type(record['line']) is not int or not 180 <= record['line'] <= 720))
                or type(record['y_delta']) not in (int, float) or not math.isfinite(record['y_delta'])
                or abs(record['y_delta']) > 20 or type(record['terminal_tracking']) is not bool):
            raise ValueError('Unsupported saved divider typography measurements.')
        seen.add(record['anchor'])
    return [dict(record) for record in records]


def candidates(root, styles):
    from app.monthly_report_import import _heading, _is_native_divider_background, _text
    result = []
    body = root.find('w:body', NS)
    if body is None or styles is None:
        return result
    # A changed master font/style invalidates old measurements even when an
    # anchor ID is reused. Reference-derived measurements never pick fonts.
    styles_signature = hashlib.sha256(E.tostring(styles, method='c14n')).hexdigest()
    for paragraph in body.findall('w:p', NS):
        recognized = _is_native_divider_background(paragraph, _text(paragraph))
        previous = paragraph.getprevious()
        if (not recognized and previous is not None and previous.tag == W + 'p'
                and not _text(previous).strip() and previous.find('.//w:sectPr', NS) is None):
            recognized = _is_native_divider_background(previous, _text(paragraph))
        if not recognized:
            continue
        for anchor in paragraph.findall('.//wp:anchor', NS):
            try:
                aid = anchor.get('{' + NS['wp14'] + '}anchorId', '')
                shape = anchor.find('.//wps:wsp', NS)
                box = shape.find('wps:txbx/w:txbxContent', NS) if shape is not None else None
                props = shape.find('wps:spPr', NS) if shape is not None else None
                bodypr = shape.find('wps:bodyPr', NS) if shape is not None else None
                pos = anchor.find('wp:positionV/wp:posOffset', NS)
                extent = anchor.find('wp:extent', NS)
                if (not re.fullmatch(r'[0-9A-F]{8}', aid) or box is None or props is None
                        or bodypr is None or pos is None or extent is None
                        or bodypr.find('a:noAutofit', NS) is None
                        or bodypr.get('anchor', 't') != 't'
                        or len(box) not in (1, 2) or any(p.tag != W + 'p' for p in box)):
                    continue
                alternate = next((p for p in anchor.iterancestors()
                                  if p.tag == '{' + NS['mc'] + '}AlternateContent'), None)
                fallback = [] if alternate is None else [p for p in alternate.findall('.//mc:Fallback//v:shape', NS)
                              if p.get('{' + NS['w14'] + '}anchorId') == aid]
                if props.find('a:noFill', NS) is None:
                    fills = [p for p in props if E.QName(p).localname.endswith('Fill')]
                    if fills or len(fallback) != 1 or fallback[0].get('filled') != 'f':
                        continue
                line_shape = props.find('a:ln', NS)
                if line_shape is not None and line_shape.find('a:noFill', NS) is None:
                    colors = line_shape.findall('a:solidFill/*', NS)
                    if (len(colors) != 1 or len(colors[0]) != 1
                            or colors[0][0].tag != '{' + NS['a'] + '}alpha'
                            or colors[0][0].get('val') != '0'):
                        continue
                texts = [' '.join(''.join(p.xpath('.//w:t/text()', namespaces=NS)).split()) for p in box]
                text = ' '.join(texts)
                numeral = len(box) == 1 and re.fullmatch(r'[1-9][0-9]', text) is not None
                title = bool(_heading(text)) and all(
                    p.find('w:pPr/w:pStyle', NS) is not None
                    and p.find('w:pPr/w:pStyle', NS).get(W + 'val') == 'Divider' for p in box)
                if not numeral and not title:
                    continue
                tracking = 0
                if numeral:
                    runs = box[0].findall('w:r', NS)
                    values = []
                    for run in runs:
                        size = run.find('w:rPr/w:sz', NS)
                        spacing = run.find('w:rPr/w:spacing', NS)
                        color = run.find('w:rPr/w:color', NS)
                        if (size is None or spacing is None or color is None
                                or color.get(W + 'val') not in {'D6EF4B', 'D5EE4A', 'D4ED49'}
                                or not 300 <= int(size.get(W + 'val')) <= 500):
                            raise ValueError
                        values.append(int(spacing.get(W + 'val')))
                    if not values or len(set(values)) != 1 or not -600 <= values[0] < 0:
                        continue
                    tracking = -values[0] * 635
                lines = []
                for p in box:
                    spacing = p.find('w:pPr/w:spacing', NS)
                    if spacing is not None and spacing.get(W + 'lineRule', 'auto') != 'auto':
                        raise ValueError
                    lines.append(int(spacing.get(W + 'line', '240')) if spacing is not None else 240)
                if len(set(lines)) != 1:
                    continue
                signature = hashlib.sha256(E.tostring(anchor, method='c14n') + styles_signature.encode()
                                           + b''.join(E.tostring(x, method='c14n') for x in fallback)).hexdigest()
                result.append({'anchor': aid, 'signature': signature, 'texts': texts, 'line': lines[0],
                               'tracking': tracking, 'kind': 'number' if numeral else 'title', 'element': anchor,
                               'fallback': fallback})
            except (ValueError, TypeError, AttributeError):
                continue
    return result if len(result) <= 32 else []


def apply_divider_metrics(root, styles, records):
    records = validate_records(records)
    changed = False
    available = candidates(root, styles) if records else []
    for record in records:
        found = [x for x in available if x['anchor'] == record['anchor'] and x['signature'] == record['signature']]
        if len(found) != 1:
            continue
        item = found[0]
        if ((record['terminal_tracking'] and item['kind'] != 'number')
                or (record['line'] is not None and (item['kind'] != 'title'
                    or not .65 <= record['line'] / item['line'] <= 1.35))):
            continue
        anchor = item['element']
        offset = anchor.find('wp:positionV/wp:posOffset', NS)
        offset.text = str(int(offset.text) + round(record['y_delta'] * 12700))
        if record['terminal_tracking']:
            for extent in [anchor.find('wp:extent', NS), anchor.find('.//wps:spPr/a:xfrm/a:ext', NS)]:
                if extent is not None:
                    extent.set('cx', str(int(extent.get('cx')) + item['tracking']))
        if record['line'] is not None:
            for p in anchor.findall('.//w:txbxContent/w:p', NS):
                pr = p.find('w:pPr', NS)
                if pr is None:
                    pr = E.Element(W + 'pPr'); p.insert(0, pr)
                spacing = pr.find(W + 'spacing')
                if spacing is None:
                    spacing = E.SubElement(pr, W + 'spacing')
                spacing.set(W + 'line', str(record['line'])); spacing.set(W + 'lineRule', 'auto')
        for shape in item['fallback']:
            style = shape.get('style', '')
            for property_name, delta in [('margin-top', record['y_delta']),
                                         ('width', item['tracking'] / 12700 if record['terminal_tracking'] else 0)]:
                match = re.search(r'(?<![-\w])' + property_name + r':([-\d.]+)(pt|in)', style)
                if match and delta:
                    unit = match.group(2)
                    value = float(match.group(1)) + delta / (72 if unit == 'in' else 1)
                    style = style[:match.start()] + f'{property_name}:{value:.6f}{unit}' + style[match.end():]
            shape.set('style', style)
            if record['line'] is not None:
                for p in shape.findall('.//w:txbxContent/w:p', NS):
                    pr = p.find('w:pPr', NS)
                    if pr is None:
                        pr = E.Element(W + 'pPr')
                        p.insert(0, pr)
                    spacing = pr.find(W + 'spacing')
                    if spacing is None:
                        spacing = E.SubElement(pr, W + 'spacing')
                    spacing.set(W + 'line', str(record['line']))
                    spacing.set(W + 'lineRule', 'auto')
        changed = True
    return changed
