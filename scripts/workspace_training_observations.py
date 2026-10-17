"""Read-only Training receipts confined to the marked synthetic browser fixture."""
from dataclasses import replace
from hashlib import sha256
from html import escape
import json

from scripts.workspace_browser_observations import require_synthetic_root


def training_state(draft):
    from app.monthly_report_training import EVENT_REF, MATRIX_REF
    block = next((block for block in draft.blocks if block.key == "training_summary"), None)
    events = next((table for table in block.extra_tables if table.reference == EVENT_REF), None) if block else None
    matrix = next((table for table in block.extra_tables if table.reference == MATRIX_REF), None) if block else None
    return {"events": [list(row) for row in events.rows] if events else [],
            "matrix": sha256(repr(matrix).encode()).hexdigest(),
            "notes": sha256((block.text if block else "").encode()).hexdigest(),
            "unrelated": replace(draft, blocks=tuple(block for block in draft.blocks
                                                    if block.key != "training_summary")).fingerprint}


def emit_training_snapshot(base, browser_token):
    require_synthetic_root(base)
    from app import monthly_report_testing as testing
    if testing.scope() is None:
        raise ValueError("Training receipts require the server-isolated synthetic namespace.")
    from app import monthly_report_qa_fixture as fixture
    from app import monthly_report_library as library
    from app.monthly_report_active_work import load
    from app.monthly_report_testing_ui import _working_report
    from app.monthly_report_training import load_training
    import streamlit as st
    saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    if saved is None:
        return
    working = _working_report(saved)
    active = load(browser_token, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    standing = json.dumps(load_training(fixture.CONTRACT), sort_keys=True)
    value = {"working": training_state(working),
             "durable": training_state(active.draft) if active is not None else None,
             "standing": sha256(standing.encode()).hexdigest(),
             "working_fingerprint": working.fingerprint,
             "durable_fingerprint": active.draft.fingerprint if active is not None else None}
    st.html('<span hidden data-enfra-training-receipt="' + escape(json.dumps(value, sort_keys=True), quote=True) + '"></span>')
