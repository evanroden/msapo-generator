"""Experimental source-pinned removal of wholly unused plain utility sections.

The ordinary complete native output must pass its existing verifier first.
A second scope is derived before rendering, never from missing output chrome.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_native_art_scope import (
    _package, _routing, NativeEmissionProof,
    verify_header_routing, W,
)
from app.monthly_report_native_interior_tail import _signature

_PLAIN = {qn('w:' + n) for n in (
    'p', 'pPr', 'r', 'rPr', 't', 'rFonts', 'b', 'bCs', 'i', 'iCs', 'sz',
    'szCs', 'color', 'highlight', 'spacing', 'ind', 'jc', 'outlineLvl',
    'tabs', 'tab', 'keepNext', 'keepLines', 'widowControl', 'noProof', 'lang',
)}


def _properties(node):
    return node.find('./' + W + 'pPr/' + W + 'sectPr') if node.tag == W + 'p' else None


def _plain(node, boundary=False):
    # Deliberately stricter than interior_tail._plain: this closed grammar
    # grants section-deletion permission, not a local empty-tail adjustment.
    clone = deepcopy(node)
    if boundary:
        props = _properties(clone)
        if props is None:
            return False
        props.getparent().remove(props)
    if clone.tag != W + 'p' or any(n.tag not in _PLAIN for n in clone.iter()):
        return False
    # Closed direct grammar. No nested properties, duplicate direct property
    # containers, or hidden text in leaf formatting may be erased into proof.
    paragraph_props = {'rPr', 'spacing', 'ind', 'jc', 'outlineLvl', 'tabs',
                       'keepNext', 'keepLines', 'widowControl'}
    run_props = {'rFonts', 'b', 'bCs', 'i', 'iCs', 'sz', 'szCs', 'color',
                 'highlight', 'noProof', 'lang'}
    grammar = {
        W+'p': {W+'pPr', W+'r'},
        W+'pPr': {W+n for n in paragraph_props},
        W+'r': {W+'rPr', W+'t', W+'tab'},
        W+'rPr': {W+n for n in run_props},
        W+'tabs': {W+'tab'},
    }
    for n in clone.iter():
        if any(c.tag not in grammar.get(n.tag, set()) for c in n):
            return False
        tags = [c.tag for c in n]
        if (n.tag in (W+'pPr', W+'rPr') and len(tags) != len(set(tags))
                or n.tag == W+'p' and tags.count(W+'pPr') > 1
                or n.tag == W+'r' and tags.count(W+'rPr') > 1):
            return False
        if (n.tag != W+'t' and (n.text or '').strip()
                or (n.tail or '').strip()):
            return False
    return True


def _empty_signature(node):
    """Predict production clearing exactly; writer changes make pruning inert.

    Never broaden this prediction by normalizing the rendered output.
    """
    clone = deepcopy(node)
    text = ''.join(n.text or '' for n in clone.iter(W+'t'))
    if text.strip():
        from app.monthly_report_native_layout import _set_text
        _set_text(clone, '')
        pr = clone.find(W+'pPr')
        if pr is not None:
            num=OxmlElement('w:numPr');ident=OxmlElement('w:numId')
            ident.set(W+'val','0');num.append(ident);pr.append(num)
    return _signature(clone)


@dataclass(frozen=True)
class UtilitySectionPrune:
    full_scope: object
    reduced_scope: object
    source_sections: tuple[int, ...]
    expected_roots: tuple[tuple[int, tuple], ...]
    decoration_sources: tuple = ()

    def apply(self, raw, proof, active_source_sections, *, decoration_receipt=None):
        """Return the full output unchanged unless every precomputed root matches."""
        verify_header_routing(raw,self.full_scope,emission_proof=proof)
        decorations = {section: (positions, support) for section, positions, support in self.decoration_sources}
        if (set(self.source_sections) - set(decorations)) & set(active_source_sections):
            return raw, self.full_scope, proof
        if set(self.source_sections) & set(proof.reserved_source_sections):
            return raw, self.full_scope, proof
        with _package(raw) as archive:
            units,_,_,_=_routing(archive)
        owners=proof.source_word_sections_by_unit
        expected=dict(self.expected_roots)
        remove=[]
        for section in self.source_sections:
            positions=[i for i,o in enumerate(owners) if o==section]
            signatures=expected[section]
            if section in decorations:
                from app.monthly_report_native_utility_intro import UtilityDecorationReceipt
                if (not isinstance(decoration_receipt, UtilityDecorationReceipt)
                        or decoration_receipt.scope_sha256 != self.full_scope.sha256
                        or len(decoration_receipt.roots) != len(units)):
                    return raw, self.full_scope, proof
                source_positions, supports = decorations[section]
                activities = decoration_receipt.activities
                if (any(a[0] is None for a in activities)
                        or any(a[2] or a[4] for a in activities if a[0] == section)
                        or tuple(sorted(a[1] for a in activities if a[0] == section and a[3] and a[1] is not None)) != supports
                        or any(a[1] is None for a in activities if a[0] == section)):
                    return raw, self.full_scope, proof
                records = [decoration_receipt.roots[i] for i in positions]
                if (tuple(r[0] for r in records) != source_positions
                        or any(r[1] or r[3] for r in records)
                        or tuple(r[0] for r in records if r[2]) != supports):
                    return raw, self.full_scope, proof
            if len(positions)!=len(signatures) or any(_signature(units[i])!=sig for i,sig in zip(positions,signatures)):
                return raw, self.full_scope, proof
            remove.extend(positions)
        removing=set(remove)
        body=units[0].getparent()
        for i in remove:
            body.remove(units[i])
        with ZipFile(BytesIO(raw)) as archive:
            from lxml import etree
            document=etree.tostring(body.getparent(),xml_declaration=True,encoding='UTF-8',standalone=True)
            result=BytesIO()
            with ZipFile(result,'w',ZIP_DEFLATED) as output:
                for info in archive.infolist():
                    output.writestr(info,document if info.filename=='word/document.xml' else archive.read(info.filename))
        filtered=tuple(o for i,o in enumerate(owners) if i not in removing)
        final_proof=NativeEmissionProof(self.reduced_scope.sha256,filtered,
            tuple(s for s in proof.reserved_source_sections if s not in self.source_sections))
        result=result.getvalue()
        verify_header_routing(result,self.reduced_scope,emission_proof=final_proof)
        return result,self.reduced_scope,final_proof


def plan_utility_section_prune(source_path, view, draft, scope):
    """Derive a second optional positive scope from source and explicit draft only."""
    utility=[b for b in draft.blocks if b.key=='utility_analysis']
    if (scope.section_key is not None or scope.omitted_sections or len(utility)>1
            or any(b.source!='Omit' and any((b.text.strip(),b.rows,b.extra_tables,
                b.asset_hashes,b.asset_instances,b.org_nodes,b.ai_paragraphs,
                b.references)) for b in utility)):
        return None
    # References alone are not rendered content, but they can encode an
    # unresolved source decision. Conservatively retain that region too.
    # AI paragraph records likewise block even when their current text is blank.
    raw=source_path.read_bytes()
    from hashlib import sha256
    if sha256(raw).hexdigest()!=scope.original_sha256:
        return None
    with _package(raw) as archive:
        original,_,original_ends,_=_routing(archive)
    with _package(view.rendition_bytes) as archive:
        rendition,routes,ends,even=_routing(archive)
    if original_ends!=ends or len(original)!=len(rendition):
        return None
    mapping=dict(scope.source_plan.section_by_position)
    items=view.original_inspection.items
    candidates=[];expected=[];decorations=[];start=0
    for section,end in enumerate(ends,1):
        positions=range(start+1,end+1)
        roots=original[start:end]
        source_items=[i for i in items if i.part=='word/document.xml' and i.position in positions]
        # Intentionally narrow: only unheaded scorecards subregions qualify.
        # Other source layouts need their own positive proof, not a looser rule.
        if (1<section<len(ends) and len(roots)<=64
                and all(mapping.get(p)=='scorecards' and p not in scope.source_plan.headings for p in positions)
                and any(i.kind=='text' and i.text.strip() for i in source_items)
                and all(i.kind=='text' and i.suggested_slot=='utility_analysis' for i in source_items)
                and all(_signature(a)==_signature(b) for a,b in zip(roots,rendition[start:end]))):
            from app.monthly_report_native_utility_intro import intro_envelope
            plain = all(_plain(n,boundary=j==len(roots)-1) for j,n in enumerate(roots))
            intro = None if plain else intro_envelope(roots,start,draft)
            if not plain and intro is None:
                start=end
                continue
            # Both adjacent transitions must be normal next-page, with no
            # inherited odd/even restart semantics silently changed.
            props=[_properties(original[end-1]),_properties(original[ends[section]-1])]
            if all(p is not None and (p.find(W+'type') is None or p.find(W+'type').get(W+'val')=='nextPage') for p in props):
                candidates.append(section)
                expected.append((section, intro[0] if intro else tuple(_empty_signature(n) for n in roots)))
                if intro:
                    decorations.append((section, tuple(positions), intro[1]))
        start=end
    if not candidates:
        return None
    removed=set(candidates);keep=tuple(s for s in scope.source_word_sections if s not in removed)
    removed_positions={p for s in candidates for p in range((ends[s-2] if s>1 else 0)+1,ends[s-1]+1)}
    selected=tuple(p for p in scope.selected_positions if p not in removed_positions)
    # Recompute inheritance from the input without candidate regions, not the
    # rendered output. Refuse if any remaining effective route would change.
    body=rendition[0].getparent()
    for p in sorted(removed_positions,reverse=True):body.remove(rendition[p-1])
    from lxml import etree
    document=etree.tostring(body.getparent())
    stream=BytesIO()
    with _package(view.rendition_bytes) as archive, ZipFile(stream,'w',ZIP_DEFLATED) as output:
        for info in archive.infolist():output.writestr(info,document if info.filename=='word/document.xml' else archive.read(info.filename))
    with _package(stream.getvalue()) as archive:_,new_routes,new_ends,new_even=_routing(archive)
    retained=tuple(routes[s-1] for s in keep)
    if new_routes!=retained or new_even!=even:
        return None
    reduced=replace(scope,selected_positions=selected,source_word_sections=keep,
        source_section_ends=tuple(ends[s-1] for s in keep),expected_output_section_ends=new_ends,
        routes=retained,expected_parts=tuple(sorted({p for r in retained for p in r.parts if p})),
        reserved_routes=tuple(scope.reserved_routes[s-1] for s in keep),
        reserved_top_margins=tuple(scope.reserved_top_margins[s-1] for s in keep))
    return UtilitySectionPrune(scope,reduced,tuple(candidates),tuple(expected),tuple(decorations))
