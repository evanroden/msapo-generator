"""Synthetic capacity intake keeps paid reading behind its exact explicit action."""

from concurrent.futures import Future
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_ai as ai, monthly_report_capacity as capacity
from app import monthly_report_capacity_ui as ui
from app.monthly_report_model import ReportTable, ResolvedBlock
from test_monthly_report_capacity import profile as capacity_profile, draft, saved
from test_monthly_report_capacity_ui import APP


@pytest.fixture
def profile(tmp_path, monkeypatch):
    return capacity_profile.__wrapped__(tmp_path, monkeypatch)


def image_upload(color="white"):
    stream = BytesIO()
    Image.new("RGB", (200, 100), color).save(stream, "PNG")
    stream.name = "synthetic-capacity.png"
    return stream


RESULT = {"tables": [{"title": "Thermal capacity", "page": 1,
    "columns": ["Facility", "Service", "Capacity", "Units"],
    "rows": [["NH", "Chilled water", "1200", "tons"],
             ["SH", "Steam", "NR", "lb/hr"]]}]}


def setup_reader(monkeypatch, profile, *, initial=None, pending=False, cached=None):
    uploads = [image_upload()]
    calls = {"start": 0, "reserve": 0, "provider": 0, "prepare": 0, "cache": 0}
    futures = []
    monkeypatch.setattr(ui.st, "file_uploader", lambda *a, **kw: uploads[0])
    monkeypatch.setattr(ai, "cached", lambda *a: cached)
    def reserve(*args):
        calls["reserve"] += 1
    def prepare(*args):
        calls["prepare"] += 1
        return ["synthetic external request"]
    def provider(payload):
        calls["provider"] += 1
        return RESULT
    def start(prepare, read):
        calls["start"] += 1
        payload = prepare()
        future = Future()
        value = read(payload)
        if pending:
            future.set_running_or_notify_cancel()
        else:
            future.set_result(value)
        futures.append(future)
        return future
    def cache(*args):
        calls["cache"] += 1
    monkeypatch.setattr(ai, "reserve_call", reserve)
    monkeypatch.setattr(capacity, "reader_request", prepare)
    monkeypatch.setattr(ai, "request_json", provider)
    monkeypatch.setattr(ui, "start_receipt", start)
    monkeypatch.setattr(ai, "save_cache", cache)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = initial or draft(profile)
    return app, calls, uploads, futures


def read_button(app):
    return next(b for b in app.button if b.label == "Read capacity file")


def test_upload_display_and_reopen_make_zero_paid_calls(profile, monkeypatch):
    app, calls, _, _ = setup_reader(monkeypatch, profile)
    app.run()
    app.run()
    assert not app.exception
    assert calls == {"start": 0, "reserve": 0, "provider": 0, "prepare": 0, "cache": 0}
    assert not read_button(app).disabled
    assert any("external document reader" in n.value and "Charges may apply" in n.value
               for n in app.get("caption"))
    assert capacity.load_capacity(profile.contract) is None

    read_button(app).click().run()
    assert not app.exception
    assert calls == {"start": 1, "reserve": 1, "provider": 1, "prepare": 1, "cache": 1}
    assert not any(b.label == "Read capacity file" for b in app.button)
    assert capacity.load_capacity(profile.contract) is None
    app.run()
    assert calls["provider"] == calls["reserve"] == 1


@pytest.mark.parametrize("value", ("0", "NR", "1200 qualified"))
def test_populated_report_capacity_keeps_upload_open_and_values_exact(
        profile, monkeypatch, value):
    block = ResolvedBlock("thermal_capacity", "This month", extra_tables=(
        ReportTable(("Facility", "Service", "Capacity", "Units"),
                    (("NH", "Steam", value, "lb/hr"),), "synthetic:report"),))
    monkeypatch.setattr(ui.st, "file_uploader", lambda *a, **kw: None)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = draft(profile, block)
    app.run()
    assert not app.exception
    panel = next(x for x in app.expander if x.label == "Capacity source and reusable data")
    assert panel.proto.expanded is True
    assert any("Capacity · this report only" in x.value
               for x in app.get("caption"))
    assert app.session_state["test_block"] == block
    assert capacity.load_capacity(profile.contract) is None
    app.run()
    assert app.session_state["test_block"] == block
    assert capacity.load_capacity(profile.contract) is None


def test_scorecards_keeps_one_native_utility_editor_without_duplicate_heading(monkeypatch, tmp_path):
    from test_monthly_report_ui import monthly
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    assert sum(x.label == "Utility analysis" for x in app.text_area) == 1
    assert not any(x.value == "**Utility analysis**" for x in app.markdown)
    assert any(x.value == "**Thermal capacity**" for x in app.markdown)
    assert any(x.label == "Thermal capacity file" for x in app.get("file_uploader"))


def test_empty_imported_schema_keeps_first_capacity_upload_primary(profile, monkeypatch):
    block = ResolvedBlock("thermal_capacity", "This month", extra_tables=(
        ReportTable(("Facility", "Capacity", "Units"), (("", "", ""),), "synthetic:empty"),))
    monkeypatch.setattr(ui.st, "file_uploader", lambda *a, **kw: None)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = draft(profile, block)
    app.run()
    assert not app.exception
    assert next(x for x in app.expander if x.label == "Capacity source and reusable data").proto.expanded is True
    assert any("Clear site matches fill missing reusable capacity automatically" in x.value for x in app.caption)
    assert app.session_state["test_block"] == block
    assert capacity.load_capacity(profile.contract) is None


@pytest.mark.parametrize("state", ("empty", "report_only", "standing"))
def test_capacity_native_picker_matches_supported_formats_and_upload_ceiling(profile, state):
    block = ResolvedBlock("thermal_capacity", "Library")
    if state == "report_only":
        block = replace(block, source="This month", rows=(("NH", "Steam", "NR", "lb/hr"),))
    if state == "standing":
        saved(profile)
    before = capacity.load_capacity(profile.contract)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = draft(profile, block)
    app.run()
    assert not app.exception
    picker, = app.get("file_uploader")
    assert picker.proto.max_upload_size_mb == 128
    assert {item.casefold() for item in picker.proto.type} == capacity.SUPPORTED
    assert "DOCX: up to 128 MiB" in picker.proto.help
    assert "Other supported files: up to 30 MiB" in picker.proto.help
    assert app.session_state["test_block"] == block
    assert capacity.load_capacity(profile.contract) == before


def test_pending_read_is_started_once_and_failure_requires_another_explicit_action(profile, monkeypatch):
    app, calls, _, futures = setup_reader(monkeypatch, profile, pending=True)
    app.run()
    read_button(app).click().run()
    app.run()
    assert not app.exception
    assert calls["provider"] == calls["reserve"] == calls["start"] == 1
    assert not any(b.label == "Read capacity file" for b in app.button)
    assert capacity.load_capacity(profile.contract) is None
    futures[0].set_exception(ValueError("Synthetic reader failure; original file kept."))
    app.run()
    app.run()
    assert not app.exception
    assert any("Synthetic reader failure" in x.value for x in app.warning)
    assert calls["provider"] == calls["reserve"] == calls["start"] == 1
    read_button(app).click().run()
    assert not app.exception
    assert calls["provider"] == calls["reserve"] == calls["start"] == 2
    futures[1].set_result(RESULT)
    app.run()
    assert not app.exception
    assert calls["cache"] == 1
    assert capacity.load_capacity(profile.contract) is None


def test_replacing_or_clearing_upload_rejects_late_result_before_cache(profile, monkeypatch):
    app, calls, uploads, futures = setup_reader(monkeypatch, profile, pending=True)
    app.run()
    read_button(app).click().run()
    old = futures[0]
    uploads[0] = image_upload("red")
    app.run()
    old.set_result(RESULT)
    app.run()
    assert not app.exception
    assert calls["cache"] == 0
    assert calls["provider"] == calls["reserve"] == 1
    read_button(app).click().run()
    latest = futures[1]
    uploads[0] = None
    app.run()
    latest.set_result(RESULT)
    app.run()
    assert not app.exception
    assert calls["cache"] == 0
    assert calls["provider"] == calls["reserve"] == 2
    assert capacity.load_capacity(profile.contract) is None


@pytest.mark.parametrize("change", ("profile", "period", "incarnation", "qa_generation"))
def test_late_read_cannot_publish_into_another_report_or_reset(profile, monkeypatch, change):
    app, calls, _, futures = setup_reader(monkeypatch, profile, pending=True)
    app.run()
    read_button(app).click().run()
    old = futures[0]
    if change == "profile":
        current = app.session_state["test_draft"]
        app.session_state["test_draft"] = replace(current, profile=replace(profile, title="Changed report scope"))
    elif change == "period":
        from app.monthly_report_model import ReportPeriod
        app.session_state["test_draft"] = replace(app.session_state["test_draft"], period=ReportPeriod(2026, 10))
    else:
        app.session_state["test_rich_text_epoch" if change == "incarnation" else "_monthly_qa_generation"] = "new-incarnation"
    app.run()
    old.set_result(RESULT)
    app.run()
    assert not app.exception
    assert calls["cache"] == 0
    assert calls["provider"] == calls["reserve"] == 1
    assert not read_button(app).disabled
    assert capacity.load_capacity(profile.contract) is None


@pytest.mark.parametrize("change", ("source", "filename", "profile", "period", "incarnation", "qa_generation"))
def test_delayed_native_read_action_cannot_send_a_new_source_or_scope(profile, monkeypatch, change):
    app, calls, uploads, _ = setup_reader(monkeypatch, profile)
    app.run()
    old = read_button(app)
    if change == "source":
        uploads[0] = image_upload("red")
    elif change == "filename":
        uploads[0].name = "another-synthetic-capacity.png"
    elif change == "profile":
        current = app.session_state["test_draft"]
        app.session_state["test_draft"] = replace(current, profile=replace(profile, title="Changed report scope"))
    elif change == "period":
        from app.monthly_report_model import ReportPeriod
        app.session_state["test_draft"] = replace(app.session_state["test_draft"], period=ReportPeriod(2026, 10))
    else:
        app.session_state["test_rich_text_epoch" if change == "incarnation" else "_monthly_qa_generation"] = "new-incarnation"
    old.click().run()
    assert not app.exception
    assert calls["provider"] == calls["reserve"] == calls["start"] == 0
    assert any("Nothing was sent" in x.value for x in app.warning)
    assert read_button(app).key != old.key
    assert capacity.load_capacity(profile.contract) is None


def test_read_action_cannot_acknowledge_unseen_shared_capacity_revision(profile, monkeypatch):
    app, calls, _, _ = setup_reader(monkeypatch, profile)
    app.run()
    displayed = read_button(app)
    concurrent = saved(profile)
    displayed.click().run()
    assert not app.exception
    assert calls["provider"] == calls["reserve"] == calls["start"] == 0
    assert any("Shared capacity changed before reading started" in x.value for x in app.warning)
    assert capacity.load_capacity(profile.contract) == concurrent
    next(b for b in app.button if b.label == "Reload shared capacity for review").click().run()
    assert not app.exception
    assert calls["provider"] == calls["reserve"] == 0
    read_button(app).click().run()
    assert not app.exception
    assert calls["provider"] == calls["reserve"] == 1
    assert capacity.load_capacity(profile.contract) == concurrent


def test_cached_read_needs_no_paid_action_and_keeps_manual_report_values(profile, monkeypatch):
    manual = ResolvedBlock("thermal_capacity", "This month", rows=(("NH", "Steam", "NR", "lb/hr"),))
    app, calls, _, _ = setup_reader(monkeypatch, profile, initial=draft(profile, manual), cached=RESULT)
    app.run()
    app.run()
    assert not app.exception
    assert calls["provider"] == calls["reserve"] == calls["start"] == calls["cache"] == 0
    assert not any(b.label == "Read capacity file" for b in app.button)
    assert app.session_state["test_block"] == manual
    assert capacity.load_capacity(profile.contract) is None
    next(b for b in app.button if b.label == "Apply reviewed capacity for 2 sites").click().run()
    assert not app.exception
    assert capacity.load_capacity(profile.contract).revision == 1
    assert app.session_state["test_block"] == manual


def test_free_inspection_failure_has_free_targeted_retry_not_automatic_read(profile, monkeypatch):
    app, calls, _, _ = setup_reader(monkeypatch, profile)
    original = capacity.inspect_capacity
    attempts = []
    def inspect(*args):
        attempts.append(args[1])
        if len(attempts) == 1:
            raise ValueError("Synthetic local file inspection failed.")
        return original(*args)
    monkeypatch.setattr(capacity, "inspect_capacity", inspect)
    app.run()
    app.run()
    assert not app.exception
    assert attempts == ["synthetic-capacity.png"]
    assert calls["provider"] == calls["reserve"] == calls["start"] == 0
    next(b for b in app.button if b.label == "Try opening capacity file again").click().run()
    assert not app.exception
    assert len(attempts) == 2
    assert not read_button(app).disabled
    assert calls["provider"] == calls["reserve"] == calls["start"] == 0


def test_isolated_scope_rejects_even_a_matching_queued_read_without_preparation(profile, monkeypatch):
    app, calls, _, _ = setup_reader(monkeypatch, profile)
    from app import monthly_report_testing as testing
    before = (testing.scope(), testing.generation())
    # AppTest uses a separate context, so expose the real isolated identity to
    # its reader while bounding the main-thread load's lease with its owner.
    with testing.isolated("7" * 32) as identity, monkeypatch.context() as scoped:
        scoped.setattr(testing, "scope", lambda: identity)
        app.run()
        assert not app.exception
        assert not any(b.label == "Read capacity file" for b in app.button)
        inspection = app.session_state["test_capacity_inspection"]
        request = {"context": app.session_state["test_capacity_context"],
                   "digest": app.session_state["test_capacity_digest"],
                   "source": inspection.content.source.fingerprint,
                   "revision": app.session_state["test_capacity_revision"]}
        app.session_state["test_capacity_read_request"] = request
        app.run()
        assert not app.exception
        assert calls["provider"] == calls["reserve"] == calls["start"] == calls["prepare"] == 0
        assert any("External reading is off in isolated testing" in n.value for n in app.warning)
        assert capacity.load_capacity(profile.contract) is None
    assert (testing.scope(), testing.generation()) == before


def test_displayed_capacity_approval_cannot_approve_another_cached_source(profile, monkeypatch):
    from copy import deepcopy
    cached = deepcopy(RESULT)
    app, calls, uploads, _ = setup_reader(monkeypatch, profile, cached=cached)
    app.run()
    displayed = next(b for b in app.button if b.label == "Apply reviewed capacity for 2 sites")
    uploads[0] = image_upload("red")
    cached["tables"][0]["rows"][0][2] = "9999"
    displayed.click().run()
    assert not app.exception
    assert capacity.load_capacity(profile.contract) is None
    current = next(b for b in app.button if b.label == "Apply reviewed capacity for 2 sites")
    assert current.key != displayed.key
    assert calls["provider"] == calls["reserve"] == 0
    current.click().run()
    assert not app.exception
    assert capacity.load_capacity(profile.contract).revision == 1
    assert capacity.load_capacity(profile.contract).tables[0].rows[0][2] == "9999"


def test_successful_read_survives_failed_cache_write_without_another_paid_call(profile, monkeypatch):
    app, calls, _, _ = setup_reader(monkeypatch, profile)
    def fail_cache(*args):
        calls["cache"] += 1
        raise OSError("Synthetic capacity reuse-copy write failed.")
    monkeypatch.setattr(ai, "save_cache", fail_cache)
    app.run()
    read_button(app).click().run()
    assert not app.exception
    assert calls["provider"] == calls["reserve"] == calls["cache"] == 1
    assert any("Synthetic capacity reuse-copy write failed" in n.value for n in app.warning)
    assert not any(b.label == "Read capacity file" for b in app.button)
    assert not next(b for b in app.button if b.label == "Apply reviewed capacity for 2 sites").disabled
    app.run()
    assert calls["provider"] == calls["reserve"] == calls["cache"] == 1
    assert capacity.load_capacity(profile.contract) is None


def test_same_event_capacity_cell_correction_and_apply_saves_the_delivered_value(profile, monkeypatch):
    app, _, _, _ = setup_reader(monkeypatch, profile, cached=RESULT)
    app.run()
    displayed = next(b for b in app.button if b.label == "Apply reviewed capacity for 2 sites")
    grid = next(w for w in app.dataframe if "_capacity_table_" in w.key)
    app.session_state[grid.key] = {
        "edited_rows": {0: {"Capacity": "1300"}}, "added_rows": [], "deleted_rows": []}
    displayed.click().run()
    assert not app.exception
    state = capacity.load_capacity(profile.contract)
    assert state is not None and state.revision == 1
    assert state.tables[0].rows[0] == ("NH", "Chilled water", "1300", "tons")
