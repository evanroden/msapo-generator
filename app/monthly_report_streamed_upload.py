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
