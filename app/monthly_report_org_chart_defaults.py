"""Explicit contract chart defaults and single-site overrides; never migrate on read.

Reports contain copies, not live pointers. Existing profile charts remain local
until the operator explicitly publishes them at the displayed scope.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import re
from app import monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets, asset_context, pending_asset_indexes, refresh_asset_source_context
from app.monthly_report_model import ResolvedBlock

@dataclass(frozen=True)
class ChartDefault:
    site_key: str
    block: ResolvedBlock
    origin_profile: str
    origin_fingerprint: str
    saved_at: str

@dataclass(frozen=True)
class ChartDefaults:
    revision: int = 0
    charts: tuple[ChartDefault, ...] = ()


def _contract(contract):
    from app.monthly_report_directory import canonical_contract
    value = canonical_contract(contract).casefold()
    library._contract_directory(value)
    return value


def _path(contract):
    return library._root() / 'org_chart_defaults' / library._contract_directory(_contract(contract))


def _site(profile, scope):
    if scope == 'contract':
        return ''
    if scope != 'site' or len(profile.facilities) != 1:
        raise library.LibraryError('A site chart requires exactly one selected site.')
    return library._valid_key(profile.facilities[0].key)


def eligible(block):
    from app.monthly_report_visuals import org_chart_problem, validate_org
    if block and block.org_nodes:
        try:
            validate_org(block.org_nodes)
        except ValueError:
            return False
    return bool(block and block.key == 'org_chart' and block.source != 'Omit'
        and not block.ai_written and not block.ai_paragraphs
        and bool(block.asset_hashes) != bool(block.org_nodes)
        and not pending_asset_indexes(block)
        and (not block.org_nodes or not org_chart_problem(block.org_nodes)))


def load_defaults(contract):
    path = _path(contract) / 'manifest.json'
    if not path.exists():
        return ChartDefaults()
    try:
        data = library._read(path)
        if data.get('schema') != 1 or data.get('contract') != _contract(contract):
            raise ValueError('Scope mismatch')
        items = tuple(ChartDefault(v['site_key'],library.block_from_dict(v['block']),
                    v['origin_profile'],v['origin_fingerprint'],v['saved_at']) for v in data['charts'])
        if type(data['revision']) is not int or data['revision'] < 1 or len({v.site_key for v in items}) != len(items):
            raise ValueError('Invalid revision or duplicate scope')
        for item in items:
            if item.site_key:
                library._valid_key(item.site_key)
            if not eligible(item.block) or not item.origin_profile or not item.origin_fingerprint or not item.saved_at:
                raise ValueError('Invalid chart')
        return ChartDefaults(data['revision'],items)
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        raise library.LibraryError('Saved chart defaults could not be read. Originals were retained.') from exc


def selected_default(profile, state):
    # A combined-site report never guesses which site's chart represents all sites.
    site = profile.facilities[0].key if len(profile.facilities) == 1 else None
    return next((v for v in state.charts if site is not None and v.site_key == site),None) or next(
        (v for v in state.charts if not v.site_key),None)


def _verify(reference, raw):
    if (not library._ASSET.fullmatch(reference) or len(raw) > library.MAX_ASSET_BYTES
            or library.asset_reference(raw,reference.rsplit('.',1)[-1]) != reference):
        raise library.LibraryError('Chart picture failed its size or integrity check.')
    return raw


def read_asset(contract, reference):
    if not library._ASSET.fullmatch(reference):
        raise library.LibraryError('Invalid chart picture reference.')
    try:
        with (_path(contract) / 'assets' / reference).open('rb') as source:
            return _verify(reference, source.read(library.MAX_ASSET_BYTES + 1))
    except OSError as exc:
        raise library.LibraryError('A saved chart picture is unavailable.') from exc


def source_pages_allowed(block, sources):
    from app.monthly_report_content_policy import page_allowed
    index = {s.id:s for s in sources}
    for ref in {r for i in range(len(block.asset_hashes)) for r in asset_context(block,i)}:
        if ref.startswith(('docx:','contract-org-chart:v1:','asset-source-context:v1:')):
            continue
        parts = ref.split(':')
        if len(parts) != 3 or not parts[1].isdigit() or not re.fullmatch(r'[a-f0-9]{64}',parts[2]):
            return False
        source, page = index.get(parts[0]), int(parts[1])
        if source is None or page not in source.selected_pages or not 1 <= page <= len(source.page_texts) or not page_allowed(source,page):
            return False
    return True


def save_default(draft, block, assets, *, scope, expected_revision, expected_fingerprint, confirmed):
    actor = library._confirmation(draft.prepared_by,confirmed)
    if draft.synthetic:
        raise library.LibraryError('Demonstration reports cannot publish chart defaults.')
    if type(expected_revision) is not int or expected_revision < 0:
        raise library.LibraryError('Review the saved chart version first.')
    if block.fingerprint != expected_fingerprint or next((b for b in draft.blocks if b.key=='org_chart'),None) != block:
        raise library.RevisionConflict('This chart changed. Review it before publishing.')
    site = _site(draft.profile,scope)
    checked = refresh_asset_source_context(block,draft.sources)
    if not eligible(checked) or not source_pages_allowed(checked,draft.sources):
        raise library.LibraryError('Include and review the chart and its source pages before publishing.')
    prepared = {ref:_verify(ref,assets[ref] if ref in assets else library.read_asset(draft.profile.contract,draft.profile.key,ref)) for ref in block.asset_hashes}
    identity = hashlib.sha256(library._json((_contract(draft.profile.contract),site,asdict(checked)))).hexdigest()
    reference = 'contract-org-chart:v1:' + identity
    # Share chart content only, not neighboring contacts, notes or tables.
    pinned = approve_all_assets(ResolvedBlock('org_chart','Library',asset_hashes=checked.asset_hashes,
                org_nodes=checked.org_nodes,references=(reference,),
                asset_provenance=tuple((ref,(reference,)) for ref in checked.asset_hashes)))
    path = _path(draft.profile.contract)
    with library._locked(path):
        current = load_defaults(draft.profile.contract)
        if current.revision != expected_revision:
            raise library.RevisionConflict('Saved charts changed. Review the latest version before publishing.')
        item = ChartDefault(site,pinned,draft.profile.key,checked.fingerprint,library._now())
        entries = {v.site_key:v for v in current.charts}; entries[site] = item
        state = ChartDefaults(current.revision+1,tuple(entries[k] for k in sorted(entries)))
        for ref,raw in prepared.items():
            target=path/'assets'/ref
            if target.exists():
                _verify(ref,target.read_bytes())
            else:
                library._atomic_write(target,raw)
        raw=library._json({'schema':1,'contract':_contract(draft.profile.contract),'actor':actor,**asdict(state)})
        library._atomic_write(path/'history'/f'{state.revision:08d}.json',raw)
        library._atomic_write(path/'manifest.json',raw)
    return state


def use_default(draft, block, assets, *, expected_revision, expected_fingerprint):
    if block.fingerprint != expected_fingerprint or next((b for b in draft.blocks if b.key=='org_chart'),None) != block:
        raise library.RevisionConflict('This chart changed. Review before replacing it.')
    state=load_defaults(draft.profile.contract)
    if state.revision != expected_revision:
        raise library.RevisionConflict('Saved charts changed. Review the latest version first.')
    item=selected_default(draft.profile,state)
    if item is None:
        raise library.LibraryError('No approved chart is saved for this scope.')
    prepared={ref:read_asset(draft.profile.contract,ref) for ref in item.block.asset_hashes}
    references=block.references
    if not block.text.strip() and not block.rows and not block.extra_tables and not block.ai_paragraphs:
        # No surrounding authored content relies on the replaced chart's provenance.
        references=()
    result=replace(block,source='This month',org_nodes=item.block.org_nodes,asset_hashes=item.block.asset_hashes,
        asset_captions=(),asset_instances=(),asset_provenance=item.block.asset_provenance,
        references=tuple(dict.fromkeys((*references,*item.block.references))),
        reviewed_fingerprint='',client_reviewed_fingerprint='',client_asset_reviews=())
    assets.update(prepared)
    return approve_all_assets(result)


def apply_defaults(draft, assets, *, initial_profile_state=None):
    """Only called for fresh reports; populated, omitted and excluded copies win."""
    block=next((b for b in draft.blocks if b.key=='org_chart'),None)
    if block is None or block.source=='Omit':
        return draft
    # Only _initial_draft supplies this proof: a just-copied profile library
    # chart is a fallback, not an explicit site override. Never use this path
    # for imported, resumed, carried or manually authored report copies.
    initial_seed = (initial_profile_state is not None
        and initial_profile_state.profile == draft.profile
        and initial_profile_state.block('org_chart') == block)
    if not initial_seed and (block.text.strip() or block.rows or block.extra_tables or block.asset_hashes or block.org_nodes or block.ai_paragraphs):
        return draft
    if not any(s.included and s.key not in draft.profile.excluded_sections and any(b.key=='org_chart' for b in s.blocks) for s in draft.sections):
        return draft
    state=load_defaults(draft.profile.contract)
    if selected_default(draft.profile,state) is None:
        return draft
    updated=use_default(draft,block,assets,expected_revision=state.revision,expected_fingerprint=block.fingerprint)
    return replace(draft,blocks=tuple(updated if b.key=='org_chart' else b for b in draft.blocks))
