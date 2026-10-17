"""Source/AppTest and real-file checks for the unrun native browser photo task."""
from dataclasses import replace
from hashlib import sha256
from html import unescape
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess

import pytest

from app import monthly_report_testing as testing
from app.monthly_report_asset_review import approve_all_assets, preserve_asset_reviews
from app.monthly_report_model import ResolvedBlock, ReportDraft, synthetic_profiles, ReportPeriod, profile_sections
from scripts.qa_progress_photo_journey import assert_outputs, expected_assets, invented_photo, native_error_init, URL, ADDED, THIRD
from scripts.workspace_progress_observations import progress_state, emit_progress_snapshot
from scripts.workspace_history_observations import storage_state

TOKEN = "a" * 32


def test_invented_uploads_are_distinct_small_normalized_and_not_customer_sources():
    from PIL import Image
    assets = expected_assets()
    assert len(assets) == 3
    for number, (reference, raw) in enumerate(assets.items(), 1):
        assert reference == sha256(raw).hexdigest() + ".jpg"
        assert 0 < len(raw) < 64 * 1024
        with Image.open(BytesIO(raw)) as image:
            assert image.format == "JPEG" and image.size == (420, 250)
        with Image.open(BytesIO(invented_photo(number))) as image:
            assert image.format == "PNG"


def test_receipt_distinguishes_omission_order_captions_reviews_and_unrelated_state():
    assets = expected_assets()
    refs = tuple(assets)
    profile = synthetic_profiles()[0]
    block = approve_all_assets(ResolvedBlock("improvements", "Omit", asset_hashes=refs[:2], asset_captions=("One", "Two")))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Reviewer", profile_sections(profile),
        (ResolvedBlock("activity_summary", "This month", text="Synthetic Activity"), block,
         ResolvedBlock("water_reports", "Omit")))
    initial = progress_state(draft)
    moved = preserve_asset_reviews(block, replace(block, asset_hashes=(refs[1], refs[0]), asset_captions=("Two", "Changed One")))
    final = progress_state(replace(draft, blocks=tuple(moved if item.key == block.key else item for item in draft.blocks)))
    assert final["source"] == initial["source"] == "Omit"
    assert [item["asset"] for item in final["images"]] == [refs[1], refs[0]]
    assert [item["reviewed"] for item in final["images"]] == [True, False]
    assert final["unrelated"] == initial["unrelated"] and final["activity"] == initial["activity"]
    assert final["omitted"] == ["water_reports"]
    assert "Synthetic Activity" not in json.dumps(final) and "Changed One" not in json.dumps(final)


def test_actual_observer_reads_cookie_journal_and_assets_without_writing(monkeypatch, tmp_path):
    from app import monthly_report_library as library, monthly_report_qa_fixture as fixture, monthly_report_active_work as active
    from app.monthly_report_editor import _signature
    import streamlit as st
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    emitted, session = [], {}
    monkeypatch.setattr(st, "session_state", session)
    monkeypatch.setattr(st, "html", emitted.append)
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        saved = fixture.prepare("prefill")
        assets = expected_assets()
        block = approve_all_assets(ResolvedBlock("improvements", "This month", asset_hashes=tuple(assets), asset_captions=("One", "Two", "Three")))
        draft = replace(saved, blocks=(*saved.blocks, block))
        active.save(TOKEN, draft, expected_revision=0, base_snapshot_revision=1, assets=assets)
        prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
        session.update({prefix + "_draft": draft, prefix + "_assets": assets})
        before = storage_state(tmp_path, TOKEN)
        monkeypatch.setattr(library, "_atomic_write", lambda *_a, **_kw: pytest.fail("Read-only photo observation attempted a write"))
        emit_progress_snapshot(tmp_path, TOKEN)
        assert storage_state(tmp_path, TOKEN) == before
    value = json.loads(unescape(re.search('data-enfra-progress-receipt="([^"]+)"', emitted[-1])[1]))
    assert value["working"] == value["durable"] == progress_state(draft)
    assert value["saved_revision"] == 1 and len(value["assets"]) == 3
    assert [item["asset"] for item in value["assets"]] == sorted(assets)
    for item in value["assets"]:
        assert item["bytes"] == len(assets[item["asset"]]) and item["sha256"] == sha256(assets[item["asset"]]).hexdigest()
    with testing.isolated("b" * 32):
        with pytest.raises(ValueError, match="current isolated"):
            emit_progress_snapshot(tmp_path, TOKEN)


def test_progress_collector_source_has_only_its_exact_origin_and_default_fresh_origin_stays_strict():
    from scripts.qa_fresh_native_error_checks import require_no_native_window_errors
    source = native_error_init()
    program = r'''const vm=require('node:vm'), assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]);
for(const origin of ['http://127.0.0.1:8530','http://127.0.0.1:8529','http://localhost:8530']){
 const listeners=[]; const window={addEventListener:(kind,fn,options)=>listeners.push({kind,fn,options})};
 vm.runInNewContext(source,{window,location:{origin},performance:{now:()=>1}});
 if(origin==='http://127.0.0.1:8530'){
  assert(window.__enfraFreshNativeErrors.installed);assert.equal(listeners.length,2);
  for(const row of listeners){assert.equal(row.options.passive,true);assert.equal(row.options.capture,true);}
  console.log(JSON.stringify(window.__enfraFreshNativeErrors));
 }else{assert.equal(window.__enfraFreshNativeErrors,undefined);assert.equal(listeners.length,0);}
}'''
    result = subprocess.run(["node", "-e", program, json.dumps(source)], check=True, capture_output=True, text=True, timeout=10)
    snapshot = [{"stage": "final", "evidence": json.loads(result.stdout)}]
    require_no_native_window_errors(snapshot, expected_origin=URL)
    with pytest.raises(AssertionError, match="not installed"):
        require_no_native_window_errors(snapshot)
    with pytest.raises(AssertionError, match="Unknown"):
        require_no_native_window_errors(snapshot, expected_origin="http://localhost:8530")
    snapshot[0]["evidence"]["total"] = 1
    snapshot[0]["evidence"]["errors"] = [{"message": "ResizeObserver loop", "kind": "error"}]
    with pytest.raises(AssertionError, match="window errors"):
        require_no_native_window_errors(snapshot, expected_origin=URL)


def test_actual_browser_wait_requires_ordered_content_durable_equality_new_receipt_and_completed_editor():
    import ast
    from scripts import qa_progress_photo_journey as qa
    tree = ast.parse(Path(qa.__file__).read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "await_state")
    expression = next(node.args[0].value for node in ast.walk(function) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "wait_for_function")
    program = r'''const assert=require('node:assert/strict'),vm=require('node:vm');
const expression=JSON.parse(process.argv[1]);let state, running='notRunning',present=true;
const document={querySelectorAll:()=>present?[{dataset:{enfraProgressReceipt:JSON.stringify(state)}}]:[],
 querySelector:()=>({getAttribute:()=>running})};
const check=vm.runInNewContext('('+expression+')',{document});
const images=[{asset:'one',caption:'first'},{asset:'two',caption:'second'}];
const wanted={after:3,state:{source:'This month',images}};
const clean=()=>({sequence:4,working:{source:'This month',images},durable:{source:'This month',images}});
state=clean();assert.equal(check(wanted),true);
state=clean();state.working.images=[...images].reverse();state.durable.images=state.working.images;assert.equal(check(wanted),false);
state=clean();state.durable={...state.durable,source:'Omit'};assert.equal(check(wanted),false);
state=clean();state.sequence=3;assert.equal(check(wanted),false);
state=clean();running='running';assert.equal(check(wanted),false);
running='notRunning';present=false;assert.equal(check(wanted),false);
console.log('PASS actual wait predicate positive and five distinct negative prerequisites');'''
    result = subprocess.run(["node", "-e", program, json.dumps(expression)], check=True, capture_output=True, text=True, timeout=10)
    assert "five distinct negative" in result.stdout


@pytest.mark.parametrize("same_packet", [False, True])
def test_opted_in_real_widget_protocol_distinguishes_prior_blur_and_action_packet(same_packet):
    from types import SimpleNamespace
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    from streamlit.proto.BackMsg_pb2 import BackMsg
    from scripts.qa_water_widget_delivery import WaterWidgetDelivery
    from scripts.qa_progress_photo_journey import action_delivery
    rows = []
    collector = WaterWidgetDelivery(rows.append, ports=(8530,), labels={"Caption", "Done editing photos"}, widget_types={"button", "text_area"})
    for kind, identity, label in (("text_area", "caption-id", "Caption"), ("button", "done-id", "Done editing photos")):
        message = ForwardMsg()
        widget = getattr(message.delta.new_element, kind)
        widget.id, widget.label = identity, label
        collector.message("received", message.SerializeToString())
    start = len(rows)
    def send(*, pressed, value):
        message = BackMsg()
        if value is not None:
            widget = message.rerun_script.widget_states.widgets.add()
            widget.id, widget.string_value = "caption-id", value
        if pressed:
            widget = message.rerun_script.widget_states.widgets.add()
            widget.id, widget.trigger_value = "done-id", True
        collector.message("sent", message.SerializeToString())
    if not same_packet:
        send(pressed=False, value="Intended synthetic caption")
    send(pressed=True, value="Intended synthetic caption" if same_packet else None)
    result = action_delivery(rows, start, "Done editing photos", "Intended synthetic caption")
    assert result["text_in_action_packet"] == same_packet
    assert result["text_in_prior_packet"] != same_packet
    assert "Intended synthetic caption" not in json.dumps(rows)
    with pytest.raises(AssertionError, match="exactly once"):
        action_delivery(rows, start, "Remove photo")
    send(pressed=True, value=None)
    with pytest.raises(AssertionError, match="exactly once"):
        action_delivery(rows, start, "Done editing photos")
    callbacks = {}
    collector.attach(SimpleNamespace(on=lambda kind, callback: callbacks.update({kind: callback})))
    for wrong in ("ws://127.0.0.1:8520/_stcore/stream", "ws://localhost:8530/_stcore/stream"):
        with pytest.raises(ValueError, match="synthetic localhost"):
            callbacks["websocket"](SimpleNamespace(url=wrong))
    socket_events = []
    callbacks["websocket"](SimpleNamespace(url="ws://127.0.0.1:8530/_stcore/stream", on=lambda kind, callback: socket_events.append(kind)))
    assert socket_events == ["framereceived", "framesent"]


def test_water_delivery_defaults_do_not_observe_progress_caption_or_new_port():
    from types import SimpleNamespace
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    from scripts.qa_water_widget_delivery import WaterWidgetDelivery
    rows = []
    collector = WaterWidgetDelivery(rows.append)
    message = ForwardMsg()
    message.delta.new_element.text_area.id = "caption-id"
    message.delta.new_element.text_area.label = "Caption"
    collector.message("received", message.SerializeToString())
    assert not rows
    callbacks = {}
    collector.attach(SimpleNamespace(on=lambda kind, callback: callbacks.update({kind: callback})))
    with pytest.raises(ValueError, match="synthetic localhost"):
        callbacks["websocket"](SimpleNamespace(url="ws://127.0.0.1:8530/_stcore/stream"))


@pytest.fixture(scope="module")
def output_fixture():
    """Actual Word output plus deliberate PDF-image fixtures for assertion tests.

    This does not invoke a browser or certify native PDF conversion.
    """
    from app.monthly_report_docx import _build_docx
    from app.monthly_report_qa_fixture import profile
    from app.monthly_report_visuals import photo_page
    import pymupdf
    assets = expected_assets()
    refs = (tuple(assets)[0], tuple(assets)[2])
    captions = (ADDED, THIRD)
    block = approve_all_assets(ResolvedBlock("improvements", "This month", asset_hashes=refs, asset_captions=captions, photos_per_page=1))
    chosen = profile()
    draft = ReportDraft(chosen, ReportPeriod(2026, 9), "Synthetic Reviewer", profile_sections(chosen), (block,))
    word = _build_docx(draft, asset_loader=assets.__getitem__)
    def pdf(order, *, changed_caption=False, jpeg=False, unrelated=False, extra_grayscale=False):
        with pymupdf.open() as result:
            for index in order:
                changed = replace(block, asset_captions=("Different synthetic caption.", captions[1])) if changed_caption else block
                if index == 2:
                    changed = replace(block, asset_hashes=(tuple(assets)[1],), asset_captions=("Unexpected removed photo.",))
                raw = photo_page(changed, assets.__getitem__, 0 if index == 2 else index)
                if jpeg:
                    from PIL import Image
                    stream = BytesIO()
                    with Image.open(BytesIO(raw)) as image:
                        image.save(stream, "JPEG", quality=85)
                    raw = stream.getvalue()
                page = result.new_page()
                if len(result) == 1:
                    activity = next(section for section in profile_sections(chosen) if section.key == "activity")
                    page.insert_text((20, 25), f"{activity.number}. {activity.title}")
                page.insert_image(pymupdf.Rect(20, 50, page.rect.width - 20, page.rect.height - 20), stream=raw)
            if unrelated:
                from PIL import Image
                stream = BytesIO()
                Image.new("RGB", (1400, 1980), "lightblue").save(stream, "PNG")
                page = result.new_page()
                page.insert_image(page.rect, stream=stream.getvalue())
            if extra_grayscale:
                from PIL import Image
                stream = BytesIO()
                Image.new("L", (1400, 1540), 128).save(stream, "PNG")
                page = result.new_page()
                page.insert_image(page.rect, stream=stream.getvalue())
            return result.tobytes()
    return word, pdf, refs, captions, assets


def test_real_docx_and_pdf_image_assertions_bind_caption_pixels_and_order(output_fixture):
    word, pdf, refs, captions, assets = output_fixture
    value = assert_outputs(word, pdf((0, 1)), refs, captions, assets)
    assert len(value["photo_page_sha256"]) == 2 and value["pdf_pages"] == 2
    assert assert_outputs(word, pdf((0, 1), jpeg=True), refs, captions, assets)["pdf_pages"] == 2
    assert assert_outputs(word, pdf((0, 1), unrelated=True), refs, captions, assets)["pdf_pages"] == 3


def test_correct_word_cannot_mask_changed_caption_pixels_in_pdf(output_fixture):
    word, pdf, refs, captions, assets = output_fixture
    with pytest.raises(AssertionError, match="PDF"):
        assert_outputs(word, pdf((0, 1), changed_caption=True, jpeg=True), refs, captions, assets)


def test_extra_known_photo_page_cannot_be_skipped_for_a_different_color_model(output_fixture):
    word, pdf, refs, captions, assets = output_fixture
    with pytest.raises(AssertionError, match="unexpected color model"):
        assert_outputs(word, pdf((0, 1), extra_grayscale=True), refs, captions, assets)


@pytest.mark.parametrize("wrong", ["caption", "order", "missing", "duplicate", "extra-unexpected"])
def test_changed_word_or_pdf_photo_content_cannot_pass(output_fixture, wrong):
    word, pdf, refs, captions, assets = output_fixture
    if wrong == "caption":
        with pytest.raises(AssertionError, match="DOCX"):
            assert_outputs(word, pdf((0, 1)), refs, ("Wrong caption.", captions[1]), assets)
    else:
        order = {"order": (1, 0), "missing": (0,), "duplicate": (0, 0, 1), "extra-unexpected": (0, 1, 2)}[wrong]
        with pytest.raises(AssertionError, match="PDF"):
            assert_outputs(word, pdf(order), refs, captions, assets)


def test_fixture_only_adds_read_only_progress_observation_after_actual_production_render():
    source = (Path(__file__).parent / "fixtures/workspaces/monthly_app.py").read_text()
    assert source.index('render(token, "America/New_York", _field, _move, base)') < source.index("emit_progress_snapshot(base, token)")
    assert 'if os.environ.get("EPC_MONTHLY_PROGRESS_TASK") == "1"' in source
    assert "_working_report" not in source  # Fixture never injects an alternate report/editor.


def test_both_browser_surfaces_are_closed_even_when_first_cleanup_raises():
    from types import SimpleNamespace
    from scripts.qa_progress_photo_journey import close_session
    calls = []
    def close(label):
        calls.append(label)
        raise RuntimeError(label + " cleanup failed")
    errors = close_session(SimpleNamespace(close=lambda: close("context")), SimpleNamespace(close=lambda: close("browser")))
    assert calls == ["context", "browser"]
    assert [row["surface"] for row in errors] == calls
    assert all(row["type"] == "RuntimeError" for row in errors)


def test_server_kill_failure_is_recorded_after_original_bounded_wait():
    from types import SimpleNamespace
    from scripts.qa_progress_photo_journey import stop_server
    calls = []
    def wait(timeout):
        calls.append(("wait", timeout))
        raise subprocess.TimeoutExpired("synthetic fixture", timeout)
    def kill():
        calls.append(("kill",))
        raise OSError("synthetic kill failed")
    errors = stop_server(SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append(("terminate",)), wait=wait, kill=kill))
    assert calls == [("terminate",), ("wait", 20), ("kill",)]
    assert len(errors) == 2 and "OSError: synthetic kill failed" in errors[1]


def test_actual_browser_task_preserves_original_failure_and_writes_cleanup_evidence(monkeypatch, tmp_path):
    """Exercise error control flow only with fake surfaces, not a browser pass."""
    import sys
    from types import SimpleNamespace
    from scripts import qa_progress_photo_journey as qa
    def unreachable(*_a, **_kw):
        pytest.fail("The original navigation failure must stop before business actions.")
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(
        sync_playwright=unreachable, expect=unreachable, TimeoutError=TimeoutError))
    from scripts import qa_water_fresh_page_journey as fresh
    import scripts
    live = SimpleNamespace(ROOT=tmp_path, EVIDENCE={})
    monkeypatch.setitem(sys.modules, "scripts.qa_monthly_live", live)
    monkeypatch.setattr(scripts, "qa_monthly_live", live, raising=False)
    monkeypatch.setattr(fresh, "observe_frontend_delivery", lambda *_a: None)
    monkeypatch.setattr(qa, "OUT", tmp_path)
    clean = {"schema": "enfra-fresh-native-errors-v1", "origin": URL, "installed": True,
             "limit": 16, "total": 0, "overflow": 0, "errors": []}
    class Page:
        def on(self, *_a): pass
        def set_default_timeout(self, *_a): pass
        def goto(self, *_a, **_kw): raise LookupError("original native navigation failure")
        def evaluate(self, *_a): return clean
        def locator(self, *_a): raise RuntimeError("no receipt before navigation")
        def screenshot(self, *_a, **_kw): pass
    class Context:
        def add_cookies(self, *_a): pass
        def add_init_script(self, *_a): pass
        def new_page(self): return Page()
        def route(self, *_a): pass
        def close(self): raise RuntimeError("context cleanup failed")
    class Browser:
        def new_context(self, **_kw): return Context()
        def close(self): raise RuntimeError("browser cleanup failed")
    with pytest.raises(LookupError, match="original native navigation"):
        qa.browser_task(SimpleNamespace(launch=lambda **_kw: Browser()), "fake-engine", tmp_path)
    record = json.loads((tmp_path / "fake-engine/task.json").read_text())
    assert record["failure"] == {"type": "LookupError", "message": "original native navigation failure"}
    assert record["result"] == "failed"
    assert [row["surface"] for row in record["cleanup_errors"]] == ["context", "browser"]
    assert (tmp_path / "fake-engine/widget-delivery.json").exists()


def test_actual_fixture_upload_review_refreshes_editor_after_matching_browser_journal(monkeypatch, tmp_path):
    """AppTest supplies uploader bytes only; all report actions use production UI.

    The subprocess confines the fixture's process-wide external-network guard.
    This is an importer/action prerequisite check, not a browser upload pass.
    """
    import os
    import sys
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    script = r'''
from io import BytesIO
import streamlit as st
from streamlit.testing.v1 import AppTest
from app import monthly_report_visual_ui as ui, monthly_report_section_preview_ui as preview
from app import monthly_report_testing as testing, monthly_report_active_work as active
from app.monthly_report_model import ReportDraft
from scripts.qa_progress_photo_journey import invented_photo, expected_assets
from scripts.workspace_progress_observations import progress_state
preview.render_section_preview=lambda *a,**kw: None
app=AppTest.from_file('tests/fixtures/workspaces/monthly_app.py',default_timeout=20)
app.session_state['_monthly_dom_app_test_token']='a'*32
app.run()
next(b for b in app.button if b.label=='Load known-value report').click().run()
assert not app.exception,app.exception
def working():
 return next(v for k,v in app.session_state.filtered_state.items()
  if k.startswith('report_guided_') and k.endswith('_draft') and isinstance(v,ReportDraft))
before=working();block=next(b for b in before.blocks if b.key=='improvements')
assert block.source=='This month' and not block.asset_hashes
class Upload(BytesIO):
 name='synthetic-progress.png'
 @property
 def size(self):return len(self.getvalue())
original=ui.st.file_uploader
ui.st.file_uploader=lambda label,*a,**kw: [Upload(invented_photo(1)),Upload(invented_photo(2))] if label=='Progress photos' else original(label,*a,**kw)
app.run()
next(b for b in app.button if b.label=='Add these photos').click().run()
assert not app.exception,app.exception
current=working();block=next(b for b in current.blocks if b.key=='improvements')
assert block.source=='This month' and block.asset_hashes==tuple(expected_assets())[:2]
with testing.isolated('a'*32):
 testing.data_dir(__import__('pathlib').Path(__import__('os').environ['EPC_DATA_DIR']))
 recovered=active.load('a'*32,current.profile.contract,current.profile.key,current.period)
 assert recovered and recovered.draft==current
assert any('data-enfra-progress-receipt' in getattr(item.proto,'body','') for item in app.get('html'))
from app.monthly_report_asset_review import pending_asset_indexes
for index in (0,1):
 next(w for w in app.text_area if w.label=='Activity summary').set_value('Activity delivered with photo review '+str(index))
 next(b for b in app.button if b.label=='This page is ready to include').click().run()
 assert not app.exception,app.exception
 current=working();block=next(b for b in current.blocks if b.key=='improvements')
 assert pending_asset_indexes(block)==tuple(range(index+1,2))
 assert next(b for b in current.blocks if b.key=='activity_summary').text=='Activity delivered with photo review '+str(index)
 with testing.isolated('a'*32):
  testing.data_dir(__import__('pathlib').Path(__import__('os').environ['EPC_DATA_DIR']))
  assert active.load('a'*32,current.profile.contract,current.profile.key,current.period).draft==current
assert any(b.label=='Edit photos or captions' for b in app.button), 'Committed picture reviews left stale photo editor controls'
assert not any(b.label=='Edit all photos or captions' for b in app.button)
assert not any(w.label=='Caption' for w in app.text_area)
with testing.isolated('a'*32):
 testing.data_dir(__import__('pathlib').Path(__import__('os').environ['EPC_DATA_DIR']))
 saved=active.load('a'*32,current.profile.contract,current.profile.key,current.period)
app.run()
assert not app.exception,app.exception
assert working()==current
assert not any(key.endswith('_period_editor_refresh') for key in app.session_state.filtered_state)
with testing.isolated('a'*32):
 testing.data_dir(__import__('pathlib').Path(__import__('os').environ['EPC_DATA_DIR']))
 assert active.load('a'*32,current.profile.contract,current.profile.key,current.period)==saved
next(b for b in app.button if b.label=='Edit photos or captions').click().run()
assert not app.exception,app.exception
assert sum(b.label=='Move earlier' for b in app.button)==2
assert any(b.label=='Done editing photos' for b in app.button)
print('PASS actual guarded fixture empty/add/journal prerequisite')
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "EPC_DATA_DIR": str(tmp_path), "EPC_MONTHLY_DOM_FIXTURE": "1",
             "EPC_MONTHLY_PROGRESS_TASK": "1", "EPC_MONTHLY_DOM_APPTEST": "1"},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS actual guarded fixture" in result.stdout
