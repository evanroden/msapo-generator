"""Anonymous browser identity used only for requester convenience memory.

The cookie contains a random opaque token, never a requester name or other PO
data. Streamlit exposes request cookies read-only, so a tiny same-origin
component creates the token and reloads once. If cookies are unavailable the
PO workflow continues normally without requester memory.

EVERYTHING device-scoped depends on this module. web_ui.main() reads the token
once per run and hands it to both workflows; app/memory.py hashes it into
device_hash, the primary key of the requester, expense-profile and
employee-number tables. If this module stops producing a token, every one of
those features silently returns nothing -- which is exactly what happened when
an invalid iframe height disabled the bootstrap for a whole deployment (see
ensure_device_cookie and tests/test_device_identity.py).

An empty token is a valid, expected state, not an error: memory treats "" as
"no device" and isolates it, so a cookie-less browser learns nothing rather
than sharing one global bucket with every other cookie-less browser.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import streamlit as st

COOKIE_NAME = "epc_device_id"
# Exactly 32 lowercase hex characters -- the 16 random bytes the bootstrap
# script writes, nothing else. This is an ALLOW-list, not a sanity check: the
# value is hashed straight into a database primary key, so anything the browser
# or an extension put under this cookie name that is not our own token must
# resolve to "no device" rather than to a new memory bucket of its own.
_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


def device_token(cookies: Mapping[str, str] | None) -> str:
    """Return a validated opaque token from Streamlit request cookies.

    Guarantees a value that is either exactly 32 lowercase hex characters or
    "". Never raises: ``st.context.cookies`` is absent outside a script run and
    has raised inside one, so the caller in web_ui wraps it as well.

    Lowercasing happens BEFORE the match and is normalizing, not permissive:
    the pattern accepts only lowercase, so an uppercase copy of our own token
    would otherwise be discarded and that browser would silently start over with
    a fresh identity. Pinned by tests/test_device_identity.py. The returned
    value is always lowercase, which matters because memory.py hashes the string
    -- an uppercase token would hash to a different device entirely.
    """
    if not cookies:
        return ""
    value = str(cookies.get(COOKIE_NAME, "") or "").strip().lower()
    return value if _TOKEN_RE.fullmatch(value) else ""


def cookie_bootstrap_html(*, reload_parent: bool = True) -> str:
    """Create the cookie, optionally reloading before transient work exists.

    Returns a self-contained script. It must never carry a requester name,
    vendor, price, site, asset or PO identifier: tests/test_device_identity.py
    scans the RETURNED STRING for those words, and the privacy claim in the
    2026-08-04 handoff is that the cookie itself holds no PO data.

    The script is a raw triple-quoted literal with a __RELOAD_PARENT__ token
    substituted afterwards, NOT an f-string. The body is full of JavaScript
    braces and a template literal, so f-string interpolation would require
    doubling every one of them; a missed pair produces a syntactically broken
    script that the browser drops with no visible error and no cookie.
    """
    source = r"""
<script>
(() => {
  const name = 'epc_device_id';
  const reloadParent = __RELOAD_PARENT__;
  const present = document.cookie.split('; ').some(item => item.startsWith(name + '='));
  if (present) return;

  const bytes = new Uint8Array(16);
  if (window.crypto && window.crypto.getRandomValues) {
    window.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  const token = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `${name}=${token}; Max-Age=31536000; Path=/; SameSite=Lax${secure}`;

  const reloadKey = 'epc-device-cookie-reload-v1';
  const stored = document.cookie.split('; ').some(item => item === `${name}=${token}`);
  if (stored && reloadParent && !sessionStorage.getItem(reloadKey)) {
    sessionStorage.setItem(reloadKey, '1');
    window.parent.location.reload();
  }
})();
</script>
"""
    # Four details in that script are load-bearing; keep all commentary out here
    # rather than adding JavaScript comments, because the returned string is
    # asserted on directly by the tests.
    #
    # 1. The early return on an existing cookie is what makes this idempotent.
    #    Streamlit re-renders the iframe on every rerun, so without it each
    #    rerun would mint a new token and every device-scoped memory row would
    #    be orphaned after a single interaction.
    # 2. `stored` re-reads document.cookie before reloading. If the browser
    #    refused the write (third-party/ITP restrictions, cookies disabled), a
    #    reload would accomplish nothing and the guard below would still be set
    #    -- so the page would reload once for nothing and never retry.
    # 3. The sessionStorage key is the ONLY thing standing between this and an
    #    infinite reload loop, because the parent reload re-runs the whole
    #    script. Version the key rather than reusing it if the flow changes.
    # 4. `window.parent.location.reload()` targets the Streamlit page, not the
    #    iframe: reloading the iframe alone would never let the server see the
    #    new cookie on a request. See ensure_device_cookie for why that reload
    #    is suppressed once a quote exists.
    return source.replace("__RELOAD_PARENT__", "true" if reload_parent else "false")


def ensure_device_cookie(*, reload_parent: bool = True) -> None:
    """Attempt cookie creation without blocking the rest of the PO workflow.

    Reload only during initial app setup, before a quote exists. Inline
    handoffs use ``reload_parent=False`` because a full mobile reload can create
    a fresh Streamlit session and discard in-memory PO values and attachments.

    Returns None and guarantees nothing. The cookie is not observable on this
    run even on success -- the server only sees it on a LATER request -- so no
    caller may treat a clean return as "a token now exists". Callers must still
    wrap the call, because a Streamlit API rejection raises here; web_ui
    deliberately logs that exception instead of swallowing it, since a silent
    swallow is what let the regression below survive in production.
    """
    # height must be a POSITIVE integer. Streamlit rejects height=0 with
    # StreamlitInvalidHeightError, and because the caller wraps this in a
    # non-blocking try/except that failure was invisible: the bootstrap iframe
    # was never rendered, the cookie was never created, device_token() always
    # returned "", and every device-scoped memory feature on BOTH workflows was
    # silently inert. 1px is the smallest value the API accepts and is not
    # perceptible; the iframe carries only a script.
    st.iframe(
        cookie_bootstrap_html(reload_parent=reload_parent),
        height=1,
        tab_index=-1,
    )
