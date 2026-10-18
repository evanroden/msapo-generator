"""A first source cannot relocate an already mounted native section control."""
from io import BytesIO

import fitz
from streamlit.testing.v1.element_tree import Block

from app import monthly_report_active_work as active, monthly_report_sources as sources
from app import monthly_report_testing as qa, monthly_report_qa_fixture as fixture
from app.monthly_report_editor import _signature
from test_monthly_report_qa_ui import ACTOR_COOKIE, visit


def _path(root, target, path=()):
    if root is target:
        return path
    if isinstance(root, Block):
        for index, child in root.children.items():
            result = _path(child, target, (*path, index))
            if result is not None:
                return result
    return None


def _water_source():
    with fitz.open() as document:
        for number in (1, 2):
            page = document.new_page()
            page.insert_text((45, 65), "TEST ONLY - ALL RECORDS INVENTED")
            page.insert_text((45, 110), "Water treatment")
            page.insert_text((45, 140), "Facility: Demo North")
            page.insert_text((45, 170), "Service date: 2026-09-17")
            page.insert_text((45, 200), f"Synthetic water page {number}: conductivity inspected.")
        return document.tobytes()


def test_first_source_review_keeps_native_page_selector_path(monkeypatch, tmp_path):
    app = visit(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Load known-value report").click().run()
    prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
    assert not app.session_state[prefix + "_draft"].sources
    import streamlit as st
    uploader = st.file_uploader
    original = _water_source()
    stream = BytesIO(original)
    stream.name = "Synthetic water treatment.pdf"
    def uploaded(label, *args, **kwargs):
        result = uploader(label, *args, **kwargs)
        return [stream] if label == "Water-treatment files" else result
    monkeypatch.setattr(st, "file_uploader", uploaded)
    app.run()
    assert not app.exception
    selectors = [w for w in app.selectbox if w.label == "Page to review"]
    assert len(selectors) == 1 and selectors[0].value == 1
    before = selectors[0]
    before_path, before_id = _path(app._tree, before), before.id
    include = [b for b in app.button if b.label == "Include page and continue"]
    assert len(include) == 1 and not include[0].disabled
    include[0].click().run()
    assert not app.exception
    selectors = [w for w in app.selectbox if w.label == "Page to review"]
    assert len(selectors) == 1 and selectors[0].value == 2
    after = selectors[0]
    draft = app.session_state[prefix + "_draft"]
    source, = draft.sources
    assert tuple(page for page, _ in source.client_page_reviews) == (1,)
    water = next(block for block in draft.blocks if block.key == "water_reports")
    assert not water.asset_hashes  # First review is durable, final page is still pending.
    with qa.isolated(ACTOR_COOKIE):
        durable = active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        assert durable.draft.fingerprint == draft.fingerprint
        assert sources.source_bytes(fixture.profile(), source) == original
    assert after.id == before_id
    assert _path(app._tree, after) == before_path
