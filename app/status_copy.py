"""Presentation-only filtering for status messages from external text.

The application keeps the original values for validation, files, and routing.
Only rendered status details omit diagnostic tokens and exception names.
"""

from __future__ import annotations

import re


_INTERNAL_STATUS_TOKEN = re.compile(
    r"(?<![a-zA-Z0-9])(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{40})(?![a-zA-Z0-9])"
    r"|\b(?:application|audio|image|message|multipart|text|video)/[a-zA-Z0-9.+_-]+"
    r"|\b(?:Traceback|[a-zA-Z_][a-zA-Z0-9_]*(?:Error|Exception))\b",
    flags=re.IGNORECASE,
)


def safe_status_detail(value: object) -> str:
    """Keep field details while suppressing internal diagnostics in UI copy."""
    return _INTERNAL_STATUS_TOKEN.sub("details omitted", str(value))
