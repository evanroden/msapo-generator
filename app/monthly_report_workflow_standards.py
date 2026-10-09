"""Pinned ENFRA outage diagrams shared across contracts on persistent storage.

Only existing, saved and reviewed diagrams can seed the standards. Seeding fills
missing slots once; a different site's chart never replaces a shared standard.
Reports keep their own pinned content and independent immutable asset copies.
"""

from dataclasses import asdict, dataclass, replace
import hashlib

from app import monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes, refresh_asset_source_context
from app.monthly_report_model import ReportPeriod, ResolvedBlock


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


def _path():
    return library._root() / "workflow_standards"


def load_standards():
    path = _path() / "manifest.json"
    if not path.exists():
        return WorkflowStandards(0, ())
    value = library._read(path)
    try:
        workflows = tuple(WorkflowStandard(
            key=item["key"], block=library.block_from_dict(item["block"]),
            origin_contract=item["origin_contract"], origin_profile=item["origin_profile"],
            origin_fingerprint=item["origin_fingerprint"], saved_at=item["saved_at"],
        ) for item in value["workflows"])
        if (type(value["revision"]) is not int or value["revision"] < 1
                or len(workflows) > 2 or len({item.key for item in workflows}) != len(workflows)
                or any(item.key not in WORKFLOW_KEYS or item.block.key != item.key
                       or not _eligible(item.block) for item in workflows)):
            raise ValueError
        return WorkflowStandards(value["revision"], workflows)
    except (KeyError, TypeError, ValueError) as exc:
        raise library.LibraryError("The saved ENFRA outage procedures could not be read.") from exc


def _eligible(block):
    # A text-only placeholder is not a workflow diagram. Newly uploaded or
    # unreviewed pages are never promoted by merely opening a report.
    return bool(block and block.key in WORKFLOW_KEYS and block.source != "Omit"
                and block.asset_hashes and not block.ai_written and not block.ai_paragraphs
                and not pending_asset_indexes(block))


def read_asset(reference):
    if not library._ASSET.fullmatch(reference):
        raise library.LibraryError("Invalid shared workflow asset reference.")
    path = _path() / "assets" / reference
    try:
        if path.stat().st_size > library.MAX_ASSET_BYTES:
            raise library.LibraryError("The shared workflow picture exceeds the size limit.")
        raw = path.read_bytes()
    except OSError as exc:
        raise library.LibraryError("A shared ENFRA workflow picture is unavailable.") from exc
    if library.asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference:
        raise library.LibraryError("A shared ENFRA workflow picture failed its integrity check.")
    return raw


def _pinned(block):
    # The original source and approval are retained in the manifest origin.
    # Consumer reports refer to this immutable standard instead of depending
    # on a different contract's source-page records being present locally.
    identity = hashlib.sha256(library._json(asdict(block))).hexdigest()
    reference = "enfra-workflow-standard:" + identity
    # Only the reviewed diagrams are organization-wide. Adjacent imported
    # notes, contact tables, chart nodes and captions can identify one site;
    # none of those fields belongs in another contract's standard procedure.
    result = ResolvedBlock(
        block.key, "Library", asset_hashes=block.asset_hashes,
        references=(reference,),
        asset_provenance=tuple((asset, (reference,)) for asset in block.asset_hashes),
    )
    return approve_all_assets(result)


def _saved_blocks(contract, profile_key):
    """Newest reviewed persisted content wins while a global slot is empty."""
    candidates = []
    profile_path = library._profile_path(contract, profile_key) / "manifest.json"
    if profile_path.exists():
        value = library._read(profile_path)
        saved = library.load_profile(contract, profile_key)
        imported = library.draft_from_dict(value["bootstrap"]) if value.get("bootstrap") else None
        if imported and (imported.profile.contract, imported.profile.key) != (contract, profile_key):
            raise library.LibraryError("Imported workflow profile does not match its directory.")
        if not imported or not imported.synthetic:
            for key, version_id in saved.current:
                if key in WORKFLOW_KEYS:
                    version = saved.version(version_id)
                    candidates.append((version.updated_at, 0, version.block))
        if imported and not imported.synthetic:
            at = max((entry.get("at", "") for entry in value.get("audit", ())
                      if entry.get("action") == "report_import"), default="")
            candidates.extend((at, 1, refresh_asset_source_context(block, imported.sources))
                              for block in imported.blocks if block.key in WORKFLOW_KEYS)
    for path in library._profile_path(contract, profile_key, snapshots=True).glob("????-??.json"):
        year, month = path.stem.split("-")
        saved = library.load_snapshot(contract, profile_key, ReportPeriod(int(year), int(month)))
        if saved and not saved.draft.synthetic:
            candidates.extend((saved.generated_at, 2, refresh_asset_source_context(block, saved.draft.sources))
                              for block in saved.draft.blocks if block.key in WORKFLOW_KEYS)
    blocks = {}
    for _at, _priority, block in sorted(candidates, key=lambda item: item[:2], reverse=True):
        if block.key not in blocks and _eligible(block):
            blocks[block.key] = block
    return blocks


def seed_from_saved_profile(contract, profile_key):
    """Install missing standards from saved libraries/imports/report snapshots."""
    saved = _saved_blocks(contract, profile_key)
    with library._locked(_path()):
        current = load_standards()
        existing = {item.key: item for item in current.workflows}
        additions, assets = [], {}
        for key in WORKFLOW_KEYS:
            if key in existing:
                continue
            block = saved.get(key)
            if not _eligible(block):
                continue
            # Verify every page before writing a manifest. A partial or missing
            # source cannot become the standard used by other contracts.
            prepared = {ref: library.read_asset(contract, profile_key, ref) for ref in block.asset_hashes}
            assets.update(prepared)
            additions.append(WorkflowStandard(key, _pinned(block), contract, profile_key,
                                              block.fingerprint, library._now()))
        if not additions:
            return current
        for reference, raw in assets.items():
            library._atomic_write(_path() / "assets" / reference, raw)
        state = WorkflowStandards(current.revision + 1, (*current.workflows, *additions))
        encoded = library._json({"schema": 1, **asdict(state)})
        library._atomic_write(_path() / "history" / f"{state.revision:08d}.json", encoded)
        library._atomic_write(_path() / "manifest.json", encoded)
        return state


def _discover_saved_standards(draft):
    current = seed_from_saved_profile(draft.profile.contract, draft.profile.key)
    if len(current.workflows) == len(WORKFLOW_KEYS):
        return current
    # Discover snapshots too: Save progress does not create standing library
    # slots, and a report need not have originated from a DOCX import.
    profiles = []
    paths = [*((library._root() / "library").glob("*/*/manifest.json")),
             *((library._root() / "snapshots").glob("*/*/????-??.json"))]
    for path in sorted(paths):
        try:
            value = library._read(path)
            if "draft" in value:
                if value["draft"].get("synthetic", False):
                    continue
                profile = library.profile_from_dict(value["draft"]["profile"])
            else:
                profile = library.profile_from_dict(value["profile"])
            identity = (profile.contract, profile.key)
            if identity not in profiles and identity != (draft.profile.contract, draft.profile.key):
                profiles.append(identity)
        except (KeyError, ValueError, OSError):
            continue
    for contract, profile_key in profiles:
        try:
            current = seed_from_saved_profile(contract, profile_key)
        except (KeyError, ValueError, OSError):
            # An unrelated old/corrupt profile must not block this report.
            continue
        if len(current.workflows) == len(WORKFLOW_KEYS):
            break
    return current


def apply_defaults(draft, assets):
    """Fill missing workflows automatically; preserve every populated report."""
    current = load_standards()
    if not draft.synthetic and len(current.workflows) < len(WORKFLOW_KEYS):
        current = _discover_saved_standards(draft)
    blocks = {block.key: block for block in draft.blocks}
    for standard in current.workflows:
        block = blocks.get(standard.key)
        if block and (block.text.strip() or block.rows or block.extra_tables
                      or block.asset_hashes or block.org_nodes):
            continue
        # Empty historical Omit slots are filled because these are standing
        # ENFRA procedures included in every report, not per-site decisions.
        copied = {ref: read_asset(ref) for ref in standard.block.asset_hashes}
        assets.update(copied)
        blocks[standard.key] = standard.block
    return replace(draft, blocks=tuple(blocks.values()))
