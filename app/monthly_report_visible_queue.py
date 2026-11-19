"""Small, process-local FIFO admission queue for monthly report assembly.

Only *waiting* work is reordered. An admitted render, shared save or export is
never preempted. The external work lock still limits active memory use.
"""
from dataclasses import dataclass
from threading import Condition
from time import monotonic


MAX_QUEUED = 16
MAX_PREVIEW_BURST = 2
POLL_SECONDS = .02


class QueueBusy(Exception):
    """No bounded admission was available; the caller retains its own draft."""


class ObsoletePreview(QueueBusy):
    """A newer owner revision or navigation superseded a waiting preview."""


@dataclass(eq=False)
class _Request:
    preview: bool
    review: bool
    owner: object
    revision: object
    cancelled: bool = False


class VisibleFirstQueue:
    """Prefer visible work, but serve one export after at most two previews.

    Per-owner dedup applies ONLY to preview waiters, never saves or exports.
    A callback may check whether a preview is still visible/current but must
    not mutate state or take this condition's lock. No persistent data is kept.
    """

    def __init__(self):
        self._condition = Condition()
        self._waiting = []
        self._preview_burst = 0

    def _head(self):
        live = [request for request in self._waiting if not request.cancelled]
        visible = [request for request in live if request.preview]
        bulk = [request for request in live if not request.preview]
        if bulk and (not visible or self._preview_burst >= MAX_PREVIEW_BURST):
            return bulk[0]
        if visible:
            return next((request for request in visible if request.review), visible[0])
        return None

    def snapshot(self):
        """An observation, not a promise that output has finished."""
        with self._condition:
            waiting = [request for request in self._waiting if not request.cancelled]
            return {
                'depth': len(waiting),
                'visible': sum(request.preview for request in waiting),
                'exports': sum(not request.preview for request in waiting),
            }

    def cancel_owner(self, owner):
        """Discard only obsolete queued previews for the named visible pane."""
        if owner is None:
            return
        with self._condition:
            for request in self._waiting:
                if request.preview and request.owner == owner:
                    request.cancelled = True
            self._condition.notify_all()

    def acquire(self, lock, *, preview=False, review=False, wait_seconds=0,
                owner=None, revision=None, is_current=None, can_admit=None):
        """Wait a finite interval; acquire the caller's existing exclusive lock.

        The lock remains owned by the caller until release(). A failed or
        cancelled request never unlocks another owner's already admitted job.
        """
        deadline = monotonic() + max(0, float(wait_seconds))
        request = _Request(preview, review, owner, revision)
        with self._condition:
            if preview and owner is not None:
                for prior in self._waiting:
                    if prior.preview and prior.owner == owner:
                        prior.cancelled = True
            live = sum(not prior.cancelled for prior in self._waiting)
            if live >= MAX_QUEUED:
                self._condition.notify_all()
                raise QueueBusy('Report capacity queue is full; your edits are unchanged.')
            self._waiting.append(request)
            self._condition.notify_all()
        try:
            while True:
                with self._condition:
                    if request.cancelled:
                        raise ObsoletePreview('This preview request was replaced. Your edits are still here.')
                    if is_current is not None:
                        try:
                            current = bool(is_current())
                        except Exception:
                            current = False  # Unknown owner state cannot publish output.
                        if not current:
                            raise ObsoletePreview('This preview is no longer current. Your edits are still here.')
                    if (self._head() is request and (can_admit is None or can_admit())
                            and lock.acquire(blocking=False)):
                        self._waiting.remove(request)
                        self._preview_burst = (min(MAX_PREVIEW_BURST, self._preview_burst + 1)
                                               if preview else 0)
                        self._condition.notify_all()
                        return
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise QueueBusy('Another report is being prepared. Your edits are unchanged; retry shortly.')
                    self._condition.wait(min(POLL_SECONDS, remaining))
        finally:
            with self._condition:
                if request in self._waiting:
                    self._waiting.remove(request)
                self._condition.notify_all()

    def release(self, lock):
        with self._condition:
            lock.release()
            self._condition.notify_all()


QUEUE = VisibleFirstQueue()
