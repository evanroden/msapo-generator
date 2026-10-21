"""Closed raw scaffold for units promoted by the experimental source view.

AlternateContent is checked separately by the capability selector. This layer
closes the surrounding paragraph, run, properties and unwrapped drawings so a
current-view cleanup cannot turn hidden/deleted payload into eligible furniture.
It never changes XML, selects media, grants a logo role, or approves artwork.
"""
from copy import deepcopy
import re

from app.monthly_report_native_design import W, A, R, WP, WPS, PIC, MC

W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
WP14 = '{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}'
A14 = '{http://schemas.microsoft.com/office/drawing/2010/main}'
XML = '{http://www.w3.org/XML/1998/namespace}'
DPI_URI = '{28A0092B-C50C-407E-A947-70E740481C1C}'
MAX_NODES = 4096
MAX_DEPTH = 48
MAX_CHARS = 256 * 1024
MAX_COORD = 50_000_000
MAX_TWIPS = 31_680
FORBIDDEN = {W + local for local in (
    'ins', 'del', 'moveFrom', 'moveTo', 'moveFromRangeStart', 'moveFromRangeEnd',
    'moveToRangeStart', 'moveToRangeEnd', 'pPrChange', 'rPrChange', 'sectPrChange',
    'fldSimple', 'fldChar', 'instrText', 'delInstrText', 'delText',
    'commentRangeStart', 'commentRangeEnd', 'commentReference',
)}


def _fail(reason):
    from app.monthly_report_compatibility_view import CompatibilityError
    raise CompatibilityError('Raw native unit is not proved: ' + reason)


def _enum(*values):
    return lambda value: value in values


def _integer(value, low=0, high=MAX_COORD):
    return bool(re.fullmatch(r'-?[0-9]{1,10}', value) and low <= int(value) <= high)


def _positive(value):
    return _integer(value, 1)


def _hex(value):
    return bool(re.fullmatch(r'[0-9a-fA-F]{8}', value))


def _metadata(value):
    return len(value) <= 4096 and not any(ord(c) < 32 and c not in '\r\n\t' for c in value)


def _identity(value):
    return bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.:-]{0,127}', value))


def _font(value):
    # Names only, never a link, font relationship, CSS expression or script.
    return value in ('Sweet Sans Pro', 'Arial Narrow', 'Arial', 'Aptos', 'Calibri', 'Times New Roman')


def prescan_unit(unit):
    """Reject revisions/commands before any current-view eligibility cleanup."""
    nodes, chars = [], 0
    for node in unit.iter():
        nodes.append(node)
        if len(nodes) > MAX_NODES or not isinstance(node.tag, str):
            _fail('node budget or non-element markup')
        if node.tag in FORBIDDEN:
            _fail('revision, field or comment payload')
        depth, parent = 0, node
        while parent is not unit:
            parent = parent.getparent(); depth += 1
            if parent is None or depth > MAX_DEPTH: _fail('depth budget')
        if len(node.attrib) > 24: _fail('attribute budget')
        chars += len(node.text or '') + len(node.tail or '')
        chars += sum(len(key) + len(value) for key, value in node.attrib.items())
        if chars > MAX_CHARS: _fail('character budget')
        if (node.tail or '').strip(): _fail('structural tail text')
    return tuple(nodes)


class _Unit:
    def __init__(self, unit, relations, archive):
        self.unit, self.relations, self.archive = unit, relations, archive
        self.nodes, self.seen, self.drawings, self.chrome = prescan_unit(unit), set(), [], []
        self.wrapper_count = 0

    def node(self, node, tag, required=None, optional=None, *, text=None):
        if node.tag != tag or node in self.seen: _fail('wrong or repeated scaffold')
        self.seen.add(node)
        required, optional = required or {}, optional or {}
        if set(required) - set(node.attrib) or set(node.attrib) - set(required) - set(optional):
            _fail('unknown or missing attribute')
        for key, value in node.attrib.items():
            if not (required.get(key) or optional.get(key))(value): _fail('invalid attribute value')
        if text is None:
            if (node.text or '').strip(): _fail('structural text')
        elif not text(node.text or ''):
            _fail('invalid text')

    def leaf(self, node, tag, required=None, optional=None, *, text=None):
        self.node(node, tag, required, optional, text=text)
        if len(node): _fail('non-leaf property')

    def sequence(self, node, spec):
        children, offset, selected = list(node), 0, {}
        for tag, low, high in spec:
            found = []
            while offset < len(children) and children[offset].tag == tag:
                found.append(children[offset]); offset += 1
            if not low <= len(found) <= high: _fail('ordered child cardinality')
            selected[tag] = found
        if offset != len(children): _fail('unknown or unordered child')
        return selected

    def run_properties(self, node):
        self.node(node, W+'rPr')
        tags = (W+'rFonts', W+'noProof', W+'kern', W+'sz', W+'szCs', W14+'ligatures')
        children = self.sequence(node, tuple((tag, 0, 1) for tag in tags))
        for tag, values in children.items():
            for child in values:
                if tag == W+'rFonts':
                    self.leaf(child, tag, optional={W+key: _font for key in ('ascii', 'hAnsi', 'eastAsia', 'cs')})
                    if not child.attrib: _fail('empty font declaration')
                elif tag == W+'noProof': self.leaf(child, tag)
                elif tag == W14+'ligatures': self.leaf(child, tag, {W14+'val': _enum('standardContextual')})
                else: self.leaf(child, tag, {W+'val': lambda value: _integer(value, 1, 400)})

    def section_properties(self, node):
        self.node(node, W+'sectPr', optional={W+key: _hex for key in ('rsidR', 'rsidRPr', 'rsidSect')})
        children = self.sequence(node, (
            (W+'headerReference', 0, 3), (W+'footerReference', 0, 3), (W+'type', 0, 1),
            (W+'pgSz', 1, 1), (W+'pgMar', 1, 1), (W+'cols', 0, 1),
            (W+'titlePg', 0, 1), (W+'docGrid', 0, 1),
        ))
        for kind in ('header', 'footer'):
            used = set()
            for reference in children[W+kind+'Reference']:
                self.leaf(reference, W+kind+'Reference', {W+'type': _enum('default', 'first', 'even'), R+'id': _identity})
                if reference.get(W+'type') in used: _fail('duplicate chrome reference kind')
                used.add(reference.get(W+'type'))
                rid = reference.get(R+'id'); target, relkind = self.relations.get(rid, ('', ''))
                if (relkind != R[1:-1]+'/'+kind or not re.fullmatch(r'word/'+kind+r'[1-9][0-9]*\.xml', target)
                        or target not in self.archive.namelist()):
                    _fail('nonlocal, missing or wrong-kind chrome relationship')
                self.chrome.append({'kind':kind, 'type':reference.get(W+'type'), 'relationship':rid, 'part':target})
        for value in children[W+'type']: self.leaf(value, W+'type', {W+'val': _enum('continuous', 'nextPage')})
        for value in children[W+'pgSz']:
            self.leaf(value, W+'pgSz', {W+key: lambda v: _integer(v, 1, MAX_TWIPS) for key in ('w', 'h')})
        for value in children[W+'pgMar']:
            self.leaf(value, W+'pgMar', {W+key: lambda v: _integer(v, 0, MAX_TWIPS) for key in ('top','right','bottom','left','header','footer','gutter')})
        for value in children[W+'cols']:
            self.leaf(value, W+'cols', {W+'space': lambda v: _integer(v, 0, MAX_TWIPS)}, {W+'num':_enum('1')})
        for value in children[W+'titlePg']: self.leaf(value, W+'titlePg')
        for value in children[W+'docGrid']:
            self.leaf(value, W+'docGrid', {W+'linePitch': lambda v: _integer(v, 1, MAX_TWIPS)})

    def paragraph_properties(self, node):
        self.node(node, W+'pPr')
        children = self.sequence(node, ((W+'rPr', 0, 1), (W+'sectPr', 0, 1)))
        for value in children[W+'rPr']: self.run_properties(value)
        for value in children[W+'sectPr']: self.section_properties(value)

    def position(self, node, axis):
        self.node(node, WP+'position'+axis, {'relativeFrom':_enum(*(('page','column','margin') if axis == 'H' else ('page','paragraph')))})
        child = self.sequence(node, ((WP+'posOffset', 1, 1),))[WP+'posOffset'][0]
        self.leaf(child, WP+'posOffset', text=lambda value:_integer(value,-MAX_COORD))

    def graphic(self, drawing, *, minimal_frame=False):
        self.node(drawing, W+'drawing')
        if len(drawing) != 1 or drawing[0].tag not in (WP+'inline', WP+'anchor'): _fail('drawing scaffold')
        container = drawing[0]; anchor = container.tag == WP+'anchor'
        if minimal_frame and anchor: _fail('minimal frame must be inline')
        common = {key: lambda value:_integer(value,0) for key in ('distT','distB','distL','distR')}
        common.update({WP14+key:_hex for key in ('anchorId','editId')})
        required = {'simplePos':_enum('0'), 'relativeHeight':lambda v:_integer(v,0,2**32-1),
                    'behindDoc':_enum('0','1'), 'locked':_enum('0'), 'layoutInCell':_enum('1'), 'allowOverlap':_enum('1')} if anchor else {}
        self.node(container, container.tag, required, common)
        before = ((WP+'simplePos',1,1),(WP+'positionH',1,1),(WP+'positionV',1,1)) if anchor else ()
        spec = before + ((WP+'extent',1,1),(WP+'effectExtent',0,1))
        if anchor: spec += ((WP+'wrapNone',1,1),)
        spec += ((WP+'docPr',int(not minimal_frame),1),(WP+'cNvGraphicFramePr',0,1),(A+'graphic',1,1))
        if anchor: spec += ((WP14+'sizeRelH',0,1),(WP14+'sizeRelV',0,1))
        children = self.sequence(container,spec)
        if anchor:
            self.leaf(children[WP+'simplePos'][0],WP+'simplePos',{'x':_enum('0'),'y':_enum('0')})
            for axis in ('H','V'):self.position(children[WP+'position'+axis][0],axis)
            self.leaf(children[WP+'wrapNone'][0],WP+'wrapNone')
        extent = children[WP+'extent'][0]
        self.leaf(extent,WP+'extent',{'cx':_positive,'cy':_positive})
        for value in children[WP+'effectExtent']:
            self.leaf(value,WP+'effectExtent',{key:_integer for key in ('l','t','r','b')})
        for value in children[WP+'docPr']:self.descriptor(value,WP+'docPr')
        for value in children[WP+'cNvGraphicFramePr']:
            self.node(value,WP+'cNvGraphicFramePr')
            for lock in self.sequence(value,((A+'graphicFrameLocks',0,1),))[A+'graphicFrameLocks']:
                self.leaf(lock,A+'graphicFrameLocks',optional={'noChangeAspect':_enum('0','1')})
        if anchor:
            for axis, percent in (('H','pctWidth'),('V','pctHeight')):
                for value in children[WP14+'sizeRel'+axis]:
                    self.node(value,WP14+'sizeRel'+axis,{'relativeFrom':_enum('margin')})
                    child = self.sequence(value,((WP14+percent,1,1),))[WP14+percent][0]
                    self.leaf(child,WP14+percent,text=_enum('0'))
        graphic = children[A+'graphic'][0]; self.node(graphic,A+'graphic')
        data = self.sequence(graphic,((A+'graphicData',1,1),))[A+'graphicData'][0]
        self.node(data,A+'graphicData',{'uri':_enum(WPS[1:-1] if minimal_frame else PIC[1:-1])})
        return data

    def descriptor(self,node,tag):
        self.leaf(node,tag,{'id':lambda value:_integer(value,0,2**32-1),'name':_metadata},
                  {'descr':_metadata,'title':_metadata})

    def picture(self,drawing):
        data = self.graphic(drawing)
        pic = self.sequence(data,((PIC+'pic',1,1),))[PIC+'pic'][0];self.node(pic,PIC+'pic')
        children = self.sequence(pic,((PIC+'nvPicPr',1,1),(PIC+'blipFill',1,1),(PIC+'spPr',1,1)))
        nonvisual = children[PIC+'nvPicPr'][0];self.node(nonvisual,PIC+'nvPicPr')
        props = self.sequence(nonvisual,((PIC+'cNvPr',1,1),(PIC+'cNvPicPr',1,1)))
        self.descriptor(props[PIC+'cNvPr'][0],PIC+'cNvPr')
        locks = props[PIC+'cNvPicPr'][0];self.node(locks,PIC+'cNvPicPr')
        for lock in self.sequence(locks,((A+'picLocks',0,1),))[A+'picLocks']:
            self.leaf(lock,A+'picLocks',optional={key:_enum('0','1') for key in ('noChangeAspect','noChangeArrowheads')})
        fill = children[PIC+'blipFill'][0];self.node(fill,PIC+'blipFill')
        fills = self.sequence(fill,((A+'blip',1,1),(A+'srcRect',0,1),(A+'stretch',1,1)))
        blip = fills[A+'blip'][0];self.node(blip,A+'blip',{R+'embed':_identity})
        for extensions in self.sequence(blip,((A+'extLst',0,1),))[A+'extLst']:
            self.node(extensions,A+'extLst')
            extension = self.sequence(extensions,((A+'ext',1,1),))[A+'ext'][0]
            self.node(extension,A+'ext',{'uri':_enum(DPI_URI)})
            dpi = self.sequence(extension,((A14+'useLocalDpi',1,1),))[A14+'useLocalDpi'][0]
            self.leaf(dpi,A14+'useLocalDpi',{'val':_enum('0','1')})
        for crop in fills[A+'srcRect']:
            self.leaf(crop,A+'srcRect',optional={key:lambda v:_integer(v,0,100_000) for key in ('l','t','r','b')})
            if any(int(crop.get(a,'0'))+int(crop.get(b,'0')) >= 100_000 for a,b in (('l','r'),('t','b'))):
                _fail('empty or inverted picture crop')
        stretch = fills[A+'stretch'][0];self.node(stretch,A+'stretch')
        self.leaf(self.sequence(stretch,((A+'fillRect',1,1),))[A+'fillRect'][0],A+'fillRect')
        props = children[PIC+'spPr'][0];self.node(props,PIC+'spPr',optional={'bwMode':_enum('auto')})
        children = self.sequence(props,((A+'xfrm',1,1),(A+'prstGeom',1,1),(A+'noFill',0,1),(A+'ln',0,1)))
        transform = children[A+'xfrm'][0];self.node(transform,A+'xfrm')
        transforms = self.sequence(transform,((A+'off',1,1),(A+'ext',1,1)))
        self.leaf(transforms[A+'off'][0],A+'off',{'x':lambda v:_integer(v,-MAX_COORD),'y':lambda v:_integer(v,-MAX_COORD)})
        self.leaf(transforms[A+'ext'][0],A+'ext',{'cx':_positive,'cy':_positive})
        self.rectangle(children[A+'prstGeom'][0], require_list=True)
        for nofill in children[A+'noFill']:self.leaf(nofill,A+'noFill')
        for line in children[A+'ln']:
            self.node(line,A+'ln',optional={'w':_integer})
            self.leaf(self.sequence(line,((A+'noFill',1,1),))[A+'noFill'][0],A+'noFill')
        from app.monthly_report_compatibility_view import _validate_picture_resource
        return {'class':'ordinary-picture',**_validate_picture_resource(blip,self.relations,self.archive)}

    def rectangle(self,node,*,require_list=False):
        self.node(node,A+'prstGeom',{'prst':_enum('rect')})
        for child in self.sequence(node,((A+'avLst',int(require_list),1),))[A+'avLst']:
            self.leaf(child,A+'avLst')

    def minimal_frame(self,drawing):
        """Finite unwrapped inline title frame; no effects, images or inheritance."""
        data = self.graphic(drawing,minimal_frame=True)
        shape = self.sequence(data,((WPS+'wsp',1,1),))[WPS+'wsp'][0];self.node(shape,WPS+'wsp')
        children = self.sequence(shape,tuple((WPS+key,1,1) for key in ('cNvSpPr','spPr','txbx','bodyPr')))
        self.leaf(children[WPS+'cNvSpPr'][0],WPS+'cNvSpPr',{'txBox':_enum('1')})
        props = children[WPS+'spPr'][0];self.node(props,WPS+'spPr')
        self.rectangle(self.sequence(props,((A+'prstGeom',1,1),))[A+'prstGeom'][0])
        textbox = children[WPS+'txbx'][0];self.node(textbox,WPS+'txbx')
        box = self.sequence(textbox,((W+'txbxContent',1,1),))[W+'txbxContent'][0];self.node(box,W+'txbxContent')
        paragraphs = self.sequence(box,((W+'p',1,16),))[W+'p'];texts=[]
        for paragraph in paragraphs:
            self.node(paragraph,W+'p')
            runs = self.sequence(paragraph,((W+'r',0,16),))[W+'r'];values=[]
            for run in runs:
                self.node(run,W+'r')
                text = self.sequence(run,((W+'t',1,1),))[W+'t'][0]
                self.leaf(text,W+'t',optional={XML+'space':_enum('preserve','default')},text=_metadata)
                values.append(text.text or '')
            texts.append(tuple(values))
        self.leaf(children[WPS+'bodyPr'][0],WPS+'bodyPr')
        return {'class':'minimal-inline-textframe','paragraph_runs':tuple(texts)}

    def drawing(self,node):
        data = list(node.iter(A+'graphicData'))
        if len(data) != 1: _fail('multiple graphic payloads')
        if data[0].get('uri') == PIC[1:-1]:record = self.picture(node)
        elif data[0].get('uri') == WPS[1:-1] and len(node)==1 and node[0].tag==WP+'inline':
            record = self.minimal_frame(node)
        elif data[0].get('uri') == WPS[1:-1] and len(node)==1 and node[0].tag==WP+'anchor':
            from lxml import etree
            from app.monthly_report_static_siblings import validate_static_branch
            branch = etree.Element(MC+'Choice',Requires='shape',nsmap={'shape':WPS[1:-1]})
            branch.append(deepcopy(node));record = validate_static_branch(branch)
            self.seen.update(node.iter())
            record = {**record,'class':'unwrapped-'+record['class']}
        else: _fail('unrecognized unwrapped drawing')
        from app.monthly_report_compatibility_view import _node_path,_subtree_digest
        self.drawings.append({**record,'path':_node_path(self.unit,node),'sha256':_subtree_digest(node)})

    def run(self,node):
        self.node(node,W+'r',optional={W+key:_hex for key in ('rsidR','rsidRPr')})
        values = list(node)
        if values and values[0].tag==W+'rPr':self.run_properties(values.pop(0))
        if values and values[0].tag==W+'lastRenderedPageBreak':self.leaf(values.pop(0),W+'lastRenderedPageBreak')
        if not 1 <= len(values) <= 16:_fail('run payload cardinality')
        for child in values:
            if child.tag==MC+'AlternateContent':
                # Central derivation validates selection and every branch. Do
                # not permit raw revisions/commands to hide inside this boundary.
                self.seen.update(child.iter());self.wrapper_count+=1
            elif child.tag==W+'drawing':self.drawing(child)
            else:_fail('unrecognized outer run child')

    def validate(self):
        self.node(self.unit,W+'p',optional={**{W+key:_hex for key in ('rsidR','rsidRPr','rsidRDefault','rsidP')},
                                          W14+'paraId':_hex,W14+'textId':_hex})
        children = self.sequence(self.unit,((W+'pPr',0,1),(W+'r',1,128)))
        for props in children[W+'pPr']:self.paragraph_properties(props)
        for run in children[W+'r']:self.run(run)
        if len(self.seen) != len(self.nodes):_fail('unconsumed outer markup')
        if not self.wrapper_count:_fail('not a candidate AlternateContent unit')
        from app.monthly_report_compatibility_view import _subtree_digest
        return {'unit_sha256':_subtree_digest(self.unit),'node_count':len(self.nodes),
                'wrapper_count':self.wrapper_count,'ordinary_drawings':tuple(self.drawings),
                'chrome_references':tuple(self.chrome)}


def validate_unit(unit, relations, archive):
    """Validate a raw candidate paragraph; wrapper branches remain caller-owned.

    A caller must use this before interpreting a current-view candidate and must
    separately pin raw/current positional identity. The receipt is evidence, not
    authority; validation must be repeated from the immutable original.
    """
    return _Unit(unit,relations,archive).validate()
