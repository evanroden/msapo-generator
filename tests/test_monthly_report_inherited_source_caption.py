"""A source's absent caption follows attached art without overwriting input."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from test_monthly_report_sources import pdf_bytes


APP = '''
import streamlit as st
from app.monthly_report_upload_ui import render_uploads
from app.monthly_report_ui import _field
st.session_state['returned'] = render_uploads(
    st.session_state['profile'], st.session_state['period'], 'source_test', _field,
    attached_blocks=st.session_state['blocks'])
'''


def editor(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-utility.pdf", pdf_bytes(1))
    source = replace(content.source, classification="Utility results", service_date="2026-09-02",
                     facility=profile.facilities[0].key, captions=(), selected_pages=(1,))
    source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    content = replace(content, source=source)
    block, = sources.prepare_pages(profile, (content,), ((source.id, "utility_analysis"),))
    block = approve_all_assets(replace(block, asset_captions=("First approved caption",)))
    app = AppTest.from_string(APP, default_timeout=15)
    app.session_state["profile"] = profile
    app.session_state["period"] = ReportPeriod(2026, 9)
    app.session_state["source_test_evidence"] = (content,)
    app.session_state["blocks"] = {block.key: block}
    app.run()
    assert not app.exception
    assert not app.session_state["returned"][0][0].captions
    return app, source, block


def caption(app):
    return next(widget for widget in app.text_input if widget.label == "Page caption")


def test_external_attached_caption_change_refreshes_inherited_display_without_source_write(monkeypatch, tmp_path):
    app, source, block = editor(monkeypatch, tmp_path)
    changed = approve_all_assets(replace(block, asset_captions=("Updated elsewhere caption",)))
    app.session_state["blocks"] = {changed.key: changed}
    app.run()
    assert not app.exception
    assert caption(app).value == "Updated elsewhere caption"
    assert app.session_state["returned"][0][0] == source
    assert app.session_state["source_test_evidence"][0].source == source
    assert app.session_state["blocks"][changed.key] == changed


@pytest.mark.parametrize("delivered", ["Operator wording delivered in the same event", ""])
def test_external_default_change_preserves_same_event_native_input(monkeypatch, tmp_path, delivered):
    app, source, block = editor(monkeypatch, tmp_path)
    changed = approve_all_assets(replace(block, asset_captions=("Updated elsewhere caption",)))
    app.session_state["blocks"] = {changed.key: changed}
    caption(app).set_value(delivered).run()
    assert not app.exception
    assert caption(app).value == delivered
    accepted = app.session_state["returned"][0][0]
    assert accepted == replace(source, captions=((1, delivered),))
    assert app.session_state["blocks"][changed.key] == changed


def test_include_reviews_an_inherited_caption_page_and_its_attached_occurrence(monkeypatch, tmp_path):
    from app.monthly_report_asset_review import pending_asset_indexes
    from app.monthly_report_page_captions import synchronize_source_captions
    app, source, block = editor(monkeypatch, tmp_path)
    # A source correction elsewhere has invalidated the attached page's review.
    unreviewed = replace(block, client_asset_reviews=(), reviewed_fingerprint="", client_reviewed_fingerprint="")
    app.session_state["blocks"] = {unreviewed.key: unreviewed}
    app.run()
    assert pending_asset_indexes(unreviewed, (source,))
    next(button for button in app.button if button.label == "Include page").click().run()
    assert not app.exception
    included = app.session_state["source_test_evidence"][0].source
    assert dict(included.captions) == {1: "First approved caption"}  # the caption the reviewer saw
    decision = app.session_state["source_test_evidence_page_decision"]
    blocks, conflicts = synchronize_source_captions({unreviewed.key: unreviewed}, (source,), (included,),
                                                    decision=decision)
    assert not conflicts and not pending_asset_indexes(blocks[unreviewed.key], (included,))
    assert blocks[unreviewed.key].asset_captions == ("First approved caption",)
