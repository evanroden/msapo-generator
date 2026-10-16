"""Read-only Progress photo receipts inside the marked cookie-isolated fixture."""
from dataclasses import replace
from hashlib import sha256
from html import escape
import json

from scripts.workspace_history_observations import namespace


def progress_state(draft):
    from app.monthly_report_asset_review import asset_context, asset_fingerprint, asset_reviewed
    block = next((item for item in draft.blocks if item.key == "improvements"), None)
    activity = next((item.text for item in draft.blocks if item.key == "activity_summary"), "")
    images = []
    if block:
        for index, reference in enumerate(block.asset_hashes):
            caption = block.asset_captions[index] if index < len(block.asset_captions) else ""
            images.append({"asset": reference, "caption": sha256(caption.encode()).hexdigest(),
                "provenance": list(asset_context(block, index)),
                "review": asset_fingerprint(block, index), "reviewed": asset_reviewed(block, index)})
    return {"fingerprint": draft.fingerprint, "source": block.source if block else None,
        "photos_per_page": block.photos_per_page if block else None, "images": images,
        "photo_context": sha256(repr((block.text, block.rows, block.extra_tables, block.references)).encode()).hexdigest() if block else None,
        "activity": sha256(activity.encode()).hexdigest(),
        "unrelated": replace(draft, blocks=tuple(item for item in draft.blocks
            if item.key not in {"improvements", "activity_summary"})).fingerprint,
        "sources": [[source.id, source.sha256, source.fingerprint] for source in draft.sources],
        "omitted": [item.key for item in draft.blocks if item.key != "improvements" and item.source == "Omit"]}


def emit_progress_snapshot(base, token):
    target, identity, generation = namespace(base, token)
    from app import monthly_report_testing as testing, monthly_report_qa_fixture as fixture
    from app import monthly_report_library as library
    if (testing.scope(), testing.generation()) != (identity, generation):
        raise ValueError("Progress receipts require the current isolated namespace generation.")
    if library._root().resolve() != (target / "monthly_reports").resolve():
        raise ValueError("Progress receipts cannot read the live library.")
    from app.monthly_report_active_work import load
    from app.monthly_report_testing_ui import _working_report
    from app.monthly_report_editor import _signature
    import streamlit as st
    saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    if saved is None:
        return
    working = _working_report(saved)
    active = load(token, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    durable = active.draft if active else saved.draft
    prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
    memory = st.session_state.get(prefix + "_assets", {})
    recovered = dict(active.assets) if active else {}
    references = set(image["asset"] for value in (working, durable) for image in progress_state(value)["images"])
    assets = []
    for reference in sorted(references):
        raw = memory.get(reference) or recovered.get(reference) or library.read_asset(fixture.CONTRACT, fixture.profile().key, reference)
        if not isinstance(raw, bytes) or not raw or len(raw) > 64 * 1024:
            raise ValueError("Progress fixture photo exceeds its bounded synthetic byte size.")
        if library.asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference:
            raise ValueError("Progress fixture photo bytes do not match their reference.")
        assets.append({"asset": reference, "bytes": len(raw), "sha256": sha256(raw).hexdigest()})
    key = "_synthetic_progress_receipt_sequence"
    st.session_state[key] = st.session_state.get(key, 0) + 1
    receipt = {"sequence": st.session_state[key], "scope": identity, "generation": generation,
        "saved_revision": saved.revision, "working": progress_state(working),
        "durable": progress_state(durable), "assets": assets}
    if namespace(base, token)[1:] != (identity, generation):
        raise ValueError("Progress fixture generation changed during observation.")
    st.html('<span hidden data-enfra-progress-receipt="' + escape(json.dumps(receipt, sort_keys=True), quote=True) + '"></span>')
