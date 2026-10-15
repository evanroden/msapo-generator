"""Read-only text receipts in the marked disposable Monthly browser fixture.

Not imported by production. Hashes distinguish a rendered field from the actual
working report and its disk journal; they neither acknowledge nor save an edit.
"""
from hashlib import sha256
from html import escape
import json

from scripts.workspace_browser_observations import require_synthetic_root


def text_hashes(draft):
    blocks = {block.key: block for block in draft.blocks}
    training = blocks.get("training_summary")
    issues = [item for item in draft.follow_ups if item.category == "issue" and item.included]
    return {
        "training": sha256(training.text.encode()).hexdigest() if training is not None else None,
        "issues": [sha256(item.text.encode()).hexdigest() for item in issues],
    }


def emit_text_snapshot(base, browser_token):
    require_synthetic_root(base)
    from app import monthly_report_testing as testing
    if testing.scope() is None:
        raise ValueError("Text receipts require the server-isolated synthetic namespace.")
    from app import monthly_report_qa_fixture as fixture
    from app import monthly_report_library as library
    from app.monthly_report_active_work import load
    from app.monthly_report_testing_ui import _working_report
    import streamlit as st

    saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    if saved is None:
        return
    working = _working_report(saved)
    active = load(browser_token, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    receipt = {"working": text_hashes(working), "working_fingerprint": working.fingerprint,
               "durable": text_hashes(active.draft) if active is not None else None,
               "durable_revision": active.revision if active is not None else None,
               "durable_fingerprint": active.draft.fingerprint if active is not None else None}
    encoded = escape(json.dumps(receipt, sort_keys=True), quote=True)
    st.html('<span hidden data-enfra-text-receipt="' + encoded + '"></span>')
