"""Read-only evidence for the marked, cookie-isolated synthetic history task."""
from hashlib import sha256
from dataclasses import replace
from html import escape
import json
from pathlib import Path
import re

from scripts.workspace_browser_observations import require_synthetic_root


# These exact process-lifecycle paths are owned by office_process and
# monthly_report_render_jobs. Their creation/removal is not a report, standing
# record or shared version write. Do not exclude the rest of render-jobs: an
# unexpected file there must remain visible to the durable equality check.
CONVERSION_RUNTIME_PATHS = frozenset({
    "render-jobs/.active-office.json", "render-jobs/.active-office.tmp",
    "render-jobs/.conversion-lock",
})


def namespace(base, token):
    """Validate an EXISTING server namespace without creating storage."""
    require_synthetic_root(base)
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("History observations require a real synthetic browser cookie.")
    from app.monthly_report_testing import _BUCKET, _location, _marker
    identity = sha256(("monthly-qa-v1:" + token).encode("ascii")).hexdigest()[:32]
    target = _location(Path(base), identity)
    if not target.is_dir() or target.is_symlink() or target.parent.name != _BUCKET:
        raise ValueError("History observations require an existing isolated namespace.")
    generation = _marker(target / ".enfra-qa-namespace", identity)
    return target, identity, generation


def _durable_root(target):
    root = target / "monthly_reports"
    if (root.is_symlink() or root.exists() and not root.is_dir()
            or not root.resolve().is_relative_to(target.resolve())):
        raise ValueError("History durable root must stay inside its browser namespace without links.")
    return root


def storage_state(base, token):
    """Fresh controller-side byte/mtime inventory, including identical rewrites.

    Preview raster caches live outside this durable library. Only the exact
    converter process-marker/temporary/lock paths above are excluded here;
    this receipt does not claim zero transient conversion activity.
    No filenames, cookie values, report words or file contents leave the probe.
    Bounds fail explicitly; a partial inventory cannot report unchanged storage.
    """
    target, identity, generation = namespace(base, token)
    root = _durable_root(target)
    groups = {name: [] for name in ("history", "assets", "standing", "journal", "cover_recovery")}
    entries = {}
    total = 0
    if root.exists():
        for n, path in enumerate(sorted(root.rglob("*"))):
            if n >= 512 or path.is_symlink():
                raise ValueError("History storage inventory exceeded its safe bounds or found a link.")
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            try:
                info = path.stat()
            except FileNotFoundError:
                if relative.as_posix() in CONVERSION_RUNTIME_PATHS:
                    continue  # The owned converter may finish during inventory.
                raise
            total += info.st_size
            if total > 64 * 1024 * 1024 or info.st_size > 32 * 1024 * 1024:
                raise ValueError("History storage inventory exceeded its byte bound.")
            if relative.as_posix() in CONVERSION_RUNTIME_PATHS:
                continue
            group = ("cover_recovery" if len(relative.parts) == 5 and relative.parts[0] == "library"
                     and relative.parts[3] in ("cover-originals", "cover-recovery") else
                     "history" if relative.parts[0] == "snapshots" else
                     "journal" if relative.parts[0] == "active_work" else
                     "assets" if relative.parts[0] == "objects" or "assets" in relative.parts else "standing")
            with path.open("rb") as stream:
                from hashlib import file_digest
                digest = file_digest(stream, "sha256").hexdigest()
            path_hash = sha256(str(relative).encode()).hexdigest()
            groups[group].append((path_hash, info.st_size, info.st_mtime_ns, digest))
            entries[path_hash] = {"group": group, "bytes": info.st_size,
                                  "mtime_ns": info.st_mtime_ns, "sha256": digest}
    return {"scope": identity, "generation": generation,
            "live_library_absent": not (Path(base) / "monthly_reports").exists(),
            "entries": entries,
            "groups": {key: {"files": len(values),
                "sha256": sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()}
                for key, values in groups.items()}}


def photograph_storage_paths(base, token, reference):
    """Exact expected paths for this fixture's current browser report photo.

    This computes identifiers only: no directory creation, asset publication or
    loader with a live-root fallback. Namespace validation precedes every path.
    """
    target, _, _ = namespace(base, token)
    _durable_root(target)
    from app import monthly_report_qa_fixture as fixture, monthly_report_library as library
    if (not isinstance(reference, str) or not library._ASSET.fullmatch(reference)
            or not reference.endswith('.jpg')):
        raise ValueError("The synthetic photograph needs its exact normalized JPEG reference.")
    digest = reference.split('.')[0]
    journal = (Path("active_work") / sha256(token.encode("ascii")).hexdigest() /
               library._contract_directory(fixture.CONTRACT) /
               library._valid_key(fixture.profile().key) / fixture.PERIOD.key)
    paths = {"journal": journal / "working.json", "photo": journal / "assets" / reference,
             "object": Path("objects") / digest[:2] / digest,
             "object_lock": Path("objects") / digest[:2] / ".write-lock"}
    return {role: sha256(str(path).encode()).hexdigest() for role, path in paths.items()}


def emit_history_snapshot(base, token):
    target, identity, generation = namespace(base, token)
    from app import monthly_report_testing as testing
    if testing.scope() != identity or testing.generation() != generation:
        raise ValueError("History receipts require the current server-isolated cookie and generation.")
    # Validate every durable descendant before the library/journal loaders read
    # it. The controller repeats this fresh inventory after each user action.
    storage_state(base, token)
    from app import monthly_report_qa_fixture as fixture, monthly_report_library as library
    from app.monthly_report_active_work import load
    from app.monthly_report_testing_ui import _working_report
    from app.monthly_report_editor import _signature
    import streamlit as st
    if library._root().resolve() != _durable_root(target).resolve():
        raise ValueError("History receipt storage escaped its browser namespace.")
    sequence_key = "_synthetic_history_observation_sequence"
    sequence = st.session_state.get(sequence_key, 0) + 1
    st.session_state[sequence_key] = sequence
    saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    receipt = {"sequence": sequence, "scope": identity, "generation": generation,
               "saved_revision": saved.revision if saved else 0, "working": None,
               "durable": None, "versions": [], "memory_assets": []}
    if saved:
        draft = _working_report(saved)
        active = load(token, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        durable = active.draft if active else saved.draft
        prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
        memory = st.session_state.get(prefix + "_assets", {})
        durable_assets = dict(active.assets) if active else {}
        def state(value, pending):
            activity = next((block.text for block in value.blocks if block.key == "activity_summary"), "")
            photos = next((block.asset_hashes for block in value.blocks if block.key == "improvements"), ())
            cover = next((block for block in value.blocks if block.key == "cover_photo"), None)
            cover_state = None
            if cover is not None:
                from app.monthly_report_asset_review import pending_asset_indexes
                if len(cover.asset_hashes) > 1:
                    raise ValueError("The synthetic cover task expects at most one photograph.")
                assets = []
                for reference in cover.asset_hashes:
                    raw = pending.get(reference)
                    if raw is None:
                        raw = library.read_asset(fixture.CONTRACT, fixture.profile().key, reference)
                    if (not isinstance(raw, bytes) or not raw or len(raw) > library.MAX_ASSET_BYTES
                            or not library._ASSET.fullmatch(reference)
                            or library.asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference):
                        raise ValueError("The synthetic cover receipt found an invalid or unbounded photograph.")
                    assets.append({"reference": reference, "bytes": len(raw), "sha256": sha256(raw).hexdigest()})
                cover_state = {"source": cover.source, "fingerprint": cover.fingerprint,
                               "assets": assets, "pending_review": list(pending_asset_indexes(cover))}
            return {"fingerprint": value.fingerprint, "activity": sha256(activity.encode()).hexdigest(),
                    "author": sha256(value.prepared_by.encode()).hexdigest(), "photos": list(photos),
                    "without_cover": replace(value, blocks=tuple(b for b in value.blocks if b.key != "cover_photo")).fingerprint,
                    "cover": cover_state}
        receipt.update(working=state(draft, memory), durable=state(durable, durable_assets))
        versions, older = library.snapshot_history(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        if older:
            raise ValueError("The bounded history fixture unexpectedly needs another page.")
        receipt["versions"] = [{"revision": item.revision, "at": item.generated_at,
            "author": sha256(item.entered_editor.encode()).hexdigest()} for item in versions]
        receipt["memory_assets"] = sorted((ref, len(raw), sha256(raw).hexdigest())
            for ref, raw in memory.items())
    # A concurrent reset/recreated namespace invalidates even an all-memory
    # observation. Never emit a receipt under the earlier generation's identity.
    _, final_identity, final_generation = namespace(base, token)
    if ((final_identity, final_generation) != (identity, generation)
            or (testing.scope(), testing.generation()) != (identity, generation)):
        raise ValueError("The isolated namespace changed during the history observation.")
    st.html('<span hidden data-enfra-history-receipt="' +
            escape(json.dumps(receipt, sort_keys=True), quote=True) + '"></span>')


def prepared_cover_storage(base, token, original):
    """Verify exactly five newly authorized private files for the tiny fixture.

    No wildcard allowance: other profiles, originals, cache entries, shared
    artwork or history writes remain visible and fail unchanged_shared.
    """
    if not isinstance(original, bytes) or not 0 < len(original) <= 64*1024:
        raise ValueError('Cover recovery receipt requires the bounded synthetic original.')
    target, _, _ = namespace(base, token)
    root = _durable_root(target)
    from app import monthly_report_qa_fixture as fixture, monthly_report_library as library
    profile = root / 'library' / library._contract_directory(fixture.CONTRACT) / library._valid_key(fixture.profile().key)
    digest = sha256(original).hexdigest()
    paths = [profile/'cover-originals'/'.write-lock', profile/'cover-originals'/(digest+'.original'),
             profile/'cover-recovery'/'.write-lock', profile/'cover-recovery'/(digest+'.json'),
             profile/'cover-recovery'/(digest+'.image')]
    if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 64*1024 for path in paths):
        raise ValueError('Cover recovery receipt found missing, linked or oversized private evidence.')
    if paths[0].read_bytes() or paths[2].read_bytes() or paths[1].read_bytes() != original:
        raise ValueError('Cover recovery changed its immutable original or lock files.')
    record = json.loads(paths[3].read_bytes())
    normalized = paths[4].read_bytes()
    if (record.get('source') != digest or record.get('status') != 'recovered'
            or type(record.get('attempts')) is not int or not 0 <= record['attempts'] <= 2
            or type(record.get('budget')) is not int or not 0 <= record['budget'] <= 256*1024*1024
            or (record.get('method') == 'normal' and (record['attempts'] != 0 or record['budget'] != 0))
            or record.get('method') not in ('normal','isolated')
            or not re.fullmatch('[0-9a-f]{64}', record.get('policy', ''))
            or record.get('derivative') != sha256(normalized).hexdigest()):
        raise ValueError('Cover recovery receipt has inconsistent original/derivative provenance.')
    from io import BytesIO
    from PIL import Image
    with Image.open(BytesIO(normalized)) as image:
        if image.format != 'JPEG' or image.size != (420,250):
            raise ValueError('Synthetic recovered cover geometry changed.')
    entries = storage_state(base, token)['entries']
    allowed = {sha256(str(path.relative_to(root)).encode()).hexdigest() for path in paths}
    if any(entries[path]['group'] != 'cover_recovery' for path in allowed):
        raise ValueError('Cover recovery receipt escaped its private storage group.')
    asset = {'reference':sha256(normalized).hexdigest()+'.jpg', 'bytes':len(normalized),
             'sha256':sha256(normalized).hexdigest()}
    return asset, {path:entries[path] for path in allowed}
