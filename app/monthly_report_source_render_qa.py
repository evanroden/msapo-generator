"""Explicit, isolated source inspection; never report generation or approval.

Only a full-resolution passive copy is rendered. Raw upload bytes remain intact,
and receipts distinguish their hash from the exact bytes given to LibreOffice.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from threading import RLock
from uuid import uuid4
from zipfile import ZipFile

import fitz

from app import monthly_report_testing as testing
from app import monthly_report_library as library
from app import monthly_report_render_jobs as jobs
from app.monthly_report_import import ImportError, _package
from app.monthly_report_native_package import passive_docx, _xml
from app.office_limits import prepare_profile
from app.office_process import run_office
from app.public_build import runtime_commit

MAX_BYTES = 32 * 1024 * 1024
MAX_STORE_BYTES = 128 * 1024 * 1024
MAX_GLOBAL_BYTES = 384 * 1024 * 1024
MIN_FREE_BYTES = 256 * 1024 * 1024
MAX_OWNERS = 128
MAX_SCAN_ENTRIES = 4096
RETENTION_SECONDS = 6 * 60 * 60
ABANDONED_SECONDS = 10 * 60
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
RESERVE_BYTES = 3 * MAX_BYTES + MAX_RECEIPT_BYTES
SCRATCH_RESERVE_BYTES = 64 * 1024 * 1024
MAX_PAGES = 150
_LOCK = RLock()
_TOKEN = re.compile(r'[0-9a-f]{32}\Z')
_LIMIT_EXEC = '''import os,resource,sys
resource.setrlimit(resource.RLIMIT_AS, (1536*1024**2,1536*1024**2))
resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024**2,32*1024**2))
resource.setrlimit(resource.RLIMIT_CPU, (90,90))
os.execv(sys.argv[1],sys.argv[1:])
'''


class SourcePreviewError(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    owner: str
    epoch: str
    scope: str
    generation: str
    request_id: str
    upload_id: str
    source_sha256: str
    label: str
    kind: str


def _root():
    if not testing.scope() or not testing.generation():
        raise SourcePreviewError('Source preview requires an active isolated QA session.')
    parent = library._root()
    if parent.is_symlink():
        raise SourcePreviewError('Source preview storage is unavailable.')
    parent.mkdir(mode=0o700, exist_ok=True)
    root = parent / 'source-previews'
    if root.is_symlink():
        raise SourcePreviewError('Source preview storage is unavailable.')
    root.mkdir(mode=0o700, exist_ok=True)
    return root


@contextmanager
def _storage_lock():
    """One short disk-wide lock for diagnostic accounting, never conversion."""
    import fcntl
    root = _root()  # Validate this caller's lease before reaching the QA bucket.
    bucket = root.parents[2]
    if bucket.name != testing._BUCKET or bucket.is_symlink():
        raise SourcePreviewError('Source preview storage is unavailable.')
    lock_path = bucket / '.source-preview-lock'
    if lock_path.is_symlink():
        raise SourcePreviewError('Source preview storage is unavailable.')
    with _LOCK, lock_path.open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            with library._locked(root):
                yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _size(folder):
    # Temporary trees can disappear during another converter's cleanup. Pending
    # attempts already carry a worst-case artifact plus scratch reservation.
    total = 0
    for item in folder.iterdir():
        try:
            if item.is_symlink():
                raise SourcePreviewError('Source preview storage is unavailable.')
            if item.is_file():
                total += item.stat().st_size
        except FileNotFoundError:
            continue
    return total


@contextmanager
def _execution_lease(folder):
    import fcntl
    path = folder / '.execution-lock'
    if path.is_symlink():
        raise SourcePreviewError('Source preview storage is unavailable.')
    with path.open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _remove(folder):
    for item in folder.rglob('*'):
        if item.is_symlink():
            raise SourcePreviewError('Source preview storage is unavailable.')
    try:
        # A deadline alone is not proof that passive validation/process cleanup
        # has stopped. Automatic expiry/browser recovery must also win this lock.
        with _execution_lease(folder):
            shutil.rmtree(folder)
        return True
    except BlockingIOError:
        return False
    except FileNotFoundError:
        if folder.exists():
            raise
        return True


def _entries(folder):
    with os.scandir(folder) as entries:
        for entry in entries:
            yield Path(entry.path)


def _catalog(*, prune=False, keep=None):
    """Only this helper's folders in marker-verified QA namespaces are touched."""
    current = _root()
    rows = []
    entries = 0
    for namespace in _entries(current.parents[2]):
        entries += 1
        if entries > MAX_SCAN_ENTRIES:
            raise SourcePreviewError('Source preview storage inventory exceeds its safety bound.')
        if not _TOKEN.fullmatch(namespace.name):
            continue
        if namespace.is_symlink():
            raise SourcePreviewError('Source preview storage is unavailable.')
        try:
            testing._marker(namespace / testing._SENTINEL, namespace.name)
            parent = namespace / 'monthly_reports'
            root = parent / 'source-previews'
            if parent.is_symlink() or root.is_symlink():
                raise SourcePreviewError('Source preview storage is unavailable.')
            if not root.exists():
                continue
            for folder in _entries(root):
                entries += 1
                if entries > MAX_SCAN_ENTRIES:
                    raise SourcePreviewError('Source preview storage inventory exceeds its safety bound.')
                if not _TOKEN.fullmatch(folder.name):
                    continue
                try:
                    if folder.is_symlink():
                        raise SourcePreviewError('Source preview storage is unavailable.')
                    active = folder / 'active.json'
                    if active.is_symlink():
                        raise SourcePreviewError('Source preview storage is unavailable.')
                    if active.stat().st_size > 4096:
                        raise SourcePreviewError('Source preview storage is unavailable.')
                    state = json.loads(active.read_text())
                    age = time.time() - active.stat().st_mtime
                    pending = (folder / 'attempt.json').exists() and not (folder / 'receipt.json').exists()
                    running = pending and time.time() < state.get('deadline', float('inf'))
                    if prune and folder != keep and age > RETENTION_SECONDS and not running:
                        if _remove(folder):
                            continue
                    size = _size(folder)
                    if not pending and any(item.is_dir() for item in folder.iterdir()):
                        size += SCRATCH_RESERVE_BYTES  # Retain a failed-cleanup scratch reservation.
                    rows.append((folder, max(size, RESERVE_BYTES) if pending else size, pending))
                except FileNotFoundError:
                    # A missing owner must not hide valid siblings from quota
                    # accounting. Only an actually empty/disappeared folder is
                    # ignorable; orphaned payloads without metadata fail closed.
                    try:
                        if any(folder.iterdir()):
                            raise SourcePreviewError('Source preview owner metadata is unavailable.')
                    except FileNotFoundError:
                        pass
                    continue
        except FileNotFoundError:
            continue  # A verified QA reset may remove this namespace concurrently.
    return rows


def earlier_previews(owner):
    """Opaque identities only; no other tab's source content is exposed."""
    with _storage_lock():
        return tuple(earlier_previews_unlocked(owner))


def clear_earlier(owner, epoch, snapshot):
    """Explicit browser-local recovery, pinned against stale/reopened owners."""
    with _storage_lock():
        if owner is not None and _active(owner).get('epoch') != epoch:
            raise SourcePreviewError('This source-preview cleanup request is stale.')
        current = set(earlier_previews_unlocked(owner))
        for old_owner, old_epoch in snapshot:
            if (old_owner, old_epoch) in current:
                _remove(_folder(old_owner))


def earlier_previews_unlocked(owner):
    # Kept separate to avoid recursively acquiring the OS lock.
    result = []
    for folder, _size_bytes, pending in _catalog(prune=True, keep=(_root() / owner if owner else None)):
        if folder.parent == _root() and folder.name != owner:
            active = folder / 'active.json'
            state = json.loads(active.read_text())
            if not pending or time.time() >= state.get('deadline', float('inf')):
                result.append((folder.name, state['epoch']))
    return result


def _folder(owner, *, create=True):
    if not isinstance(owner, str) or not _TOKEN.fullmatch(owner):
        raise SourcePreviewError('Invalid source preview session.')
    root = _root()
    folder = root / owner
    if folder.is_symlink():
        raise SourcePreviewError('Source preview storage is unavailable.')
    if create:
        folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def _write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        path.chmod(0o600)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _active(owner):
    path = _folder(owner, create=False) / 'active.json'
    if path.is_symlink() or path.stat().st_size > 4096:
        raise SourcePreviewError('Source preview session changed.')
    return json.loads(path.read_text())


def session_current(owner, epoch):
    """Read-only owner check; a peer may have expired an idle browser session."""
    with _storage_lock():
        try:
            return _active(owner).get('epoch') == epoch
        except FileNotFoundError:
            return False


def retire(owner, *, expected_epoch=None):
    """Explicit new selection/clear invalidates only this session's artifacts."""
    if not isinstance(owner, str) or not _TOKEN.fullmatch(owner):
        raise SourcePreviewError('Invalid source preview session.')
    with _storage_lock():
        rows = _catalog(prune=True, keep=_root() / owner)
        if not (_root() / owner).exists() and len(rows) >= MAX_OWNERS:
            raise SourcePreviewError('QA source-preview storage is full. Earlier diagnostics expire after six hours.')
        folder = _folder(owner)
        if expected_epoch is not None and _active(owner).get('epoch') != expected_epoch:
            raise SourcePreviewError('This source-preview clear request is stale.')
        for child in folder.rglob('*'):
            if child.is_symlink():
                raise SourcePreviewError('Source preview storage is unavailable.')
        for child in tuple(folder.iterdir()):
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        epoch = uuid4().hex
        _write(folder / 'active.json', {'epoch': epoch})
        return epoch


def new_request(owner, epoch, raw, *, upload_id, label, kind):
    _root()  # Revalidate the immutable namespace lease before capturing it.
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise SourcePreviewError('Choose one DOCX no larger than 32 MiB.')
    if kind not in {'original', 'named derivative'} or not label.strip() or len(label) > 80:
        raise SourcePreviewError('Name this original or test derivative (up to 80 characters).')
    if any(ord(char) < 32 for char in label) or not upload_id:
        raise SourcePreviewError('Choose a fresh upload and a plain-text name.')
    if _active(owner).get('epoch') != epoch:
        raise SourcePreviewError('This upload changed. Make a fresh render request.')
    return Request(owner, epoch, testing.scope(), testing.generation(), uuid4().hex,
                   str(upload_id), sha256(raw).hexdigest(), label.strip(), kind)


def _check(request):
    if (testing.scope(), testing.generation()) != (request.scope, request.generation):
        raise SourcePreviewError('The isolated QA session changed; this request is stale.')
    active = _active(request.owner)  # library._root also checks reset-on-disk.
    if (active.get('deadline', float('inf')) < time.time()
            and not (_folder(request.owner, create=False) / 'receipt.json').exists()):
        raise SourcePreviewError('This source-preview attempt expired. Make a fresh request.')
    if active.get('epoch') != request.epoch:
        raise SourcePreviewError('The upload changed; this request is stale.')
    return active


def _safe_source(path):
    # The normal native sanitizer validates the reachable graph. Additionally
    # reject macros/active binary payloads even when unreachable, and external
    # resource relationships even when the sanitizer would discard them.
    with _package(path) as package:
        for name in package.namelist():
            if re.search(r'(?i)(vbaproject|vbadata|activex|embeddings)(?:[/.]|$)', name):
                raise SourcePreviewError('Active or embedded content is not supported for source preview.')
            if name == '[Content_Types].xml':
                root = _xml(package.read(name))
                if any(any(token in node.get('ContentType', '').lower()
                           for token in ('macroenabled', 'vbaproject', 'activex', 'oleobject')) for node in root):
                    raise SourcePreviewError('Macro-enabled or active documents cannot be previewed.')
            if name.endswith('.rels'):
                for relation in _xml(package.read(name)):
                    if (relation.get('TargetMode', '').casefold() == 'external'
                            and not relation.get('Type', '').endswith('/hyperlink')):
                        raise SourcePreviewError('External document resources cannot be previewed.')
    result = passive_docx(path)
    if len(result) > MAX_BYTES:
        raise SourcePreviewError('The passive render input exceeds 32 MiB.')
    return result


def _transform_inventory(source, passive):
    """Part-level evidence of exactly which payloads sanitation changed."""
    with ZipFile(source) as before, ZipFile(BytesIO(passive)) as after:
        old, new = set(before.namelist()), set(after.namelist())
        changes = []
        inventory_bytes = 2
        for name in sorted(old | new):
            a = sha256(before.read(name)).hexdigest() if name in old else None
            b = sha256(after.read(name)).hexdigest() if name in new else None
            if a != b:
                row = {'part': name, 'source_sha256': a, 'render_sha256': b}
                inventory_bytes += len(json.dumps(row).encode()) + 2
                if inventory_bytes > 1024 * 1024:
                    raise SourcePreviewError('The package change inventory exceeds its diagnostic budget.')
                changes.append(row)
        return changes


def _renderer(binary):
    # Query the same binary under the same conversion lease as the real render.
    result = run_office([binary, '--version'], timeout=15)
    version = result.stdout.strip()
    if result.returncode or not re.fullmatch(r'LibreOffice 24\.2\.\d+(?:\.\d+)?(?: [A-Za-z0-9.()+:_-]{1,160})?', version):
        raise SourcePreviewError('Source preview requires the deployed LibreOffice 24.2 renderer.')
    from runtime.check_renderer import FONT_MATCHES
    fonts = []
    for pattern, expected in FONT_MATCHES.items():
        match = subprocess.run(['fc-match', '--format=%{file}', pattern], capture_output=True, timeout=5, check=True)
        path = Path(match.stdout.decode().strip())
        if path.name != expected or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise SourcePreviewError('The deployed font check failed; no fidelity result was produced.')
        fonts.append({'pattern': pattern, 'file': path.name, 'sha256': sha256(path.read_bytes()).hexdigest()})
    inventory = subprocess.run(['fc-list', '--format=%{family}|%{style}|%{file}\n'],
                               capture_output=True, timeout=5, check=True).stdout
    if len(inventory) > 1024 * 1024:
        raise SourcePreviewError('The font inventory exceeds its diagnostic budget.')
    # Do not publish server paths. Font family/style/basenames are sufficient
    # for the inventory; the expected resolved faces also carry byte hashes.
    rows = sorted(set('|'.join(row.split('|')[:-1] + [Path(row.split('|')[-1]).name])
                      for row in inventory.decode('utf-8', 'replace').splitlines()))
    if len(json.dumps(rows).encode()) > 1024 * 1024:
        raise SourcePreviewError('The font inventory exceeds its diagnostic budget.')
    return {'version': version, 'fonts': fonts, 'font_inventory': rows,
            'font_inventory_sha256': sha256('\n'.join(rows).encode()).hexdigest(),
            'app_commit': runtime_commit() or 'unavailable'}


def _diagnostics(result):
    """Non-content evidence; run_office caps each captured stream at 16 KiB."""
    evidence = {'capture_limit_bytes_per_stream': 16 * 1024}
    for name in ('stdout', 'stderr'):
        raw = getattr(result, name, '').encode('utf-8')
        evidence[name] = {'present': bool(raw), 'decoded_capture_bytes': len(raw),
                          'sha256': sha256(raw).hexdigest(), 'may_be_truncated': len(raw) >= 16 * 1024}
    return evidence


def _render(source, directory):
    binary = shutil.which('libreoffice') or shutil.which('soffice')
    if not binary:
        raise SourcePreviewError('LibreOffice 24.2 is unavailable; no PDF was produced.')
    with jobs.conversion_slot(wait_seconds=0):
        renderer = _renderer(binary)
        profile_uri = prepare_profile(directory / 'profile')
        result = run_office([sys.executable, '-c', _LIMIT_EXEC, binary, '--headless', '--norestore',
                             f'-env:UserInstallation={profile_uri}', '--convert-to', 'pdf:writer_pdf_Export',
                             '--outdir', str(directory), str(source.resolve())], timeout=120)
        renderer['office_diagnostics'] = _diagnostics(result)
        def fail(message):
            error = SourcePreviewError(message)
            error.renderer = renderer
            raise error
        output = directory / (source.stem + '.pdf')
        # Never log Office output: it may contain document text or paths.
        if result.returncode or not output.is_file() or output.is_symlink() or not 0 < output.stat().st_size <= MAX_BYTES:
            fail('The source conversion failed; no valid PDF was produced.')
        with fitz.open(output) as document:
            if not document.is_pdf or document.is_encrypted or not 1 <= len(document) <= MAX_PAGES:
                fail('The source PDF exceeds the 150-page limit or is unreadable.')
            if any(not math.isfinite(n) or not 0 < n <= 2448 for page in document
                   for n in (page.rect.width, page.rect.height)):
                fail('The source PDF has unsupported page dimensions.')
            pages = len(document)
        return output, renderer, pages


def execute(request, raw, *, upload_id):
    """One attempt only. A failure is retained, never silently retried."""
    with _storage_lock():
        active = _check(request)
        if (active.get('attempt') or str(upload_id) != request.upload_id
                or sha256(raw).hexdigest() != request.source_sha256 or len(raw) > MAX_BYTES):
            raise SourcePreviewError('This submission is stale or was already attempted. Choose a fresh upload.')
        folder = _folder(request.owner)
        # Global accounting survives cookie churn; only expired diagnostics are
        # pruned. Non-preview QA/editor/live storage is never removed.
        rows = _catalog(prune=True, keep=folder)
        used = sum(size for saved, size, _pending in rows if saved.parent == _root())
        global_used = sum(size + (SCRATCH_RESERVE_BYTES if pending else 0)
                          for _saved, size, pending in rows)
        reservation = RESERVE_BYTES + SCRATCH_RESERVE_BYTES
        if (used + RESERVE_BYTES > MAX_STORE_BYTES
                or global_used + reservation > MAX_GLOBAL_BYTES
                or shutil.disk_usage(_root()).free < MIN_FREE_BYTES + reservation):
            raise SourcePreviewError('QA source-preview storage is full. Clear earlier source-preview files; diagnostics expire after six hours.')
        # Exclusive claim survives reruns/replays even if the office process fails.
        _write(folder / 'attempt.json', asdict(request))
        active['attempt'] = request.request_id
        active['deadline'] = time.time() + ABANDONED_SECONDS
        temporary = folder / 'active-next.json'
        _write(temporary, active)
        temporary.replace(folder / 'active.json')
    receipt = {**asdict(request), 'purpose': 'SOURCE PREVIEW ONLY — not a completed report',
               'source_bytes': len(raw), 'created_at': datetime.now(timezone.utc).isoformat(),
               'transforms': ['current passive_docx sanitation; full-resolution media; no report assembly'],
               'status': 'failed', 'stage': 'admission'}
    try:
        # Diagnostics yield to foreground work and never form an unbounded queue.
        with _execution_lease(folder), jobs.work_slot(preview=True, wait_seconds=0):
            _check(request)
            with (folder / 'source.docx').open('xb') as source:
                source.write(raw)
            (folder / 'source.docx').chmod(0o400)
            receipt['stage'] = 'passive package validation'
            passive = _safe_source(folder / 'source.docx')
            render_input = folder / 'render-input.docx'
            with render_input.open('xb') as source:
                source.write(passive)
            render_input.chmod(0o400)
            receipt.update(render_input_sha256=sha256(passive).hexdigest(), render_input_bytes=len(passive))
            receipt['changed_package_parts'] = _transform_inventory(folder / 'source.docx', passive)
            del passive
            _check(request)  # Do not start Office after an expired/cancelled validation.
            receipt['stage'] = 'LibreOffice conversion'
            with tempfile.TemporaryDirectory(prefix='.conversion-', dir=folder) as temporary:
                output, renderer, pages = _render(render_input, Path(temporary))
                with _storage_lock():
                    _check(request)  # Reset/upload/clear cannot publish a stale result.
                    destination = folder / 'source-preview.pdf'
                    os.link(output, destination)
                    receipt.update(renderer=renderer, pages=pages, pdf_bytes=destination.stat().st_size,
                                   pdf_sha256=sha256(destination.read_bytes()).hexdigest(), status='rendered')
            receipt['stage'] = 'complete'
    except jobs.RenderBusy:
        receipt['error'] = 'Renderer busy. No automatic retry occurred; make a new explicit attempt.'
    except subprocess.TimeoutExpired:
        receipt['error'] = 'The bounded renderer timed out. No automatic retry occurred.'
    except SourcePreviewError as exc:
        receipt['error'] = str(exc)
        if hasattr(exc, 'renderer'):
            receipt['renderer'] = exc.renderer
    except (ImportError, OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        receipt['error'] = 'Source inspection failed at the recorded stage. Original bytes were not modified; no automatic retry occurred.'
    with _storage_lock():
        _check(request)
        if len(json.dumps(receipt).encode()) > MAX_RECEIPT_BYTES:
            raise SourcePreviewError('The source-preview receipt exceeds its diagnostic budget.')
        _write(folder / 'receipt.json', receipt)
    return receipt


def artifact(request, name):
    """Revalidate lease, request and checksum at each per-session download."""
    expected = {'source.docx': 'source_sha256', 'render-input.docx': 'render_input_sha256',
                'source-preview.pdf': 'pdf_sha256'}
    with _storage_lock():
        active = _check(request)
        if active.get('attempt') != request.request_id or name not in (*expected, 'receipt.json'):
            raise SourcePreviewError('This source preview is no longer current.')
        folder = _folder(request.owner)
        receipt_path = folder / 'receipt.json'
        if receipt_path.is_symlink() or receipt_path.stat().st_size > MAX_RECEIPT_BYTES:
            raise SourcePreviewError('Source preview receipt is unavailable.')
        receipt = json.loads(receipt_path.read_text())
        if receipt.get('request_id') != request.request_id:
            raise SourcePreviewError('Source preview receipt does not match.')
        path = folder / name
        if path.is_symlink() or not 0 < path.stat().st_size <= MAX_BYTES:
            raise SourcePreviewError('Source preview artifact is unavailable.')
        raw = path.read_bytes()
        if name != 'receipt.json' and sha256(raw).hexdigest() != receipt.get(expected[name]):
            raise SourcePreviewError('Source preview artifact failed its checksum.')
        os.utime(folder / 'active.json', None)  # Downloads renew diagnostic retention.
        return raw
