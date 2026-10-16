"""History evidence must observe real isolated storage without writing to it."""
import ast
from dataclasses import replace
from hashlib import sha256
from html import unescape
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from app import monthly_report_testing as testing
from scripts.workspace_history_observations import namespace, storage_state, emit_history_snapshot


TOKEN = "a" * 32


def prepare_root(monkeypatch, tmp_path, token=TOKEN):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    with testing.isolated(token):
        return testing.data_dir(tmp_path)


def test_inventory_rejects_unmarked_missing_and_foreign_namespaces_without_creating_them(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="marked disposable"):
        storage_state(tmp_path, TOKEN)
    root = prepare_root(monkeypatch, tmp_path)
    before = list(root.parent.iterdir())
    with pytest.raises(ValueError, match="existing isolated"):
        storage_state(tmp_path, "b" * 32)
    with pytest.raises(ValueError, match="cookie"):
        namespace(tmp_path, "")
    assert list(root.parent.iterdir()) == before


@pytest.mark.parametrize("relative,group", [
    ("snapshots/demo/history/2026-09-00000001.json", "history"),
    ("library/demo/assets/picture.png", "assets"),
    ("directory/demo/manifest.json", "standing"),
    ("active_work/demo/working.json", "journal"),
])
def test_fresh_inventory_detects_identical_byte_rewrites_in_each_scope(monkeypatch, tmp_path, relative, group):
    root = prepare_root(monkeypatch, tmp_path)
    target = root / "monthly_reports" / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(b"SYNTHETIC ONLY")
    first = storage_state(tmp_path, TOKEN)
    original = target.stat()
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns + 1000000))
    second = storage_state(tmp_path, TOKEN)
    assert first["groups"][group]["files"] == second["groups"][group]["files"] == 1
    assert first["groups"][group]["sha256"] != second["groups"][group]["sha256"]
    assert first["live_library_absent"] and second["live_library_absent"]
    assert "SYNTHETIC" not in json.dumps(second) and relative not in json.dumps(second)
    for name in first["groups"]:
        if name != group:
            assert first["groups"][name] == second["groups"][name]


def test_other_cookie_writes_cannot_change_primary_inventory_and_links_are_rejected(monkeypatch, tmp_path):
    root = prepare_root(monkeypatch, tmp_path)
    primary = storage_state(tmp_path, TOKEN)
    with testing.isolated("b" * 32):
        other = testing.data_dir(tmp_path)
    (other / "monthly_reports").mkdir()
    (other / "monthly_reports" / "other.json").write_text("OTHER SYNTHETIC BROWSER")
    assert storage_state(tmp_path, TOKEN) == primary
    (root / "monthly_reports").mkdir()
    (root / "monthly_reports" / "unsafe").symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="link"):
        storage_state(tmp_path, TOKEN)


def test_linked_durable_root_is_rejected_before_reading_another_directory(monkeypatch, tmp_path):
    root = prepare_root(monkeypatch, tmp_path)
    outside = tmp_path / "outside-cookie-namespace"
    outside.mkdir()
    (outside / "invented.json").write_text("SYNTHETIC OUTSIDE NAMESPACE")
    (root / "monthly_reports").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="root"):
        storage_state(tmp_path, TOKEN)
    from app import monthly_report_library as library
    monkeypatch.setattr(library, "load_snapshot", lambda *a, **kw: pytest.fail("linked library read"))
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        with pytest.raises(ValueError, match="root"):
            emit_history_snapshot(tmp_path, TOKEN)


def test_receipt_requires_matching_server_cookie_and_current_generation_before_library_reads(monkeypatch, tmp_path):
    prepare_root(monkeypatch, tmp_path)
    from app import monthly_report_library as library
    monkeypatch.setattr(library, "load_snapshot", lambda *a, **kw: pytest.fail("foreign library read"))
    with testing.isolated("b" * 32):
        with pytest.raises(ValueError, match="server-isolated cookie"):
            emit_history_snapshot(tmp_path, TOKEN)
    with testing.isolated(TOKEN):
        with pytest.raises(ValueError, match="server-isolated cookie"):
            emit_history_snapshot(tmp_path, TOKEN)  # No current storage lease yet.


def test_actual_history_receipt_reads_existing_versions_and_performs_no_storage_write(monkeypatch, tmp_path):
    prepare_root(monkeypatch, tmp_path)
    from app import monthly_report_library as library, monthly_report_qa_fixture as fixture
    import streamlit as st
    emitted = []
    monkeypatch.setattr(st, "session_state", {})
    monkeypatch.setattr(st, "html", emitted.append)
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        draft = fixture.prepare("prefill")
        saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        before = storage_state(tmp_path, TOKEN)
        monkeypatch.setattr(library, "_atomic_write", lambda *a, **kw: pytest.fail("observer attempted a write"))
        emit_history_snapshot(tmp_path, TOKEN)
        assert storage_state(tmp_path, TOKEN) == before
        assert library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD) == saved
    match = re.search('data-enfra-history-receipt="([^"]+)"', emitted[-1])
    receipt = json.loads(unescape(match[1]))
    assert receipt["working"]["fingerprint"] == receipt["durable"]["fingerprint"] == draft.fingerprint
    assert receipt["versions"] == [{"revision": 1, "at": saved.generated_at,
        "author": sha256(fixture.ACTOR.encode()).hexdigest()}]
    assert receipt["saved_revision"] == 1 and receipt["memory_assets"] == []
    assert fixture.ACTOR not in json.dumps(receipt)


def cover_receipt(monkeypatch, tmp_path, *, omitted=False):
    prepare_root(monkeypatch, tmp_path)
    from app import monthly_report_library as library, monthly_report_qa_fixture as fixture
    from app import monthly_report_active_work as active
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_editor import _signature
    from app.monthly_report_docx import normalize_report_image
    from scripts.qa_cover_photo_controls import photograph
    import streamlit as st
    emitted, session = [], {}
    monkeypatch.setattr(st, "session_state", session)
    monkeypatch.setattr(st, "html", emitted.append)
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        original = fixture.prepare("prefill")
        image = normalize_report_image(photograph(), ".png")
        reference = library.asset_reference(image.data, image.extension)
        photo = ResolvedBlock("cover_photo", "Omit" if omitted else "Replace once", asset_hashes=(reference,))
        current = replace(original, blocks=(*original.blocks, photo))
        prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
        session.update({prefix + "_draft": current, prefix + "_assets": {reference: image.data}})
        active.save(TOKEN, current, expected_revision=0, base_snapshot_revision=1, assets={reference: image.data})
    return emitted, session, current, original, reference, image.data


@pytest.mark.parametrize("omitted", [False, True])
def test_cover_receipt_binds_normalized_bytes_to_actual_working_and_durable_asset_without_write(monkeypatch, tmp_path, omitted):
    emitted, session, current, original, reference, raw = cover_receipt(monkeypatch, tmp_path, omitted=omitted)
    from app import monthly_report_library as library
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        before = storage_state(tmp_path, TOKEN)
        monkeypatch.setattr(library, "_atomic_write", lambda *a, **kw: pytest.fail("observer attempted a write"))
        emit_history_snapshot(tmp_path, TOKEN)
        assert storage_state(tmp_path, TOKEN) == before
    value = json.loads(unescape(re.search('data-enfra-history-receipt="([^"]+)"', emitted[-1])[1]))
    assert value["working"] == value["durable"]
    assert value["working"]["without_cover"] == original.fingerprint
    assert value["working"]["cover"]["assets"] == [{"reference": reference, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}]
    assert value["working"]["cover"]["source"] == ("Omit" if omitted else "Replace once")
    assert value["working"]["cover"]["pending_review"] == [0]


@pytest.mark.parametrize("bad", ["wrong-bytes", "oversized"])
def test_cover_observer_refuses_false_memory_identity_or_unbounded_bytes(monkeypatch, tmp_path, bad):
    emitted, session, current, original, reference, raw = cover_receipt(monkeypatch, tmp_path)
    assets_key = next(key for key in session if key.endswith("_assets"))
    from app import monthly_report_library as library
    session[assets_key][reference] = b"CORRUPT SYNTHETIC" if bad == "wrong-bytes" else b"x" * (library.MAX_ASSET_BYTES + 1)
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        with pytest.raises(ValueError, match="invalid or unbounded"):
            emit_history_snapshot(tmp_path, TOKEN)
    assert emitted == []


def test_cover_asset_link_is_rejected_before_loading_journal_or_external_asset(monkeypatch, tmp_path):
    emitted, session, current, original, reference, raw = cover_receipt(monkeypatch, tmp_path)
    from app import monthly_report_active_work as active
    from app import monthly_report_library as library
    outside = tmp_path / "outside-normalized-photo.jpg"
    outside.write_bytes(raw)
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        path = active._directory(TOKEN, current.profile.contract, current.profile.key, current.period) / "assets" / reference
        path.unlink()
        path.symlink_to(outside)
        monkeypatch.setattr(library, "load_snapshot", lambda *a, **kw: pytest.fail("linked durable library was read"))
        with pytest.raises(ValueError, match="link"):
            emit_history_snapshot(tmp_path, TOKEN)
    assert emitted == []


def test_reset_during_receipt_cannot_publish_stale_all_memory_cover(monkeypatch, tmp_path):
    emitted, session, current, original, reference, raw = cover_receipt(monkeypatch, tmp_path)
    from app import monthly_report_library as library
    real = library.snapshot_history
    def reset_after_history(*args):
        result = real(*args)
        testing.reset(tmp_path)
        return result
    monkeypatch.setattr(library, "snapshot_history", reset_after_history)
    with testing.isolated(TOKEN):
        testing.data_dir(tmp_path)
        with pytest.raises((ValueError, OSError), match="existing isolated|generation|namespace"):
            emit_history_snapshot(tmp_path, TOKEN)
    assert emitted == []


def predicate():
    source = Path(__file__).resolve().parents[1] / "scripts/qa_monthly_history.py"
    tree = ast.parse(source.read_text())
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "await_state")
    return ast.literal_eval(fn.body[0].value.args[0])


def run_predicate(state, wanted, running="notRunning"):
    code = """const document={querySelectorAll:()=>[{dataset:{enfraHistoryReceipt:process.argv[1]}}],
querySelector:()=>({getAttribute:()=>process.argv[3]})};
console.log(JSON.stringify(eval('('+process.argv[4]+')')(JSON.parse(process.argv[2]))));"""
    result = subprocess.run(["node", "-e", code, json.dumps(state), json.dumps(wanted), running, predicate()],
                            text=True, capture_output=True, check=True, timeout=5)
    return json.loads(result.stdout)


def test_browser_acknowledgment_cannot_accept_old_wrong_cookie_or_undurable_values():
    part = {"fingerprint": "actual", "author": "author", "activity": "manual", "photos": ["one", "two"]}
    state = {"scope": "cookie", "sequence": 5, "saved_revision": 3, "working": part, "durable": part}
    wanted = {"scope": "cookie", "after": 4, "revision": 3, "author": "author", "activity": "manual", "photos": 2}
    assert run_predicate(state, wanted)
    assert not run_predicate(state, wanted, "running")
    for key, value in (("scope", "another-cookie"), ("sequence", 4), ("saved_revision", 2)):
        assert not run_predicate({**state, key: value}, wanted)
    assert not run_predicate({**state, "durable": {**part, "activity": "older"}}, wanted)
    assert not run_predicate({**state, "working": {**part, "photos": ["one"]}}, wanted)
