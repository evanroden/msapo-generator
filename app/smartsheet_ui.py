"""Reusable Streamlit component for manual Smartsheet form entry.

Two independent handoff controls, both consumed by ``app.smartsheet_inline``:

* ``render_prefilled_link`` -- the primary route, a native Streamlit link
  control. Native because it is the only one that reliably opens a NEW tab on
  iOS Safari; an anchor rendered inside a component frame is subject to the
  frame's navigation rules and popup blocking.
* ``render_manual_handoff`` -- the fallback shown only inside a collapsed
  troubleshooting expander, for the case where prefill silently did not take
  (an expired Smartsheet session is the common cause).

The fallback is a self-contained HTML/JS frame rather than Streamlit widgets on
purpose: per-field clipboard copy and progress that survives a rerun cannot be
expressed with server-side widgets, and every rerun would otherwise discard the
operator's place in a 16-field form.

Note for anyone changing the frame: Streamlit embeds this HTML via ``srcdoc``,
which is SAME-ORIGIN with the app. There is no sandbox between this markup and
the Streamlit page, so the payload escaping in ``render_manual_handoff`` is a
security control, not formatting.

tests/test_smartsheet_handoff_entrypoint.py asserts on this file's SOURCE TEXT,
including exact counts of the two Streamlit call sites and the absence of the
deprecated components HTML helper. A second embed added here fails the suite
with no behavioural change.
"""

from __future__ import annotations

import hashlib
import json

import streamlit as st


def render_prefilled_link(
    form_url: str,
    *,
    link_label: str = "Open Smartsheet in a new tab ↗",
) -> None:
    """Render the primary handoff with Streamlit's native new-tab control.

    ``form_url`` must already be the fully validated, length-checked prefill URL
    from ``build_prefilled_form_url``; this function performs no checks of its
    own and will happily render whatever it is given.

    The default ``link_label`` is asserted verbatim by the entrypoint test, as
    is ``type="primary"`` -- the operator has to find this control on a phone
    screen below two download buttons, and it demoting itself to a plain link is
    exactly the regression the assertion catches.
    """
    st.link_button(
        link_label,
        form_url,
        type="primary",
        width="stretch",
        help=(
            "Opens the prefilled form in a new browser tab. On iPhone or iPad, "
            "iOS may hand the same link to the signed-in Smartsheet app."
        ),
    )


def render_manual_handoff(
    rows: list[tuple[str, str, str]],
    form_url: str,
    *,
    key: str = "smartsheet-handoff",
    link_label: str = "Open Smartsheet form ↗",
) -> None:
    """Render an iPhone/iPad-friendly copy-in-order form assistant.

    Browser storage contains only completed row indexes. The storage key includes
    a digest of the exact labels and values, preventing progress from one PO or
    form revision from appearing on another.

    ``rows`` must arrive in the live form's top-to-bottom order (that is what
    ``handoff_rows`` produces) -- the whole value of this control is that the
    operator can work straight down the real form without hunting.

    Renders nothing but the frame; it never writes session state, so it is safe
    to call on every rerun.
    """
    row_payload = [
        {"field": field, "label": label, "value": value}
        for field, label, value in rows
    ]
    # The digest covers the exact labels AND values, not just a filename. Keying
    # progress on anything coarser was FM-C02: green checkmarks from a previous
    # PO reappeared on the next one, and the operator skipped fields they had
    # never actually copied. sort_keys makes the digest independent of dict
    # ordering; 16 hex characters is plenty for a per-browser namespace.
    digest = hashlib.sha256(
        json.dumps(row_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    # This payload carries VENDOR-CONTROLLED text (vendor name, description,
    # notes lifted from an uploaded quote) into a <script> block inside a
    # same-origin frame. json.dumps does NOT escape "<", so a value containing
    # a literal closing script tag would terminate the block early and execute
    # the remainder as page script. Rewriting every "<" as its JSON unicode
    # escape makes that impossible while leaving the parsed value identical.
    #
    # Do not "simplify" this away as redundant with json.dumps, and do not swap
    # it for an HTML-escape of the whole document -- the JS reads these values
    # as data and escapes them again with escapeHtml before they reach innerHTML.
    payload = json.dumps(
        {
            "rows": row_payload,
            "formUrl": form_url,
            "linkLabel": link_label,
            "storageKey": f"{key}-{digest}",
        },
        ensure_ascii=False,
    ).replace("<", "\\u003c")

    # A raw string, and every style is inline. The frame is a separate document,
    # so it inherits none of the app's theme CSS; the literal ENFRA hex values
    # below are what keep the fallback from looking like a different product.
    # There is also no external stylesheet or script to load -- an offline or
    # proxy-blocked asset would leave the operator with an unusable copy list.
    #
    # Four things inside this markup are load-bearing and are NOT obvious from
    # reading the script. Editing them without knowing why is how this control
    # regresses silently:
    #
    # 1. copyText tries the Clipboard API first, then falls back to a hidden
    #    textarea and execCommand. The API is required for modern Chrome, but it
    #    REJECTS -- silently -- on older iOS Safari, on an insecure origin, and
    #    when permission is denied. Deleting the fallback removes copy support
    #    for the iPad users this control was built for (FM-C03).
    # 2. That fallback textarea sets contentEditable='true' AND readOnly=false,
    #    and hides itself with opacity:0 at a real 1x1 size. This is the exact
    #    documented iOS shape: without both flags Safari refuses to select the
    #    contents, and display:none or visibility:hidden makes the element
    #    unselectable -- in both cases execCommand copies nothing and still
    #    returns true, so the operator pastes an empty string.
    # 3. Stored progress is re-validated as in-range integers on load, and the
    #    read is wrapped in try/catch because Safari private mode throws on
    #    localStorage. Failing silently is intended here: losing checkmarks is
    #    acceptable, refusing to render the copy list is not.
    # 4. A row is marked done ONLY when copyText confirms success. Ticking it
    #    optimistically would tell the operator a field is handled while the
    #    clipboard is empty; the value stays on screen so a failed copy is still
    #    recoverable by hand.
    #
    # Every interpolated value passes through escapeHtml before it reaches
    # innerHTML -- vendor-supplied text lands in this DOM.
    html = r"""
<div id="ss-root" style="font-family:Arial,Helvetica,sans-serif;color:#092B24;">
  <div style="display:flex;gap:8px;margin-bottom:10px;">
    <a id="ss-open" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer"
       style="flex:1;text-align:center;background:#092B24;color:#fff;text-decoration:none;border-radius:4px;padding:12px;font-weight:700;">
       Open Smartsheet form &#8599;
    </a>
    <button id="ss-reset" type="button" style="border:1px solid #D3CCC4;background:#D3E7E0;border-radius:4px;padding:0 13px;font-weight:700;color:#092B24;">Reset</button>
  </div>
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
    <div style="flex:1;height:7px;background:#D3CCC4;border-radius:99px;overflow:hidden;">
      <div id="ss-bar" style="height:100%;width:0;background:#D6EF4B;transition:width .2s;"></div>
    </div>
    <div id="ss-count" style="font-size:12px;font-weight:700;color:#557F7F;"></div>
  </div>
  <div id="ss-list"></div>
  <button id="ss-copy-all" type="button" style="width:100%;margin-top:8px;border:1px solid #557F7F;background:#D3E7E0;color:#092B24;border-radius:4px;padding:10px;font-weight:700;">
    Copy all fields as a list
  </button>
  <div id="ss-status" role="status" aria-live="polite" style="min-height:20px;margin-top:7px;font-size:12px;color:#557F7F;"></div>
</div>
<script>
(() => {
  const D = __PAYLOAD__;
  const list = document.getElementById('ss-list');
  const status = document.getElementById('ss-status');
  const storageKey = 'epc-' + D.storageKey;
  let done = new Set();
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
    done = new Set(Array.isArray(saved) ? saved.filter(i => Number.isInteger(i) && i >= 0 && i < D.rows.length) : []);
  } catch (_) {}

  const escapeHtml = value => String(value).replace(/[&<>"']/g, ch => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[ch]);

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {}
    let ta = null;
    try {
      ta = document.createElement('textarea');
      ta.value = text;
      ta.contentEditable = 'true';
      ta.readOnly = false;
      ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;opacity:0;';
      document.body.appendChild(ta);
      ta.focus();
      ta.setSelectionRange(0, text.length);
      return document.execCommand('copy');
    } catch (_) {
      return false;
    } finally {
      if (ta && ta.parentNode) ta.parentNode.removeChild(ta);
    }
  }

  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify([...done])); } catch (_) {}
  }

  function paint() {
    const next = D.rows.findIndex((_, index) => !done.has(index));
    list.innerHTML = D.rows.map((row, index) => {
      const complete = done.has(index);
      const active = next === index;
      return `<div style="display:flex;gap:9px;align-items:center;padding:9px 10px;margin-bottom:6px;border-radius:4px;border:${active ? '2px solid #557F7F' : '1px solid #D3CCC4'};background:${complete ? '#D3E7E0' : '#fff'};opacity:${complete ? '.78' : '1'};">
        <div style="flex:1;min-width:0;">
          <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#557F7F;">${complete ? '&#10003; ' : ''}${escapeHtml(row.label)}</div>
          <div style="font-size:13px;font-weight:600;overflow-wrap:anywhere;white-space:pre-wrap;">${escapeHtml(row.value)}</div>
        </div>
        <button type="button" data-index="${index}" style="border:1px solid #092B24;background:${active ? '#D6EF4B' : '#D3E7E0'};color:#092B24;border-radius:4px;padding:7px 12px;font-weight:700;white-space:nowrap;">Copy</button>
      </div>`;
    }).join('');
    const percent = D.rows.length ? done.size / D.rows.length * 100 : 0;
    document.getElementById('ss-bar').style.width = percent + '%';
    document.getElementById('ss-count').textContent = done.size + ' / ' + D.rows.length;
    list.querySelectorAll('button[data-index]').forEach(button => {
      button.addEventListener('click', async () => {
        const index = Number(button.dataset.index);
        const ok = await copyText(D.rows[index].value);
        status.textContent = ok ? `Copied: ${D.rows[index].label}` : 'Copy failed. Select the displayed value manually.';
        if (ok) {
          done.add(index);
          save();
          paint();
        }
      });
    });
  }

  document.getElementById('ss-open').href = D.formUrl;
  document.getElementById('ss-open').textContent = D.linkLabel;
  document.getElementById('ss-reset').addEventListener('click', () => {
    done.clear(); save(); paint(); status.textContent = 'Progress reset.';
  });
  document.getElementById('ss-copy-all').addEventListener('click', async () => {
    const text = D.rows.map(row => `${row.label}: ${row.value}`).join('\n');
    const ok = await copyText(text);
    status.textContent = ok ? 'Copied all fields.' : 'Copy failed. Use the individual field buttons.';
  });
  paint();
})()
</script>
"""
    # 175px of chrome (open button, progress bar, copy-all button, status line)
    # plus ~67px per row, capped so a 16-field PO cannot push a 1,200px frame
    # into the middle of a phone page.
    #
    # The cap is only safe because st.iframe hard-codes the frame's scrolling
    # attribute ON, so a clipped list scrolls internally. The deprecated
    # components HTML helper this replaced defaults to scrolling OFF: switching
    # back would silently CUT the last three fields and the copy-all button off
    # the bottom with no scrollbar and no error -- the operator would simply
    # never see them. Any replacement embed must be re-checked for that.
    #
    # height must also stay a POSITIVE int; Streamlit rejects 0, and this call
    # is not wrapped in a try/except, so that would surface as a page error.
    height = min(1050, 175 + 67 * len(rows))
    st.iframe(
        html.replace("__PAYLOAD__", payload),
        height=height,
        # tab_index=0 keeps the frame in the natural tab order: this is a
        # keyboard-and-touch data-entry aid, and removing it from the tab order
        # would strand keyboard users between the download buttons and the link.
        tab_index=0,
    )
