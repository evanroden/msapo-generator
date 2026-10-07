"""Versioned report library on EPC_DATA_DIR, never in the public repository.

Each profile has one atomic manifest and immutable content-addressed assets.
An OS advisory lock plus an expected revision protects read/confirm/write from
lost updates. A crash can leave an unreferenced asset, never a half-written head.
Snapshots pin resolved values, rather than following the library's latest head.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from app.memory import _data_dir
from app.monthly_report_model import (
    BLOCK_SOURCES, BlockSpec, ColumnSpec, Facility, ReportDraft, ReportPeriod, ReportProfile,
    ResolvedBlock, SectionSpec, ReportSource, default_sections, layout_blocks, used_asset_references,
)


MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 30 * 1024 * 1024
_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")
_ASSET = re.compile(r"[0-9a-f]{64}\.(?:png|jpg)\Z")


class LibraryError(ValueError):
    """Visible persistence failure; never pretend an unsuccessful save worked."""


class RevisionConflict(LibraryError):
    pass


@dataclass(frozen=True)
class LibraryVersion:
    id: str
    slot: str
    label: str
    block: ResolvedBlock
    actor: str
    updated_at: str
    spec: BlockSpec | None = None


@dataclass(frozen=True)
class LibraryState:
    profile: ReportProfile
    revision: int
    versions: tuple[LibraryVersion, ...]
    current: tuple[tuple[str, str], ...]
    audit: tuple[dict, ...]

    def version(self, version_id: str) -> LibraryVersion:
        for version in self.versions:
            if version.id == version_id:
                return version
        raise LibraryError("That library version no longer exists.")

    def block(self, slot: str) -> ResolvedBlock | None:
        version_id = dict(self.current).get(slot)
        return self.version(version_id).block if version_id else None


@dataclass(frozen=True)
class SavedReport:
    draft: ReportDraft
    generated_at: str
    revision: int
    open_issues: tuple[str, ...] = ()
    pending_proposals: tuple[str, ...] = ()
    entered_editor: str = ""


def _json(value) -> bytes:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_JSON_BYTES:
        raise LibraryError("Report metadata exceeds the storage limit.")
    return encoded


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_key(value: str) -> str:
    if not _KEY.fullmatch(value):
        raise LibraryError("Use a key containing lowercase letters, digits, underscores or hyphens.")
    return value


def _contract_directory(contract: str) -> str:
    if not contract.strip() or len(contract) > 200:
        raise LibraryError("A valid contract is required.")
    slug = re.sub(r"[^a-z0-9]+", "-", contract.casefold()).strip("-")[:50] or "contract"
    # The hash prevents two punctuation variants from sharing one directory.
    return slug + "-" + hashlib.sha256(contract.encode()).hexdigest()[:12]


def _root() -> Path:
    return _data_dir() / "monthly_reports"


def _profile_path(contract: str, key: str, *, snapshots: bool = False) -> Path:
    return _root() / ("snapshots" if snapshots else "library") / _contract_directory(contract) / _valid_key(key)


def _read(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise LibraryError("Saved report metadata exceeds the storage limit.")
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict) or value.get("schema") != 1:
            raise LibraryError("Unsupported report storage schema; existing data was preserved.")
        return value
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LibraryError("Saved report data could not be read; existing data was preserved.") from exc


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as output:
            temporary = Path(output.name)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        # Flush the directory entry as well as the file on Render's Linux disk.
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _locked(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    with (path / ".write-lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.write(b"0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def profile_from_dict(value: dict) -> ReportProfile:
    try:
        return ReportProfile(
            contract=value["contract"], key=_valid_key(value["key"]), title=value["title"],
            facilities=tuple(Facility(f["key"], f["title"], tuple(f.get("aliases", ()))) for f in value["facilities"]),
            scope_type=value.get("scope_type", "individual"),
            section_order=tuple(value.get("section_order", ())),
            default_block_sources=tuple(tuple(pair) for pair in value.get("default_block_sources", ())),
            template=value.get("template", "monthly_review_v1"),
            excluded_sections=tuple(value.get("excluded_sections", ())),
            block_overrides=tuple(spec_from_dict(b) for b in value.get("block_overrides", ())),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise LibraryError("Invalid report profile.") from exc


def block_from_dict(value: dict) -> ResolvedBlock:
    try:
        return ResolvedBlock(
            key=value["key"], source=value["source"], text=value.get("text", ""),
            rows=tuple(tuple(str(cell) for cell in row) for row in value.get("rows", ())),
            asset_hashes=tuple(value.get("asset_hashes", ())), references=tuple(value.get("references", ())),
            ai_written=value.get("ai_written", False), reviewed_fingerprint=value.get("reviewed_fingerprint", ""),
            pending_library_save=value.get("pending_library_save", False),
            asset_captions=tuple(value.get("asset_captions", ())),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LibraryError("Invalid saved report block.") from exc


def spec_from_dict(value: dict) -> BlockSpec:
    return BlockSpec(value["key"], value["type"], value.get("required", False),
                     tuple(value.get("allowed_sources", BLOCK_SOURCES)),
                     tuple(value.get("stock_text_keys", ())),
                     tuple(ColumnSpec(**c) for c in value.get("columns", ())))


def draft_from_dict(value: dict) -> ReportDraft:
    try:
        sections = tuple(SectionSpec(
            key=s["key"], number=s["number"], title=s["title"],
            blocks=tuple(BlockSpec(
                key=b["key"], type=b["type"], required=b["required"],
                allowed_sources=tuple(b["allowed_sources"]), stock_text_keys=tuple(b["stock_text_keys"]),
                columns=tuple(ColumnSpec(**c) for c in b["columns"]),
            ) for b in s["blocks"]), divider_asset=s.get("divider_asset", ""),
            included=s.get("included", True), appendix=s.get("appendix", False),
        ) for s in value["sections"])
        return ReportDraft(
            profile=profile_from_dict(value["profile"]), period=ReportPeriod(**value["period"]),
            prepared_by=value["prepared_by"], sections=sections,
            blocks=tuple(block_from_dict(b) for b in value["blocks"]),
            address_line=value.get("address_line", ""), synthetic=value.get("synthetic", False),
            sources=tuple(source_from_dict(s) for s in value.get("sources", ())),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LibraryError("Invalid report snapshot.") from exc


def source_from_dict(value: dict) -> ReportSource:
    fields = dict(value)
    for key in ("tags", "page_texts", "selected_pages", "needs_vision", "notices"):
        fields[key] = tuple(fields.get(key, ()))
    fields["captions"] = tuple(tuple(v) for v in fields.get("captions", ()))
    return ReportSource(**fields)


def _state(value: dict) -> LibraryState:
    try:
        return LibraryState(
            profile_from_dict(value["profile"]), value["revision"],
            tuple(LibraryVersion(v["id"], v["slot"], v["label"], block_from_dict(v["block"]), v["actor"], v["updated_at"],
                                 spec_from_dict(v["spec"]) if v.get("spec") else None)
                  for v in value.get("versions", ())),
            tuple(tuple(item) for item in value.get("current", ())), tuple(value.get("audit", ())),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LibraryError("Invalid library manifest.") from exc


def load_profile(contract: str, key: str) -> LibraryState:
    result = _state(_read(_profile_path(contract, key) / "manifest.json"))
    if (result.profile.contract, result.profile.key) != (contract, key):
        raise LibraryError("Library profile identity does not match its directory.")
    return result


def list_profiles(contract: str) -> tuple[ReportProfile, ...]:
    path = _root() / "library" / _contract_directory(contract)
    profiles = [_state(_read(p)).profile for p in sorted(path.glob("*/manifest.json"))]
    if any(p.contract != contract for p in profiles):
        raise LibraryError("Library contains a mismatched contract.")
    return tuple(sorted(profiles, key=lambda p: p.title.casefold()))


def _confirmation(actor: str, confirmed: bool) -> str:
    if confirmed is not True or not actor.strip():
        raise LibraryError("Confirm this library change and enter the editor's name.")
    if len(actor.strip()) > 160:
        raise LibraryError("Editor name is too long.")
    return actor.strip()


def _expected(value: dict, revision: int) -> None:
    if value["revision"] != revision:
        raise RevisionConflict("Someone changed this profile. Reload and review the new version before saving.")


def save_profile(profile: ReportProfile, *, expected_revision: int, actor: str, confirmed: bool) -> LibraryState:
    actor = _confirmation(actor, confirmed)
    if not profile.title.strip():
        raise LibraryError("Enter the report profile title.")
    skeleton = default_sections()
    if profile.section_order and (len(set(profile.section_order)) != len(profile.section_order)
                                 or set(profile.section_order) != {s.key for s in skeleton}):
        raise LibraryError("Default section order must contain every section exactly once.")
    if not set(profile.excluded_sections) <= {s.key for s in skeleton}:
        raise LibraryError("Unknown omitted section.")
    known_blocks = {b.key for s in skeleton for b in s.blocks} | {b.key for b in layout_blocks()}
    if any(key not in known_blocks or source not in BLOCK_SOURCES for key, source in profile.default_block_sources):
        raise LibraryError("Invalid default block source.")
    _validate_overrides(profile.block_overrides)
    path = _profile_path(profile.contract, profile.key)
    with _locked(path):
        manifest = path / "manifest.json"
        value = _read(manifest) if manifest.exists() else {"schema": 1, "revision": 0, "versions": [], "current": [], "audit": []}
        _expected(value, expected_revision)
        before = hashlib.sha256(_json(value.get("profile", {}))).hexdigest()
        value["profile"] = asdict(profile)
        value["revision"] += 1
        value["audit"].append({"action": "profile", "actor": actor, "at": _now(), "old_hash": before,
                               "new_hash": hashlib.sha256(_json(value["profile"])).hexdigest()})
        # Retain whole manifests as well as block versions so profile edits can
        # be restored without reconstructing membership from an audit message.
        _atomic_write(path / "history" / f'{value["revision"]:08d}.json', _json(value))
        _atomic_write(manifest, _json(value))
        return _state(value)


def _validate_overrides(overrides: tuple[BlockSpec, ...]) -> None:
    specs = {b.key: b for s in default_sections() for b in s.blocks}
    if len({b.key for b in overrides}) != len(overrides):
        raise LibraryError("Duplicate table override.")
    for b in overrides:
        if (b.key not in specs or b.type != "table" or
                (specs[b.key].type not in ("table", "work_order_grid") and b.key != "contact_matrix") or
                not b.columns or len(b.columns) > 100 or len({c.title for c in b.columns}) != len(b.columns)):
            raise LibraryError("Invalid imported table schema.")


def save_import(contract: str, key: str, blocks: tuple[ResolvedBlock, ...], *,
                overrides: tuple[BlockSpec, ...] = (), assets: tuple[tuple[str, bytes], ...] = (),
                expected_revision: int, actor: str, confirmed: bool) -> LibraryState:
    """Apply a confirmed set of mappings as one manifest revision, or none.

    Immutable assets/history may survive a failed head write. Existing defaults
    remain intact, and a later retry is guarded by the same expected revision.
    """
    actor = _confirmation(actor, confirmed)
    _validate_overrides(overrides)
    known = {b.key for s in default_sections() for b in s.blocks} | {b.key for b in layout_blocks()}
    if not blocks or len({b.key for b in blocks}) != len(blocks) or any(b.key not in known for b in blocks):
        raise LibraryError("Choose unique valid destinations for imported content.")
    path = _profile_path(contract, key)
    with _locked(path):
        value = _read(path / "manifest.json")
        _expected(value, expected_revision)
        profile = profile_from_dict(value["profile"])
        specs = {b.key: b for b in profile.block_overrides}
        specs.update({b.key: b for b in overrides})
        defaults = dict(profile.default_block_sources)
        defaults.update({b.key: "Library" for b in blocks})
        profile = replace(profile, block_overrides=tuple(specs.values()), default_block_sources=tuple(sorted(defaults.items())))
        _validate_overrides(profile.block_overrides)
        for reference, raw in assets:
            if not _ASSET.fullmatch(reference) or asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference:
                raise LibraryError("Invalid imported image.")
            _atomic_write(path / "assets" / reference, raw)
        for block in blocks:
            for reference in block.asset_hashes:
                read_asset(contract, key, reference)
        current = dict(value["current"])
        value["revision"] += 1
        at = _now()
        for block in blocks:
            old = next((v for v in value["versions"] if v["id"] == current.get(block.key)), None)
            block = replace(block, source="Library")
            version_id = hashlib.sha256(_json({"revision": value["revision"], "block": asdict(block)})).hexdigest()
            value["versions"].append(asdict(LibraryVersion(version_id, block.key, "DOCX import · " + block.key, block, actor, at, specs.get(block.key))))
            current[block.key] = version_id
            value["audit"].append({"action": "import", "slot": block.key, "actor": actor, "at": at,
                                   "old_hash": block_from_dict(old["block"]).fingerprint if old else "", "new_hash": block.fingerprint})
        value["profile"] = asdict(profile)
        value["current"] = sorted(current.items())
        raw = _json(value)
        _atomic_write(path / "history" / f'{value["revision"]:08d}.json', raw)
        _atomic_write(path / "manifest.json", raw)
        return _state(value)


def asset_reference(raw: bytes, extension: str) -> str:
    if extension not in ("png", "jpg") or not raw or len(raw) > MAX_ASSET_BYTES:
        raise LibraryError("Only bounded normalized PNG/JPEG assets may enter the library.")
    return hashlib.sha256(raw).hexdigest() + "." + extension


def read_asset(contract: str, key: str, reference: str) -> bytes:
    if not _ASSET.fullmatch(reference):
        raise LibraryError("Invalid asset reference.")
    path = _profile_path(contract, key) / "assets" / reference
    try:
        if path.stat().st_size > MAX_ASSET_BYTES:
            raise LibraryError("Asset exceeds the size limit.")
        raw = path.read_bytes()
    except OSError as exc:
        raise LibraryError("A referenced library asset is unavailable.") from exc
    if hashlib.sha256(raw).hexdigest() != reference.split(".")[0]:
        raise LibraryError("A library asset failed its integrity check.")
    return raw


def replace_block(contract: str, key: str, slot: str, block: ResolvedBlock, *, label: str,
                  expected_revision: int, actor: str, confirmed: bool,
                  assets: tuple[tuple[str, bytes], ...] = (), restore_spec: BlockSpec | None = None,
                  restoring: bool = False) -> LibraryState:
    actor = _confirmation(actor, confirmed)
    _valid_key(slot)
    if block.key != slot:
        raise LibraryError("The replacement block does not match its destination.")
    path = _profile_path(contract, key)
    with _locked(path):
        value = _read(path / "manifest.json")
        _expected(value, expected_revision)
        current = dict(value["current"])
        old_version = next((v for v in value["versions"] if v["id"] == current.get(slot)), None)
        for reference, raw in assets:
            if not _ASSET.fullmatch(reference) or asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference:
                raise LibraryError("Invalid replacement asset.")
            _atomic_write(path / "assets" / reference, raw)
        for reference in block.asset_hashes:
            read_asset(contract, key, reference)
        value["revision"] += 1
        version_id = hashlib.sha256(_json({"revision": value["revision"], "block": asdict(block)})).hexdigest()
        profile = profile_from_dict(value["profile"])
        specs = {b.key: b for b in profile.block_overrides}
        if restoring:
            specs.pop(slot, None)
            if restore_spec:
                if restore_spec.key != slot:
                    raise LibraryError("Restored table schema does not match its destination.")
                specs[slot] = restore_spec
            _validate_overrides(tuple(specs.values()))
            value["profile"] = asdict(replace(profile, block_overrides=tuple(specs.values())))
        version = LibraryVersion(version_id, slot, label.strip() or slot, block, actor, _now(), specs.get(slot))
        value["versions"].append(asdict(version))
        current[slot] = version_id
        value["current"] = sorted(current.items())
        value["audit"].append({"action": "replace", "slot": slot, "actor": actor, "at": version.updated_at,
                               "old_hash": block_from_dict(old_version["block"]).fingerprint if old_version else "",
                               "new_hash": block.fingerprint})
        raw = _json(value)
        _atomic_write(path / "history" / f'{value["revision"]:08d}.json', raw)
        _atomic_write(path / "manifest.json", raw)
        return _state(value)


def restore_block(contract: str, key: str, version_id: str, *, expected_revision: int,
                  actor: str, confirmed: bool) -> LibraryState:
    version = load_profile(contract, key).version(version_id)
    return replace_block(contract, key, version.slot, version.block, label=version.label,
                         expected_revision=expected_revision, actor=actor, confirmed=confirmed,
                         restore_spec=version.spec, restoring=True)


def restore_profile(contract: str, key: str, revision: int, *, expected_revision: int,
                    actor: str, confirmed: bool) -> LibraryState:
    if type(revision) is not int or revision < 1:
        raise LibraryError("Invalid profile revision.")
    historical = _read(_profile_path(contract, key) / "history" / f"{revision:08d}.json")
    profile = profile_from_dict(historical["profile"])
    if (profile.contract, profile.key) != (contract, key):
        raise LibraryError("Historical profile identity mismatch.")
    return save_profile(profile, expected_revision=expected_revision, actor=actor, confirmed=confirmed)


def save_snapshot(draft: ReportDraft, *, expected_revision: int, open_issues: tuple[str, ...] = (),
                  pending_proposals: tuple[str, ...] = (), assets: tuple[tuple[str, bytes], ...] = (),
                  entered_editor: str = "") -> SavedReport:
    path = _profile_path(draft.profile.contract, draft.profile.key, snapshots=True)
    # One-off assets are saved for this report's snapshot only, without adding
    # a current library slot. Future templates cannot accidentally inherit them.
    asset_path = _profile_path(draft.profile.contract, draft.profile.key) / "assets"
    for reference, raw in assets:
        if not _ASSET.fullmatch(reference) or asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference:
            raise LibraryError("Invalid snapshot asset.")
        _atomic_write(asset_path / reference, raw)
    for block in draft.blocks:
        for reference in block.asset_hashes:
            read_asset(draft.profile.contract, draft.profile.key, reference)
    for section in draft.sections:
        if section.divider_asset:
            read_asset(draft.profile.contract, draft.profile.key, section.divider_asset)
    with _locked(path):
        target = path / (draft.period.key + ".json")
        previous = _read(target) if target.exists() else {"revision": 0}
        _expected(previous, expected_revision)
        saved = SavedReport(draft, _now(), expected_revision + 1, open_issues, pending_proposals, entered_editor)
        raw = _json({"schema": 1, **asdict(saved)})
        _atomic_write(path / "history" / f"{draft.period.key}-{saved.revision:08d}.json", raw)
        _atomic_write(target, raw)
        return saved


def load_snapshot(contract: str, key: str, period: ReportPeriod) -> SavedReport | None:
    target = _profile_path(contract, key, snapshots=True) / (period.key + ".json")
    if not target.exists():
        return None
    value = _read(target)
    try:
        draft = draft_from_dict(value["draft"])
        if (draft.profile.contract, draft.profile.key, draft.period) != (contract, key, period):
            raise LibraryError("Snapshot identity does not match its directory.")
        return SavedReport(draft, value["generated_at"], value["revision"],
                           tuple(value.get("open_issues", ())), tuple(value.get("pending_proposals", ())),
                           value.get("entered_editor", ""))
    except (KeyError, TypeError) as exc:
        raise LibraryError("Invalid saved report snapshot.") from exc


def usage_count(contract: str, key: str, reference: str) -> int:
    """Count monthly report heads, not every regeneration of the same month."""
    count = 0
    for path in _profile_path(contract, key, snapshots=True).glob("????-??.json"):
        value = _read(path)
        draft = draft_from_dict(value["draft"])
        if reference in used_asset_references(draft):
            count += 1
    return count
