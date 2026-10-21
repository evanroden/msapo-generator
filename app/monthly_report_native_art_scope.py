"""Source-derived page-chrome closure for the explicit native source-view route.

This module never learns permission from the output. A section's expected
header/footer parts and routing are determined from the verified input before
native editing. No logo role, artwork approval or generic OOXML waiver is minted.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
import re
from zipfile import BadZipFile, ZipFile

from docx.oxml.ns import qn

from app.monthly_report_compatibility_view import (
    CompatibilityError, CompatibilityView, MAX_VIEW_SOURCE_BYTES,
    MAX_VIEW_EXPANDED_BYTES, MAX_VIEW_XML_BYTES, _canonical, _subtree_digest,
)
from app.monthly_report_import import _heading, _is_native_divider_background, _text
from app.monthly_report_native_package import _xml

POLICY = 'native-source-art-section-routing-v1-experimental'
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
REL_KIND = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
KINDS = tuple((kind, variant) for kind in ('header', 'footer') for variant in ('default', 'first', 'even'))
MAX_SECTIONS = 512
MAX_BODY_UNITS = 100_000


def _error(message):
    raise CompatibilityError('Native artwork section scope is not proved: ' + message)


@dataclass(frozen=True)
class NativeSectionPlan:
    section_by_position: tuple[tuple[int, str], ...]
    headings: tuple[int, ...]
    first_word_end: int | None
    nonterminal_positions: tuple[int, ...]

    def selected_positions(self, section_key):
        if section_key is None:
            return self.nonterminal_positions
        found = dict(self.section_by_position)
        if section_key not in set(found.values()):
            _error('the source does not contain the requested logical section')
        return tuple(position for position in self.nonterminal_positions
                     if found[position] == section_key
                     and (section_key != 'cover' or self.first_word_end is None or position <= self.first_word_end))


def source_section_plan(original, inspection):
    """Shared, pure version of native_layout's existing logical selector.

    Call at the existing selector point for legacy behavior. The source-view
    verifier also calls it against the immutable rendition before any editing.
    """
    original = tuple(original)
    if len(original) > MAX_BODY_UNITS:
        _error('source body-unit budget')
    items = defaultdict(list)
    for item in inspection.items:
        if item.part == 'word/document.xml':
            items[item.position].append(item)
    section_by_pos, section, headings = {}, 'cover', set()
    first_word_end = None
    for position, element in enumerate(original, 1):
        if first_word_end is None and (element.tag == W + 'sectPr' or element.find('.//' + W + 'sectPr') is not None):
            first_word_end = position
        group = items[position]
        detected = next((item.section for item in group if item.section), '')
        if detected:
            section = detected
        section_by_pos[position] = section
        if (any(item.note == 'Native divider artwork' for item in group)
                and _is_native_divider_background(element, _text(element))):
            headings.add(position)
        if any(item.note == 'Native section heading' or
               (item.kind == 'text' and not item.suggested_slot and _heading(item.text)) for item in group):
            headings.add(position)
    for heading_position in sorted(headings):
        for position in range(heading_position - 1, 0, -1):
            element = original[position - 1]
            if element.find('.//' + W + 'sectPr') is not None:
                break
            if _is_native_divider_background(element, _text(element)):
                headings.add(position)
                for previous in range(position, heading_position):
                    section_by_pos[previous] = section_by_pos[heading_position]
                break
    return NativeSectionPlan(tuple(section_by_pos.items()), tuple(sorted(headings)), first_word_end,
                             tuple(p for p, element in enumerate(original, 1) if element.tag != W + 'sectPr'))


@dataclass(frozen=True)
class NativeHeaderRoute:
    # Six positions follow KINDS; empty means no applicable source definition.
    parts: tuple[str, ...]
    title_page: bool
    properties_sha256: str


@dataclass(frozen=True)
class NativeHeaderScope:
    policy: str
    original_sha256: str
    rendition_sha256: str
    receipt_sha256: str
    section_key: str | None
    selected_positions: tuple[int, ...]
    source_word_sections: tuple[int, ...]
    source_section_ends: tuple[int, ...]
    expected_output_section_ends: tuple[int, ...]
    routes: tuple[NativeHeaderRoute, ...]
    even_and_odd: bool
    expected_parts: tuple[str, ...]
    plan_sha256: str
    source_plan: NativeSectionPlan

    @property
    def sha256(self):
        from dataclasses import asdict
        return sha256(_canonical(asdict(self))).hexdigest()


def _on_off(node):
    if node is None:
        return False
    if len(node) or set(node.attrib) - {W + 'val'}:
        _error('unknown on/off setting grammar')
    value = node.get(W + 'val', 'true')
    if value not in ('true', '1', 'on', 'false', '0', 'off'):
        _error('invalid on/off setting')
    return value in ('true', '1', 'on')


def _read(archive, name):
    try:
        info = archive.getinfo(name)
        if info.file_size > MAX_VIEW_XML_BYTES:
            _error('XML part budget')
        return _xml(archive.read(info))
    except (KeyError, OSError, BadZipFile, RuntimeError) as exc:
        raise CompatibilityError('Native artwork section scope cannot read its pinned package part.') from exc


def _package(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_VIEW_SOURCE_BYTES:
        _error('encoded package budget')
    try:
        archive = ZipFile(BytesIO(raw))
    except BadZipFile as exc:
        raise CompatibilityError('Native artwork section scope requires a valid package.') from exc
    info = archive.infolist()
    if (len(info) > 512 or len({item.filename for item in info}) != len(info)
            or sum(item.file_size for item in info) > MAX_VIEW_EXPANDED_BYTES):
        archive.close()
        _error('package identity/expanded budget')
    return archive


def _routing(archive):
    document = _read(archive, 'word/document.xml')
    bodies = document.findall(W + 'body')
    body = bodies[0] if len(bodies) == 1 else None
    if document.tag != W + 'document' or body is None:
        _error('document scaffold')
    units = tuple(body)
    if len(units) > MAX_BODY_UNITS:
        _error('body-unit budget')
    relations = _read(archive, 'word/_rels/document.xml.rels')
    if relations.tag != REL + 'Relationships':
        _error('relationship scaffold')
    indexed = {}
    for relation in relations:
        identity = relation.get('Id')
        if (relation.tag != REL + 'Relationship' or not identity or identity in indexed
                or len(relation) or set(relation.attrib) - {'Id', 'Type', 'Target', 'TargetMode'}):
            _error('duplicate or malformed document relationship')
        indexed[identity] = relation
    settings = _read(archive, 'word/settings.xml')
    if settings.tag != W + 'settings':
        _error('settings scaffold')
    even_nodes = settings.findall(W + 'evenAndOddHeaders')
    if len(even_nodes) > 1:
        _error('duplicate even/odd header setting')
    even_and_odd = _on_off(even_nodes[0] if even_nodes else None)
    inherited, routes, ends = {}, [], []
    checked_parts = set()
    for position, unit in enumerate(units, 1):
        properties = [unit] if unit.tag == W + 'sectPr' else list(unit.iter(W + 'sectPr'))
        if not properties:
            continue
        if len(properties) != 1:
            _error('ambiguous source section boundary')
        properties = properties[0]
        if unit.tag == W + 'sectPr':
            if position != len(units):
                _error('nonterminal body section properties')
        elif (unit.tag != W + 'p' or properties.getparent() is None
              or properties.getparent().tag != W + 'pPr'
              or properties.getparent().getparent() is not unit):
            _error('nonordinary source section boundary')
        if len(routes) >= MAX_SECTIONS:
            _error('source section budget')
        present = {}
        for reference in properties:
            if reference.tag not in (W + 'headerReference', W + 'footerReference'):
                continue
            kind = 'header' if reference.tag == W + 'headerReference' else 'footer'
            variant = reference.get(W + 'type', 'default')
            key = (kind, variant)
            if (key not in KINDS or key in present or len(reference)
                    or set(reference.attrib) - {W + 'type', R + 'id'}):
                _error('duplicate or unknown header/footer routing')
            relation = indexed.get(reference.get(R + 'id'))
            if (relation is None or relation.get('Type') != REL_KIND + kind
                    or relation.get('TargetMode') not in (None, 'Internal')):
                _error('missing, external or wrong-kind header/footer relationship')
            target = relation.get('Target', '')
            if (not re.fullmatch(kind + r'[A-Za-z0-9_.-]*\.xml', target)
                    or PurePosixPath(target).name != target):
                _error('header/footer target is not a bounded local part')
            part = 'word/' + target
            if part not in checked_parts:
                root = _read(archive, part)
                if root.tag != W + ('hdr' if kind == 'header' else 'ftr'):
                    _error('header/footer target has wrong root')
                checked_parts.add(part)
            present[key] = part
        titles = properties.findall(W + 'titlePg')
        if len(titles) > 1:
            _error('duplicate first-page header setting')
        inherited.update(present)
        # Pin ALL remaining section properties, including page size/margins,
        # header distances, columns/direction, numbering restart/format and
        # section-break semantics. Only relationship references are represented
        # separately through their exact effective routing targets above.
        geometry = deepcopy(properties)
        for reference in list(geometry):
            if reference.tag in (W + 'headerReference', W + 'footerReference'):
                geometry.remove(reference)
        routes.append(NativeHeaderRoute(tuple(inherited.get(key, '') for key in KINDS),
                                        _on_off(titles[0] if titles else None), _subtree_digest(geometry)))
        ends.append(position)
    if not ends or ends[-1] != len(units) or units[-1].tag != W + 'sectPr':
        _error('missing terminal source section properties')
    return units, tuple(routes), tuple(ends), even_and_odd


def expected_header_scope(source_view, section_key=None):
    """Compute pre-render closure from an independently verified view supplied by caller."""
    if not isinstance(source_view, CompatibilityView):
        _error('typed verified source view required')
    raw = source_view.rendition_bytes
    if sha256(raw).hexdigest() != source_view.rendition_inspection.sha256:
        _error('truthful rendition identity changed')
    with _package(raw) as archive:
        units, all_routes, ends, even_and_odd = _routing(archive)
        plan = source_section_plan(units, source_view.rendition_inspection)
    selected = plan.selected_positions(section_key)
    if not selected:
        _error('empty selected source range')
    source_sections = (tuple(range(1, len(ends) + 1)) if section_key is None else
                       tuple(index for index, end in enumerate(ends, 1)
                             if any((ends[index - 2] if index > 1 else 0) < p <= end for p in selected)))
    routes = tuple(all_routes[index - 1] for index in source_sections)
    if section_key is None:
        output_ends = ends
    else:
        ordinal = {position: index for index, position in enumerate(selected, 1)}
        if any(ends[index - 1] not in ordinal for index in source_sections[:-1]):
            _error('a selected interior section boundary has no retained source anchor')
        output_ends = (*tuple(ordinal[ends[index - 1]] for index in source_sections[:-1]), len(selected) + 1)
    from dataclasses import asdict
    return NativeHeaderScope(POLICY, source_view.original_inspection.sha256,
        source_view.rendition_inspection.sha256, source_view.receipt_sha256, section_key,
        selected, source_sections, tuple(ends[index - 1] for index in source_sections), output_ends, routes,
        even_and_odd, tuple(sorted({part for route in routes for part in route.parts if part})),
        sha256(_canonical(asdict(plan))).hexdigest(), plan)


@dataclass(frozen=True)
class NativeEmissionProof:
    scope_sha256: str
    source_word_sections_by_unit: tuple[int, ...]


def source_emission_proof(scope, body, pages):
    """Bind every emitted root to its pre-edit source section, never its output break.

    NativePages assigns original roots before editing and propagates ownership
    only from an explicit source anchor. Unknown insertions have no authority.
    """
    if not isinstance(scope, NativeHeaderScope):
        _error('typed source scope required for emission')
    owners = []
    for unit in body:
        region = pages.owner.get(unit)
        if region is None or not 0 <= region < len(pages.source_word_sections):
            _error('an emitted body unit has no source-region owner')
        owners.append(pages.source_word_sections[region])
    proof = NativeEmissionProof(scope.sha256, tuple(owners))
    _emission_ends(scope, proof)
    return proof


def _emission_ends(scope, proof):
    if not isinstance(proof, NativeEmissionProof) or proof.scope_sha256 != scope.sha256:
        _error('emission proof belongs to a different source scope')
    owners = proof.source_word_sections_by_unit
    if not owners or len(owners) > MAX_BODY_UNITS:
        _error('empty or over-budget source-region emission')
    groups, ends = [], []
    for position, owner in enumerate(owners, 1):
        if not groups or owner != groups[-1]:
            if groups:
                ends.append(position - 1)
            groups.append(owner)
    if tuple(groups) != scope.source_word_sections:
        _error('emitted source-region order or coverage changed')
    return (*ends, len(owners))


def verify_header_routing(output_bytes, scope, *, emission_proof=None):
    """Reject missing/extra/retargeted/reordered output chrome against source scope.

    This checkpoint requires exact source-selected section count/order and
    geometry. A writer-owned emission proof permits changed body-unit ordinals,
    never changed source-region order/coverage or additional Word sections.
    """
    if not isinstance(scope, NativeHeaderScope) or scope.policy != POLICY:
        _error('typed current source header scope required')
    from dataclasses import asdict
    if sha256(_canonical(asdict(scope.source_plan))).hexdigest() != scope.plan_sha256:
        _error('source section-plan identity changed')
    with _package(output_bytes) as archive:
        _, routes, ends, even_and_odd = _routing(archive)
    expected_ends = (scope.expected_output_section_ends if emission_proof is None
                     else _emission_ends(scope, emission_proof))
    if ends != expected_ends:
        _error('output section boundary ownership moved without source-region proof')
    if even_and_odd != scope.even_and_odd or routes != scope.routes:
        _error('output header/footer routing or first/even-page semantics changed')
    output_parts = tuple(sorted({part for route in routes for part in route.parts if part}))
    if output_parts != scope.expected_parts:
        _error('output header/footer closure changed')
