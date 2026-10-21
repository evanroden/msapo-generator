"""EXPERIMENTAL, NOT ACTIVATED: deterministic native-rendition derivation.

No caller in production uses this module. It selects an explicitly supported
Word rendition, not equivalent pixels. Original inspection and every original
ID remain immutable audit data; a separate occurrence map binds the rendition.
A receipt is evidence only: consumers must rederive it from the original.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from app.monthly_report_import import ImportError, MAX_DOCX_BYTES, _package, _relations, inspect_docx
from app.monthly_report_native_design import A, MC, PIC, R, W, WP, WPS, equivalent_native_alternatives
from app.monthly_report_native_package import _xml, passive_docx

V = '{urn:schemas-microsoft-com:vml}'
O = '{urn:schemas-microsoft-com:office:office}'
W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
WP14 = '{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}'
A14 = '{http://schemas.microsoft.com/office/drawing/2010/main}'
XML = '{http://www.w3.org/XML/1998/namespace}'
POLICY = 'closed-native-wps-rendition-v3-experimental'
CAPABILITY_PROFILE = 'closed-wps-native-furniture'
CAPABILITY_VERSION = 3
IMAGE_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'
DPI_URI = '{28A0092B-C50C-407E-A947-70E740481C1C}'
MAX_COORD = 50_000_000
# Narrow prototype envelope, not the importer's much larger general limits.
MAX_VIEW_SOURCE_BYTES = 24 * 1024 * 1024
MAX_VIEW_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_VIEW_XML_BYTES = 20 * 1024 * 1024
MAX_VIEW_MEDIA_BYTES = 16 * 1024 * 1024
MAX_VIEW_XML_NODES = 120_000


def _view_budget(archive):
    infos = archive.infolist()
    if len(infos) > 512 or sum(i.file_size for i in infos) > MAX_VIEW_EXPANDED_BYTES:
        _fail('capability package expansion budget')
    xml = [i for i in infos if i.filename.endswith(('.xml', '.rels'))]
    if sum(i.file_size for i in xml) > MAX_VIEW_XML_BYTES:
        _fail('capability XML byte budget')
    if sum(i.file_size for i in infos if i.filename.startswith('word/media/')) > MAX_VIEW_MEDIA_BYTES:
        _fail('capability cumulative media byte budget')
    from defusedxml import ElementTree as safe_xml
    nodes = 0
    for info in xml:
        depth = 0
        with archive.open(info) as stream:
            for event, element in safe_xml.iterparse(stream, events=('start','end'), forbid_dtd=True):
                if event == 'start':
                    nodes += 1; depth += 1
                    if nodes > MAX_VIEW_XML_NODES or depth > 64:
                        _fail('capability XML complexity budget')
                else:
                    depth -= 1; element.clear()


class CompatibilityError(ImportError):
    pass


def _fail(message):
    raise CompatibilityError('Native rendition is not proved: ' + message)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()


def _node_path(root, node):
    """Namespace-independent, root-relative child-index occurrence path."""
    steps = []
    while node is not root:
        parent = node.getparent()
        if parent is None: _fail('occurrence outside document root')
        steps.append(parent.index(node)); node = parent
    return tuple(reversed(steps))


def _path_node(root, steps):
    if not isinstance(steps, (tuple, list)) or len(steps) > 64:
        _fail('invalid occurrence path')
    node = root
    for index in steps:
        if type(index) is not int or not 0 <= index < len(node):
            _fail('missing occurrence path')
        node = node[index]
    return node


def _subtree_digest(node):
    return _hash(_canonical([(n.tag, len(n), sorted(n.attrib.items()), n.text or '', n.tail or '') for n in node.iter()]))


def _zip(parts):
    """Pin metadata/order; no clock-dependent receipt or compressed output."""
    stream = BytesIO()
    with ZipFile(stream, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name, raw in sorted(parts.items()):
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, raw, compress_type=ZIP_DEFLATED, compresslevel=6)
    return stream.getvalue()


def _integer(value, low=-MAX_COORD, high=MAX_COORD):
    return bool(re.fullmatch(r'-?\d{1,10}', value or '') and low <= int(value) <= high)


def _enum(*values):
    return lambda value: value in values


def _text(value):
    return len(value) <= 4096 and not any(ord(c) < 32 and c not in '\t\n\r' for c in value)


def _identity(value):
    return bool(re.fullmatch(r'[A-Za-z_][\w.:-]{0,127}', value))


def _hex(value):
    return bool(re.fullmatch(r'[0-9A-Fa-f]{8}', value))


BOOLEAN = _enum('0', '1', 'true', 'false')
NONNEGATIVE = lambda value: _integer(value, 0)
POSITIVE = lambda value: _integer(value, 1)
# Every supported element has an explicit attribute/value whitelist. Unknown
# nonnamespaced attributes are no safer than unknown namespaced attributes.
ATTRS = {}
CHILDREN = {}


def _rule(namespace, local, attributes=None, children=()):
    ATTRS[namespace + local] = attributes or {}
    CHILDREN[namespace + local] = set(children)


for tag in ('b', 'bCs', 'noProof'):
    _rule(W, tag, {W + 'val': BOOLEAN})
for tag, values in [('jc', ('center',)), ('highlight', ('yellow',))]:
    _rule(W, tag, {W + 'val': _enum(*values)})
_rule(W, 'p', {**{W + key: _hex for key in ('rsidR', 'rsidRDefault', 'rsidP', 'rsidRPr')},
               W14 + 'paraId': _hex, W14 + 'textId': _hex}, (W+'pPr', W+'r'))
_rule(W, 'pPr', children=(W+'jc', W+'rPr'))
_rule(W, 'r', children=(W+'rPr', W+'t', W+'drawing'))
_rule(W, 'rPr', children=tuple(W+x for x in ('b', 'bCs', 'noProof', 'highlight')))
_rule(W, 't', {XML+'space': _enum('preserve', 'default')})
_rule(W, 'drawing', children=(WP+'inline', WP+'anchor'))
_rule(W, 'pict', children=(V+'shape',))
_rule(W, 'txbxContent', children=(W+'p',))
_rule(MC, 'Choice', {'Requires': lambda value: bool(value) and len(value) < 512}, (W+'drawing', W+'pict'))
_rule(MC, 'Fallback', children=(W+'drawing', W+'pict'))
_common_position = {key: NONNEGATIVE for key in ('distT', 'distB', 'distL', 'distR')}
_common_position.update({WP14+'anchorId': _hex, WP14+'editId': _hex})
_wp_children = tuple(WP+x for x in ('extent', 'effectExtent', 'docPr', 'cNvGraphicFramePr')) + (A+'graphic',)
_rule(WP, 'inline', _common_position, _wp_children)
_rule(WP, 'anchor', {**_common_position, **{key: BOOLEAN for key in ('simplePos', 'behindDoc', 'locked', 'layoutInCell', 'allowOverlap')},
    'relativeHeight': lambda value: _integer(value, 0, 2**32-1)}, _wp_children + tuple(WP+x for x in ('simplePos', 'positionH', 'positionV', 'wrapNone')) + (WP14+'sizeRelH', WP14+'sizeRelV'))
_rule(WP, 'simplePos', {'x': _integer, 'y': _integer})
_rule(WP, 'positionH', {'relativeFrom': _enum('column')}, (WP+'posOffset',))
_rule(WP, 'positionV', {'relativeFrom': _enum('paragraph')}, (WP+'posOffset',))
_rule(WP, 'posOffset')
_rule(WP, 'extent', {'cx': POSITIVE, 'cy': POSITIVE})
_rule(WP, 'effectExtent', {key: NONNEGATIVE for key in ('l', 't', 'r', 'b')})
_rule(WP, 'wrapNone')
_rule(WP, 'docPr', {'id': lambda value: _integer(value, 0, 2**32-1), 'name': _text, 'descr': _text, 'title': _text})
_rule(WP, 'cNvGraphicFramePr', children=(A+'graphicFrameLocks',))
for axis in ('H', 'V'):
    _rule(WP14, 'sizeRel'+axis, {'relativeFrom': _enum('margin')}, (WP14 + ('pctWidth' if axis == 'H' else 'pctHeight'),))
for tag in ('pctWidth', 'pctHeight'):
    _rule(WP14, tag)
_rule(A, 'graphic', children=(A+'graphicData',))
_rule(A, 'graphicData', {'uri': _enum(WPS[1:-1], PIC[1:-1])}, (WPS+'wsp', PIC+'pic'))
_rule(A, 'graphicFrameLocks', {'noChangeAspect': BOOLEAN})
_rule(A, 'picLocks', {'noChangeAspect': BOOLEAN, 'noChangeArrowheads': BOOLEAN})
_rule(A, 'xfrm', children=(A+'off', A+'ext'))
_rule(A, 'off', {'x': _integer, 'y': _integer})
_rule(A, 'ext', {'cx': POSITIVE, 'cy': POSITIVE, 'uri': _enum(DPI_URI)}, (A14+'useLocalDpi',))
_rule(A, 'prstGeom', {'prst': _enum('rect')}, (A+'avLst',))
_rule(A, 'avLst')
for tag in ('noFill', 'noAutofit', 'fillRect'):
    _rule(A, tag)
_rule(A, 'solidFill', children=(A+'schemeClr', A+'prstClr'))
_rule(A, 'schemeClr', {'val': _enum('lt1')})
_rule(A, 'prstClr', {'val': _enum('black')})
_rule(A, 'ln', {'w': NONNEGATIVE}, (A+'solidFill', A+'noFill'))
_rule(A, 'prstTxWarp', {'prst': _enum('textNoShape')}, (A+'avLst',))
_rule(A, 'blip', {R+'embed': _identity}, (A+'extLst',))
_rule(A, 'extLst', children=(A+'ext',))
_rule(A14, 'useLocalDpi', {'val': _enum('0', '1')})
_rule(A, 'srcRect', {key: lambda value: _integer(value, 0, 100_000) for key in ('l', 't', 'r', 'b')})
_rule(A, 'stretch', children=(A+'fillRect',))
_rule(PIC, 'pic', children=(PIC+'nvPicPr', PIC+'blipFill', PIC+'spPr'))
_rule(PIC, 'nvPicPr', children=(PIC+'cNvPr', PIC+'cNvPicPr'))
_rule(PIC, 'cNvPr', ATTRS[WP+'docPr'])
_rule(PIC, 'cNvPicPr', children=(A+'picLocks',))
_rule(PIC, 'blipFill', children=(A+'blip', A+'srcRect', A+'stretch'))
_rule(PIC, 'spPr', {'bwMode': _enum('auto')}, (A+'xfrm', A+'prstGeom', A+'noFill', A+'ln'))
_rule(WPS, 'wsp', children=(WPS+'cNvSpPr', WPS+'spPr', WPS+'txbx', WPS+'bodyPr'))
_rule(WPS, 'cNvSpPr', {'txBox': _enum('1')})
_rule(WPS, 'spPr', children=(A+'xfrm', A+'prstGeom', A+'noFill', A+'solidFill', A+'ln'))
_rule(WPS, 'txbx', children=(W+'txbxContent',))
_body = {key: _enum('0') for key in ('rot', 'spcFirstLastPara', 'spcCol', 'rtlCol', 'fromWordArt', 'anchorCtr', 'forceAA')}
_body.update({key: NONNEGATIVE for key in ('lIns', 'tIns', 'rIns', 'bIns')})
_body.update({'vertOverflow': _enum('overflow'), 'horzOverflow': _enum('overflow'), 'vert': _enum('horz'),
              'wrap': _enum('square'), 'numCol': _enum('1'), 'anchor': _enum('t'), 'compatLnSpc': _enum('1')})
_rule(WPS, 'bodyPr', _body, (A+'prstTxWarp', A+'noAutofit'))


def _style(value):
    """Closed VML textbox style; no CSS URLs, expressions or arbitrary properties."""
    if len(value) > 4096:
        return False
    fixed = {'position': {'absolute'}, 'visibility': {'visible'}, 'mso-wrap-style': {'square'},
             'mso-position-horizontal': {'absolute'}, 'mso-position-horizontal-relative': {'text'},
             'mso-position-vertical': {'absolute'}, 'mso-position-vertical-relative': {'text'},
             'mso-width-relative': {'margin'}, 'mso-height-relative': {'margin'}, 'v-text-anchor': {'top'}}
    lengths = {'margin-left', 'margin-top', 'width', 'height', 'mso-wrap-distance-left',
               'mso-wrap-distance-right', 'mso-wrap-distance-top', 'mso-wrap-distance-bottom'}
    seen = {}
    for pair in value.split(';'):
        if not pair:
            continue
        if pair.count(':') != 1:
            return False
        key, val = pair.split(':')
        if key in seen and seen[key] != val:
            return False
        seen[key] = val
        if key in fixed:
            if val not in fixed[key]: return False
        elif key in lengths:
            if not re.fullmatch(r'-?(?:\d{1,4}(?:\.\d{1,4})?|\.\d{1,4})(?:pt)?', val): return False
            numeric = float(val.removesuffix('pt'))
            if not -4000 <= numeric <= 4000 or (key in ('width', 'height') and numeric <= 0): return False
        elif key == 'z-index':
            if not _integer(val, 0, 2**32-1): return False
        elif key in ('mso-width-percent', 'mso-height-percent'):
            if val != '0': return False
        else:
            return False
    return {'position', 'width', 'height'} <= seen.keys()


_rule(V, 'shape', {'id': lambda value: bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.: -]{0,127}', value)), 'type': _enum('#_x0000_t202'), 'style': _style,
    W14+'anchorId': _hex, O+'spid': _identity,
    O+'gfxdata': lambda value: len(value) <= 64*1024 and bool(re.fullmatch(r'[A-Za-z0-9+/=\r\n\t ]+', value)),
    'fillcolor': _enum('white [3201]'), 'strokeweight': _enum('.5pt')}, (V+'textbox',))
_rule(V, 'textbox', children=(W+'txbxContent',))


def _exact_children(node, required, optional=()):
    tags = [n.tag for n in node]
    if any(tags.count(tag) != 1 for tag in required) or any(tags.count(tag) > 1 for tag in optional):
        _fail('missing or duplicate structural child')
    if set(tags) - set(required) - set(optional):
        _fail('unexpected structural child')


def _scaffold(node, uri):
    for tag in (A+'graphicData', A+'graphic', (WP+'inline', WP+'anchor'), W+'drawing'):
        node = node.getparent()
        if node is None or node.tag not in (tag if isinstance(tag, tuple) else (tag,)):
            _fail('picture/frame scaffold')
        if node.tag == A+'graphicData' and node.get('uri') != uri:
            _fail('graphicData URI')
    return node


def _branch(branch, relations, archive):
    nodes = list(branch.iter())
    if len(nodes) > 2048:
        _fail('branch node budget')
    opaque = []
    for node in nodes:
        if node.tag not in ATTRS:
            _fail('unknown or active element')
        if (node.tail or '').strip(): _fail('structural tail text')
        for key, value in node.attrib.items():
            validator = ATTRS[node.tag].get(key)
            if validator is None or not validator(value): _fail('unknown or invalid attribute')
            if key == O+'gfxdata': opaque.append({'attribute':key, 'path':_node_path(branch,node),
                'sha256':_hash(value.encode()), 'encoded_size':len(value)})
        if any(child.tag not in CHILDREN[node.tag] for child in node): _fail('invalid child scaffold')
        repeatable = {W+'txbxContent': {W+'p'}, W+'p': {W+'r'}, W+'r': {W+'t', W+'drawing'}}.get(node.tag, set())
        child_tags = [child.tag for child in node]
        if any(child_tags.count(tag) > 1 for tag in set(child_tags) - repeatable):
            _fail('duplicate structural/property child')
        if node.tag not in (W+'t', WP+'posOffset', WP14+'pctWidth', WP14+'pctHeight') and (node.text or '').strip():
            _fail('structural text')
        if node.tag == W+'t' and not _text(node.text or ''): _fail('text budget')
        if node.tag == WP+'posOffset' and not _integer(node.text or ''): _fail('position offset')
        if node.tag in (WP14+'pctWidth', WP14+'pctHeight') and (node.text or '') != '0': _fail('relative size')
        if node.tag in (W+'drawing', W+'pict', A+'graphic', A+'graphicData', WPS+'txbx', V+'textbox', A+'solidFill', A+'stretch', WP+'positionH', WP+'positionV', WP14+'sizeRelH', WP14+'sizeRelV') and len(node) != 1:
            _fail('non-single structural container')
        if node.tag in (WP+'inline', WP+'anchor'):
            _exact_children(node, (WP+'extent', A+'graphic'), CHILDREN[node.tag] - {WP+'extent', A+'graphic'})
            if set(node.find(WP+'extent').attrib) != {'cx','cy'}: _fail('incomplete extent')
        if node.tag == A+'xfrm':
            _exact_children(node, (A+'off', A+'ext'))
            if set(node[0].attrib) != {'x','y'} or set(node[1].attrib) != {'cx','cy'}: _fail('incomplete transform')
        if node.tag == A+'graphicData':
            expected = WPS+'wsp' if node.get('uri') == WPS[1:-1] else PIC+'pic'
            if node[0].tag != expected: _fail('graphicData payload')
        if node.tag == PIC+'pic': _exact_children(node, (PIC+'nvPicPr', PIC+'blipFill', PIC+'spPr'))
        if node.tag == PIC+'nvPicPr': _exact_children(node, (PIC+'cNvPr', PIC+'cNvPicPr'))
        if node.tag == PIC+'blipFill': _exact_children(node, (A+'blip', A+'stretch'), (A+'srcRect',))
        if node.tag == A+'srcRect' and (int(node.get('l','0')) + int(node.get('r','0')) >= 100_000 or
                                       int(node.get('t','0')) + int(node.get('b','0')) >= 100_000):
            _fail('empty or inverted picture crop')
        if node.tag in (WPS+'spPr', PIC+'spPr'):
            _exact_children(node, (A+'prstGeom',), CHILDREN[node.tag] - {A+'prstGeom'})
            if node.find(A+'prstGeom').get('prst') != 'rect': _fail('nonrectangular geometry')
        if node.tag == WPS+'wsp': _exact_children(node, (WPS+'cNvSpPr', WPS+'spPr', WPS+'txbx', WPS+'bodyPr'))
        if node.tag in (W+'pPr', W+'rPr', WPS+'bodyPr', A+'prstGeom', A+'prstTxWarp', A+'blip'):
            _exact_children(node, (), CHILDREN[node.tag])
        if node.find(A+'solidFill') is not None and node.find(A+'noFill') is not None:
            _fail('competing fills')
        if node.tag == A+'extLst':
            if (len(node) != 1 or node[0].tag != A+'ext' or dict(node[0].attrib) != {'uri': DPI_URI}
                    or len(node[0]) != 1 or node[0][0].tag != A14+'useLocalDpi'
                    or set(node[0][0].attrib) != {'val'}): _fail('unknown image extension')
        if node.tag == A+'ext' and node.getparent().tag != A+'extLst' and (set(node.attrib) != {'cx', 'cy'} or len(node)):
            _fail('invalid extent variant')
        for property_tag in (W+'pPr', W+'rPr'):
            if sum(child.tag == property_tag for child in node) > 1:
                _fail('duplicate Word property container')
    if len(branch) != 1: _fail('multiple branch roots')
    frames = [n for n in nodes if n.tag in (WPS+'wsp', V+'shape')]
    pictures = [n for n in nodes if n.tag == PIC+'pic']
    blips = [n for n in nodes if n.tag == A+'blip']
    if len(frames) != 1 or len(pictures) != 1 or len(blips) != 1: _fail('frame/picture occurrence count')
    frame, pic, blip = frames[0], pictures[0], blips[0]
    if frame.tag == WPS+'wsp': _scaffold(frame, WPS[1:-1])
    elif frame.get('type') != '#_x0000_t202': _fail('unsupported legacy frame')
    box = frame.find((WPS+'txbx/' if frame.tag == WPS+'wsp' else V+'textbox/') + W+'txbxContent')
    if box is None or len(list(frame.iter(W+'txbxContent'))) != 1: _fail('textbox ownership')
    drawing = _scaffold(pic, PIC[1:-1])
    run = drawing.getparent(); paragraph = run.getparent()
    if run.tag != W+'r' or paragraph.tag != W+'p' or paragraph.getparent() is not box: _fail('picture ownership')
    text = ''.join(n.text or '' for n in nodes if n.tag == W+'t')
    if text not in ('', 'INSERT CLIENT LOGO'): _fail('non-furniture textbox text')
    from app.monthly_report_import import _logo_label_role
    labels = {_logo_label_role(n.get(k, '')) for n in nodes for k in ('descr', 'title')} - {''}
    if labels or any(n.get('alt') for n in nodes): _fail('competing descriptor identity')
    return {'text':text, **_validate_picture_resource(blip, relations, archive),
            'branch_sha256':_subtree_digest(branch), 'node_count':len(nodes), 'opaque_caches':opaque}


def _validate_picture_resource(blip, relations, archive):
    """The same bounded passive local image check for each closed occurrence."""
    rid = blip.get(R+'embed')
    target, kind = relations.get(rid, ('', ''))
    if not target.startswith('word/media/') or kind != IMAGE_REL or target not in archive.namelist():
        _fail('nonlocal or missing image')
    if archive.getinfo(target).file_size > 30*1024*1024 or Path(target).suffix.lower() not in ('.png','.jpg','.jpeg'):
        _fail('unsupported or oversized image')
    raw = archive.read(target)
    # Existing bounded header/format validation, never decoded-pixel proof.
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG') or image.width*image.height > 25_000_000:
                _fail('image format/pixel budget')
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise CompatibilityError('Invalid branch image') from exc
    return {'media_part':target, 'media_sha256':_hash(raw), 'media_size':len(raw)}


def _selection(wrapper):
    """Resolve tokens by inherited namespace URI, never by prefix spelling."""
    branches = list(wrapper)
    if [n.tag for n in branches] != [MC+'Choice', MC+'Fallback'] or wrapper.attrib:
        _fail('v1 requires exactly one Choice and one Fallback')
    for ancestor in (wrapper, *wrapper.iterancestors()):
        for key, value in ancestor.attrib.items():
            if not key.startswith(MC): continue
            if ancestor.getparent() is None and key == MC+'Ignorable':
                if any(token not in ancestor.nsmap for token in value.split()): _fail('unbound root Ignorable')
            else: _fail('ancestor compatibility override')
    choice = branches[0]
    tokens = choice.get('Requires','').split()
    if not tokens or len(set(tokens)) != len(tokens) or any(not re.fullmatch(r'[A-Za-z_][\w.-]*', x) for x in tokens):
        _fail('malformed Requires')
    uris = [choice.nsmap.get(token) for token in tokens]
    if any(uri is None for uri in uris): _fail('unbound Requires')
    if not all(uri == WPS[1:-1] for uri in uris) or len(uris) != 1:
        _fail('no fully supported v1 Choice')
    # The first supported branch is definitive: validation may reject it but
    # must never fall through to a later easier branch or the Fallback.
    return choice, tuple(uris)


@dataclass(frozen=True)
class OccurrenceBinding:
    original_id: str
    rendition_id: str | None
    status: str
    original_section: str = ""
    rendition_section: str = ""


@dataclass(frozen=True)
class CompatibilityView:
    original_inspection: object
    rendition_inspection: object
    rendition_bytes: bytes
    bindings: tuple[OccurrenceBinding, ...]
    receipt_bytes: bytes

    @property
    def receipt_sha256(self):
        return _hash(self.receipt_bytes)


def derive_compatibility_view(original_bytes):
    """Pure default-off derivation; no original or persistent state is written."""
    if not isinstance(original_bytes, bytes) or len(original_bytes) > MAX_VIEW_SOURCE_BYTES:
        _fail('source byte budget/type')
    with TemporaryDirectory(prefix='native-view-') as temporary:
        source = Path(temporary)/'original.docx'; source.write_bytes(original_bytes)
        with _package(source) as budget_archive:
            _view_budget(budget_archive)
            # Coarse raw discovery never supplies eligibility: it only locates
            # possible picture-frame units for complete rejection/validation
            # BEFORE the inspector can normalize revisions. Every later
            # promoted candidate must match one of these raw source proofs.
            raw_root = _xml(budget_archive.read('word/document.xml'))
            from app.monthly_report_compatibility_unit import validate_unit
            from app.monthly_report_static_siblings import validate_static_definitions
            original_static_definitions = validate_static_definitions(raw_root)
            raw_relations = _relations(budget_archive, 'word/document.xml')
            raw_unit_proofs = {}
            raw_section = 1
            for position, raw_unit in enumerate(raw_root.find(W+'body'), 1):
                possible = raw_section <= 2 and any(
                    shape.find(WPS+'txbx') is not None and len(list(shape.iter(PIC+'pic'))) == 1
                    for wrapper in raw_unit.iter(MC+'AlternateContent') for shape in wrapper.iter(WPS+'wsp'))
                if possible:
                    unit_audit = validate_unit(raw_unit, raw_relations, budget_archive)
                    raw_unit_proofs[position] = {'position':position, 'word_section':raw_section,
                        'raw_subtree_sha256':_subtree_digest(raw_unit), 'closure':unit_audit}
                if raw_unit.find('.//'+W+'sectPr') is not None:
                    raw_section += 1
            del raw_root, raw_relations
        original = inspect_docx(source)
        candidates = [i for i in original.items if i.note.startswith('Alternate Word representations')]
        if not candidates or any(i.part != 'word/document.xml' or i.word_section not in (1,2) or i.section not in ('','cover') for i in candidates):
            _fail('no eligible cover/contents furniture')
        resolutions = []
        static_resolutions = []
        selected_drawings = []
        with _package(source) as archive:
            relations = _relations(archive, 'word/document.xml')
            parts = {name: archive.read(name) for name in archive.namelist()}
            root = _xml(parts['word/document.xml']); body = root.find(W+'body')
            from lxml import etree
            original_wrappers = {node: (root.getroottree().getpath(node), _hash(etree.tostring(node)))
                                 for node in root.iter(MC+'AlternateContent')}
            used_original_ids = {value for node in root.iter() for key, value in node.attrib.items() if key.startswith(R)}
            aliases = defaultdict(set)
            for rid, (target, kind) in relations.items():
                if target.startswith(('word/header', 'word/footer')):
                    if kind not in (R[1:-1] + '/header', R[1:-1] + '/footer'):
                        _fail('ambiguous chrome relationship kind')
                    aliases[target].add(rid)
            archival_chrome = {target for target, rids in aliases.items() if not rids.intersection(used_original_ids)}
            for item in candidates:
                unit = body[item.position-1]
                proof = raw_unit_proofs.get(item.position)
                if (proof is None or proof['word_section'] != item.word_section
                        or proof['raw_subtree_sha256'] != _subtree_digest(unit)):
                    _fail('candidate does not match a prevalidated raw unit anchor')
                wrappers = list(unit.iter(MC+'AlternateContent'))
                resolved = 0
                for index, wrapper in enumerate(wrappers):
                    def identity(rid):
                        target, kind = relations.get(rid, ('',''))
                        if not target.startswith('word/media/') or kind != IMAGE_REL or target not in parts:
                            return None
                        return _hash(parts[target])
                    # A wrapper alone isn't found by the existing descendant
                    # check; retain a harmless parent for the unchanged guard.
                    from lxml import etree
                    holder = etree.Element(W+'r'); holder.append(deepcopy(wrapper))
                    # Every branch of every wrapper in a promoted unit is
                    # validated, selected and audited. Equality is not a skip.
                    choice, requires = _selection(wrapper)
                    is_static = not any(list(branch.iter(A+'blip')) for branch in wrapper)
                    if is_static:
                        from app.monthly_report_static_siblings import validate_static_branch
                        records = [validate_static_branch(branch) for branch in wrapper]
                        if (records[0]['class'] != records[1]['class']
                                or records[0]['paragraph_runs'] != records[1]['paragraph_runs']
                                or not equivalent_native_alternatives(holder, identity)):
                            _fail('static sibling content disagreement')
                    else:
                        records = [_branch(branch, relations, archive) for branch in wrapper]
                        if records[0]['text'] != records[1]['text']: _fail('branch text disagreement')
                        if item.word_section == 1 and records[0]['text'] != 'INSERT CLIENT LOGO': _fail('cover label missing')
                        if item.word_section == 2 and records[0]['text'] != '': _fail('contents not empty furniture')
                    path, wrapper_digest = original_wrappers[wrapper]
                    record = {'original_item_id':item.id, 'part':item.part, 'position':item.position,
                        'wrapper_index':index, 'wrapper_path':path, 'wrapper_sha256':wrapper_digest,
                        'requires_uris':requires, 'selected_branch':0, 'branches':records}
                    (static_resolutions if is_static else resolutions).append(record)
                    parent = wrapper.getparent(); at = parent.index(wrapper)
                    for child in list(choice):
                        selected_child = deepcopy(child)
                        parent.insert(at, selected_child); at += 1
                        selected_drawings.append((record, selected_child, is_static))
                    parent.remove(wrapper); resolved += 1
                if not resolved: _fail('unresolved candidate unit')
            from lxml import etree
            for record, drawing, is_static in selected_drawings:
                pictures = list(drawing.iter(A+'blip'))
                if len(pictures) != (0 if is_static else 1): _fail('selected picture occurrence changed')
                record['selected_drawing_path'] = _node_path(root, drawing)
                if not is_static:
                    record['selected_picture_path'] = _node_path(root, pictures[0])
                record['selected_drawing_sha256'] = _subtree_digest(drawing)
            parts['word/document.xml'] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
        if not resolutions: _fail('no picture-frame resolution in bounded recovery scope')
        disposable = Path(temporary)/'selected.docx'; disposable.write_bytes(_zip(parts))
        del parts, root, body, original_wrappers, unit, wrappers, wrapper, holder, choice, parent, child, selected_child, selected_drawings, drawing, pictures
        passive = passive_docx(disposable)
        with ZipFile(BytesIO(passive)) as archive:
            checked_root = _xml(archive.read('word/document.xml'))
            rendition_static_definitions = validate_static_definitions(checked_root)
            for record in (*resolutions, *static_resolutions):
                found = _path_node(checked_root, record['selected_drawing_path'])
                if _subtree_digest(found) != record['selected_drawing_sha256']:
                    _fail('selected geometry/markup changed during passive closure')
                if 'selected_picture_path' in record:
                    picture = _path_node(checked_root, record['selected_picture_path'])
                    if picture not in set(found.iter()) or picture.tag != A+'blip':
                        _fail('selected picture path changed during passive closure')
            del checked_root, found, picture
            rendition_bytes = _zip({name:archive.read(name) for name in archive.namelist()})
        derivative = Path(temporary)/'rendition.docx'; derivative.write_bytes(rendition_bytes)
        rendition = inspect_docx(derivative)
        if any(i.note.startswith('Alternate Word representations') for i in rendition.items): _fail('unresolved derivative')
        bindings = _bind(original, rendition, {i.id for i in candidates}, archival_chrome)
        from app.monthly_report_revision_view import VERSION as revision_policy_version
        receipt = {'schema':1, 'policy':POLICY, 'capability_uris':[WPS[1:-1]],
            'capability_profile':CAPABILITY_PROFILE, 'capability_version':CAPABILITY_VERSION,
            'revision_policy_version':revision_policy_version,
            'applied_revision_view_version':original.revision_view_version,
            'original_sha256':original.sha256, 'original_size':len(original_bytes),
            'rendition_sha256':rendition.sha256, 'rendition_size':len(rendition_bytes),
            'static_definitions':{'original':original_static_definitions, 'rendition':rendition_static_definitions},
            'raw_units':[raw_unit_proofs[p] for p in sorted({i.position for i in candidates})],
            'resolutions':resolutions, 'static_resolutions':static_resolutions, 'archived_unreferenced_chrome':sorted(archival_chrome),
            'bindings':[asdict(b) for b in bindings]}
        return CompatibilityView(original, rendition, rendition_bytes, bindings, _canonical(receipt))


def _bind(original, rendition, candidates, archival_chrome=()):
    """Keep every audit ID, including removed unused assets and rejected units."""
    buckets = defaultdict(list)
    scopes = {(i.part, i.position, i.word_section) for i in original.items if i.id in candidates}
    for scope in scopes:
        matches = [i for i in rendition.items if (i.part, i.position, i.word_section) == scope and i.kind == 'native_layout']
        if len(matches) != 1 or matches[0].note not in (
                'Native cover title and artwork', 'Native contents text frames', 'Native contents notice and artwork'):
            _fail('ambiguous candidate native furniture classification')
    def signature(item, *, original_side=False):
        data = asdict(item); data.pop('id')
        if item.part.startswith(('word/header', 'word/footer')):
            data.pop('section')  # Ambient parser state, never chrome routing evidence.
        candidate = (item.id in candidates if original_side else
                     item.kind == 'native_layout' and (item.part, item.position, item.word_section) in scopes)
        if candidate:
            data['kind'], data['note'] = 'native-furniture', ''
        return _canonical(data)
    for item in rendition.items:
        buckets[signature(item)].append(item)
    bindings = []
    for item in original.items:
        matches = buckets[signature(item, original_side=True)]
        if matches:
            target = matches.pop(0)
            if item.id in candidates and target.kind != 'native_layout': _fail('candidate not recognized as native furniture')
            bindings.append(OccurrenceBinding(item.id, target.id, 'resolved' if item.id in candidates else 'retained',
                                                item.section, target.section))
        elif item.position == 0 or item.part in archival_chrome:
            bindings.append(OccurrenceBinding(item.id, None, 'archived-only', item.section, ''))
        else:
            _fail('visible original occurrence changed during derivation')
    if any(buckets.values()): _fail('unbound new rendition occurrence')
    return tuple(bindings)


def rederive_compatibility_view(path, expected_receipt=None):
    """Boundary primitive: caller receipts never grant permission by themselves."""
    path = Path(path)
    if path.stat().st_size > MAX_VIEW_SOURCE_BYTES: _fail('source byte budget')
    view = derive_compatibility_view(path.read_bytes())
    if expected_receipt is not None and expected_receipt != view.receipt_bytes:
        _fail('stale or tampered source-view receipt')
    return view
