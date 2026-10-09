from dataclasses import replace
from io import BytesIO
from concurrent.futures import Future

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_capacity as capacity
from app import monthly_report_capacity_ui as ui
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_capacity import profile as capacity_profile, CSV, draft, saved


@pytest.fixture
def profile(tmp_path, monkeypatch):
    return capacity_profile.__wrapped__(tmp_path, monkeypatch)


APP = '''
import streamlit as st
from app.monthly_report_capacity_ui import render_capacity
def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
draft = st.session_state['test_draft']
block = next(b for b in draft.blocks if b.key == 'thermal_capacity')
draft, block = render_capacity(draft, block, 'test', field)
st.session_state['test_draft'] = draft
st.session_state['test_block'] = block
'''


def app_for(monkeypatch, profile, initial=None):
    upload = BytesIO(CSV)
    upload.name = "capacity.csv"
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: upload)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = initial or draft(profile)
    return app.run()


def test_upload_reviews_and_saves_all_sites_once(profile, monkeypatch):
    app = app_for(monkeypatch, profile)
    assert not app.exception
    assert capacity.load_capacity(profile.contract) is None
    assert not app.checkbox
    save = next(b for b in app.button if b.label == "Save capacity for 2 sites")
    save.click().run()
    assert not app.exception
    assert capacity.load_capacity(profile.contract).revision == 1
    assert {s for t in capacity.load_capacity(profile.contract).tables for s in t.site_keys} == {"north", "south"}
    assert len(app.session_state["test_block"].extra_tables[0].rows) == 2
    app.run()
    assert not app.exception
    assert capacity.load_capacity(profile.contract).revision == 1
    assert not any(b.label.startswith("Save capacity") for b in app.button)
    assert next(w for w in app.toggle if w.label == "Update shared capacity").value is False


def test_actor_missing_disables_contract_save(profile, monkeypatch):
    app = app_for(monkeypatch, profile, replace(draft(profile), prepared_by=""))
    assert not app.exception
    assert next(b for b in app.button if b.label == "Save capacity for 2 sites").disabled
    assert capacity.load_capacity(profile.contract) is None


def test_shared_save_keeps_existing_manual_report_content(profile, monkeypatch):
    manual = ResolvedBlock("thermal_capacity", "This month", text="Manual plant note", rows=(("NH", "Steam", "123", "lb/hr"),))
    app = app_for(monkeypatch, profile, draft(profile, manual))
    next(b for b in app.button if b.label == "Save capacity for 2 sites").click().run()
    assert not app.exception
    assert capacity.load_capacity(profile.contract).revision == 1
    assert app.session_state["test_block"] == manual


def test_external_update_conflict_keeps_draft_and_reviewed_values(profile, monkeypatch):
    app = app_for(monkeypatch, profile)
    saved(profile, CSV.replace(b"1200", b"1400"))
    next(b for b in app.button if b.label == "Save capacity for 2 sites").click().run()
    # The existing shared data now hides the uploader until explicitly opened.
    next(w for w in app.toggle if w.label == "Update shared capacity").set_value(True).run()
    next(b for b in app.button if b.label == "Save capacity for 2 sites").click().run()
    assert not app.exception
    assert capacity.load_capacity(profile.contract).revision == 1
    assert any("Someone updated" in w.value for w in app.warning)


def test_image_upload_reads_automatically_then_reviews_all_sites(profile, monkeypatch):
    upload = BytesIO()
    Image.new("RGB", (200, 100), "white").save(upload, "PNG")
    upload.name = "capacity.png"
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: upload)
    requests = []
    def start(prepare, read):
        requests.append(prepare())
        future = Future()
        future.set_result({"tables": [{"title": "Thermal capacity", "page": 1,
            "columns": ["Facility", "Service", "Capacity", "Units"],
            "rows": [["NH", "Chilled water", "1200", "tons"], ["SH", "Steam", "40000", "lb/hr"]]}]})
        return future
    monkeypatch.setattr(ui, "start_receipt", start)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = draft(profile)
    app.run()
    assert not app.exception
    assert len(requests) == 1 and any(part["type"] == "image" for part in requests[0])
    assert not any("Check reading" in b.label for b in app.button)
    assert capacity.load_capacity(profile.contract) is None
    next(b for b in app.button if b.label == "Save capacity for 2 sites").click().run()
    assert not app.exception
    assert capacity.load_capacity(profile.contract).revision == 1
