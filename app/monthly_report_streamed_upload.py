"""Bounded, request-owned staging for native Streamlit upload streams.

The browser uploader has already completed its transfer before this code runs.
This layer never calls getvalue() or places the original bytes in session_state.
On Linux, TemporaryFile is unlinked immediately, even if the request process
dies. Other platforms use an owned TemporaryDirectory cleaned on exit.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable, Iterator

from app.monthly_report_upload_limits import byte_limit_label

CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class StagedUpload:
    """A file descriptor-backed, bounded original, valid only in its context."""

    path: Path
    size: int
    sha256: str


@contextmanager
def stage_upload(upload, limit: int, *, on_progress: Callable[[int], None] | None = None
                 ) -> Iterator[StagedUpload]:
    """Hash and stage one file without materializing a second upload-sized blob.

    The advertised size is only a fast rejection; enforce the actual byte
    count as well. Neither success nor a raised BaseException retains a stage.
    """
    if type(limit) is not int or limit <= 0:
        raise ValueError("An upload limit must be positive.")
    advertised = getattr(upload, "size", None)
    if isinstance(advertised, int) and advertised > limit:
        raise ValueError(f"File exceeds the {byte_limit_label(limit)} upload limit.")
    with ExitStack() as stack:
        if os.name == "posix" and Path("/proc/self/fd").is_dir():
            # Linux anonymous inode: a SIGKILL cannot leave a named partial.
            output = stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
            path = Path("/proc/self/fd") / str(output.fileno())
        else:
            # Windows/macOS fallback: delete on rejection, success or rerun.
            directory = Path(stack.enter_context(
                tempfile.TemporaryDirectory(prefix="monthly-upload-")))
            path = directory / "source"
            output = stack.enter_context(path.open("w+b"))
        try:
            upload.seek(0)
            total = 0
            hasher = hashlib.sha256()
            while True:
                chunk = upload.read(CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"File exceeds the {byte_limit_label(limit)} upload limit.")
                hasher.update(chunk)
                output.write(chunk)
                if on_progress:
                    on_progress(total)
            if total == 0:
                raise ValueError("This source file is empty. Choose a nonempty copy.")
            output.flush()
            output.seek(0)
            yield StagedUpload(path, total, hasher.hexdigest())
        finally:
            # A widget may disappear during cancellation; never mask the
            # original reader/parser exception with a failed cursor reset.
            try:
                upload.seek(0)
            except (OSError, ValueError):
                pass


def ingest_uploaded_selection(profile, uploads, existing=(), *, on_progress=None, on_checkpoint=None):
    """Admit one source at a time; each successful sibling is checkpointable.

    Return (contents, messages, file receipts). Receipts contain no file bytes.
    A broken upload is isolated from its siblings. Unexpected BaseException is
    deliberately propagated after the anonymous stage has been reclaimed.
    """
    from app import monthly_report_sources as sources
    from app.monthly_report_upload_limits import source_size_error

    contents = tuple(existing)
    messages = []
    receipts = []
    for upload in uploads:
        filename = Path(str(getattr(upload, "name", "")).replace("\\", "/")).name
        suffix = Path(filename).suffix.casefold()
        if suffix not in sources.SUPPORTED:
            reason = "Unsupported file type. Choose PDF, DOCX, XLSX, CSV, EML, MSG, TXT or a supported image."
            message = f"Not read: {filename or 'unnamed file'}. {reason}"
            messages.append(message)
            receipts.append((filename, "rejected", message))
            continue
        limit = sources.file_size_limit(suffix)
        try:
            with stage_upload(upload, limit, on_progress=(
                    (lambda n, name=filename, declared=getattr(upload, "size", None):
                     on_progress(name, n, declared)) if on_progress else None)) as staged:
                previous = contents
                before = {c.source.sha256 for c in contents}
                contents, new_messages = sources.ingest_batch(
                    profile, ((filename, staged),), contents)
                for message in new_messages:
                    if message not in messages:
                        messages.append(message)
                rejected = next((m for m in new_messages if m.startswith(
                    f"Not read: {filename}.") or m.startswith(
                    f"Could not restore saved source: {filename}.")), None)
                if rejected is not None or staged.sha256 not in {c.source.sha256 for c in contents}:
                    receipts.append((filename, "rejected", rejected or f"Not read: {filename}. File was not accepted."))
                elif staged.sha256 not in before:
                    receipts.append((filename, "accepted", f"Accepted: {filename} ({staged.size:,} bytes)."))
                elif any(m.startswith(f"Saved source restored: {filename}.") for m in new_messages):
                    receipts.append((filename, "restored", f"Restored: {filename}. Existing source reviews are unchanged."))
                else:
                    receipts.append((filename, "duplicate", f"Duplicate skipped: {filename}. Existing source reviews are unchanged."))
                if on_checkpoint is not None and contents != previous:
                    on_checkpoint(contents)
        except (ValueError, OSError) as exc:
            if isinstance(exc, OSError):
                reason = "The file could not be staged. Retry this file."
            elif "File exceeds the " in str(exc):
                reason = source_size_error(suffix, limit)
            else:
                reason = str(exc)[:300]
            message = f"Not read: {filename}. {reason}"
            messages.append(message)
            receipts.append((filename, "rejected", message))
    return contents, tuple(messages), tuple(receipts)


def publish_staged_original(path: Path, staged: StagedUpload) -> None:
    """Atomically publish the verified original using existing shared objects.

    TXT and less common image types do not belong to the shared object pool;
    their profile-local originals get the same streamed atomic publication.
    """
    from app import monthly_report_library as library
    from app.monthly_report_objects import object_path, store_file

    library._qa_path_guard(path)
    if path.is_symlink():
        raise ValueError("Saved source path is not a regular file.")
    with staged.path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != staged.sha256:
            raise ValueError("Staged source failed integrity verification.")
    if object_path(path) is not None:
        store_file(path, staged.path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == staged.sha256:
                return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            with staged.path.open("rb") as stream:
                while chunk := stream.read(CHUNK_BYTES):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != staged.sha256:
                raise ValueError("Staged source changed while publishing.")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
