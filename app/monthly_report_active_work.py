"""Per-browser recovery journal, independent from finished report snapshots.

A device cookie is *convenience identity*, not authentication. It scopes one
working copy to one browser, contract, exact selected-site profile and month.
No monthly edit is promoted into contract-wide standing storage by this code.
No automatic expiration or history deletion is inferred from abandonment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re
import uuid

from app import monthly_report_library as library
from app.monthly_report_model import ReportDraft, ReportPeriod

_TOKEN = re.compile(r"[0-9a-f]{32}\Z")


class ActiveWorkConflict(library.RevisionConflict):
    """A newer browser-tab journal exists; never overwrite it automatically."""


@dataclass(frozen=True)
class ActiveWork:
    draft: ReportDraft
    revision: int
    base_snapshot_revision: int
    assets: tuple[tuple[str, bytes], ...] = ()
    generation: str = ""


def enabled(token: str) -> bool:
    return isinstance(token, str) and bool(_TOKEN.fullmatch(token))


def _directory(token: str, contract: str, key: str, period: ReportPeriod) -> Path:
    if not enabled(token):
        raise library.LibraryError("Automatic recovery requires this browser's device cookie.")
    browser = hashlib.sha256(token.encode("ascii")).hexdigest()
    return (library._root() / "active_work" / browser /
            library._contract_directory(contract) / library._valid_key(key) / period.key)


def _generation(value: dict) -> str:
    """Legacy journals have no generation; current ones use opaque random IDs."""
    generation = value.get("generation", "")
    if not isinstance(generation, str) or (generation and not enabled(generation)):
        raise library.LibraryError("The unfinished report has an invalid recovery identity.")
    return generation


def current_generation(token: str, contract: str, key: str, period: ReportPeriod) -> str:
    """Recover the new identity after an explicit discard, even without a draft."""
    if not enabled(token):
        return ""
    path = _directory(token, contract, key, period) / "working.json"
    return _generation(library._read(path)) if path.exists() else ""


def load(token: str, contract: str, key: str, period: ReportPeriod) -> ActiveWork | None:
    if not enabled(token):
        return None
    folder = _directory(token, contract, key, period)
    path = folder / "working.json"
    if not path.exists():
        return None
    value = library._read(path)
    if value.get("kind") == "browser_active_work_discarded_v1":
        _generation(value)
        return None
    if (value.get("kind") != "browser_active_work_v1" or
            not isinstance(value.get("revision"), int) or value["revision"] < 1 or
            not isinstance(value.get("base_snapshot_revision"), int) or
            value["base_snapshot_revision"] < 0):
        raise library.LibraryError("The browser's unfinished report data could not be read safely.")
    draft = library.draft_from_dict(value.get("draft", {}))
    if (draft.profile.contract, draft.profile.key, draft.period) != (contract, key, period):
        raise library.LibraryError("Unfinished browser work belongs to a different report.")
    result = []
    for name in value.get("assets", ()):
        if not isinstance(name, str) or not library._ASSET.fullmatch(name):
            raise library.LibraryError("An unfinished report picture reference is invalid.")
        path = folder / "assets" / name
        try:
            if path.stat().st_size > library.MAX_ASSET_BYTES:
                raise library.LibraryError("An unfinished report picture exceeds the file limit.")
            raw = path.read_bytes()
        except OSError as exc:
            raise library.LibraryError("An unfinished picture could not be restored. Saved reports are unchanged.") from exc
        if library.asset_reference(raw, name.rsplit(".", 1)[-1]) != name:
            raise library.LibraryError("An unfinished report picture failed its integrity check.")
        result.append((name, raw))
    return ActiveWork(draft, value["revision"], value["base_snapshot_revision"], tuple(result), _generation(value))


def save(token: str, draft: ReportDraft, *, expected_revision: int,
         base_snapshot_revision: int, assets: dict[str, bytes] | None = None,
         expected_generation: str | None = None) -> ActiveWork:
    """Atomically retain active input without creating report-history revisions.

    Content-addressed pictures are published before the journal manifest. If a
    write fails, the old manifest and all previously saved business data remain.
    Same-browser tabs use a revision guard; a stale one cannot replace new work.
    """
    folder = _directory(token, draft.profile.contract, draft.profile.key, draft.period)
    pending = assets or {}
    if expected_revision < 0 or base_snapshot_revision < 0:
        raise library.LibraryError("Invalid active report revision.")
    if expected_generation is not None and (not isinstance(expected_generation, str) or
                                           (expected_generation and not enabled(expected_generation))):
        raise library.LibraryError("Invalid active report recovery identity.")
    if len(pending) > 100:
        raise library.LibraryError("There are too many unsaved pictures to retain automatically.")
    for name, raw in pending.items():
        if (not isinstance(name, str) or not library._ASSET.fullmatch(name)
                or not isinstance(raw, bytes) or len(raw) > library.MAX_ASSET_BYTES
                or library.asset_reference(raw, name.rsplit(".", 1)[-1]) != name):
            raise library.LibraryError("An unsaved picture could not be retained safely.")
    with library._locked(folder):
        path = folder / "working.json"
        previous = library._read(path) if path.exists() else None
        if previous and (previous.get("kind") not in ("browser_active_work_v1", "browser_active_work_discarded_v1")
                         or type(previous.get("revision")) is not int or previous["revision"] < 1):
            raise library.LibraryError("The unfinished browser journal could not be read safely.")
        generation = _generation(previous) if previous else ""
        revision = previous["revision"] if previous and previous["kind"] == "browser_active_work_v1" else 0
        if revision != expected_revision or (expected_generation is not None
                                             and generation != expected_generation):
            raise ActiveWorkConflict(
                "Another tab or a new working copy changed this browser's unfinished report. "
                "Your current edits remain on this page; reload and compare before continuing.")
        next_revision = (previous["revision"] if previous else 0) + 1
        asset_names = tuple(sorted(pending))
        same = bool(previous and previous["kind"] == "browser_active_work_v1"
                    and previous.get("fingerprint") == draft.fingerprint
                    and previous.get("base_snapshot_revision") == base_snapshot_revision
                    and tuple(previous.get("assets", ())) == asset_names)
        missing = any(not (folder / "assets" / name).is_file() for name in asset_names)
        if same and not missing:
            return ActiveWork(draft, revision, base_snapshot_revision, generation=generation)
        for name, raw in pending.items():
            target = folder / "assets" / name
            if not target.is_file():
                library._atomic_write(target, raw)
        next_generation = generation or uuid.uuid4().hex
        value = {"schema": 1, "kind": "browser_active_work_v1", "revision": next_revision,
                 "generation": next_generation, "base_snapshot_revision": base_snapshot_revision,
                 "fingerprint": draft.fingerprint,
                 "updated_at": library._now(), "assets": asset_names,
                 "draft": asdict(draft)}
        library._atomic_write(path, library._json(value))
        return ActiveWork(draft, next_revision, base_snapshot_revision, generation=next_generation)


def discard(token: str, contract: str, key: str, period: ReportPeriod, *,
            expected_revision: int | None = None,
            expected_generation: str | None = None) -> str:
    """Discard only this browser copy; retain a durable, nonrepeating boundary.

    An atomic tombstone replaces the working manifest. A later first save starts
    beyond the old revision, and a stale tab cannot reuse its old generation.
    The immutable saved-report library is never touched.
    """
    if not enabled(token):
        return ""
    folder = _directory(token, contract, key, period)
    if not folder.exists():
        return ""
    with library._locked(folder):
        path = folder / "working.json"
        if not path.exists():
            return ""
        try:
            value = library._read(path)
        except library.LibraryError:
            # Explicitly confirmed restart of a corrupt copy is permitted
            # only without a previously observed positive revision.
            if expected_revision not in (None, 0):
                raise
            value = {"revision": 0}
        revision = value.get("revision", 0)
        if type(revision) is not int or revision < 0:
            raise library.LibraryError("The unfinished browser journal is invalid.")
        active_revision = 0 if value.get("kind") == "browser_active_work_discarded_v1" else revision
        if (expected_revision is not None and active_revision != expected_revision or
                expected_generation is not None and _generation(value) != expected_generation):
            raise ActiveWorkConflict("Another tab changed this unfinished report. Nothing was cleared.")
        next_generation = uuid.uuid4().hex
        tombstone = {"schema": 1, "kind": "browser_active_work_discarded_v1",
                     "revision": revision + 1, "generation": next_generation}
        library._atomic_write(path, library._json(tombstone))
        assets = folder / "assets"
        if assets.is_dir():
            for picture in assets.iterdir():
                if library._ASSET.fullmatch(picture.name) and picture.is_file() and not picture.is_symlink():
                    picture.unlink()
        return next_generation
