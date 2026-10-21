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
    ResolvedBlock, ReportTable, TrainingSessionTable, OrgChartNode, ReportFollowUp, SectionSpec, ReportSource, EvidenceFact, DraftParagraph, default_sections, known_sections, layout_blocks, used_asset_references,
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


@dataclass(frozen=True)
class SnapshotVersion:
    """Small history index; listing versions does not retain every draft in memory."""
    revision: int
    generated_at: str
    entered_editor: str


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


def _qa_path_guard(path: Path) -> None:
    """Fail closed on stale/foreign paths, even if a job cached a Path before reset."""
    from app.monthly_report_testing import scope
    if scope() is None:
        return
    root = _root()  # Revalidates the current generation on every operation.
    if not Path(path).resolve().is_relative_to(root.resolve()):
        raise LibraryError("Test report path is outside its isolated storage; no data was read or changed.")


def _read(path: Path) -> dict:
    return _read_with_bytes(path)[0]


def _read_with_bytes(path: Path) -> tuple[dict, bytes]:
    _qa_path_guard(path)
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise LibraryError("Saved report metadata exceeds the storage limit.")
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("schema") != 1:
            raise LibraryError("Unsupported report storage schema; existing data was preserved.")
        return value, raw
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LibraryError("Saved report data could not be read; existing data was preserved.") from exc


def _atomic_write(path: Path, raw: bytes) -> None:
    _qa_path_guard(path)
    from app.monthly_report_objects import object_path, store_bytes
    if object_path(path) is not None:
        store_bytes(path, raw)
        return
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
    _qa_path_guard(path)
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
            section_titles=tuple(tuple(v) for v in value.get("section_titles", ())),
            section_block_order=tuple((k, tuple(v)) for k, v in value.get("section_block_order", ())),
            imported_from=value.get("imported_from", ""),
            asset_tags=tuple(value.get("asset_tags", ())),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise LibraryError("Invalid report profile.") from exc


def _report_table_from_dict(value: dict) -> ReportTable:
    columns, rows = tuple(value["columns"]), tuple(tuple(row) for row in value["rows"])
    reference = value.get("reference", "")
    if reference == "training:events:v1" and "row_tokens" in value:
        return TrainingSessionTable(columns, rows, reference, tuple(value["row_tokens"]))
    return ReportTable(columns, rows, reference)


def block_from_dict(value: dict) -> ResolvedBlock:
    try:
        from app.monthly_report_asset_review import normalize_asset_reviews
        block = ResolvedBlock(
            key=value["key"], source=value["source"], text=value.get("text", ""),
            rows=tuple(tuple(str(cell) for cell in row) for row in value.get("rows", ())),
            asset_hashes=tuple(value.get("asset_hashes", ())), references=tuple(value.get("references", ())),
            ai_written=value.get("ai_written", False), reviewed_fingerprint=value.get("reviewed_fingerprint", ""),
            pending_library_save=value.get("pending_library_save", False),
            asset_captions=tuple(value.get("asset_captions", ())),
            extra_tables=tuple(_report_table_from_dict(t) for t in value.get("extra_tables", ())),
            client_reviewed_fingerprint=value.get("client_reviewed_fingerprint", ""),
            ai_evidence_fingerprint=value.get("ai_evidence_fingerprint", ""),
            ai_paragraphs=tuple(DraftParagraph(p["text"], tuple(p["fact_ids"]), tuple(p["references"]), tuple(p.get("flags", ()))) for p in value.get("ai_paragraphs", ())),
            org_nodes=tuple(OrgChartNode(**node) for node in value.get("org_nodes", ())),
            photos_per_page=int(value.get("photos_per_page", 1)),
            client_asset_reviews=tuple(value.get("client_asset_reviews", ())),
            asset_provenance=tuple((reference, tuple(context)) for reference, context in value.get("asset_provenance", ())),
        )
        # Only migrate actual legacy approvals while their old content digest
        # is still exact. Unreviewed historical blocks stay unchanged on read.
        return (normalize_asset_reviews(block) if block.client_reviewed_fingerprint == block.fingerprint
                and not block.client_asset_reviews and not block.asset_provenance else block)
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
            follow_ups=tuple(ReportFollowUp(**{**item, "references":tuple(item.get("references",()))}) for item in value.get("follow_ups",())),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LibraryError("Invalid report snapshot.") from exc


def source_from_dict(value: dict) -> ReportSource:
    fields = dict(value)
    for key in ("tags", "page_texts", "selected_pages", "needs_vision", "notices"):
        fields[key] = tuple(fields.get(key, ()))
    fields["captions"] = tuple(tuple(v) for v in fields.get("captions", ()))
    fields["client_page_reviews"] = tuple(tuple(v) for v in fields.get("client_page_reviews", ()))
    fields["client_page_exclusions"] = tuple(tuple(v) for v in fields.get("client_page_exclusions", ()))
    fields["facts"] = tuple(EvidenceFact(**{**f, "tags": tuple(f.get("tags", ())), "flags": tuple(f.get("flags", ()))}) for f in fields.get("facts", ()))
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


def _validate_profile(profile: ReportProfile) -> None:
    if not profile.title.strip():
        raise LibraryError("Enter the report profile title.")
    if len(profile.asset_tags) > 500 or any(not isinstance(tag,str) or not tag.strip() or len(tag)>80 for tag in profile.asset_tags):
        raise LibraryError("Use at most 500 confirmed equipment tags, each up to 80 characters.")
    skeleton = known_sections()
    core = {s.key for s in default_sections() if not s.appendix}
    if profile.section_order and (len(set(profile.section_order)) != len(profile.section_order)
                                 or not core <= set(profile.section_order) <= {s.key for s in skeleton}):
        raise LibraryError("Default section order must contain every section exactly once.")
    if not set(profile.excluded_sections) <= {s.key for s in skeleton}:
        raise LibraryError("Unknown omitted section.")
    known_blocks = {b.key for s in skeleton for b in s.blocks} | {b.key for b in layout_blocks()}
    if any(key not in known_blocks or source not in BLOCK_SOURCES for key, source in profile.default_block_sources):
        raise LibraryError("Invalid default block source.")
    _validate_overrides(profile.block_overrides)
    section_keys = {s.key for s in skeleton}
    if (len(dict(profile.section_titles)) != len(profile.section_titles)
            or any(k not in section_keys or not title.strip() for k, title in profile.section_titles)):
        raise LibraryError("Invalid saved section titles.")
    if len(dict(profile.section_block_order)) != len(profile.section_block_order):
        raise LibraryError("Duplicate saved block order.")
    for key, order in profile.section_block_order:
        section = next((s for s in skeleton if s.key == key), None)
        if section is None or len(set(order)) != len(order) or set(order) != {b.key for b in section.blocks}:
            raise LibraryError("Each section's block order must contain its blocks exactly once.")
    if profile.imported_from and not re.fullmatch(r"[0-9a-f]{64}", profile.imported_from):
        raise LibraryError("Invalid original design reference.")


def save_profile(profile: ReportProfile, *, expected_revision: int, actor: str, confirmed: bool) -> LibraryState:
    actor = _confirmation(actor, confirmed)
    _validate_profile(profile)
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


def _verified_source_view(original: Path, expected):
    """A persisted receipt is evidence, never authority to select a rendition."""
    from app.monthly_report_operational_source import verify_source_view
    try:
        return verify_source_view(original, expected)
    except (OSError, TypeError, ValueError) as exc:
        raise LibraryError("The expected source view could not be verified against the original.") from exc


def _source_view_scope(view, contract: str, key: str, period: ReportPeriod) -> dict:
    from app.monthly_report_operational_source import receipt_record
    receipt = receipt_record(view)
    return {
        "schema": 1, "contract": contract, "profile_key": key, "period": period.key,
        "original_sha256": view.original_inspection.sha256,
        "receipt_sha256": view.receipt_sha256, "policy": receipt["policy"],
    }


def _source_view_key(scope: dict) -> str:
    return ":".join(scope[key] for key in ("period", "original_sha256", "policy", "receipt_sha256"))


def _source_view_record(scope: dict, native_art_digest: str = "") -> dict:
    result = {"scope": scope, "scope_sha256": hashlib.sha256(_json(scope)).hexdigest()}
    if native_art_digest:
        result["native_art_review_sha256"] = native_art_digest
    return result


def _source_view_is_recorded(value, digest):
    index = value.get("source_views", {})
    if not isinstance(index, dict):
        raise LibraryError("Saved source-view index is invalid.")
    return any(isinstance(record, dict) and isinstance(record.get("scope"), dict)
               and record["scope"].get("original_sha256") == digest
               or isinstance(name, str) and isinstance(digest, str) and (":" + digest + ":") in name
               for name, record in index.items())


def source_view_replay_recorded(contract, key, period, digest):
    """Discovery only, never approval: existing scoped records must be verified.

    A new incoming view cannot supply the expected view for a prior import.
    Malformed records identifiable by their exact source/month key still count
    as recorded, ensuring the caller verifies/refuses rather than downgrades.
    """
    value = _read(_profile_path(contract, key) / 'manifest.json')
    index = value.get('source_views', {})
    if not isinstance(index, dict):
        raise LibraryError('Saved source-view index is invalid.')
    prefix = period.key + ':' + digest + ':'
    return any(isinstance(name, str) and name.startswith(prefix)
               or isinstance(record, dict) and isinstance(record.get('scope'), dict)
               and record['scope'].get('original_sha256') == digest
               and record['scope'].get('period') == period.key
               for name, record in index.items())


def _source_view_receipt_path(path: Path, scope: dict) -> Path:
    return path / "imports" / (scope["original_sha256"] + "." + scope["receipt_sha256"] + ".source-view.json")


def _receipt_matches(path: Path, raw: bytes) -> bool:
    _qa_path_guard(path)
    if (len(raw) > MAX_JSON_BYTES or path.is_symlink() or not path.is_file()
            or path.stat().st_size != len(raw)):
        return False
    with path.open("rb") as stream:
        return stream.read(len(raw) + 1) == raw


def _immutable_receipt(path: Path, raw: bytes) -> None:
    _qa_path_guard(path)
    if len(raw) > MAX_JSON_BYTES:
        raise LibraryError("Source-view receipt exceeds the storage limit.")
    if path.exists() or path.is_symlink():
        if not _receipt_matches(path, raw):
            raise LibraryError("Saved source-view receipt changed; existing data was preserved.")
    else:
        _atomic_write(path, raw)


def _saved_source_view(value: dict, path: Path, contract: str, key: str,
                       period: ReportPeriod, digest: str, expected, *, head: bool = False,
                       discover: bool = False):
    # Recorded source preparation shares the existing process-wide admission.
    # Ordinary no-record reads do not acquire a slot or change serialization.
    # Rerender reads must yield immediately; callers retry, never use an
    # unverified/stale draft. Nested admitted saves/renders remain reentrant.
    if _source_view_is_recorded(value, digest) or "import_source_view" in value or expected is not None:
        from app.monthly_report_render_jobs import work_slot
        with work_slot(wait_seconds=0):
            return _read_saved_source_view(value, path, contract, key, period, digest,
                                           expected, head=head, discover=discover)
    return _read_saved_source_view(value, path, contract, key, period, digest,
                                   expected, head=head, discover=discover)


def _read_saved_source_view(value: dict, path: Path, contract: str, key: str,
                            period: ReportPeriod, digest: str, expected, *, head=False, discover=False):
    """Validate the on-disk original, canonical receipt and separate report scope.

    Discovery is allowed only from an already scoped immutable saved original.
    It never bootstraps a legacy record or trusts a stored receipt as authority.
    """
    index = value.get("source_views", {})
    if not isinstance(index, dict):
        raise LibraryError("Saved source-view index is invalid.")
    source_is_scoped = any(
        isinstance(record, dict) and isinstance(record.get("scope"), dict)
        and record["scope"].get("original_sha256") == digest
        or isinstance(name, str) and isinstance(digest, str) and (":" + digest + ":") in name
        for name, record in index.items()
    )
    if head:
        saved_key = value.get("import_source_view")
        if "import_source_view" in value and (not isinstance(saved_key, str) or saved_key not in index):
            raise LibraryError("Saved source-view head is invalid.")
        if saved_key is None and source_is_scoped:
            raise LibraryError("Saved source-view head is missing; no legacy fallback is permitted.")
        scoped = saved_key is not None
    else:
        # Refuse no-view replay of this original even for a different month;
        # it must not fall through to a legacy approval/bootstrap branch.
        scoped = source_is_scoped
    if expected is None:
        if scoped and not discover:
            raise LibraryError("This import requires its explicitly verified source view.")
        if not scoped:
            return None
    if not scoped:
        raise LibraryError("This import has no saved source-view receipt; legacy records remain unchanged.")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise LibraryError("Source-view original identity is invalid.")
    original = path / "imports" / (digest + ".docx")
    if expected is None:
        matches = [(name, record) for name, record in index.items()
                   if isinstance(record, dict) and isinstance(record.get("scope"), dict)
                   and record["scope"].get("original_sha256") == digest
                   and record["scope"].get("period") == period.key]
        if len(matches) != 1 or head and matches[0][0] != saved_key:
            raise LibraryError("Saved source-view ownership is missing or ambiguous for this report month.")
        saved_scope = matches[0][1]["scope"]
        receipt_digest = saved_scope.get("receipt_sha256")
        if (saved_scope.get("contract") != contract or saved_scope.get("profile_key") != key
                or not isinstance(receipt_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt_digest)):
            raise LibraryError("Saved source-view identity is invalid.")
        receipt_path = _source_view_receipt_path(path, saved_scope)
        _qa_path_guard(receipt_path)
        if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size > MAX_JSON_BYTES:
            raise LibraryError("Saved source-view receipt is unavailable.")
        from app.monthly_report_compatibility_view import rederive_compatibility_view
        from zipfile import BadZipFile
        try:
            fresh = rederive_compatibility_view(original, receipt_path.read_bytes())
        except (OSError, ValueError, BadZipFile) as exc:
            raise LibraryError("Saved source view no longer matches its immutable original and current policy.") from exc
    else:
        fresh = _verified_source_view(original, expected)
    if fresh.original_inspection.sha256 != digest:
        raise LibraryError("Source-view original does not match the saved source identity.")
    scope = _source_view_scope(fresh, contract, key, period)
    replay_key = _source_view_key(scope)
    from app.monthly_report_native_art_review import _verify_native_art_review
    art_index = value.get("source_view_art_reviews", {})
    if not isinstance(art_index, dict):
        raise LibraryError("Saved native artwork review index is invalid.")
    art_context = _verify_native_art_review(
        path / "imports" / (digest + ".docx"), fresh, _state(value).profile,
        period, art_index.get(replay_key))
    record = _source_view_record(scope, art_context.digest if art_context else "")
    if index.get(replay_key) != record or head and saved_key != replay_key:
        raise LibraryError("Saved source-view receipt belongs to a different report scope or policy.")
    receipt_path = _source_view_receipt_path(path, scope)
    try:
        if not _receipt_matches(receipt_path, fresh.receipt_bytes):
            raise LibraryError("Saved source-view receipt changed; existing data was preserved.")
    except OSError as exc:
        raise LibraryError("Saved source-view receipt is unavailable.") from exc
    return replay_key, record, art_context, fresh


def verified_render_source_view(draft: ReportDraft, original_path: Path, expected_view=None, *, section_key=None, with_native_art=False):
    """Permit native preservation only from an explicitly saved same-site view.

    Rehash the caller's original, then independently rederive once from the
    immutable stored original. A scope receipt or a manual review string alone
    cannot establish source identity or facility ownership.
    """
    from app.monthly_report_compatibility_view import CompatibilityView
    from app.monthly_report_import import MAX_DOCX_BYTES
    from app.monthly_report_start_import import source_sites

    profile = draft.profile
    path = _profile_path(profile.contract, profile.key)
    manifest = path / "manifest.json"
    value = _read(manifest) if manifest.exists() else {}
    if (expected_view is None and not _source_view_is_recorded(value, profile.imported_from)
            and "import_source_view" not in value):
        return (None, None) if with_native_art else None
    digest = (getattr(getattr(expected_view, "original_inspection", None), "sha256", None)
              if expected_view is not None else profile.imported_from)
    if (expected_view is not None and not isinstance(expected_view, CompatibilityView)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or draft.profile.imported_from != digest):
        raise LibraryError("Native source-view rendering requires the original profile pin and explicit view.")
    if "import_source_view" in value and value.get("import_review") != digest:
        raise LibraryError("Saved source-view original differs from the current profile pin.")
    try:
        original_path = Path(original_path)
        if original_path.stat().st_size > MAX_DOCX_BYTES:
            raise LibraryError("Native source-view original exceeds the import limit.")
        hasher, size = hashlib.sha256(), 0
        with original_path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOCX_BYTES:
                    raise LibraryError("Native source-view original exceeds the import limit.")
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise LibraryError("Native source-view original does not match its immutable source pin.")
    except (OSError, TypeError) as exc:
        raise LibraryError("Native source-view original could not be read.") from exc
    saved_view = _saved_source_view(value, path, profile.contract, profile.key, draft.period,
                                    digest, expected_view, discover=True)
    if saved_view is None:
        raise LibraryError("The saved source-view scope is unavailable; no legacy fallback is permitted.")
    expected_view = expected_view if expected_view is not None else saved_view[3]
    # _saved_source_view compares the whole independently rederived view,
    # including both inspections, bytes and occurrence map, with expected_view.
    persisted = _state(value).profile
    if (persisted.contract, persisted.key, persisted.imported_from, persisted.facilities, persisted.scope_type) != (
            profile.contract, profile.key, profile.imported_from, profile.facilities, profile.scope_type):
        raise LibraryError("Native source-view ownership does not match the persisted profile membership and source pin.")
    from app.monthly_report_site_catalog import site_options
    from app.monthly_report_start_import import _words
    # A caller cannot hide another known site by supplying only its preferred
    # facility. Merge aliases only where an existing identity is unambiguous.
    known = {site.key: site for site in persisted.facilities}
    for site in (*site_options(profile.contract),
                 *(s for p in list_profiles(profile.contract) for s in p.facilities)):
        names = {_words(n) for n in (site.title, *site.aliases)}
        overlaps = [prior for prior in known.values()
                    if names.intersection(_words(n) for n in (prior.title, *prior.aliases))]
        if len(overlaps) > 1:
            raise LibraryError("Native source-view facility catalog has ambiguous ownership.")
        if overlaps:
            prior = overlaps[0]
            known[prior.key] = replace(prior, aliases=tuple(dict.fromkeys(
                (*prior.aliases, *(n for n in (site.title, *site.aliases) if n != prior.title)))))
        elif site.key in known and known[site.key] != site:
            raise LibraryError("Native source-view facility catalog has conflicting identity.")
        else:
            known[site.key] = site
    recognized = source_sites(expected_view.original_inspection, known.values())
    if {site.key for site in recognized} != {site.key for site in persisted.facilities}:
        raise LibraryError("Native source-view preservation requires independently recognized same-site ownership.")
    if section_key in (None, "cover"):
        # Removal/replacement UI intentionally clears photograph references.
        # Do not silently preserve a formerly mapped photo when its placement
        # authority has been lost. V1 refuses this operation rather than guessing
        # or changing global artwork approval/reference semantics.
        index = value.get("starting_contributions", {})
        reference = index.get(saved_view[0]) if isinstance(index, dict) else None
        if not isinstance(reference, str) or not re.fullmatch(r"[0-9a-f]{64}", reference):
            raise LibraryError("Native source-view rendering requires its acknowledged source contribution.")
        payload = _read(path / "imports" / (reference + ".contribution.json"))
        if (hashlib.sha256(_json(payload)).hexdigest() != reference
                or payload.get("source_view") != saved_view[1]
                or not isinstance(payload.get("draft"), dict)):
            raise LibraryError("Native source-view contribution changed or lost its report scope.")
        baseline = draft_from_dict(payload["draft"])
        if (baseline.profile.contract, baseline.profile.key, baseline.profile.imported_from, baseline.period) != (
                profile.contract, profile.key, digest, draft.period):
            raise LibraryError("Native source-view contribution has different original/report ownership.")
        prior_photo = next((b for b in baseline.blocks if b.key == "cover_photo"), None)
        current_photo = next((b for b in draft.blocks if b.key == "cover_photo"), None)
        old_refs = set(prior_photo.references) if prior_photo is not None else set()
        if old_refs and (current_photo is None or not old_refs <= set(current_photo.references)):
            raise LibraryError("The cover-photo decision lost its exact source placement; this experimental rendering is unsupported.")
    art_context = saved_view[2]
    if art_context is not None:
        from app.monthly_report_native_art_review import _scope as native_art_scope
        scope_profile = profile
        from app import monthly_report_designs as designs
        reviewed_template = art_context.inventory.scope['template']
        # Opening an imported report pins its implicit original design. This
        # changes only the template spelling, not the reviewed source. Accept
        # that one-way promotion only while the saved design still resolves to
        # this exact original; installed overrides and every other scope field
        # remain authoritative. Never rewrite the immutable review receipt.
        if (persisted.template == reviewed_template
                and not reviewed_template.startswith((designs.PREFIX, designs.MASTER_PREFIX, designs.BUILTIN_PREFIX))
                and profile.template == designs.PREFIX + digest
                and designs.fingerprint(persisted) == digest):
            scope_profile = replace(profile, template=reviewed_template)
        if native_art_scope(expected_view, scope_profile, draft.period) != art_context.inventory.scope_bytes:
            raise LibraryError("Native artwork preservation belongs to a different current profile or template scope.")
        kept_refs = {f"docx:{digest}:{item.original_id}" for item in art_context.inventory.occurrences}
        if any(kept_refs.intersection(block.references) for block in draft.blocks):
            raise LibraryError("Native artwork preservation conflicts with an exact mapped or omitted occurrence.")
    return (expected_view, art_context) if with_native_art else expected_view


def save_report_setup(profile: ReportProfile, draft: ReportDraft, source: Path, review: dict, *,
                      assets: tuple[tuple[str, bytes], ...], expected_revision: int,
                      actor: str, confirmed: bool, snapshot_revision: int = 0,
                      source_draft: ReportDraft | None = None, source_view=None) -> LibraryState:
    """Publish design, original, review decisions and working seed in one manifest.

    New profiles become visible only after every immutable asset and the original
    are durable. Existing report snapshots are not overwritten by an import.
    """
    from app.monthly_report_setup import MONTHLY_BLOCKS
    actor = _confirmation(actor, confirmed)
    _validate_profile(profile)
    if (draft.profile.contract, draft.profile.key) != (profile.contract, profile.key):
        raise LibraryError("Imported draft identity does not match the profile.")
    if source_draft is not None and (
            source_draft.profile.contract, source_draft.profile.key, source_draft.period
    ) != (profile.contract, profile.key, draft.period):
        raise LibraryError("Starting contribution does not match the report sites or month.")
    if source.stat().st_size > 128 * 1024 * 1024:
        raise LibraryError("Original DOCX exceeds the import limit.")
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != review.get("sha256"):
        raise LibraryError("Original DOCX changed during review. Analyze it again.")
    fresh_view = _verified_source_view(source, source_view) if source_view is not None else None
    art_context = None
    if fresh_view is None and review.get("native_art_review") is not None:
        raise LibraryError("Native artwork review requires its explicitly verified source view.")
    if fresh_view is not None:
        if (fresh_view.original_inspection.sha256 != digest or profile.imported_from != digest
                or draft.profile.imported_from != digest
                or source_draft is not None and source_draft.profile.imported_from != digest
                or review.get("period") != draft.period.key):
            raise LibraryError("Source-view import must retain its original source and report-month pins.")
        view_scope = _source_view_scope(fresh_view, profile.contract, profile.key, draft.period)
        from app.monthly_report_native_art_review import _verify_native_art_review
        art_context = _verify_native_art_review(source, fresh_view, profile, draft.period,
                                               review.get("native_art_review"))
        if art_context is not None:
            kept_refs = {f"docx:{digest}:{item.original_id}" for item in art_context.inventory.occurrences}
            if any(kept_refs.intersection(block.references)
                   for candidate in (draft, source_draft) if candidate is not None for block in candidate.blocks):
                raise LibraryError("Native artwork preservation conflicts with an exact mapped or omitted occurrence.")
        view_key = _source_view_key(view_scope)
        view_record = _source_view_record(view_scope, art_context.digest if art_context else "")
    path = _profile_path(profile.contract, profile.key)
    with _locked(path):
        manifest = path / "manifest.json"
        value = _read(manifest) if manifest.exists() else {"schema": 1, "revision": 0, "versions": [], "current": [], "audit": []}
        _expected(value, expected_revision)
        if art_context is not None and art_context.receipt["visual_review"]["actor"] != actor:
            prior = value.get("source_view_art_reviews", {})
            if not isinstance(prior, dict) or prior.get(view_key) != art_context.receipt:
                raise LibraryError("Native artwork visual-review actor does not match this saved review.")
        if fresh_view is None:
            _saved_source_view(value, path, profile.contract, profile.key, draft.period, digest, None)
        if expected_revision == 0:
            # New uploaded designs receive the same empty-logo defaults as the
            # template route. Existing designs, imported logos and omissions
            # remain pinned to the manager's choices.
            from app.monthly_report_branding import apply_defaults
            initial_assets = dict(assets)
            draft = apply_defaults(draft, initial_assets)
            assets = tuple(initial_assets.items())
        for reference, raw in assets:
            if not _ASSET.fullmatch(reference) or asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference:
                raise LibraryError("Invalid imported asset.")
            _atomic_write(path / "assets" / reference, raw)
        for block in draft.blocks:
            for reference in block.asset_hashes:
                read_asset(profile.contract, profile.key, reference)
        original = path / "imports" / (digest + ".docx")
        from app.monthly_report_objects import store_file
        store_file(original, source)
        saved_review = {"schema": 1, **review, "actor": actor, "at": _now()}
        if fresh_view is not None:
            # Verify the durable original too, not just a caller-owned path.
            _verified_source_view(original, fresh_view)
            _immutable_receipt(_source_view_receipt_path(path, view_scope), fresh_view.receipt_bytes)
            index = value.setdefault("source_views", {})
            if not isinstance(index, dict) or view_key in index and index[view_key] != view_record:
                raise LibraryError("Saved source-view scope changed; existing data was preserved.")
            index[view_key] = view_record
            art_index = value.setdefault("source_view_art_reviews", {})
            if not isinstance(art_index, dict):
                raise LibraryError("Saved native artwork review index is invalid.")
            if art_context is not None:
                if view_key in art_index and art_index[view_key] != art_context.receipt:
                    raise LibraryError("Saved native artwork review changed; existing data was preserved.")
                art_index[view_key] = art_context.receipt
            elif view_key in art_index:
                raise LibraryError("Saved native artwork review cannot be silently removed.")
            value["import_source_view"] = view_key
            value["import_source_view_review"] = saved_review
        else:
            value.pop("import_source_view", None)
            value.pop("import_source_view_review", None)
            _atomic_write(path / "imports" / (digest + ".json"), _json(saved_review))
        # Only first setup seeds standing defaults. A partial report cannot
        # silently change everyone else's org chart or contact matrix.
        if expected_revision == 0:
            current, at = {}, _now()
            for block in draft.blocks:
                if block.key in MONTHLY_BLOCKS or block.source == "Omit":
                    continue
                identity = hashlib.sha256(_json(asdict(block))).hexdigest()
                value["versions"].append(asdict(LibraryVersion(identity, block.key, block.key.replace("_", " "),
                                                              replace(block, source="Library"), actor, at)))
                current[block.key] = identity
            value["current"] = sorted(current.items())
        if source_draft is not None:
            # Publish this immutable contribution only through the same atomic
            # manifest as the import. An interrupted write cannot acknowledge
            # content that was never saved. No artwork bytes are duplicated.
            payload = {"schema": 1, "draft": asdict(source_draft)}
            if fresh_view is not None:
                payload["source_view"] = view_record
            contribution = _json(payload)
            reference = hashlib.sha256(contribution).hexdigest()
            _atomic_write(path / "imports" / (reference + ".contribution.json"), contribution)
            replay_key = view_key if fresh_view is not None else draft.period.key + ":" + digest
            value.setdefault("starting_contributions", {})[replay_key] = reference
        value["profile"] = asdict(profile)
        value["bootstrap"] = asdict(draft)
        value["bootstrap_snapshot_revision"] = snapshot_revision
        value["import_review"] = digest
        value["revision"] += 1
        value["audit"].append({"action": "report_import", "actor": actor, "at": _now(), "source": digest,
                               "period": draft.period.key, "intent": review.get("intent", "")})
        if fresh_view is not None:
            value["audit"][-1]["source_view"] = view_record
        raw = _json(value)
        _atomic_write(path / "history" / f'{value["revision"]:08d}.json', raw)
        _atomic_write(manifest, raw)
        return _state(value)


def starting_contribution(contract: str, key: str, period: ReportPeriod,
                          digest: str, *, source_view=None) -> tuple[ReportDraft | None, bool]:
    """Read only an acknowledged contribution for these source bytes and month.

    Older installations may have only a merged bootstrap. It can prove an
    unchanged replay but cannot authorize changed source-review replacements.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise LibraryError("Invalid Starting report source identity.")
    path = _profile_path(contract, key)
    value = _read(path / "manifest.json")
    saved_view = _saved_source_view(value, path, contract, key, period, digest, source_view, discover=True)
    index = value.get("starting_contributions", {})
    if not isinstance(index, dict):
        raise LibraryError("Starting report replay index is invalid; your current report is unchanged.")
    replay_key = saved_view[0] if saved_view is not None else period.key + ":" + digest
    reference = index.get(replay_key)
    if replay_key in index:
        if not isinstance(reference, str) or not re.fullmatch(r"[0-9a-f]{64}", reference):
            raise LibraryError("Starting report replay record has an invalid identity.")
        payload = _read(path / "imports" / (reference + ".contribution.json"))
        if hashlib.sha256(_json(payload)).hexdigest() != reference:
            raise LibraryError("Starting report replay record changed; your current report is unchanged.")
        if not isinstance(payload.get("draft"), dict):
            raise LibraryError("Starting report replay record has no valid draft.")
        if (saved_view is not None and payload.get("source_view") != saved_view[1]
                or saved_view is None and "source_view" in payload):
            raise LibraryError("Starting report replay source-view scope changed.")
        result = draft_from_dict(payload["draft"])
        verified = True
    elif saved_view is not None:
        raise LibraryError("This source-view import has no separately acknowledged Starting contribution.")
    elif value.get("import_review") == digest and value.get("bootstrap"):
        result = draft_from_dict(value["bootstrap"])
        if result.period != period:
            return None, False
        verified = False
    elif any(a.get("action") == "report_import" and a.get("source") == digest
             and a.get("period") == period.key for a in value.get("audit", ())):
        raise LibraryError(
            "This earlier Starting import has no separate replay record. Your report is unchanged. "
            "Make any remaining corrections in the report editor instead of reimporting this source."
        )
    else:
        return None, False
    if (result.profile.contract, result.profile.key, result.period) != (contract, key, period):
        raise LibraryError("Starting report replay record belongs to different sites or a different month.")
    if saved_view is not None and result.profile.imported_from != digest:
        raise LibraryError("Starting report replay lost its original source identity.")
    return result, verified


def load_imported_draft(contract: str, key: str, *, source_view=None) -> ReportDraft | None:
    path = _profile_path(contract, key)
    value = _read(path / "manifest.json")
    return _load_imported_draft_value(value, path, contract, key, source_view=source_view)


def _load_imported_draft_value(value, path, contract, key, *, source_view=None):
    draft = draft_from_dict(value["bootstrap"]) if value.get("bootstrap") else None
    if draft is None:
        if source_view is not None or "import_source_view" in value:
            raise LibraryError("Source-view import has no saved working draft.")
        return None
    saved_view = _saved_source_view(value, path, contract, key, draft.period,
                                    value.get("import_review", ""), source_view, head=True, discover=True)
    if saved_view is not None and (
            (draft.profile.contract, draft.profile.key) != (contract, key)
            or draft.profile.imported_from != value["import_review"]):
        raise LibraryError("Source-view working draft lost its original report identity.")
    return draft


def imported_snapshot_revision(contract: str, key: str) -> int:
    value = _read(_profile_path(contract, key) / "manifest.json")
    return int(value.get("bootstrap_snapshot_revision", 0))


@contextmanager
def _imported_draft_read(contract: str, key: str):
    """One read-only selection operation, not a reusable proof/cache token.

    Reload independently on every entry. Before returning selected drafts,
    reject changed metadata, immutable original or canonical receipt. Output,
    saves and previews retain their own independent verification boundaries.
    """
    from app.monthly_report_source_view_runtime import _file_digest
    from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES
    folder = _profile_path(contract, key)
    manifest = folder / "manifest.json"
    def digest(path, limit):
        _qa_path_guard(path)
        try:
            return _file_digest(path, limit)
        except OSError as exc:
            raise LibraryError("Saved report evidence disappeared or could not be read during report selection.") from exc

    value, raw = _read_with_bytes(manifest)
    before = hashlib.sha256(raw).hexdigest()
    draft = _load_imported_draft_value(value, folder, contract, key)
    if digest(manifest, MAX_JSON_BYTES) != before:
        raise LibraryError("Saved report metadata changed during report selection.")
    evidence = [(manifest, MAX_JSON_BYTES, before)]
    if "import_source_view" in value:
        # The loader above has independently checked this exact head, scope,
        # original and artwork receipt. Never infer a replacement receipt.
        record = value.get("source_views", {}).get(value["import_source_view"])
        if draft is None or not isinstance(record, dict) or not isinstance(record.get("scope"), dict):
            raise LibraryError("Saved source-view head changed during report selection.")
        scope = record["scope"]
        evidence.extend((
            (folder / "imports" / (draft.profile.imported_from + ".docx"),
             MAX_VIEW_SOURCE_BYTES, draft.profile.imported_from),
            (_source_view_receipt_path(folder, scope), MAX_JSON_BYTES, scope["receipt_sha256"]),
        ))

    def unchanged():
        for path, limit, expected in evidence:
            if digest(path, limit) != expected:
                raise LibraryError("Saved report evidence changed during report selection. Retry without changing the report.")

    unchanged()
    yield draft, int(value.get("bootstrap_snapshot_revision", 0))
    unchanged()


def imported_original(contract: str, key: str) -> Path | None:
    value = _read(_profile_path(contract, key) / "manifest.json")
    digest = value.get("import_review", "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    return _profile_path(contract, key) / "imports" / (digest + ".docx")


def imported_native_art_review(contract: str, key: str, period: ReportPeriod, *, source_view):
    """Reuse only an independently verified immutable source-art disposition."""
    path = _profile_path(contract, key)
    value = _read(path / "manifest.json")
    saved = _saved_source_view(value, path, contract, key, period,
                               value.get("import_review", ""), source_view)
    return saved[2].receipt if saved is not None and saved[2] is not None else None


def imported_review_scope(contract: str, key: str, period: ReportPeriod, *, source_view=None) -> str:
    path = _profile_path(contract, key)
    value = _read(path / "manifest.json")
    digest = value.get("import_review", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        if source_view is not None or "import_source_view" in value:
            raise LibraryError("Source-view original identity is unavailable.")
        return ""
    saved_view = _saved_source_view(value, path, contract, key, period, digest, source_view, head=True, discover=True)
    if saved_view is not None:
        review = value.get("import_source_view_review")
        if not isinstance(review, dict) or review.get("sha256") != digest or review.get("period") != period.key:
            raise LibraryError("Saved source-view review belongs to a different source or month.")
    else:
        review = _read(path / "imports" / (digest + ".json"))
    return review.get("image_review_scope", "") if review.get("period") == period.key else ""


def _validate_overrides(overrides: tuple[BlockSpec, ...]) -> None:
    specs = {b.key: b for s in known_sections() for b in s.blocks}
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
    known = {b.key for s in known_sections() for b in s.blocks} | {b.key for b in layout_blocks()}
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


def _saved_report(value, contract, key, period, *, revision=None):
    try:
        draft = draft_from_dict(value["draft"])
        if (draft.profile.contract, draft.profile.key, draft.period) != (contract, key, period):
            raise LibraryError("Snapshot identity does not match its directory.")
        if (type(value["revision"]) is not int or value["revision"] < 1
                or revision is not None and value["revision"] != revision):
            raise LibraryError("Snapshot revision does not match its history version.")
        if (not isinstance(value["generated_at"], str)
                or not isinstance(value.get("entered_editor", ""), str)):
            raise LibraryError("Invalid saved report attribution.")
        return SavedReport(draft, value["generated_at"], value["revision"],
                           tuple(value.get("open_issues", ())), tuple(value.get("pending_proposals", ())),
                           value.get("entered_editor", ""))
    except (KeyError, TypeError) as exc:
        raise LibraryError("Invalid saved report snapshot.") from exc


def load_snapshot(contract: str, key: str, period: ReportPeriod) -> SavedReport | None:
    target = _profile_path(contract, key, snapshots=True) / (period.key + ".json")
    return _saved_report(_read(target), contract, key, period) if target.exists() else None


def load_snapshot_version(contract: str, key: str, period: ReportPeriod, revision: int) -> SavedReport:
    """Read an immutable version without advancing the head or changing browser work."""
    if type(revision) is not int or revision < 1:
        raise LibraryError("Invalid saved report version.")
    head = load_snapshot(contract, key, period)
    if head is None or revision > head.revision:
        raise LibraryError("That version has not been published to shared report history.")
    target = (_profile_path(contract, key, snapshots=True) / "history"
              / f"{period.key}-{revision:08d}.json")
    return _saved_report(_read(target), contract, key, period, revision=revision)


def snapshot_history(contract: str, key: str, period: ReportPeriod, *,
                     before_revision: int | None = None, limit: int = 20) -> tuple[tuple[SnapshotVersion, ...], bool]:
    """Bounded newest-first history, with an explicit cursor for older versions.

    A broken/misplaced version is an error, never silently hidden as absent history.
    Listing validates each version's scope/revision/attribution, without building
    every historical draft. Selecting a version validates its complete draft.
    """
    if type(limit) is not int or not 1 <= limit <= 50:
        raise LibraryError("Invalid report history page size.")
    if before_revision is not None and (type(before_revision) is not int or before_revision < 1):
        raise LibraryError("Invalid report history cursor.")
    head = load_snapshot(contract, key, period)
    if head is None:
        return (), False
    directory = _profile_path(contract, key, snapshots=True) / "history"
    _qa_path_guard(directory)
    pattern = re.compile(re.escape(period.key) + r"-([0-9]{8,})\.json\Z")
    candidates = []
    for path in directory.glob(period.key + "-*.json"):
        match = pattern.fullmatch(path.name)
        if (match and int(match[1]) <= head.revision
                and (before_revision is None or int(match[1]) < before_revision)):
            candidates.append(int(match[1]))
    candidates.sort(reverse=True)
    if before_revision is None and head.revision not in candidates:
        raise LibraryError("The current shared report exists, but its immutable history version is unavailable.")
    expected = min(head.revision, before_revision - 1 if before_revision is not None else head.revision)
    if len(set(candidates)) != expected:
        raise LibraryError("Some published report history versions are unavailable. Existing saved versions were preserved.")
    versions = []
    for revision in candidates[:limit]:
        value = _read(directory / f"{period.key}-{revision:08d}.json")
        try:
            saved = value["draft"]
            if ((saved["profile"]["contract"], saved["profile"]["key"], ReportPeriod(**saved["period"]))
                    != (contract, key, period)):
                raise LibraryError("Snapshot identity does not match its directory.")
            if type(value["revision"]) is not int or value["revision"] != revision:
                raise LibraryError("Snapshot revision does not match its history version.")
            author = value.get("entered_editor", "") or saved["prepared_by"]
            if not isinstance(value["generated_at"], str) or not isinstance(author, str):
                raise LibraryError("Invalid saved report attribution.")
            versions.append(SnapshotVersion(revision, value["generated_at"], author))
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, LibraryError):
                raise
            raise LibraryError("Invalid saved report history metadata.") from exc
    return tuple(versions), len(candidates) > limit


def usage_count(contract: str, key: str, reference: str) -> int:
    """Count monthly report heads, not every regeneration of the same month."""
    count = 0
    for path in _profile_path(contract, key, snapshots=True).glob("????-??.json"):
        value = _read(path)
        draft = draft_from_dict(value["draft"])
        if reference in used_asset_references(draft):
            count += 1
    return count
