"""Operation-local discovery of already persisted, source-bound renditions.

No saved record means the unchanged legacy route. A recorded view is always
rederived; neither a receipt nor this private context grants content approval.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
from pathlib import Path
from stat import S_ISREG
from threading import RLock, get_ident

_CURRENT = ContextVar('monthly_verified_source_operation', default=None)


@dataclass
class _Operation:
    key: tuple
    original: Path | None
    view: object
    native_art: object
    manifest: Path | None
    manifest_digest: str
    receipt: Path | None
    receipt_digest: str
    owner: int
    active: bool = True

    @property
    def art_digest(self):
        return self.native_art.digest if self.native_art is not None else ''


def _file_digest(path, limit):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('Source-view evidence is unavailable or oversized.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError('Source-view evidence changed while reading.')
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def render_operation(draft, expected=None, *, source_path=None, section_key=None):
    """Private nested-call reuse; closed/copied contexts never remain valid."""
    from app import monthly_report_library as library
    from app.monthly_report_designs import source_for
    from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES
    original = Path(source_path) if source_path is not None else source_for(draft.profile)
    original = original.resolve() if original is not None else None
    key = (draft.fingerprint, section_key, str(original))
    current = _CURRENT.get()
    if current is not None and current.active and current.owner == get_ident() and current.key == key:
        if expected is not None and expected != current.view:
            raise ValueError('The expected source view differs from this verified operation.')
        yield current
        return
    manifest = library._profile_path(draft.profile.contract, draft.profile.key) / 'manifest.json'
    before = _file_digest(manifest, library.MAX_JSON_BYTES) if manifest.exists() else ''
    if original is None:
        saved = library._read(manifest) if manifest.exists() else {}
        if expected is not None or library._source_view_is_recorded(saved, draft.profile.imported_from) or 'import_source_view' in saved:
            raise ValueError('The source view requires its pinned original design.')
        view, art = None, None
    else:
        view, art = library.verified_render_source_view(
            draft, original, expected, section_key=section_key, with_native_art=True)
    receipt = None
    stored_original = None
    receipt_digest = ''
    if view is not None:
        scope = library._source_view_scope(view, draft.profile.contract, draft.profile.key, draft.period)
        receipt = library._source_view_receipt_path(manifest.parent, scope)
        receipt_digest = _file_digest(receipt, library.MAX_JSON_BYTES)
        stored_original = manifest.parent / 'imports' / (view.original_inspection.sha256 + '.docx')
        if _file_digest(stored_original, MAX_VIEW_SOURCE_BYTES) != view.original_inspection.sha256:
            raise ValueError('The stored source-view original changed during verification.')
        if receipt_digest != view.receipt_sha256:
            raise ValueError('The saved source-view receipt changed during verification.')
    operation = _Operation(key, original, view, art, manifest if before else None, before,
                           receipt, receipt_digest, get_ident())
    token = _CURRENT.set(operation)
    try:
        yield operation
        if view is not None:
            try:
                changed = (_file_digest(manifest, library.MAX_JSON_BYTES) != before
                           or _file_digest(original, MAX_VIEW_SOURCE_BYTES) != view.original_inspection.sha256
                           or _file_digest(stored_original, MAX_VIEW_SOURCE_BYTES) != view.original_inspection.sha256
                           or _file_digest(receipt, library.MAX_JSON_BYTES) != receipt_digest)
            except OSError as exc:
                raise ValueError('The saved source-view evidence disappeared during this operation; no output was published.') from exc
            if changed:
                raise ValueError('The saved source-view evidence changed during this operation; no output was published.')
    finally:
        operation.active = False
        _CURRENT.reset(token)


def import_candidate(inspection):
    """Attempt only the finite body-furniture class; this is not eligibility."""
    return any(item.kind == 'unsupported' and item.part == 'word/document.xml'
               and item.word_section in (1, 2)
               and item.note.startswith('Alternate Word representations contain different or unsupported content.')
               for item in inspection.items)


def derive_import_view(path, inspection):
    from app.monthly_report_compatibility_view import rederive_compatibility_view
    if not import_candidate(inspection):
        return None
    fresh = rederive_compatibility_view(path)
    if fresh.original_inspection != inspection:
        raise ValueError('The staged original changed during automatic rendition analysis.')
    return fresh


def source_revision_identity(draft):
    """Ordered source-byte and review-revision identities for preview admission.

    Filenames are descriptive, never authority: the immutable SHA and the
    reviewed record revision distinguish a replaced same-name upload. This
    identity is operation-local and cannot change standing data or receipts.
    """
    return tuple(sorted((source.id, source.filename, source.sha256, source.fingerprint)
                        for source in draft.sources))


# Preview-only identity hints. These contain no source bytes or authorization.
# Full render/preview operations continue to rederive and hash the original.
_IDENTITY_HINTS = OrderedDict()
_IDENTITY_HINT_LOCK = RLock()
_MAX_IDENTITY_HINTS = 64


def _evidence_stamp(path, limit):
    """Reject links/oversized files; include ctime to detect restored mtime."""
    from app import monthly_report_library as library
    library._qa_path_guard(path)
    status = path.lstat()
    if not S_ISREG(status.st_mode) or status.st_size > limit:
        raise ValueError('Source-view evidence is unavailable or oversized.')
    return (status.st_dev, status.st_ino, status.st_mode, status.st_nlink,
            status.st_size, status.st_mtime_ns, status.st_ctime_ns)


def _drop_identity_hint(key):
    with _IDENTITY_HINT_LOCK:
        _IDENTITY_HINTS.pop(key, None)


def cache_identity(draft):
    """Preview-ticket invalidation, not an import approval or render authority.

    Once a digest was verified, ordinary UI reruns check the *same* scoped
    original, receipt and manifest through inode/size/mtime/ctime metadata.
    A changed, missing or linked file cannot reuse the hint. Independent
    render_operation() and saved-source reads still perform full-byte checks.
    """
    import json
    from dataclasses import asdict
    from app import monthly_report_library as library
    from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES, POLICY

    folder = library._profile_path(draft.profile.contract, draft.profile.key)
    manifest = folder / 'manifest.json'
    # Profile values and the exact physical namespace are part of the key;
    # never share an identity across a site, contract, month or QA root.
    profile_identity = json.dumps(asdict(draft.profile), sort_keys=True, separators=(',', ':'))
    key = (str(folder), draft.period.key, profile_identity)
    if not manifest.exists():
        _drop_identity_hint(key)
        return ''
    with _IDENTITY_HINT_LOCK:
        hint = _IDENTITY_HINTS.get(key)
    if hint is not None:
        identity, paths, limits, previous = hint
        try:
            current = tuple(_evidence_stamp(path, limit) for path, limit in zip(paths, limits))
        except (OSError, ValueError):
            _drop_identity_hint(key)
            raise
        if current == previous:
            with _IDENTITY_HINT_LOCK:
                if key in _IDENTITY_HINTS:
                    _IDENTITY_HINTS.move_to_end(key)
            return identity
        _drop_identity_hint(key)

    # The first request, or any metadata revision, rechecks all original bytes
    # with existing size bounds and saved scope/receipt validation.
    manifest_before = _evidence_stamp(manifest, library.MAX_JSON_BYTES)
    value = library._read(manifest)
    digest = draft.profile.imported_from
    if not library._source_view_is_recorded(value, digest) and 'import_source_view' not in value:
        return ''
    matches = [record for record in value.get('source_views', {}).values()
               if isinstance(record, dict) and isinstance(record.get('scope'), dict)
               and record['scope'].get('original_sha256') == digest
               and record['scope'].get('period') == draft.period.key]
    if len(matches) != 1:
        raise library.LibraryError('This report month requires its source-bound artwork review.')
    record = matches[0]; scope = record['scope']
    if (scope.get('contract'), scope.get('profile_key'), scope.get('policy')) != (
            draft.profile.contract, draft.profile.key, POLICY):
        raise library.LibraryError('The saved source-view scope or policy changed.')
    original = folder / 'imports' / (digest + '.docx')
    receipt = library._source_view_receipt_path(folder, scope)
    paths = (manifest, original, receipt)
    limits = (library.MAX_JSON_BYTES, MAX_VIEW_SOURCE_BYTES, library.MAX_JSON_BYTES)
    before = (manifest_before,
              _evidence_stamp(original, MAX_VIEW_SOURCE_BYTES),
              _evidence_stamp(receipt, library.MAX_JSON_BYTES))
    actual = _file_digest(original, MAX_VIEW_SOURCE_BYTES)
    if actual != digest:
        raise library.LibraryError('The saved source-view original changed.')
    receipt_digest = _file_digest(receipt, library.MAX_JSON_BYTES)
    if receipt_digest != scope.get('receipt_sha256'):
        raise library.LibraryError('The saved source-view receipt changed.')
    manifest_digest = _file_digest(manifest, library.MAX_JSON_BYTES)
    after = tuple(_evidence_stamp(path, limit) for path, limit in zip(paths, limits))
    if before != after:
        raise library.LibraryError('Saved source-view evidence changed during preview identity verification.')
    # Full manifest identity includes the scoped visual suitability record;
    # unrelated saved changes invalidate a hint, never confer approval.
    identity = hashlib.sha256(json.dumps((asdict(draft.profile), draft.period.key,
        manifest_digest, actual, receipt_digest),
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with _IDENTITY_HINT_LOCK:
        _IDENTITY_HINTS[key] = (identity, paths, limits, after)
        _IDENTITY_HINTS.move_to_end(key)
        while len(_IDENTITY_HINTS) > _MAX_IDENTITY_HINTS:
            _IDENTITY_HINTS.popitem(last=False)
    return identity


def preview_fingerprint(draft):
    identity = cache_identity(draft)
    return hashlib.sha256((draft.fingerprint + ':' + identity).encode()).hexdigest() if identity else draft.fingerprint
