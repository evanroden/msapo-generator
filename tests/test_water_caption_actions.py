"""One page-confirmation action must include the caption actually submitted."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_asset_review import pending_asset_indexes
from app.monthly_report_content_policy import page_allowed
from app.monthly_report_page_controls import apply_page_request, revise_included_page
from test_monthly_report_page_manager import _prepared
from test_monthly_report_section_uploads import button
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_water_auto_include import _water_app


def test_review_retains_report_caption_when_source_has_no_caption_entry(monkeypatch, tmp_path):
    profile, content, block = _prepared(monkeypatch, tmp_path)
    from app.monthly_report_sources import source_bytes
    raw = source_bytes(profile, content.source)
    source = replace(content.source, captions=())
    block = replace(block, asset_captions=("Retained operating note", "Second page"))
    reviewed, source = revise_included_page(block, source, 1, "review", all_sources=(source,))
    assert reviewed.asset_captions == block.asset_captions
    assert dict(source.captions)[1] == "Retained operating note"
    assert page_allowed(source, 1)
    assert 0 not in pending_asset_indexes(reviewed, (source,))
    assert source_bytes(profile, source) == raw


def test_explicit_empty_source_caption_is_not_replaced_by_fallback(monkeypatch, tmp_path):
    _, content, block = _prepared(monkeypatch, tmp_path, pages=1)
    source = replace(content.source, captions=((1, ""),))
    block = replace(block, asset_captions=("Old caption",))
    reviewed, source = revise_included_page(block, source, 1, "review", all_sources=(source,))
    assert reviewed.asset_captions == ("",)
    assert dict(source.captions) == {1: ""}
    assert page_allowed(source, 1)


CAPTION_EDITOR = '''
import streamlit as st
from app.monthly_report_upload_ui import _included_page_controls

def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key

if "content" in st.session_state:
    content = st.session_state["content"]
    source, handled = _included_page_controls(content.source, 1, "synthetic", field,
        st.session_state["blocks"], True, (content,))
    st.session_state["handled"] = handled
'''


def test_fresh_caption_editor_displays_fallback_without_mutating_source(monkeypatch, tmp_path):
    _, content, block = _prepared(monkeypatch, tmp_path, pages=1)
    source = replace(content.source, captions=())
    block = replace(block, asset_captions=("Retained operating note",))
    app = AppTest.from_string(CAPTION_EDITOR).run()
    app.session_state["content"] = replace(content, source=source)
    app.session_state["blocks"] = {block.key: block}
    app.run()
    assert not app.exception
    assert next(w for w in app.text_input if w.label == "Page caption").value == "Retained operating note"
    assert app.session_state["blocks"][block.key] == block
    assert app.session_state["content"].source == source


def _included_editor(monkeypatch, tmp_path):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(1))
    button(app, "Include page").click().run()
    app.run()
    button(app, "Report pages").click().run()
    assert not app.exception
    return app


@pytest.mark.parametrize("caption", ["Newly submitted operating note", ""])
def test_edit_then_immediate_include_reviews_that_exact_caption(monkeypatch, tmp_path, caption):
    app = _included_editor(monkeypatch, tmp_path)
    original = app.session_state["test_blocks"]["water_reports"]
    # Both values are delivered in one native submission. Do not insert an
    # intermediate rerun/blur to disguise callback-before-render ordering.
    next(w for w in app.text_input if w.label == "Page caption").set_value(caption)
    button(app, "Include page").click().run()
    assert not app.exception
    updated = app.session_state["test_blocks"]["water_reports"]
    source = app.session_state["test_sources"][0]
    assert updated.asset_captions == (caption,)
    assert dict(source.captions)[1] == caption
    assert page_allowed(source, 1)
    assert pending_asset_indexes(updated, (source,)) == ()
    assert updated.asset_hashes == original.asset_hashes
    app.run()
    assert app.session_state["test_blocks"]["water_reports"] == updated
    assert app.session_state["test_apply_count"] == 1


def test_immediate_include_cannot_approve_newly_submitted_price(monkeypatch, tmp_path):
    app = _included_editor(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Page caption").set_value("Invoice amount $125")
    button(app, "Include page").click().run()
    assert not app.exception
    source = app.session_state["test_sources"][0]
    updated = app.session_state["test_blocks"]["water_reports"]
    assert not page_allowed(source, 1)
    assert pending_asset_indexes(updated, (source,)) == (0,)
    assert dict(source.captions)[1] == "Invoice amount $125"


def _request(content, block, action, caption):
    return {"source_id": content.source.id, "source_fingerprint": content.source.fingerprint,
            "block_key": block.key, "block_fingerprint": block.fingerprint,
            "number": 1, "action": action, "caption": caption}


@pytest.mark.parametrize("action", ["review", "omit", "later"])
def test_request_captures_caption_with_page_action_atomically(monkeypatch, tmp_path, action):
    _, content, block = _prepared(monkeypatch, tmp_path)
    before_source, before_block = content.source, block
    request = _request(content, block, action, "Submitted caption")
    result, changes = apply_page_request((content,), {block.key: block}, request)
    updated, source = changes[block.key], result[0].source
    assert dict(source.captions)[1] == "Submitted caption"
    if action == "omit":
        assert len(updated.asset_hashes) == 1
        assert 1 not in source.selected_pages
        assert 1 in dict(source.client_page_exclusions)
    else:
        index = 0 if action == "review" else 1
        assert updated.asset_captions[index] == "Submitted caption"
        assert page_allowed(source, 1) == (action == "review")
    assert block == before_block and content.source == before_source


@pytest.mark.parametrize("changed", ["block", "source"])
def test_caption_payload_does_not_waive_stale_revision_guard(monkeypatch, tmp_path, changed):
    _, content, block = _prepared(monkeypatch, tmp_path)
    request = _request(content, block, "review", "Old tab caption")
    if changed == "block":
        block = replace(block, text="A newer report note")
    else:
        content = replace(content, source=replace(content.source, vendor="Corrected vendor"))
    with pytest.raises(ValueError, match="changed after"):
        apply_page_request((content,), {block.key: block}, request)


def test_nontext_caption_payload_is_rejected_without_mutation(monkeypatch, tmp_path):
    _, content, block = _prepared(monkeypatch, tmp_path)
    request = _request(content, block, "review", 42)
    with pytest.raises(ValueError, match="could not be recovered"):
        apply_page_request((content,), {block.key: block}, request)
