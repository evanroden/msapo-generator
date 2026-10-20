"""Explicit, isolated source inspection; never report generation or approval.

Only a full-resolution passive copy is rendered. Raw upload bytes remain intact,
and receipts distinguish their hash from the exact bytes given to LibreOffice.
"""
from __future__ import annotations

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


def _folder(owner):
    if not isinstance(owner, str) or not _TOKEN.fullmatch(owner):
        raise SourcePreviewError('Invalid source preview session.')
    root = _root()
    folder = root / owner
    if folder.is_symlink():
        raise SourcePreviewError('Source preview storage is unavailable.')
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def _write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        path.chmod(0o600)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _active(owner):
    path = _folder(owner) / 'active.json'
    if path.is_symlink() or path.stat().st_size > 4096:
        raise SourcePreviewError('Source preview session changed.')
    return json.loads(path.read_text())


def retire(owner, *, expected_epoch=None):
    """Explicit new selection/clear invalidates only this session's artifacts."""
    with _LOCK, library._locked(_root()):
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
        for name in sorted(old | new):
            a = sha256(before.read(name)).hexdigest() if name in old else None
            b = sha256(after.read(name)).hexdigest() if name in new else None
            if a != b:
                changes.append({'part': name, 'source_sha256': a, 'render_sha256': b})
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
    with _LOCK, library._locked(_root()):
        active = _check(request)
        if (active.get('attempt') or str(upload_id) != request.upload_id
                or sha256(raw).hexdigest() != request.source_sha256 or len(raw) > MAX_BYTES):
            raise SourcePreviewError('This submission is stale or was already attempted. Choose a fresh upload.')
        folder = _folder(request.owner)
        # Reserve one bounded job rather than evict another tab's first failure.
        used = 0
        for saved in _root().iterdir():
            if saved.is_symlink():
                raise SourcePreviewError('Source preview storage is unavailable.')
            if saved.is_dir():
                size = sum(item.stat().st_size for item in saved.rglob('*') if item.is_file())
                # Account for another process's admitted conversion before its
                # full source/input/PDF files have been written.
                pending = (saved / 'attempt.json').exists() and not (saved / 'receipt.json').exists()
                used += max(size, 3 * MAX_BYTES) if pending else size
        if used + 3 * MAX_BYTES > MAX_STORE_BYTES:
            raise SourcePreviewError('QA source-preview storage is full. Clear this browser’s earlier source previews.')
        # Exclusive claim survives reruns/replays even if the office process fails.
        _write(folder / 'attempt.json', asdict(request))
        active['attempt'] = request.request_id
        temporary = folder / 'active-next.json'
        _write(temporary, active)
        temporary.replace(folder / 'active.json')
    receipt = {**asdict(request), 'purpose': 'SOURCE PREVIEW ONLY — not a completed report',
               'source_bytes': len(raw), 'created_at': datetime.now(timezone.utc).isoformat(),
               'transforms': ['current passive_docx sanitation; full-resolution media; no report assembly'],
               'status': 'failed', 'stage': 'admission'}
    try:
        # Diagnostics yield to foreground work and never form an unbounded queue.
        with jobs.work_slot(preview=True, wait_seconds=0):
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
            receipt.update(render_input_sha256=sha256(passive).hexdigest(), render_input_bytes=len(passive),
                           changed_package_parts=_transform_inventory(folder / 'source.docx', passive))
            del passive
            receipt['stage'] = 'LibreOffice conversion'
            with tempfile.TemporaryDirectory(prefix='.conversion-', dir=folder) as temporary:
                output, renderer, pages = _render(render_input, Path(temporary))
                with _LOCK, library._locked(_root()):
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
    with _LOCK, library._locked(_root()):
        _check(request)
        _write(folder / 'receipt.json', receipt)
    return receipt


def artifact(request, name):
    """Revalidate lease, request and checksum at each per-session download."""
    expected = {'source.docx': 'source_sha256', 'render-input.docx': 'render_input_sha256',
                'source-preview.pdf': 'pdf_sha256'}
    with _LOCK, library._locked(_root()):
        active = _check(request)
        if active.get('attempt') != request.request_id or name not in (*expected, 'receipt.json'):
            raise SourcePreviewError('This source preview is no longer current.')
        folder = _folder(request.owner)
        receipt_path = folder / 'receipt.json'
        if receipt_path.is_symlink() or receipt_path.stat().st_size > 1024 * 1024:
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
        return raw
