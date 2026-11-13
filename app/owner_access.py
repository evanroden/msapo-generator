"""Owner-only access gate for saved contacts and PO history (#21).

The owner decided on 13 November 2026 that only he views or edits saved
contacts. The app has no sign-in, so the gate is a server-side passcode read
from the ``MSAPO_OWNER_PASSCODE`` environment variable:

* Unset, blank or shorter than 12 characters: the owner screen is not shown at
  all and the app behaves exactly as before. Nothing in the code sets it.
* Set: the purchase page's About section offers an unlock box. The passcode is
  compared in constant time, and after five wrong tries in fifteen minutes the
  gate refuses every try (right or wrong) until the window passes.

The passcode never leaves the server and is never written to session state;
only an "unlocked" flag is kept in the visitor's own Streamlit session.
"""
from __future__ import annotations

import hmac
import os
import threading
import time

ENV_VAR = "MSAPO_OWNER_PASSCODE"
MIN_PASSCODE_LENGTH = 12
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()
_failures: list[float] = []


def _configured_passcode() -> str:
    value = (os.environ.get(ENV_VAR) or "").strip()
    return value if len(value) >= MIN_PASSCODE_LENGTH else ""


def owner_access_configured() -> bool:
    """True only when a usable passcode is set on the server."""
    return bool(_configured_passcode())


def locked_out(now: float | None = None) -> bool:
    current = time.time() if now is None else now
    with _lock:
        _failures[:] = [t for t in _failures if current - t < FAILURE_WINDOW_SECONDS]
        return len(_failures) >= MAX_FAILURES


def check_owner_passcode(attempt: str | None, now: float | None = None) -> bool:
    """Return True for the right passcode; count wrong ones toward the lockout."""
    expected = _configured_passcode()
    if not expected:
        return False
    current = time.time() if now is None else now
    if locked_out(current):
        return False
    ok = hmac.compare_digest(
        (attempt or "").strip().encode("utf-8"), expected.encode("utf-8")
    )
    if not ok:
        with _lock:
            _failures.append(current)
    return ok


def _reset_for_tests() -> None:
    with _lock:
        _failures.clear()
