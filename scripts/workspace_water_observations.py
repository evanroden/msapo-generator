"""Read-only Water receipts in the marked disposable browser fixture only."""
from hashlib import sha256
from html import escape
import json

from scripts.workspace_browser_observations import require_synthetic_root


def water_state(draft):
    """Compare actual page identity/order/review without exposing report wording."""
    from app.monthly_report_asset_review import asset_context, pending_asset_indexes
    from app.monthly_report_section_uploads import page_identity
    from app.monthly_report_content_policy import page_allowed, page_fingerprint
    block = next((b for b in draft.blocks if b.key == "water_reports"), None)
    pages = []
    if block is not None:
        for n, asset in enumerate(block.asset_hashes):
            pairs = sorted({p for ref in asset_context(block, n)
                            if (p := page_identity(ref)) is not None})
            pages.append({"asset": asset, "source_pages": pairs,
                          "caption_sha256": sha256((block.asset_captions[n]
                              if n < len(block.asset_captions) else "").encode()).hexdigest()})
    sources = [{"id": s.id, "sha256": s.sha256,
                "selected": list(s.selected_pages),
                "reviewed": [n for n in s.selected_pages if page_allowed(s, n)],
                "excluded": [n for n, digest in s.client_page_exclusions
                             if digest == page_fingerprint(s, n)]}
               for s in draft.sources if s.classification == "Water treatment"]
    unrelated = [(b.key, b.fingerprint) for b in draft.blocks if b.key != "water_reports"]
    return {"pages": pages, "sources": sources,
            "pending": list(pending_asset_indexes(block)) if block else [],
            "unrelated_sha256": sha256(json.dumps(unrelated).encode()).hexdigest()}


def emit_water_snapshot(base, token):
    require_synthetic_root(base)
    from app import monthly_report_testing as testing
    if testing.scope() is None:
        raise ValueError("Water receipts require the server-isolated synthetic namespace.")
    from app import monthly_report_qa_fixture as fixture, monthly_report_library as library
    from app.monthly_report_active_work import load
    from app.monthly_report_testing_ui import _working_report
    from app.monthly_report_sources import source_bytes
    import streamlit as st

    saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    if saved is None:
        return
    working = _working_report(saved)
    active = load(token, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    durable = active.draft if active is not None else saved.draft
    originals = []
    for source in working.sources:
        if source.classification == "Water treatment":
            raw = source_bytes(working.profile, source)
            originals.append({"id": source.id, "size": len(raw), "sha256": sha256(raw).hexdigest()})
    receipt = {"working": water_state(working), "durable": water_state(durable),
               "working_fingerprint": working.fingerprint,
               "durable_fingerprint": durable.fingerprint, "originals": originals}
    st.html('<span hidden data-enfra-water-receipt="' +
            escape(json.dumps(receipt, sort_keys=True), quote=True) + '"></span>')
