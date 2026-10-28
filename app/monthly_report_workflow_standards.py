"""Explicit, versioned outage-procedure defaults for one contract.

The old global store is read-only migration input. Opening a report never seeds
standing data, discovers other contracts, or adopts legacy procedures.
"""
from dataclasses import asdict, dataclass, replace
import hashlib

from app import monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes, refresh_asset_source_context
from app.monthly_report_model import ResolvedBlock, profile_sections

WORKFLOW_KEYS = ("business_hours_workflow", "after_hours_workflow")


@dataclass(frozen=True)
class WorkflowStandard:
    key: str
    block: ResolvedBlock
    origin_contract: str
    origin_profile: str
    origin_fingerprint: str
    saved_at: str


@dataclass(frozen=True)
class WorkflowStandards:
    revision: int
    workflows: tuple[WorkflowStandard, ...]


def _contract(contract):
    from app.monthly_report_directory import canonical_contract
    # Match the directory's case/whitespace identity, never fuzzy aliases.
    value = canonical_contract(contract).casefold()
    library._contract_directory(value)  # Validate before any path is used.
    return value


def _path(contract=None):
    root = library._root() / "workflow_standards"
    return root if contract is None else root / "contracts" / library._contract_directory(_contract(contract))


def _eligible(block):
    return bool(block and block.key in WORKFLOW_KEYS and block.source != "Omit"
                and block.asset_hashes and not block.ai_written and not block.ai_paragraphs
                and not pending_asset_indexes(block))


def load_standards(contract=None):
    """Without a contract, read legacy migration input only; never use as defaults."""
    path = _path(contract) / "manifest.json"
    if not path.exists():
        return WorkflowStandards(0, ())
    try:
        value = library._read(path)
        if contract is not None and (value.get("workflow_scope") != "contract"
                                    or value.get("contract") != _contract(contract)):
            raise ValueError("Contract identity mismatch")
        workflows = tuple(WorkflowStandard(
            key=item["key"], block=library.block_from_dict(item["block"]),
            origin_contract=item["origin_contract"], origin_profile=item["origin_profile"],
            origin_fingerprint=item["origin_fingerprint"], saved_at=item["saved_at"],
        ) for item in value["workflows"])
        if (type(value["revision"]) is not int or value["revision"] < 1
                or len(workflows) > 2 or len({item.key for item in workflows}) != len(workflows)
                or any(item.key not in WORKFLOW_KEYS or item.block.key != item.key
                       or not _eligible(item.block) or not item.origin_profile
                       or not item.origin_fingerprint or not item.saved_at
                       or (contract is not None and _contract(item.origin_contract) != _contract(contract))
                       for item in workflows)):
            raise ValueError("Invalid procedure manifest")
        return WorkflowStandards(value["revision"], workflows)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise library.LibraryError("The saved outage procedures could not be read. Originals were retained.") from exc


def _verify_asset(reference, raw):
    if not library._ASSET.fullmatch(reference):
        raise library.LibraryError("Invalid workflow asset reference.")
    if len(raw) > library.MAX_ASSET_BYTES:
        raise library.LibraryError("The workflow picture exceeds the size limit.")
    if library.asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference:
        raise library.LibraryError("A workflow picture failed its integrity check.")
    return raw


def read_asset(reference, *, contract=None):
    if not library._ASSET.fullmatch(reference):
        raise library.LibraryError("Invalid workflow asset reference.")
    path = _path(contract) / "assets" / reference
    try:
        with path.open("rb") as source:
            raw = source.read(library.MAX_ASSET_BYTES + 1)
    except OSError as exc:
        raise library.LibraryError("A saved workflow picture is unavailable.") from exc
    return _verify_asset(reference, raw)


def _pinned(block, contract):
    identity = hashlib.sha256(library._json((_contract(contract), asdict(block)))).hexdigest()
    reference = "contract-workflow-standard:v1:" + identity
    # Share the reviewed diagram only. Site notes, contacts, chart nodes and
    # captions remain in the originating report, not in another site's default.
    return approve_all_assets(ResolvedBlock(
        block.key, "Library", asset_hashes=block.asset_hashes, references=(reference,),
        asset_provenance=tuple((asset, (reference,)) for asset in block.asset_hashes),
    ))


def _publish(contract, block, assets, *, origin_profile, origin_fingerprint,
             expected_revision, actor, confirmed):
    actor = library._confirmation(actor, confirmed)
    if type(expected_revision) is not int or expected_revision < 0:
        raise library.LibraryError("Review the current contract procedure version before saving.")
    if not _eligible(block):
        raise library.LibraryError("Include and review every procedure picture before saving a contract default.")
    prepared = {ref: _verify_asset(ref, assets[ref]) for ref in block.asset_hashes}
    pinned = _pinned(block, contract)
    path = _path(contract)
    with library._locked(path):
        current = load_standards(contract)
        if current.revision != expected_revision:
            raise library.RevisionConflict("Contract procedures changed. Review the current version before saving again.")
        previous = next((item for item in current.workflows if item.key == block.key), None)
        if (previous and previous.block == pinned and previous.origin_profile == origin_profile
                and previous.origin_fingerprint == origin_fingerprint):
            return current
        item = WorkflowStandard(block.key, pinned, _contract(contract), origin_profile,
                                origin_fingerprint, library._now())
        entries = {entry.key: entry for entry in current.workflows}
        entries[block.key] = item
        state = WorkflowStandards(current.revision + 1,
                                  tuple(entries[key] for key in WORKFLOW_KEYS if key in entries))
        for ref, raw in prepared.items():
            library._atomic_write(path / "assets" / ref, raw)
        raw = library._json({"schema": 1, "workflow_scope": "contract", "contract": _contract(contract),
                             "actor": actor, **asdict(state)})
        library._atomic_write(path / "history" / f"{state.revision:08d}.json", raw)
        library._atomic_write(path / "manifest.json", raw)
        return state


def save_standard(draft, block, assets, *, expected_revision, expected_fingerprint, confirmed):
    """An explicit report action publishes only this contract's reviewed picture."""
    if draft.synthetic:
        raise library.LibraryError("Demonstration reports cannot change contract procedures.")
    if block.fingerprint != expected_fingerprint:
        raise library.RevisionConflict("This report's procedure changed. Review it before saving a contract default.")
    current = next((b for b in draft.blocks if b.key == block.key), None)
    if current != block:
        raise library.RevisionConflict("The selected procedure no longer matches this report.")
    checked = refresh_asset_source_context(block, draft.sources)
    if not _eligible(checked):
        raise library.LibraryError("Include and review every procedure picture before saving a contract default.")
    prepared = {ref: (assets[ref] if ref in assets else library.read_asset(
        draft.profile.contract, draft.profile.key, ref)) for ref in checked.asset_hashes}
    return _publish(draft.profile.contract, checked, prepared,
                    origin_profile=draft.profile.key, origin_fingerprint=checked.fingerprint,
                    expected_revision=expected_revision, actor=draft.prepared_by, confirmed=confirmed)


def legacy_candidate(contract, key):
    """Only expose a legacy procedure whose recorded origin matches this contract."""
    return next((item for item in load_standards().workflows
                 if item.key == key and _contract(item.origin_contract) == _contract(contract)), None)


def adopt_legacy(draft, key, *, expected_revision, expected_legacy_fingerprint, confirmed):
    if draft.synthetic:
        raise library.LibraryError("Demonstration reports cannot change contract procedures.")
    item = legacy_candidate(draft.profile.contract, key)
    if item is None or item.block.fingerprint != expected_legacy_fingerprint:
        raise library.RevisionConflict("The legacy procedure changed or belongs to another contract. Review it again.")
    assets = {ref: read_asset(ref) for ref in item.block.asset_hashes}
    return _publish(draft.profile.contract, item.block, assets,
                    origin_profile=item.origin_profile, origin_fingerprint=item.origin_fingerprint,
                    expected_revision=expected_revision, actor=draft.prepared_by, confirmed=confirmed)


def use_standard(draft, block, assets, *, expected_revision, expected_fingerprint):
    """Explicitly replace diagram pages, preserving the report's notes and tables."""
    if block.fingerprint != expected_fingerprint:
        raise library.RevisionConflict("The report procedure changed. Review it before replacing its pages.")
    current = load_standards(draft.profile.contract)
    if current.revision != expected_revision:
        raise library.RevisionConflict("Contract procedures changed. Review the current version before using it.")
    item = next((item for item in current.workflows if item.key == block.key), None)
    if item is None:
        raise library.LibraryError("No approved procedure is saved for this contract.")
    prepared = {ref: read_asset(ref, contract=draft.profile.contract) for ref in item.block.asset_hashes}
    result = replace(block, source="This month", asset_hashes=item.block.asset_hashes,
                     asset_captions=(), asset_instances=(), asset_provenance=item.block.asset_provenance,
                     references=tuple(dict.fromkeys((*block.references, *item.block.references))),
                     reviewed_fingerprint="", client_reviewed_fingerprint="", client_asset_reviews=())
    result = approve_all_assets(result)
    assets.update(prepared)
    return result


def apply_defaults(draft, assets):
    """Read selected-contract defaults only; keep populated and omitted slots pinned."""
    current = load_standards(draft.profile.contract)
    blocks = {block.key: block for block in draft.blocks}
    prepared = {}
    excluded = {spec.key for section in (*draft.sections, *profile_sections(draft.profile))
                if not section.included or section.key in draft.profile.excluded_sections
                for spec in section.blocks}
    for standard in current.workflows:
        if standard.key in excluded:
            continue
        block = blocks.get(standard.key)
        if block and (block.source == "Omit" or block.text.strip() or block.rows or block.extra_tables
                      or block.asset_hashes or block.org_nodes):
            continue
        prepared.update({ref: read_asset(ref, contract=draft.profile.contract)
                         for ref in standard.block.asset_hashes})
        blocks[standard.key] = standard.block
    # A later corrupt picture must not leave partial additions in caller assets.
    assets.update(prepared)
    return replace(draft, blocks=tuple(blocks.values()))
