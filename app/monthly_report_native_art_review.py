"""Explicit, occurrence-bound preservation of already supported native page art.

This default-off source-view companion proves WHICH original/rendered drawings
an operator reviewed for preservation. It never identifies a logo, approves a
client asset, certifies an encoding, or waives pricing/unsupported-content gates.
Public entry points rederive the source view. Private entry points accept only a
view already verified by their enclosing operation and still rehash its source.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from zipfile import BadZipFile, ZipFile

from docx import Document

from app.monthly_report_compatibility_view import (
    CompatibilityError, CompatibilityView, IMAGE_REL, MAX_VIEW_SOURCE_BYTES,
    _canonical, _node_path, _path_node, _subtree_digest,
)
from app.monthly_report_model import ReportPeriod, ReportProfile
from app.monthly_report_native_design import A, R, W, WP
from app.monthly_report_native_package import _xml

POLICY = 'native-source-art-preservation-v3-experimental'
DRAWING_PRIVACY_POLICY = 'native-layout-source-drawing-metadata-v1'
MAX_OCCURRENCES = 128
MAX_REPRESENTATIONS = 512
V = '{urn:schemas-microsoft-com:vml}'
_FORBIDDEN = {W + name for name in (
    'ins', 'del', 'moveFrom', 'moveTo', 'delText', 'instrText', 'fldChar',
    'fldSimple', 'vanish', 'webHidden', 'object', 'altChunk', 'control',
    'commentReference', 'commentRangeStart', 'commentRangeEnd', 'hyperlink',
    'delInstrText', 'subDoc',
)}


def _error(message):
    raise CompatibilityError('Native artwork preservation is not proved: ' + message)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _scope(view, profile, period):
    if (not isinstance(view, CompatibilityView) or not isinstance(profile, ReportProfile)
            or not isinstance(period, ReportPeriod)
            or profile.imported_from not in ('', view.original_inspection.sha256)):
        _error('source/profile/period identity')
    from app.monthly_report_site_catalog import site_options
    from app.monthly_report_library import list_profiles
    from app.monthly_report_designs import is_master
    from app.monthly_report_start_import import source_sites, _words
    saved_profiles = list_profiles(profile.contract)
    if is_master(profile) or any(saved.key == profile.key and is_master(saved) for saved in saved_profiles):
        _error('company-master sources cannot grant ordinary native artwork preservation')
    known = {site.key: site for site in profile.facilities}
    if not known or len(known) != len(profile.facilities):
        _error('nonempty unambiguous facility ownership is required')
    from dataclasses import replace
    # Recognize against the authoritative contract catalog too. Supplying only
    # one desired site cannot hide a second known source facility.
    for site in (*site_options(profile.contract),
                 *(site for saved in saved_profiles for site in saved.facilities)):
        names = {_words(n) for n in (site.title, *site.aliases)}
        overlaps = [prior for prior in known.values()
                    if names.intersection(_words(n) for n in (prior.title, *prior.aliases))]
        if len(overlaps) > 1:
            _error('ambiguous facility ownership')
        if overlaps:
            prior = overlaps[0]
            known[prior.key] = replace(prior, aliases=tuple(dict.fromkeys(
                (*prior.aliases, *(n for n in (site.title, *site.aliases) if n != prior.title)))))
        elif site.key in known and known[site.key] != site:
            _error('conflicting facility identity')
        else:
            known[site.key] = site
    recognized = source_sites(view.original_inspection, known.values())
    if {site.key for site in recognized} != {site.key for site in profile.facilities}:
        _error('ordinary same-site source ownership is required')
    receipt = json.loads(view.receipt_bytes)
    from app.monthly_report_native_art_scope import POLICY as routing_policy
    return _canonical({
        'policy': POLICY, 'drawing_privacy_policy': DRAWING_PRIVACY_POLICY,
        'header_routing_policy': routing_policy,
        'original_sha256': view.original_inspection.sha256,
        'rendition_sha256': view.rendition_inspection.sha256,
        'source_view_receipt_sha256': view.receipt_sha256,
        'source_view_policy': receipt['policy'],
        'source_view_capability_profile': receipt['capability_profile'],
        'source_view_capability_version': receipt['capability_version'],
        'contract': profile.contract, 'profile_key': profile.key,
        'profile_title': profile.title, 'template': profile.template,
        'scope_type': profile.scope_type,
        'facilities': [asdict(site) for site in profile.facilities],
        'period': period.key,
    })


@dataclass(frozen=True)
class NativeArtRepresentation:
    image_path: tuple[int, ...]
    image_tag: str
    relationship_attribute: str
    relationship_id: str
    relationship_type: str
    media_part: str
    media_sha256: str
    drawing_path: tuple[int, ...]
    drawing_sha256: str
    passive_drawing_sha256: str
    output_drawing_sha256: str
    ancestor_context_sha256: str
    unit_path: tuple[int, ...]
    unit_sha256: str
    crop_orientation: tuple


@dataclass(frozen=True)
class NativeArtOccurrence:
    original_id: str
    rendition_id: str
    original_part: str
    rendition_part: str
    original_position: int
    rendition_position: int
    original_word_section: int
    rendition_word_section: int
    original_media_sha256: str
    rendition_media_sha256: str
    original_representations: tuple[NativeArtRepresentation, ...]
    rendition_representations: tuple[NativeArtRepresentation, ...]
    preservation_kind: str = 'header_footer'

    @property
    def sha256(self):
        return _hash(_canonical(asdict(self)))

    @property
    def preview_group_key(self):
        # This is a DISPLAY grouping key, never role or occurrence authority.
        # Full ordered occurrence records are still required for every member.
        return _hash(_canonical(tuple((p.media_sha256, p.crop_orientation)
                                      for p in self.rendition_representations)))


@dataclass(frozen=True)
class NativeArtInventory:
    scope_bytes: bytes
    occurrences: tuple[NativeArtOccurrence, ...]

    @property
    def scope(self):
        return json.loads(self.scope_bytes)

    @property
    def sha256(self):
        return _hash(_canonical({'scope': self.scope,
                                 'occurrences': [asdict(x) for x in self.occurrences]}))


@dataclass(frozen=True)
class NativeArtReview:
    inventory: NativeArtInventory
    receipt_bytes: bytes

    @property
    def receipt(self):
        return json.loads(self.receipt_bytes)

    @property
    def digest(self):
        return _hash(self.receipt_bytes)


def _eligible(item):
    return (item.kind == 'image' and item.position > 0
            and re.fullmatch(r'word/(?:header|footer)[0-9]+\.xml', item.part)
            and item.image_role in ('', 'header_artwork')
            and item.suggested_slot not in ('brand_logo', 'client_logo', 'cover_photo'))


def native_cover_furniture_ids(items):
    """Structural photo exclusion ONLY; no ownership or preservation authority.

    Truthful source-view inspections must independently retain the same first
    cover-band unit. Physical branch and suitability proofs remain separate.
    """
    unit = tuple(i for i in items if i.part == 'word/document.xml' and i.position == 1)
    images = tuple(i for i in unit if i.kind == 'image')
    if (len(images) != 1 or images[0].word_section != 1 or images[0].image_role
            or images[0].suggested_slot not in ('', 'cover_photo')
            or not any(i.kind == 'native_layout' and i.note == 'Native cover branding band'
                       and i.word_section == 1 for i in unit)
            or any(i.kind not in ('image', 'native_layout', 'text')
                   or i.kind == 'text' and i.text.strip() not in ('', '=') for i in unit)):
        return frozenset()
    return frozenset((images[0].id,))


def _cover_band_representations(part, item, representations):
    from app.monthly_report_native_design import MC, WPG
    root = part.element
    unit = root.body[0]
    wrappers = tuple(unit.iter(MC + 'AlternateContent'))
    if (item.position != 1 or item.word_section != 1 or len(wrappers) != 1
            or [n.tag for n in wrappers[0]] != [MC + 'Choice', MC + 'Fallback']
            or len(representations) != 2
            or {p.image_tag for p in representations} != {A + 'blip', V + 'imagedata'}
            or len({p.media_sha256 for p in representations}) != 1):
        _error('cover band requires exactly one picture in each existing equivalent branch')
    for branch, tag, group_tag in zip(wrappers[0], (A + 'blip', V + 'imagedata'),
                                    (WPG + 'wgp', V + 'group')):
        groups = tuple(branch.iter(group_tag))
        pictures = tuple(n for n in branch.iter() if n.tag in (A + 'blip', V + 'imagedata'))
        text = ''.join(n.text or '' for n in branch.iter(W + 't')).strip()
        if (len(groups) != 1 or len(pictures) != 1 or pictures[0].tag != tag
                or pictures[0] not in set(groups[0].iter()) or text):
            _error('cover band branch picture/group/text ownership is ambiguous')
    if any(n.tag in (A + 'blip', V + 'imagedata') and not any(n is p for b in wrappers[0] for p in b.iter())
           for n in unit.iter()):
        _error('cover band has artwork outside its closed wrapper')


def _privacy_drawing_digest(drawing):
    """Pin the exact existing native-output privacy transform, not an ignore list.

    The helper visits only package-part elements. A minimal protocol holder
    lets it process this isolated copy without constructing another DOCX.
    We compare output to this PRECOMPUTED expected tree; arbitrary new output
    attributes cannot disappear into a normalization step during verification.
    """
    from app.monthly_report_native_layout import _clear_source_drawing_metadata
    expected = deepcopy(drawing)
    holder = SimpleNamespace(part=SimpleNamespace(package=SimpleNamespace(
        parts=(SimpleNamespace(element=expected),))))
    _clear_source_drawing_metadata(holder)
    return _subtree_digest(expected)


def _ancestor_context_digest(drawing):
    # Render selection can depend on enclosing Choice Requires or inherited
    # namespace/MC attributes even when the drawing subtree is unchanged.
    # Text and unrelated sibling subtrees are intentionally not part of this
    # context; exact indexed paths and each retained drawing are pinned apart.
    return _hash(_canonical(tuple((node.tag, tuple(sorted(node.attrib.items())),
        tuple(sorted(node.nsmap.items(), key=lambda entry: entry[0] or '')))
        for node in reversed(tuple(drawing.iterancestors())))))


def _representation(part, node, attr, item):
    root = part.element
    if (node.tag, attr) not in ((A + 'blip', R + 'embed'), (V + 'imagedata', R + 'id')):
        _error('unsupported physical image occurrence')
    rel = part.rels.get(node.get(attr))
    if (rel is None or rel.is_external or rel.reltype != IMAGE_REL
            or not hasattr(rel.target_part, 'blob')):
        _error('nonlocal or wrong-kind physical image relationship')
    media_part = str(rel.target_part.partname).lstrip('/')
    if not re.fullmatch(r'word/media/[A-Za-z0-9_.-]{1,100}', media_part):
        _error('invalid physical media part')
    drawing = next((ancestor for ancestor in node.iterancestors()
                    if ancestor.tag in (W + 'drawing', W + 'pict')), None)
    if drawing is None:
        _error('image is not in an ordinary native drawing')
    unit = node
    unit_parent = root.body if item.part == 'word/document.xml' else root
    while unit.getparent() is not unit_parent:
        unit = unit.getparent()
        if unit is None:
            _error('physical occurrence is outside its part')
    if unit_parent.index(unit) + 1 != item.position:
        _error('inspection and raw occurrence position differ')
    if any(n.tag in _FORBIDDEN for n in unit.iter()):
        _error('revision, field, hidden text or command in native art unit')
    # All original branch nodes are pinned before cleanup. Preserve only exact
    # image relationships here; a link or secondary relationship cannot become
    # eligible by being erased in the passive source view.
    for n in unit.iter():
        if any(k.startswith(R) for k in n.attrib) and n.tag not in (A + 'blip', V + 'imagedata'):
            _error('non-image relationship in native art unit')
    if any(k.startswith(R) and k != attr for k in node.attrib):
        _error('ambiguous image relationship attributes')
    crop = []
    for n in drawing.iter():
        if n.tag in (A + 'srcRect', WP + 'extent', A + 'ext'):
            crop.append((n.tag, tuple(sorted(n.attrib.items()))))
        if n.tag == A + 'xfrm':
            crop.append((n.tag, tuple((k, n.get(k)) for k in ('rot', 'flipH', 'flipV') if k in n.attrib)))
        if n.tag in (V + 'shape', V + 'group', V + 'imagedata'):
            # VML crop/rotation/flip can live in attributes or style tokens.
            crop.append((n.tag, tuple(sorted((k, v) for k, v in n.attrib.items()
                         if 'crop' in k.casefold() or 'rotation' in k.casefold() or 'flip' in k.casefold()))))
            transforms = tuple(sorted(token.strip() for token in n.get('style', '').split(';')
                                      if token.partition(':')[0].strip() in ('rotation', 'flip')))
            if transforms:
                crop.append(('style-transforms', transforms))
    passive_drawing = deepcopy(drawing)
    # The existing passive package operation removes this explicitly named
    # opaque Office cache. No geometry/other drawing attribute is normalized.
    for element in passive_drawing.iter():
        element.attrib.pop('{urn:schemas-microsoft-com:office:office}gfxdata', None)
    return NativeArtRepresentation(
        _node_path(root, node), node.tag, attr, node.get(attr), rel.reltype,
        media_part, _hash(rel.target_part.blob), _node_path(root, drawing),
        _subtree_digest(drawing), _subtree_digest(passive_drawing),
        _privacy_drawing_digest(passive_drawing),
        _ancestor_context_digest(drawing),
        _node_path(root, unit), _subtree_digest(unit), tuple(crop))


def _physical_inventory(document, inspection, wanted):
    from app.monthly_report_native_layout import _header_image_occurrences
    results = defaultdict(list)
    parts = {str(part.partname).lstrip('/'): part for part in document.part.package.parts
             if hasattr(part, 'element') and (str(part.partname).startswith(('/word/header', '/word/footer'))
                                             or str(part.partname) == '/word/document.xml')}
    by_part = defaultdict(set)
    for item in wanted.values():
        by_part[item.part].add(item.id)
    for name, ids in by_part.items():
        part = parts.get(name)
        if part is None:
            _error('retained native part is missing')
        targets = {wanted[identity].position for identity in ids}
        if any(item.kind == 'unsupported' and item.part == name and item.position in targets
               for item in inspection.items):
            _error('unsupported native art unit cannot be reviewed as preservation')
        bindings = _header_image_occurrences(part, inspection,
            elements=part.element.body if name == 'word/document.xml' else None)
        seen_nodes = set()
        for node, attr, item in bindings:
            if item.id not in ids:
                continue
            if node in seen_nodes:
                _error('duplicate physical occurrence binding')
            seen_nodes.add(node)
            results[item.id].append(_representation(part, node, attr, item))
        for identity in ids:
            if not results[identity]:
                _error('missing or ambiguous physical native artwork binding')
            if name == 'word/document.xml':
                _cover_band_representations(part, wanted[identity], results[identity])
    if sum(map(len, results.values())) > MAX_REPRESENTATIONS:
        _error('physical artwork occurrence budget')
    return {key: tuple(value) for key, value in results.items()}


def native_art_inventory(original_path, source_view, profile, period):
    """Independently verify source semantics before offering preservation."""
    from app.monthly_report_operational_source import verify_source_view
    fresh = verify_source_view(original_path, source_view)
    return _native_art_inventory(original_path, fresh, profile, period)


def _native_art_inventory(original_path, source_view, profile, period):
    """Internal operation helper; source_view MUST already be independently verified."""
    if not isinstance(source_view, CompatibilityView):
        _error('explicit source view required')
    path = Path(original_path)
    if path.stat().st_size > MAX_VIEW_SOURCE_BYTES:
        _error('source exceeds narrow view budget')
    # A staged source can grow or be replaced between stat() and open().
    # Enforce the *same* narrow-artwork cap on the read itself, before hashing
    # or opening the Word package. Do not truncate, resave or alter the source.
    with path.open('rb') as stream:
        raw = stream.read(MAX_VIEW_SOURCE_BYTES + 1)
    if len(raw) > MAX_VIEW_SOURCE_BYTES:
        _error('source exceeds narrow view budget')
    if _hash(raw) != source_view.original_inspection.sha256:
        _error('immutable original changed')
    originals = {i.id: i for i in source_view.original_inspection.items}
    rendered = {i.id: i for i in source_view.rendition_inspection.items}
    bindings = {b.original_id: b for b in source_view.bindings}
    selected = []
    original_bands = native_cover_furniture_ids(source_view.original_inspection.items)
    rendition_bands = native_cover_furniture_ids(source_view.rendition_inspection.items)
    for item in originals.values():
        if not _eligible(item) and item.id not in original_bands:
            continue
        binding = bindings.get(item.id)
        if binding is not None and binding.status == 'archived-only' and binding.rendition_id is None:
            continue  # No rendered occurrence; no preservation/review authority.
        target = rendered.get(binding.rendition_id) if binding is not None else None
        if (binding is None or binding.status != 'retained' or target is None
                or not (_eligible(target) or item.id in original_bands and target.id in rendition_bands)
                or item.part != target.part
                or item.image_digest != target.image_digest):
            _error('eligible original has no unchanged retained rendition')
        selected.append((item, target))
    if len(selected) > MAX_OCCURRENCES:
        _error('native artwork occurrence budget')
    if not selected:
        # This feature grants no authority when no retained native-art target
        # exists. Do not impose new profile/site gates on legacy view callers.
        return NativeArtInventory(_canonical({
            'policy': POLICY, 'original_sha256': source_view.original_inspection.sha256,
            'source_view_receipt_sha256': source_view.receipt_sha256,
        }), ())
    scope = _scope(source_view, profile, period)
    original_nodes = _physical_inventory(Document(BytesIO(raw)), source_view.original_inspection,
                                        {a.id: a for a, _ in selected})
    del raw
    # python-docx package relationships form cycles. These private temporary
    # trees are no longer reachable from the immutable scalar proofs; release
    # them before allocating the second package, not merely before rendering.
    from app.monthly_report_pdf_image_budget import release_transient_word_memory
    release_transient_word_memory()
    rendition_nodes = _physical_inventory(Document(BytesIO(source_view.rendition_bytes)),
                                         source_view.rendition_inspection, {b.id: b for _, b in selected})
    release_transient_word_memory()
    result = []
    for original, target in selected:
        before, after = original_nodes[original.id], rendition_nodes[target.id]
        if (len(before) != len(after)
                or tuple(p.media_sha256 for p in before) != tuple(p.media_sha256 for p in after)
                or tuple(p.passive_drawing_sha256 for p in before) != tuple(p.passive_drawing_sha256 for p in after)
                or tuple(p.crop_orientation for p in before) != tuple(p.crop_orientation for p in after)):
            _error('native representation media/crop/orientation changed')
        result.append(NativeArtOccurrence(original.id, target.id, original.part, target.part,
            original.position, target.position, original.word_section, target.word_section,
            original.image_digest, target.image_digest, before, after,
            'cover_band' if original.id in original_bands else 'header_footer'))
    return NativeArtInventory(scope, tuple(result))


def make_native_art_review(inventory, *, actor, keep_native_ids, visually_reviewed_ids, suitable_ids=None):
    """Record separate preservation and visible-content suitability, never logo ownership."""
    if not isinstance(inventory, NativeArtInventory):
        _error('typed occurrence inventory required')
    expected = tuple(item.original_id for item in inventory.occurrences)
    if not expected:
        _error('no native artwork needs a preservation record')
    if (tuple(keep_native_ids) != expected or tuple(visually_reviewed_ids) != expected
            or suitable_ids is None or tuple(suitable_ids) != expected):
        _error('every exact eligible occurrence requires preservation, inspection and visible-content suitability review')
    if (not isinstance(actor, str) or not actor.strip() or len(actor) > 120
            or any(ord(c) < 32 or ord(c) == 127 for c in actor)):
        _error('a named review operator is required')
    return json.loads(_canonical({
        'schema': 1, 'policy': POLICY, 'scope': inventory.scope,
        'inventory_sha256': inventory.sha256,
        'dispositions': [{'original_id': item.original_id, 'rendition_id': item.rendition_id,
                          'occurrence_sha256': item.sha256, 'action': 'keep_native'}
                         for item in inventory.occurrences],
        'visual_review': {'kind': 'operator_source_art_inspection', 'actor': actor.strip(),
                          'original_ids': list(expected)},
        'visible_content_review': {
            'kind': 'operator_source_art_suitability', 'actor': actor.strip(),
            'original_ids': list(expected),
            'checks': ['relevance', 'no_visible_pricing', 'no_inappropriate_private_information'],
        },
    }))


def _validate_review(inventory, receipt):
    if not inventory.occurrences and receipt is None:
        return None
    if not isinstance(receipt, dict):
        _error('explicit native artwork preservation review is missing')
    try:
        actor = receipt['visual_review']['actor']
        expected = make_native_art_review(inventory, actor=actor,
            keep_native_ids=[v['original_id'] for v in receipt['dispositions']],
            visually_reviewed_ids=receipt['visual_review']['original_ids'],
            suitable_ids=receipt['visible_content_review']['original_ids'])
    except (KeyError, TypeError) as exc:
        raise CompatibilityError('Native artwork preservation review is malformed.') from exc
    # JSON canonical bytes distinguish bool/int and reject unserializable
    # extras; Python dictionary equality alone would accept schema=True.
    try:
        unchanged = _canonical(receipt) == _canonical(expected)
    except (TypeError, ValueError) as exc:
        raise CompatibilityError('Native artwork preservation review is malformed.') from exc
    if not unchanged:
        _error('saved source/view/scope/occurrence review changed')
    return NativeArtReview(inventory, _canonical(expected))


def verify_native_art_review(original_path, source_view, profile, period, receipt):
    """Public trust boundary: independently rederive source view and all bindings."""
    return _validate_review(native_art_inventory(original_path, source_view, profile, period), receipt)


def _verify_native_art_review(original_path, source_view, profile, period, receipt):
    """Internal boundary after independent source-view verification by caller."""
    return _validate_review(_native_art_inventory(original_path, source_view, profile, period), receipt)


def verify_native_art_output(output_bytes, review, *, stage='native', source_scope=None, emission_proof=None):
    """Check kept native drawings survive cleanup at their exact rendered paths.

    Strictly compare media bytes and containing drawing structure/geometry.
    Native output MUST match the exact precomputed result of the existing
    drawing-description privacy transform. The explicit 'rendition' audit
    stage instead requires the exact raw view tree; stages never substitute
    for each other. Media privacy is a separate boundary; this function does
    not normalize output for comparison.
    """
    if review is None:
        return
    if not isinstance(review, NativeArtReview) or not isinstance(output_bytes, bytes):
        _error('verified native artwork review context required')
    if stage not in ('native', 'rendition'):
        _error('unknown native artwork verification stage')
    if len(output_bytes) > MAX_VIEW_SOURCE_BYTES:
        _error('native output encoded-byte budget')
    _validate_review(review.inventory, review.receipt)
    expected_parts = None
    if source_scope is not None:
        from app.monthly_report_native_art_scope import NativeHeaderScope, verify_header_routing
        if (stage != 'native' or not isinstance(source_scope, NativeHeaderScope)
                or source_scope.original_sha256 != review.inventory.scope['original_sha256']
                or source_scope.rendition_sha256 != review.inventory.scope['rendition_sha256']
                or source_scope.receipt_sha256 != review.inventory.scope['source_view_receipt_sha256']):
            _error('header routing scope does not match the reviewed source view')
        # Positive source-selected closure, NEVER a subset inferred from output.
        # Full output and previews use the same independent route/boundary proof.
        verify_header_routing(output_bytes, source_scope, emission_proof=emission_proof)
        expected_parts = set(source_scope.expected_parts)
    from app.monthly_report_import import _resolve
    try:
        archive = ZipFile(BytesIO(output_bytes))
    except BadZipFile as exc:
        raise CompatibilityError('Native output is not a valid package.') from exc
    with archive:
        names = archive.namelist()
        if (len(names) != len(set(names)) or len(names) > 512
                or sum(i.file_size for i in archive.infolist()) > 32 * 1024 * 1024):
            _error('native output package budget/identity')
        by_part = defaultdict(list)
        for occurrence in review.inventory.occurrences:
            if occurrence.preservation_kind == 'cover_band':
                if stage == 'native' and source_scope is None:
                    _error('cover band output requires a positive source-selected placement scope')
                if source_scope is not None and occurrence.rendition_position not in source_scope.selected_positions:
                    continue  # Excluded by the source plan, never by observed output absence.
                if source_scope is not None and source_scope.selected_positions[0] != occurrence.rendition_position:
                    _error('cover band is not the exact first emitted source unit')
            elif expected_parts is not None and occurrence.rendition_part not in expected_parts:
                continue
            by_part[occurrence.rendition_part].extend(occurrence.rendition_representations)
        media_hashes = {}
        for part, proofs in by_part.items():
            try:
                root = _xml(archive.read(part))
                rel_name = str(Path(part).parent / '_rels' / (Path(part).name + '.rels'))
                relations_root = _xml(archive.read(rel_name))
                relationships = {n.get('Id'): n for n in relations_root}
                if len(relationships) != len(relations_root):
                    _error('duplicate native output relationship')
                for proof in proofs:
                    node = _path_node(root, proof.image_path)
                    drawing = _path_node(root, proof.drawing_path)
                    rel = relationships.get(node.get(proof.relationship_attribute))
                    if (node.tag != proof.image_tag or node not in set(drawing.iter())
                            or _ancestor_context_digest(drawing) != proof.ancestor_context_sha256
                            or _subtree_digest(drawing) != (
                                proof.output_drawing_sha256 if stage == 'native' else proof.drawing_sha256)
                            or rel is None or rel.get('Type') != IMAGE_REL
                            or rel.get('TargetMode', '').casefold() == 'external'):
                        _error('kept native drawing was removed, moved or changed')
                    target = _resolve(part, rel.get('Target', ''))
                    if target not in media_hashes:
                        media_hashes[target] = _hash(archive.read(target))
                    if target != proof.media_part or media_hashes[target] != proof.media_sha256:
                        _error('kept native image bytes changed')
            except (BadZipFile, KeyError, OSError, ValueError) as exc:
                if isinstance(exc, CompatibilityError):
                    raise
                raise CompatibilityError('Kept native artwork could not be verified in output.') from exc
