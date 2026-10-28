"""Disposable ordinary Monthly UI plus read-only simplicity acceptance receipts.

The existing fresh fixture owns the isolation and outbound-network guard. No
widget, callback, source parser, acceptance result, or report state is replaced.
"""
from html import escape
import json
import os
from pathlib import Path
import runpy
from uuid import uuid4

if os.environ.get("EPC_MONTHLY_SIMPLICITY_TASK") != "1":
    raise ValueError("This fixture requires the explicit simplicity task flag.")
runpy.run_path(str(Path(__file__).with_name("monthly_fresh_app.py")), run_name="__main__")

import streamlit as st
from app.monthly_report_training import EVENT_REF

# This is a neutral rerun probe, not a product action or report mutation.
st.button("Refresh synthetic observation", key="simplicity_observation_refresh")
drafts = [value for key, value in st.session_state.items()
          if key.startswith("report_guided_") and key.endswith("_draft")
          and hasattr(value, "blocks")]
if len(drafts) == 1:
    draft = drafts[0]
    training = next((b for b in draft.blocks if b.key == "training_summary"), None)
    events = next((t for t in training.extra_tables if t.reference == EVENT_REF), None) if training else None
    value = {"render_id": uuid4().hex, "fingerprint": draft.fingerprint, "period": draft.period.key,
             "events": [list(row) for row in events.rows] if events else [],
             "sources": [{"id": s.id, "fingerprint": s.fingerprint} for s in draft.sources]}
    st.html('<span hidden data-monthly-simplicity-receipt="' + escape(json.dumps(value), quote=True) + '"></span>')
