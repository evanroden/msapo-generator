"""Anonymous browser identity used only for requester convenience memory.

The cookie contains a random opaque token, never a requester name or other PO
data. Streamlit exposes request cookies read-only, so a tiny same-origin
component creates the token and reloads once. If cookies are unavailable the
PO workflow continues normally without requester memory.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import streamlit.components.v1 as components

COOKIE_NAME = "epc_device_id"
_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


def device_token(cookies: Mapping[str, str] | None) -> str:
    """Return a validated opaque token from Streamlit request cookies."""
    if not cookies:
        return ""
    value = str(cookies.get(COOKIE_NAME, "") or "").strip().lower()
    return value if _TOKEN_RE.fullmatch(value) else ""


def cookie_bootstrap_html() -> str:
    """Static script that creates the anonymous cookie and reloads at most once."""
    return r"""
<script>
(() => {
  const name = 'epc_device_id';
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
  if (stored && !sessionStorage.getItem(reloadKey)) {
    sessionStorage.setItem(reloadKey, '1');
    window.parent.location.reload();
  }
})();
</script>
"""


def ensure_device_cookie() -> None:
    """Attempt cookie creation without blocking the rest of the PO workflow."""
    components.html(cookie_bootstrap_html(), height=0, scrolling=False)
