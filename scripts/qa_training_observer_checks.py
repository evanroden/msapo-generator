"""Terminal checks for passive native error observations across page reloads."""
from __future__ import annotations

import json


def require_no_native_window_errors(documents):
    """A clean final document cannot erase an earlier document's native error.

    Some native window errors do not become Playwright ``pageerror`` events.
    Keep every observed message terminal; this is not a ResizeObserver filter.
    """
    errors = [
        {"document_stage": document.get("stage"), **error}
        for document in documents
        for error in (document.get("evidence") or {}).get("errors", ())
    ]
    assert not errors, "Native window errors were observed: " + json.dumps(errors, ensure_ascii=False)
