"""Default-off finite static siblings; not a general OOXML/VML decoder.

This validator is independent of the one-picture grammar. It does not mutate
XML, decode opaque caches, decide equivalence, select a branch, or grant review.
Every node is consumed by an ordered, class-specific closed scaffold.
"""
from decimal import Decimal
import hashlib
import re

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
WPS = '{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
V = '{urn:schemas-microsoft-com:vml}'
O = '{urn:schemas-microsoft-com:office:office}'
W10 = '{urn:schemas-microsoft-com:office:word}'
W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
WP14 = '{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}'
XML = '{http://www.w3.org/XML/1998/namespace}'
MAX_NODES = 2048
MAX_DEPTH = 32
MAX_TEXT = 8192
MAX_BRANCH_CHARS = 128 * 1024
MAX_CACHE = 64 * 1024
MAX_COORD = 50_000_000
MAX_DEFINITION_PART_NODES = 120_000
MAX_DEFINITION_PART_DEPTH = 64
MAX_DEFINITION_PART_CHARS = 20 * 1024 * 1024
MAX_STANDARD_DEFINITIONS = 8


def _fail(reason):
    # Lazy import avoids a cycle when the capability orchestrator calls us.
    from app.monthly_report_compatibility_view import CompatibilityError
    raise CompatibilityError('Static sibling is not proved: ' + reason)


def _enum(*allowed):
    return lambda value: value in allowed


def _integer(value, low=0, high=MAX_COORD):
    return bool(re.fullmatch(r'-?[0-9]{1,10}', value) and low <= int(value) <= high)


def _positive(value):
    return _integer(value, 1)


def _hex(value):
    return bool(re.fullmatch(r'[0-9A-Fa-f]{8}', value))


def _color(value):
    return bool(re.fullmatch(r'[0-9A-Fa-f]{6}', value))


def _label(value):
    return bool(value) and len(value) <= 128 and not any(ord(c) < 32 for c in value)


def _identity(value):
    return bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.: -]{0,127}', value))


def _plain(value):
    return len(value) <= 4096 and not any(ord(c) < 32 and c not in '\t\n\r' for c in value)


def _cache(value):
    compact = re.sub(r'[\r\n\t ]', '', value)
    return (bool(compact) and len(value) <= MAX_CACHE
            and bool(re.fullmatch(r'(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?', compact)))


def _style(value, kind):
    if len(value) > 4096:
        return False
    relative = 'page' if kind == 'horizontal-textframe' else 'text'
    fixed = {'position': 'absolute', 'visibility': 'visible', 'mso-wrap-style': 'square',
             'mso-position-horizontal': 'absolute', 'mso-position-horizontal-relative': relative,
             'mso-position-vertical': 'absolute', 'mso-position-vertical-relative': relative,
             'mso-height-relative': 'margin', 'v-text-anchor': 'top', 'mso-height-percent': '0'}
    if kind == 'horizontal-textframe':
        fixed.update({'mso-width-percent': '0', 'mso-width-relative': 'margin'})
    lengths = {'margin-left', 'margin-top', 'width', 'height', 'mso-wrap-distance-left',
               'mso-wrap-distance-top', 'mso-wrap-distance-right', 'mso-wrap-distance-bottom'}
    seen = {}
    for pair in value.split(';'):
        if not pair:
            return False
        if pair.count(':') != 1:
            return False
        key, item = pair.split(':')
        if key in seen and (key not in ('mso-width-percent', 'mso-height-percent') or seen[key] != item):
            return False
        seen[key] = item
        if key in fixed:
            if item != fixed[key]: return False
        elif key in lengths:
            if not re.fullmatch(r'-?(?:[0-9]{1,4}(?:\.[0-9]{1,4})?|\.[0-9]{1,4})(?:pt)?', item): return False
            number = Decimal(item.removesuffix('pt'))
            if not -4000 <= number <= 4000: return False
            if key in ('width', 'height') and number <= 0: return False
            if key.startswith('mso-wrap-distance') and number < 0: return False
        elif key == 'z-index':
            if not _integer(item, -(2**31), 2**31 - 1): return False
        else:
            return False
    return set(seen) == set(fixed) | lengths | {'z-index'}


class _Validator:
    def __init__(self, branch):
        self.branch, self.seen, self.caches = branch, set(), []
        self.nodes = []
        size = 0
        for node in branch.iter():
            self.nodes.append(node)
            if len(self.nodes) > MAX_NODES or not isinstance(node.tag, str): _fail('node budget or non-element')
            depth, parent = 0, node
            while parent is not branch:
                parent = parent.getparent(); depth += 1
                if parent is None or depth > MAX_DEPTH: _fail('depth budget')
            if len(node.attrib) > 24: _fail('attribute budget')
            size += len(node.text or '') + len(node.tail or '')
            size += sum(len(key) + len(value) for key, value in node.attrib.items())
            if size > MAX_BRANCH_CHARS: _fail('character budget')
            if (node.tail or '').strip(): _fail('structural tail text')

    def node(self, node, tag, required=None, optional=None, *, text=None):
        if node.tag != tag or node in self.seen: _fail('wrong or repeated scaffold')
        self.seen.add(node)
        required, optional = required or {}, optional or {}
        if set(required) - set(node.attrib) or set(node.attrib) - set(required) - set(optional):
            _fail('unknown or missing attribute')
        for key, value in node.attrib.items():
            if not (required.get(key) or optional.get(key))(value): _fail('invalid static attribute')
        if text is None:
            if (node.text or '').strip(): _fail('structural text')
        elif not text(node.text or ''):
            _fail('invalid text or numeric content')
        return node

    def leaf(self, node, tag, required=None, optional=None, *, text=None):
        self.node(node, tag, required, optional, text=text)
        if len(node): _fail('non-leaf property')

    def sequence(self, node, specification):
        children, offset, result = list(node), 0, {}
        for tag, low, high in specification:
            selected = []
            while offset < len(children) and children[offset].tag == tag:
                selected.append(children[offset]); offset += 1
            if not low <= len(selected) <= high: _fail('ordered child cardinality')
            result[tag] = selected
        if offset != len(children): _fail('unknown or unordered child')
        return result

    def empty_list(self, node, tag):
        self.leaf(node, tag)

    def transform(self, node):
        self.node(node, A+'xfrm')
        children = self.sequence(node, ((A+'off', 1, 1), (A+'ext', 1, 1)))
        self.leaf(children[A+'off'][0], A+'off', {'x': _enum('0'), 'y': _enum('0')})
        extent = children[A+'ext'][0]
        self.leaf(extent, A+'ext', {'cx': _positive, 'cy': _positive})
        return int(extent.get('cx')), int(extent.get('cy'))

    def rectangle(self, node):
        self.node(node, A+'prstGeom', {'prst': _enum('rect')})
        child = self.sequence(node, ((A+'avLst', 1, 1),))[A+'avLst'][0]
        self.empty_list(child, A+'avLst')

    def warp(self, node):
        self.node(node, A+'prstTxWarp', {'prst': _enum('textNoShape')})
        child = self.sequence(node, ((A+'avLst', 1, 1),))[A+'avLst'][0]
        self.empty_list(child, A+'avLst')

    def fill(self, node, *, polygon=False):
        self.node(node, A+'solidFill')
        if len(node) != 1: _fail('solid fill cardinality')
        child = node[0]
        if polygon and child.tag == A+'srgbClr': self.leaf(child, A+'srgbClr', {'val': _color})
        else: self.leaf(child, A+'schemeClr', {'val': _enum('accent2' if polygon else 'lt1')})

    def body(self, node, kind):
        horizontal = {'wrap': _enum('square'), 'rtlCol': _enum('0'),
                      **{name: _enum('0') for name in ('lIns', 'tIns', 'rIns', 'bIns')}}
        vertical = {**horizontal, **{name: _integer for name in ('lIns', 'tIns', 'rIns', 'bIns')},
                    **{name: _enum('0') for name in ('rot', 'spcFirstLastPara', 'spcCol', 'fromWordArt', 'anchorCtr', 'forceAA')},
                    'vertOverflow': _enum('overflow'), 'horzOverflow': _enum('overflow'), 'vert': _enum('vert270'),
                    'numCol': _enum('1'), 'anchor': _enum('t'), 'compatLnSpc': _enum('1')}
        self.node(node, WPS+'bodyPr', vertical if kind == 'vertical-outlined-textframe' else horizontal)
        warp = kind != 'horizontal-textframe'
        children = self.sequence(node, ((A+'prstTxWarp', int(warp), int(warp)), (A+'noAutofit', 1, 1)))
        for child in children[A+'prstTxWarp']: self.warp(child)
        self.leaf(children[A+'noAutofit'][0], A+'noAutofit')

    def outline(self, node):
        attrs = {W14+'w': _enum('9525'), W14+'cap': _enum('rnd'), W14+'cmpd': _enum('sng'), W14+'algn': _enum('ctr')}
        self.node(node, W14+'textOutline', attrs)
        children = self.sequence(node, ((W14+'solidFill', 1, 1), (W14+'prstDash', 1, 1), (W14+'bevel', 1, 1)))
        fill = children[W14+'solidFill'][0]
        self.node(fill, W14+'solidFill')
        color = self.sequence(fill, ((W14+'schemeClr', 1, 1),))[W14+'schemeClr'][0]
        self.leaf(color, W14+'schemeClr', {W14+'val': _enum('bg2')})
        self.leaf(children[W14+'prstDash'][0], W14+'prstDash', {W14+'val': _enum('solid')})
        self.leaf(children[W14+'bevel'][0], W14+'bevel')

    def run_properties(self, node, vertical):
        self.node(node, W+'rPr')
        order = ('rFonts', 'b', 'bCs', 'outline', 'color', 'spacing', 'sz', 'szCs')
        spec = [(W+name, int(vertical or name in ('sz', 'szCs')), 0 if name == 'outline' and not vertical else 1) for name in order]
        spec += [(W14+'textOutline', int(vertical), int(vertical)), (W14+'textFill', int(vertical), int(vertical))]
        children = self.sequence(node, spec)
        for tag, values in children.items():
            for child in values:
                if tag == W+'rFonts': self.leaf(child, tag, {W+'ascii': _enum('Arial Narrow')}, {W+'hAnsi': _enum('Arial Narrow')})
                elif tag in (W+'b', W+'bCs', W+'outline'): self.leaf(child, tag)
                elif tag == W+'color': self.leaf(child, tag, {W+'val': _color}, {W+'themeColor': _enum('background2')})
                elif tag == W+'spacing': self.leaf(child, tag, {W+'val': lambda value: _integer(value, -20, 120)})
                elif tag in (W+'sz', W+'szCs'): self.leaf(child, tag, {W+'val': lambda value: _integer(value, 1, 400)})
                elif tag == W14+'textOutline': self.outline(child)
                else:
                    self.node(child, W14+'textFill')
                    fill = self.sequence(child, ((W14+'noFill', 1, 1),))[W14+'noFill'][0]
                    self.leaf(fill, W14+'noFill')

    def paragraph_properties(self, node, vertical):
        self.node(node, W+'pPr')
        spec = ((W+'jc', 1, 1), (W+'rPr', 1, 1)) if vertical else ((W+'spacing', 1, 1), (W+'ind', 0, 1), (W+'rPr', 1, 1))
        children = self.sequence(node, spec)
        if vertical:
            self.leaf(children[W+'jc'][0], W+'jc', {W+'val': _enum('center')})
        else:
            spacing = children[W+'spacing'][0]
            optional = {W+key: lambda value: _integer(value, 0, 10000) for key in ('before', 'after')}
            optional.update({W+'line': lambda value: _integer(value, 1, 10000), W+'lineRule': _enum('auto', 'exact'), W+'beforeAutospacing': _enum('1')})
            self.leaf(spacing, W+'spacing', optional=optional)
            if (W+'line' in spacing.attrib) != (W+'lineRule' in spacing.attrib): _fail('incomplete paragraph line spacing')
            if W+'beforeAutospacing' in spacing.attrib and W+'before' not in spacing.attrib: _fail('incomplete paragraph before spacing')
            for indent in children[W+'ind']:
                self.leaf(indent, W+'ind', {W+'left': lambda value: _integer(value, 0, 10000)},
                          {W+key: lambda value: _integer(value, 0, 10000) for key in ('right', 'hanging')})
        self.run_properties(children[W+'rPr'][0], vertical)

    def textbox(self, node, kind):
        self.node(node, W+'txbxContent')
        vertical = kind == 'vertical-outlined-textframe'
        paragraphs = self.sequence(node, ((W+'p', 1, 1 if vertical else 16),))[W+'p']
        sequence, run_count, text_size = [], 0, 0
        metadata = {W14+name: _hex for name in ('paraId', 'textId')}
        metadata.update({W+name: _hex for name in ('rsidR', 'rsidRPr', 'rsidRDefault', 'rsidP')})
        for paragraph in paragraphs:
            self.node(paragraph, W+'p', optional=metadata)
            children = self.sequence(paragraph, ((W+'pPr', 1, 1), (W+'r', int(vertical), 1 if vertical else 16)))
            self.paragraph_properties(children[W+'pPr'][0], vertical)
            runs = []
            for run in children[W+'r']:
                run_count += 1
                if run_count > 128: _fail('run budget')
                self.node(run, W+'r')
                pair = self.sequence(run, ((W+'rPr', 1, 1), (W+'t', 1, 1)))
                self.run_properties(pair[W+'rPr'][0], vertical)
                text = pair[W+'t'][0]
                self.leaf(text, W+'t', optional={XML+'space': _enum('preserve')}, text=_plain)
                runs.append(text.text or '')
                text_size += len(text.text or '')
                if text_size > MAX_TEXT: _fail('text budget')
            sequence.append(tuple(runs))
        if not any(text.strip() for paragraph in sequence for text in paragraph): _fail('empty static text frame')
        return tuple(sequence)

    def polygon(self, node):
        self.node(node, A+'custGeom')
        tags = ('avLst', 'gdLst', 'ahLst', 'cxnLst', 'rect', 'pathLst')
        children = self.sequence(node, tuple((A+tag, 1, 1) for tag in tags))
        for tag in tags[:4]: self.empty_list(children[A+tag][0], A+tag)
        self.leaf(children[A+'rect'][0], A+'rect', {key: _enum(key) for key in ('l', 't', 'r', 'b')})
        paths = children[A+'pathLst'][0]
        self.node(paths, A+'pathLst')
        path = self.sequence(paths, ((A+'path', 1, 1),))[A+'path'][0]
        self.node(path, A+'path', {'w': _positive, 'h': _positive})
        self.sequence(path, ((A+'moveTo', 1, 1), (A+'lnTo', 4, 4), (A+'close', 1, 1)))
        points = []
        for command in list(path)[:-1]:
            self.node(command, command.tag)
            point = self.sequence(command, ((A+'pt', 1, 1),))[A+'pt'][0]
            self.leaf(point, A+'pt', {'x': _integer, 'y': _integer})
            points.append((int(point.get('x')), int(point.get('y'))))
        self.leaf(path[-1], A+'close')
        first, zero, bottom, shoulder, close = points
        width, height = int(path.get('w')), int(path.get('h'))
        if (zero != (0, 0) or first[1] != 0 or bottom[0] != 0 or shoulder[1] != bottom[1]
                or close != first or not 0 < shoulder[0] < first[0] <= width
                or not 0 < bottom[1] <= height): _fail('closed polygon topology')

    def modern(self, drawing):
        self.node(drawing, W+'drawing')
        anchor = self.sequence(drawing, ((WP+'anchor', 1, 1),))[WP+'anchor'][0]
        attrs = {name: _integer for name in ('distT', 'distB', 'distL', 'distR')}
        attrs.update({'simplePos': _enum('0'), 'relativeHeight': lambda v: _integer(v, 0, 2**32-1),
                      'behindDoc': _enum('0', '1'), 'locked': _enum('0'), 'layoutInCell': _enum('1'), 'allowOverlap': _enum('1')})
        self.node(anchor, WP+'anchor', attrs, {WP14+name: _hex for name in ('anchorId', 'editId')})
        order = ('simplePos', 'positionH', 'positionV', 'extent', 'effectExtent', 'wrapNone', 'docPr', 'cNvGraphicFramePr')
        children = self.sequence(anchor, tuple((WP+tag, 1, 1) for tag in order) + ((A+'graphic', 1, 1), (WP14+'sizeRelH', 0, 1), (WP14+'sizeRelV', 0, 1)))
        self.leaf(children[WP+'simplePos'][0], WP+'simplePos', {'x': _enum('0'), 'y': _enum('0')})
        for axis, values in (('H', ('page', 'column')), ('V', ('page', 'paragraph'))):
            position = children[WP+'position'+axis][0]
            self.node(position, WP+'position'+axis, {'relativeFrom': _enum(*values)})
            offset = self.sequence(position, ((WP+'posOffset', 1, 1),))[WP+'posOffset'][0]
            self.leaf(offset, WP+'posOffset', text=lambda v: _integer(v, -MAX_COORD))
        extent = children[WP+'extent'][0]
        self.leaf(extent, WP+'extent', {'cx': _positive, 'cy': _positive})
        self.leaf(children[WP+'effectExtent'][0], WP+'effectExtent', {key: _integer for key in ('l', 't', 'r', 'b')})
        self.leaf(children[WP+'wrapNone'][0], WP+'wrapNone')
        self.leaf(children[WP+'docPr'][0], WP+'docPr', {'id': lambda v: _integer(v, 0, 2**32-1), 'name': _label})
        locks = children[WP+'cNvGraphicFramePr'][0]
        self.node(locks, WP+'cNvGraphicFramePr')
        for lock in self.sequence(locks, ((A+'graphicFrameLocks', 0, 1),))[A+'graphicFrameLocks']:
            self.leaf(lock, A+'graphicFrameLocks')
        for axis, percentage in (('H', 'pctWidth'), ('V', 'pctHeight')):
            for size in children[WP14+'sizeRel'+axis]:
                self.node(size, WP14+'sizeRel'+axis, {'relativeFrom': _enum('margin')})
                value = self.sequence(size, ((WP14+percentage, 1, 1),))[WP14+percentage][0]
                self.leaf(value, WP14+percentage, text=_enum('0'))
        graphic = children[A+'graphic'][0]
        self.node(graphic, A+'graphic')
        data = self.sequence(graphic, ((A+'graphicData', 1, 1),))[A+'graphicData'][0]
        self.node(data, A+'graphicData', {'uri': _enum(WPS[1:-1])})
        shape = self.sequence(data, ((WPS+'wsp', 1, 1),))[WPS+'wsp'][0]
        self.node(shape, WPS+'wsp')
        shape_children = self.sequence(shape, ((WPS+'cNvSpPr', 1, 1), (WPS+'spPr', 1, 1), (WPS+'txbx', 0, 1), (WPS+'bodyPr', 1, 1)))
        body = shape_children[WPS+'bodyPr'][0]
        kind = ('vertical-outlined-textframe' if body.get('vert') == 'vert270' else 'horizontal-textframe') if shape_children[WPS+'txbx'] else 'closed-5point-polygon'
        properties = shape_children[WPS+'cNvSpPr'][0]
        self.node(properties, WPS+'cNvSpPr', {'txBox': _enum('1')} if kind != 'closed-5point-polygon' else {})
        for lock in self.sequence(properties, ((A+'spLocks', 0, int(kind == 'horizontal-textframe')),))[A+'spLocks']:
            self.leaf(lock, A+'spLocks')
        geometry = shape_children[WPS+'spPr'][0]
        self.node(geometry, WPS+'spPr')
        polygon, vertical = kind == 'closed-5point-polygon', kind == 'vertical-outlined-textframe'
        geometry_children = self.sequence(geometry, ((A+'xfrm', 1, 1), (A+('custGeom' if polygon else 'prstGeom'), 1, 1), (A+'solidFill', int(polygon or vertical), int(polygon or vertical)), (A+'ln', int(vertical), int(vertical))))
        if self.transform(geometry_children[A+'xfrm'][0]) != (int(extent.get('cx')), int(extent.get('cy'))): _fail('inconsistent static extents')
        if polygon: self.polygon(geometry_children[A+'custGeom'][0])
        else: self.rectangle(geometry_children[A+'prstGeom'][0])
        for fill in geometry_children[A+'solidFill']: self.fill(fill, polygon=polygon)
        for line in geometry_children[A+'ln']:
            self.node(line, A+'ln', {'w': _enum('6350')})
            child = self.sequence(line, ((A+'noFill', 1, 1),))[A+'noFill'][0]
            self.leaf(child, A+'noFill')
        paragraphs = ()
        for textbox in shape_children[WPS+'txbx']:
            self.node(textbox, WPS+'txbx')
            paragraphs = self.textbox(self.sequence(textbox, ((W+'txbxContent', 1, 1),))[W+'txbxContent'][0], kind)
        self.body(body, kind)
        return kind, paragraphs

    def shape_type(self, node):
        self.node(node, V+'shapetype', {'id': _enum('_x0000_t202'), 'coordsize': _enum('21600,21600'), O+'spt': _enum('202'), 'path': _enum('m,l,21600r21600,l21600,xe')}, {W14+'anchorId': _hex})
        children = self.sequence(node, ((V+'stroke', 1, 1), (V+'path', 1, 1)))
        self.leaf(children[V+'stroke'][0], V+'stroke', {'joinstyle': _enum('miter')})
        self.leaf(children[V+'path'][0], V+'path', {'gradientshapeok': _enum('t'), O+'connecttype': _enum('rect')})

    def legacy(self, pict):
        self.node(pict, W+'pict')
        children = self.sequence(pict, ((V+'shapetype', 0, 1), (V+'shape', 1, 1)))
        shape = children[V+'shape'][0]
        textbox = shape.find(V+'textbox')
        kind = ('vertical-outlined-textframe' if textbox is not None and textbox.get('style') is not None else 'horizontal-textframe') if 'path' not in shape.attrib else 'closed-5point-polygon'
        if children[V+'shapetype'] and kind != 'horizontal-textframe': _fail('unneeded shape declaration')
        for definition in children[V+'shapetype']: self.shape_type(definition)
        attrs = {'id': _identity, 'style': lambda value: _style(value, kind), 'stroked': _enum('f')}
        optional = {W14+'anchorId': _hex, O+'spid': _identity, O+'gfxdata': _cache}
        if kind == 'horizontal-textframe': attrs.update({'type': _enum('#_x0000_t202'), 'filled': _enum('f')})
        elif kind == 'vertical-outlined-textframe': attrs.update({'type': _enum('#_x0000_t202'), 'fillcolor': _enum('white [3201]'), 'strokeweight': _enum('.5pt')})
        else:
            attrs.update({'coordsize': lambda v: bool(re.fullmatch(r'[0-9]{1,8},[0-9]{1,8}', v)),
                          'path': lambda v: len(v) <= 128,
                          'fillcolor': lambda v: bool(re.fullmatch(r'#[0-9a-fA-F]{6}(?: \[3205\])?', v))})
        self.node(shape, V+'shape', attrs, optional)
        if O+'gfxdata' in shape.attrib:
            cache = shape.get(O+'gfxdata'); cursor, path = shape, []
            while cursor is not self.branch:
                parent = cursor.getparent(); path.append(parent.index(cursor)); cursor = parent
            self.caches.append({'attribute': O+'gfxdata', 'path': tuple(reversed(path)),
                                'sha256': hashlib.sha256(cache.encode()).hexdigest(), 'encoded_size': len(cache.encode())})
        if kind == 'closed-5point-polygon':
            child = self.sequence(shape, ((V+'path', 1, 1),))[V+'path'][0]
            self.leaf(child, V+'path', {'arrowok': _enum('t')})
            width, height = (int(v) for v in shape.get('coordsize').split(','))
            match = re.fullmatch(r'm([0-9]{1,8}),l,,,([0-9]{1,8})r([0-9]{1,8}),l([0-9]{1,8}),xe', shape.get('path'))
            if not match: _fail('unsupported VML polygon topology')
            first, bottom, shoulder, close = map(int, match.groups())
            if not (0 < shoulder < first == close <= width <= MAX_COORD and 0 < bottom <= height <= MAX_COORD): _fail('invalid VML polygon bounds')
            return kind, ()
        children = self.sequence(shape, ((V+'textbox', 1, 1), (W10+'wrap', 0, int(kind == 'horizontal-textframe'))))
        textbox = children[V+'textbox'][0]
        self.node(textbox, V+'textbox', {'inset': _enum('0,0,0,0')} if kind == 'horizontal-textframe' else {'style': _enum('layout-flow:vertical;mso-layout-flow-alt:bottom-to-top')})
        paragraphs = self.textbox(self.sequence(textbox, ((W+'txbxContent', 1, 1),))[W+'txbxContent'][0], kind)
        for wrap in children[W10+'wrap']:
            self.leaf(wrap, W10+'wrap', {'anchorx': _enum('page'), 'anchory': _enum('page')})
        return kind, paragraphs


def validate_static_definitions(root):
    """Prove the sole allowed inherited VML template in the ORIGINAL part.

    ``type="#_x0000_t202"`` is an ID reference, not an implicit declaration.
    Its declaration can live outside a candidate branch (including a group).
    Scan the entire standalone document part before any branch removal, and
    again after passive closure. A referenced but missing declaration or
    conflicting template fails closed. Repeated declarations are accepted only
    when each independently passes the finite standard grammar and all agree
    exactly except the validated optional w14:anchorId metadata. Every occurrence
    remains separately audited. Other template IDs are outside this function's
    authority; there is no general VML inheritance resolver.

    This contextual check supplements, and does not replace, branch validation
    or whole-part security inspection. It never changes the supplied tree.
    """
    if getattr(root, 'tag', None) != W+'document' or root.getparent() is not None:
        _fail('definition scan requires the original document root')
    definitions, references, count, characters = [], 0, 0, 0
    for node in root.iter():
        count += 1
        if count > MAX_DEFINITION_PART_NODES or not isinstance(node.tag, str):
            _fail('definition part node budget or non-element')
        depth, cursor = 0, node
        while cursor is not root:
            cursor = cursor.getparent(); depth += 1
            if cursor is None or depth > MAX_DEFINITION_PART_DEPTH:
                _fail('definition part depth budget')
        characters += len(node.text or '') + len(node.tail or '')
        characters += sum(len(key) + len(value) for key, value in node.attrib.items())
        if characters > MAX_DEFINITION_PART_CHARS:
            _fail('definition part character budget')
        if node.tag == V+'shape' and node.get('type') == '#_x0000_t202':
            references += 1
        if node.tag.startswith(V) and node.get('id') == '_x0000_t202':
            if node.tag != V+'shapetype':
                _fail('conflicting standard shape template identifier')
            definitions.append(node)
            if len(definitions) > MAX_STANDARD_DEFINITIONS:
                _fail('standard shape template declaration budget')
    if references and not definitions:
        _fail('referenced standard shape template is not declared')
    audits, rendering_structure = [], None
    from app.monthly_report_compatibility_view import _subtree_digest
    for definition in definitions:
        validator = _Validator(definition)
        validator.shape_type(definition)
        if len(validator.seen) != len(validator.nodes):
            _fail('unconsumed shape template markup')
        signature = tuple((node.tag, len(node),
                           tuple(sorted((key, value) for key, value in node.attrib.items()
                                        if not (node is definition and key == W14+'anchorId'))),
                           node.text or '', node.tail or '') for node in definition.iter())
        if rendering_structure is not None and signature != rendering_structure:
            _fail('standard shape template declarations disagree')
        rendering_structure = signature
        path, cursor = [], definition
        while cursor is not root:
            parent = cursor.getparent()
            path.append(parent.index(cursor)); cursor = parent
        audits.append({'path': tuple(reversed(path)),
                       'sha256': _subtree_digest(definition),
                       'node_count': len(validator.nodes)})
    return {'reference_count': references, 'definitions': tuple(audits),
            'node_count': count}


def validate_static_branch(branch):
    """Return class, exact paragraph/run strings, and named opaque-cache audits.

    The caller must still validate wrapper namespace selection, both-branch
    equivalence and text sequence, document-scope ``validate_static_definitions``,
    receipt provenance, and passive closure.
    """
    validator = _Validator(branch)
    if branch.tag == MC+'Choice':
        def requires(value):
            tokens = value.split()
            return len(tokens) == 1 and bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,127}', tokens[0])) and branch.nsmap.get(tokens[0]) == WPS[1:-1]
        validator.node(branch, MC+'Choice', {'Requires': requires})
        drawing = validator.sequence(branch, ((W+'drawing', 1, 1),))[W+'drawing'][0]
        kind, paragraphs = validator.modern(drawing)
    elif branch.tag == MC+'Fallback':
        validator.node(branch, MC+'Fallback')
        pict = validator.sequence(branch, ((W+'pict', 1, 1),))[W+'pict'][0]
        kind, paragraphs = validator.legacy(pict)
    else:
        _fail('not an AlternateContent branch')
    if len(validator.seen) != len(validator.nodes): _fail('unconsumed markup')
    from app.monthly_report_compatibility_view import _subtree_digest
    return {'class': kind, 'paragraph_runs': paragraphs, 'text': ''.join(text for p in paragraphs for text in p),
            'opaque_caches': tuple(validator.caches), 'branch_sha256': _subtree_digest(branch),
            'node_count': len(validator.nodes)}
