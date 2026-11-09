"""Unobtrusive public build identity, never a design/master pin or server ID."""
from __future__ import annotations

import os
import re
from collections.abc import Mapping


def runtime_commit(environ: Mapping[str, str] | None = None) -> str:
    """The served commit; reject arbitrary/untrusted text.

    Render provides RENDER_GIT_COMMIT at runtime. Other hosts stamp
    APP_GIT_COMMIT into the image at build time (Dockerfile build argument).
    """
    source = os.environ if environ is None else environ
    for name in ("RENDER_GIT_COMMIT", "APP_GIT_COMMIT"):
        value = str(source.get(name, "") or "")
        if re.fullmatch(r"[0-9a-fA-F]{40}", value):
            return value.lower()
    return ""
