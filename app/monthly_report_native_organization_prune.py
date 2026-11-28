"""Closed picture-only grammar for an unused organization content region.

No textbox, vector shape, diagram, alternative branch, link or bookmark gains
removal authority here. Ordinary source/rendition and final-root receipts remain
mandatory. This is deliberately narrower than the normal picture renderer.
"""
from copy import deepcopy
from hashlib import sha256
import re

from app.monthly_report_native_art_scope import W, R, _package, _routing
from app.monthly_report_native_utility_prune import _signature, _plain, _properties

A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
PIC = '{http://schemas.openxmlformats.org/drawingml/2006/picture}'
WP14 = '{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}'
A14 = '{http://schemas.microsoft.com/office/drawing/2010/main}'
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'


def _picture(drawing, relationships, names):
    # Exact direct child sequences, including optional known passive metadata.
    grammar = {
        W+'drawing': ((WP+'inline',), (WP+'anchor',)),
        WP+'inline': tuple((WP+'extent', *e, WP+'docPr', WP+'cNvGraphicFramePr', A+'graphic') for e in ((), (WP+'effectExtent',))),
        WP+'anchor': tuple((WP+'simplePos', WP+'positionH', WP+'positionV', WP+'extent', *e, WP+'wrapSquare', WP+'docPr', WP+'cNvGraphicFramePr', A+'graphic', *s) for e in ((), (WP+'effectExtent',)) for s in ((), (WP14+'sizeRelH', WP14+'sizeRelV'))),
        WP+'cNvGraphicFramePr': ((A+'graphicFrameLocks',),),
        A+'graphic': ((A+'graphicData',),),
        A+'graphicData': ((PIC+'pic',),),
        PIC+'pic': ((PIC+'nvPicPr', PIC+'blipFill', PIC+'spPr'),),
        PIC+'nvPicPr': ((PIC+'cNvPr', PIC+'cNvPicPr'),),
        PIC+'cNvPicPr': ((), (A+'picLocks',)),
        PIC+'blipFill': ((A+'blip', A+'stretch'), (A+'blip', A+'srcRect', A+'stretch')),
        A+'blip': ((), (A+'extLst',)),
        A+'extLst': ((A+'ext',),),
        A+'stretch': ((A+'fillRect',),),
        PIC+'spPr': ((A+'xfrm', A+'prstGeom'), (A+'xfrm', A+'prstGeom', A+'noFill', A+'ln')),
        A+'xfrm': ((A+'off', A+'ext'),),
        A+'prstGeom': ((), (A+'avLst',)),
        A+'ln': ((A+'noFill',),),
        WP+'positionH': ((WP+'align',),),
        WP+'positionV': ((WP+'posOffset',),),
        WP14+'sizeRelH': ((WP14+'pctWidth',),),
        WP14+'sizeRelV': ((WP14+'pctHeight',),),
    }
    leaves = {WP+n for n in ('extent','effectExtent','docPr','simplePos','wrapSquare','align','posOffset')} | {A+n for n in ('graphicFrameLocks','picLocks','srcRect','fillRect','off','avLst','noFill')} | {PIC+'cNvPr', A14+'useLocalDpi', WP14+'pctWidth', WP14+'pctHeight'}
    attrs = {
        WP+'inline': {'distT','distB','distL','distR',WP14+'anchorId',WP14+'editId'},
        WP+'anchor': {'distT','distB','distL','distR','simplePos','relativeHeight','behindDoc','locked','layoutInCell','allowOverlap',WP14+'anchorId',WP14+'editId'},
        WP+'extent': {'cx','cy'}, WP+'effectExtent': {'l','t','r','b'},
        WP+'docPr': {'id','name','descr','title'}, PIC+'cNvPr': {'id','name','descr','title'},
        A+'graphicFrameLocks': {'noChangeAspect'}, A+'picLocks': {'noChangeAspect','noChangeArrowheads'},
        A+'graphicData': {'uri'}, A+'blip': {R+'embed'}, A+'ext': {'uri','cx','cy'},
        A14+'useLocalDpi': {'val'}, A+'srcRect': {'l','t','r','b'}, PIC+'spPr': {'bwMode'},
        A+'xfrm': {'rot','flipH','flipV'}, A+'off': {'x','y'}, A+'prstGeom': {'prst'},
        WP+'simplePos': {'x','y'}, WP+'positionH': {'relativeFrom'}, WP+'positionV': {'relativeFrom'},
        WP+'wrapSquare': {'wrapText'}, WP14+'sizeRelH': {'relativeFrom'}, WP14+'sizeRelV': {'relativeFrom'},
    }
    if drawing.tag != W+'drawing':
        return False
    for node in drawing.iter():
        children = tuple(n.tag for n in node)
        if node.tag == A+'ext':
            parent = node.getparent()
            choices = ((A14+'useLocalDpi',),) if parent.tag == A+'extLst' else ((),)
            if children not in choices:
                return False
            if parent.tag == A+'extLst' and node.get('uri') != '{28A0092B-C50C-407E-A947-70E740481C1C}':
                return False
            if parent.tag == A+'xfrm' and set(node.attrib) != {'cx','cy'}:
                return False
        elif children not in grammar.get(node.tag, ((),) if node.tag in leaves else ()):
            return False
        if set(node.attrib) - attrs.get(node.tag, set()) or (node.tail or '').strip():
            return False
        text = node.text or ''
        if node.tag == WP+'align':
            if text not in ('left','center','right'):
                return False
        elif node.tag in (WP+'posOffset',WP14+'pctWidth',WP14+'pctHeight'):
            if not re.fullmatch(r'-?[0-9]{1,16}',text):
                return False
        elif text.strip():
            return False
        if node.tag == A+'graphicData' and node.get('uri') != PIC[1:-1]:
            return False
        if node.tag == A+'prstGeom' and node.get('prst') != 'rect':
            return False
    images = list(drawing.iter(A+'blip'))
    if len(images) != 1 or set(images[0].attrib) != {R+'embed'}:
        return False
    relation = relationships.get(images[0].get(R+'embed'))
    if relation is None or relation.get('TargetMode') or relation.get('Type') != R[1:-1]+'/image':
        return False
    target = relation.get('Target','')
    return bool(re.fullmatch(r'media/[A-Za-z0-9_.-]+',target) and 'word/'+target in names)


def _empty_picture_root(node, relationships, names, *, boundary=False):
    clone = deepcopy(node)
    drawings = list(clone.iter(W+'drawing'))
    if len(drawings) > 4:
        return None
    for draw in drawings:
        if (draw.getparent().tag != W+'r' or draw.getparent().getparent() is not clone
                or not _picture(draw, relationships, names)):
            return None
        draw.getparent().remove(draw)
    expected = _signature(clone)
    # Only direct source page-break/cache markers, with no other data, may
    # accompany the unused pictures. They are not erased from final signatures.
    for tag in ('br','lastRenderedPageBreak'):
        for marker in list(clone.iter(W+tag)):
            allowed = {W+'type':'page'} if tag == 'br' else {}
            if (dict(marker.attrib) != allowed or len(marker) or (marker.text or '').strip()
                    or (marker.tail or '').strip() or marker.getparent().tag != W+'r'
                    or marker.getparent().getparent() is not clone):
                return None
            marker.getparent().remove(marker)
    if any((n.text or '').strip() for n in clone.iter(W+'t')) or not _plain(clone,boundary=boundary):
        return None
    return expected, len(drawings)


def organization_candidates(source_path, view, draft, scope):
    """Return only source-derived candidates; current output is not an input."""
    if scope.section_key is not None or scope.omitted_sections:
        return ()
    blocks = [b for b in draft.blocks if b.key in ('org_chart','business_hours_workflow','after_hours_workflow','contact_matrix')]
    if (len({b.key for b in blocks}) != len(blocks) or any(b.source != 'Omit' and any((
            b.text.strip(),b.rows,b.extra_tables,b.asset_hashes,b.asset_instances,b.org_nodes,
            b.ai_paragraphs,b.references)) for b in blocks)):
        return ()
    raw = source_path.read_bytes()
    if sha256(raw).hexdigest() != scope.original_sha256:
        return ()
    from app.monthly_report_xml_parser import parse_xml
    with _package(raw) as archive:
        original,_,source_ends,_ = _routing(archive)
        rels = list(parse_xml(archive.read('word/_rels/document.xml.rels')))
        if len({n.get('Id') for n in rels}) != len(rels):
            return ()
        relationships = {n.get('Id'):n for n in rels}
        names = set(archive.namelist())
    with _package(view.rendition_bytes) as archive:
        rendition,_,ends,_ = _routing(archive)
    if source_ends != ends or len(original) != len(rendition):
        return ()
    mapping = dict(scope.source_plan.section_by_position)
    result = []; start = 0
    for section,end in enumerate(ends,1):
        positions = tuple(range(start+1,end+1)); roots=original[start:end]
        items = [i for i in view.original_inspection.items if i.part=='word/document.xml' and i.position in positions]
        if (1<section<len(ends) and 1<=len(roots)<=8
                and all(mapping.get(p)=='organization' and p not in scope.source_plan.headings for p in positions)
                and items and all(i.kind=='image' and i.suggested_slot=='org_chart' for i in items)
                and all(_signature(a)==_signature(b) for a,b in zip(roots,rendition[start:end]))):
            envelopes = [_empty_picture_root(n,relationships,names,boundary=j==len(roots)-1) for j,n in enumerate(roots)]
            if (all(x is not None for x in envelopes)
                    and all(sum(i.position == pos for i in items) == envelope[1]
                            for pos, envelope in zip(positions, envelopes))):
                props=[_properties(original[end-1]),_properties(original[ends[section]-1])]
                if all(p is not None and (p.find(W+'type') is None or p.find(W+'type').get(W+'val')=='nextPage') for p in props):
                    result.append((section,tuple(x[0] for x in envelopes),positions))
        start=end
    return tuple(result)


def plan_native_unused_sections(source_path, view, draft, scope):
    """Combine independent positive envelopes before one source-route simulation.

    Organization contributes only inactive root positions, never utility's
    narrow permission to retain source-generated label/month support.
    """
    from app.monthly_report_native_utility_prune import plan_utility_section_prune, _source_prune_plan
    utility = plan_utility_section_prune(source_path, view, draft, scope)
    organization = organization_candidates(source_path, view, draft, scope)
    if not organization:
        return utility
    sections = list(utility.source_sections if utility else ())
    expected = list(utility.expected_roots if utility else ())
    decorations = list(utility.decoration_sources if utility else ())
    for section, signatures, positions in organization:
        if section in sections:
            return None
        sections.append(section)
        expected.append((section, signatures))
        decorations.append((section, positions, ()))
    return _source_prune_plan(view, scope, tuple(sorted(sections)), tuple(expected), tuple(decorations))
