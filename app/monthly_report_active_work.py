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


def enabled(token: str) -> bool:
    return isinstance(token, str) and bool(_TOKEN.fullmatch(token))


def _directory(token: str, contract: str, key: str, period: ReportPeriod) -> Path:
    if not enabled(token):
        raise library.LibraryError("Automatic recovery requires this browser's device cookie.")
    browser = hashlib.sha256(token.encode("ascii")).hexdigest()
    return (library._root() / "active_work" / browser /
            library._contract_directory(contract) / library._valid_key(key) / period.key)


def load(token: str, contract: str, key: str, period: ReportPeriod) -> ActiveWork | None:
    if not enabled(token):
        return None
    folder = _directory(token, contract, key, period)
    path = folder / "working.json"
    if not path.exists():
        return None
    value = library._read(path)
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
    return ActiveWork(draft, value["revision"], value["base_snapshot_revision"], tuple(result))


def save(token: str, draft: ReportDraft, *, expected_revision: int,
         base_snapshot_revision: int, assets: dict[str, bytes] | None = None) -> ActiveWork:
    """Atomically retain active input without creating report-history revisions.

    Content-addressed pictures are published before the journal manifest. If a
    write fails, the old manifest and all previously saved business data remain.
    Same-browser tabs use a revision guard; a stale one cannot replace new work.
    """
    folder = _directory(token, draft.profile.contract, draft.profile.key, draft.period)
    pending = assets or {}
    if expected_revision < 0 or base_snapshot_revision < 0:
        raise library.LibraryError("Invalid active report revision.")
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
        revision = previous["revision"] if previous else 0
        if revision != expected_revision:
            raise ActiveWorkConflict(
                "Another tab changed this browser's unfinished report. Your current edits remain on this page; "
                "reload and compare before continuing.")
        asset_names = tuple(sorted(pending))
        same = bool(previous and previous.get("fingerprint") == draft.fingerprint
                    and previous.get("base_snapshot_revision") == base_snapshot_revision
                    and tuple(previous.get("assets", ())) == asset_names)
        missing = any(not (folder / "assets" / name).is_file() for name in asset_names)
        if same and not missing:
            return ActiveWork(draft, revision, base_snapshot_revision)
        for name, raw in pending.items():
            target = folder / "assets" / name
            if not target.is_file():
                library._atomic_write(target, raw)
        value = {"schema": 1, "kind": "browser_active_work_v1", "revision": revision + 1,
                 "base_snapshot_revision": base_snapshot_revision,
                 "fingerprint": draft.fingerprint,
                 "updated_at": library._now(), "assets": asset_names,
                 "draft": asdict(draft)}
        library._atomic_write(path, library._json(value))
        return ActiveWork(draft, revision + 1, base_snapshot_revision)


def discard(token: str, contract: str, key: str, period: ReportPeriod, *,
            expected_revision: int | None = None) -> None:
    """Remove only this browser's uncommitted copy, never snapshot history."""
    if not enabled(token):
        return
    folder = _directory(token, contract, key, period)
    if not folder.exists():
        return
    with library._locked(folder):
        path = folder / "working.json"
        if not path.exists():
            return
        try:
            value = library._read(path)
        except library.LibraryError:
            # Explicitly confirmed restart can repair this browser's unreadable
            # active copy. Never touch report snapshots or another browser.
            if expected_revision not in (None, 0):
                raise
            value = {"revision": 0}
        if expected_revision is not None and value.get("revision") != expected_revision:
            raise ActiveWorkConflict("Another tab changed this browser's unfinished report. Nothing was cleared.")
        path.unlink()
        assets = folder / "assets"
        if assets.is_dir():
            for image in assets.iterdir():
                if library._ASSET.fullmatch(image.name) and image.is_file() and not image.is_symlink():
                    image.unlink()
