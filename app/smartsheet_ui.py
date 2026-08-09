"""Reusable Streamlit component for manual Smartsheet form entry."""

from __future__ import annotations

import hashlib
import json

import streamlit as st


def render_prefilled_link(
    form_url: str,
    *,
    link_label: str = "Open Smartsheet in a new tab ↗",
) -> None:
    """Render the primary handoff with Streamlit's native new-tab control."""
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
    """
    row_payload = [
        {"field": field, "label": label, "value": value}
        for field, label, value in rows
    ]
    digest = hashlib.sha256(
        json.dumps(row_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    payload = json.dumps(
        {
            "rows": row_payload,
            "formUrl": form_url,
            "linkLabel": link_label,
            "storageKey": f"{key}-{digest}",
        },
        ensure_ascii=False,
    ).replace("<", "\\u003c")

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
    height = min(1050, 175 + 67 * len(rows))
    st.iframe(
        html.replace("__PAYLOAD__", payload),
        height=height,
        tab_index=0,
    )
