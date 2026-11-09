"""Real drafting controls respect omitted vendor context without network calls."""
from concurrent.futures import Future
from dataclasses import replace
import json

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_ai as ai
from app import monthly_report_ai_ui as ui
from app import monthly_report_sources as sources
from app.monthly_report_model import EvidenceFact, ResolvedBlock
from test_monthly_report_vendor_prompt_scope import report, VENDOR_A, VENDOR_B


APP = '''
import streamlit as st
from dataclasses import replace
from app.monthly_report_ai_ui import render_drafting
from app.monthly_report_ui import _field
draft = st.session_state["synthetic_draft"]
draft, blocks = render_drafting(
    draft, {block.key: block for block in draft.blocks}, "vendor_scope", _field,
    allowed_keys={"activity_summary"})
st.session_state["rendered_draft"] = replace(draft, blocks=tuple(blocks.values()))
'''


@pytest.mark.parametrize("source,included,visible", [
    ("Omit", True, False),
    ("Library", False, False),
    ("Library", True, True),
])
def test_copy_and_explicit_draft_controls_use_only_included_vendor_context(
        monkeypatch, tmp_path, source, included, visible):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original = report(source=source, include_section=included)
    manual = ResolvedBlock("activity_summary", "This month", text="Keep this human wording.")
    original = replace(original, blocks=(*original.blocks, manual))
    raw = b"Service date: 2026-09-06\nTechnician inspected the synthetic pressure sensor."
    content, _ = sources.ingest(original.profile, "synthetic maintenance report.txt", raw)
    wording = "Technician inspected the synthetic pressure sensor."
    fact = EvidenceFact("synthetic-ui-fact", content.source.id, 1, "action", wording, wording)
    content = replace(content, source=replace(content.source, facts=(fact,)))
    original = replace(original, sources=(content.source,))
    requests = []

    def forbidden_reader(*args, **kwargs):
        raise AssertionError("This synthetic regression must never call an external reader.")

    def synthetic_receipt(prepare, read):
        # Run the real local budget admission and capture its exact payload,
        # then supply a synthetic completion instead of invoking the worker.
        payload = prepare()
        requests.append(payload)
        future = Future()
        future.set_result({"paragraphs": [{"text": wording, "fact_ids": [fact.id]}]})
        return future

    monkeypatch.setattr(ai, "request_json", forbidden_reader)
    monkeypatch.setattr(ui, "start_receipt", synthetic_receipt)
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["synthetic_draft"] = original
    app.session_state["vendor_scope_evidence"] = (content,)
    app.run()
    assert not app.exception
    copied = next(w.value for w in app.text_area
                  if w.label == "Prompt to copy manually if needed")
    assert requests == [], "Rendering a copyable prompt must not start a request"
    next(b for b in app.button if b.label == "Suggest wording / redraft").click().run()
    assert not app.exception
    assert len(requests) == 1, "Only the explicit drafting action may prepare a request"
    outgoing = requests[0][0]["text"]
    payload = json.loads(outgoing[len(ai.DRAFT_PROMPT) + 1:])
    assert payload["block"] == "activity_summary"
    assert payload["facts"][0]["id"] == fact.id
    expected = [VENDOR_A, VENDOR_B, "Synthetic Gamma Services"] if visible else []
    assert payload["vendors"] == expected
    for name in (VENDOR_A, VENDOR_B, "Synthetic Gamma Services"):
        assert (name in copied) == visible
        assert (name in outgoing) == visible
    assert "555-0110" not in copied and "555-0110" not in outgoing
    assert app.session_state["rendered_draft"].blocks == original.blocks
    assert app.session_state["rendered_draft"].sources == original.sources
    assert sources.source_bytes(original.profile, content.source) == raw
    app.run()
    assert not app.exception and len(requests) == 1
    assert app.session_state["rendered_draft"].blocks == original.blocks
