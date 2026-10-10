"""Unobtrusive public build identity, never a design/master pin or server ID."""
from __future__ import annotations

import os
import re
from collections.abc import Mapping


def runtime_commit(environ: Mapping[str, str] | None = None) -> str:
    """Render provides the commit at runtime; reject arbitrary/untrusted text."""
    source = os.environ if environ is None else environ
    value = str(source.get("RENDER_GIT_COMMIT", "") or "")
    return value.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", value) else ""
