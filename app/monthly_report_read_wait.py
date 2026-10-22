"""Cooperative capacity retries for a pure starting-source read, never actions."""
from time import monotonic, sleep

from app.monthly_report_render_jobs import RenderBusy

READ_WAIT_SECONDS = 20


def read_with_capacity_wait(read, checkpoint, waiting, *, wait_seconds=READ_WAIT_SECONDS):
    """Repeat only a failed read; every attempt obtains admission and fresh proof.

    The deadline bounds capacity waiting, not an admitted proof's execution.
    Checkpoints run on the script thread so newer navigation/Stop cancels old
    waiters. Callers must not supply save/generate or other mutating operations.
    """
    deadline = monotonic() + min(READ_WAIT_SECONDS, max(0, wait_seconds))
    while True:
        checkpoint()
        try:
            return read()
        except RenderBusy:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise
            waiting()
            sleep(min(.1, remaining))
