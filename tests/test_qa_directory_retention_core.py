"""Offline only: no server/browser or external API is run by these tests."""
import ast
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re
import tempfile
from unittest.mock import Mock

import pytest
from scripts import qa_directory_retention_core as core
from scripts import qa_directory_retention_local as local


@pytest.fixture
def store(monkeypatch):
    with tempfile.TemporaryDirectory(prefix=local.PREFIX) as value:
        base = Path(value)
        (base / local.MARKER).write_text("a" * 32)
        raw = core.live.workbook()
        journey = core.CoreJourney.__new__(core.CoreJourney)
        journey.base, journey.raw = base, raw
        journey.namespace = base / "_enfra_monthly_report_qa_v1" / ("b" * 32)
        journey.guard = Mock()
        journey.storage_receipts = []
        contract = "Synthetic Retention 291 test"
        state = core.expected_state(contract, raw, "2026-11-07T12:00:00+00:00")
        root = journey.namespace / "monthly_reports"
        key = re.sub(r"[^a-z0-9]+", "-", contract.casefold()).strip("-")[:50] + "-" + sha256(contract.encode()).hexdigest()[:12]
        directory = root / "directory" / key
        for path in (directory / "manifest.json", directory / "history/00000001.json"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state))
        # Exercise the real retention import/object-pool publication in this
        # offline fixture only, confined to the newly owned disposable root.
        # These writes never create native browser acceptance evidence.
        from app.monthly_report_directory_retention import store_import
        monkeypatch.setenv("EPC_DATA_DIR", str(journey.namespace))
        digest = sha256(raw).hexdigest()
        store_import(digest, raw)
        source = root / "directory_sources" / (digest + ".xlsx")
        pool = root / "objects" / digest[:2] / digest
        assert source.stat().st_nlink == pool.stat().st_nlink == 2
        assert source.samefile(pool)
        yield journey, contract, directory, state


def test_store_exact_values_byte_retention_and_stability(store):
    j, contract, directory, state = store
    first = j.store_receipt(contract, "saved")
    assert j.store_receipt(contract, "reloaded") == first
    assert j.store_receipt(contract, "after-storage") == first
    assert first["state"] == state
    assert j.guard.call_count == 6
    state["updated_at"] = "changed"
    for p in (directory / "manifest.json", directory / "history/00000001.json"):
        p.write_text(json.dumps(state))
    with pytest.raises(core.SafetyStop, match="changed across"):
        j.store_receipt(contract, "changed")


@pytest.mark.parametrize("mutation", ["contact", "site", "source", "extra-field", "extra-revision", "extra-contract", "pool", "original", "mismatch"])
def test_store_rejects_wrong_or_extra_evidence(store, mutation):
    j, contract, directory, state = store
    if mutation == "contact":
        state["sites"][0]["contacts"][0]["email"] = "wrong@example.invalid"
    elif mutation == "site":
        state["sites"][0]["title"] = "wrong synthetic site"
    elif mutation == "source":
        state["source_sheet"] = "wrong"
    elif mutation == "extra-field":
        state["unexpected"] = True
    elif mutation == "extra-revision":
        (directory / "history/00000002.json").write_text("{}")
    elif mutation == "extra-contract":
        (directory.parent / "unexpected").mkdir()
    elif mutation in {"pool", "original"}:
        digest = sha256(j.raw).hexdigest()
        root = j.namespace / "monthly_reports"
        path = root / "objects" / digest[:2] / digest if mutation == "pool" else root / "directory_sources" / (digest + ".xlsx")
        path.unlink()
        path.write_bytes(b"changed")
    for path in (directory / "manifest.json", directory / "history/00000001.json"):
        path.write_text(json.dumps(state))
    if mutation == "mismatch":
        (directory / "manifest.json").write_text("{}")
    with pytest.raises(core.SafetyStop):
        j.store_receipt(contract, "saved")


@pytest.mark.parametrize("kind", ["leaf-link", "parent-link", "oversize", "hardlink", "fifo", "escape"])
def test_read_only_reader_fails_closed(store, kind):
    import os
    j, _, directory, _ = store
    path = j.base / "owned"
    path.write_bytes(b"synthetic")
    relative = Path("owned")
    if kind == "leaf-link":
        (j.base / "link").symlink_to(path)
        relative = Path("link")
    elif kind == "parent-link":
        (j.base / "link").symlink_to(directory, target_is_directory=True)
        relative = Path("link/manifest.json")
    elif kind == "oversize":
        path.write_bytes(b"x" * 65537)
    elif kind == "hardlink":
        os.link(path, j.base / "other")
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif kind == "escape":
        relative = Path("../outside")
    with pytest.raises((core.SafetyStop, OSError)):
        core.read_owned(j.base, relative)


def test_guards_server_actions_and_environment_are_inherited_not_replaced():
    for name in ("guard", "boundary", "transport_boundary", "action", "button", "radio", "fill", "expand"):
        assert getattr(core.CoreJourney, name) is getattr(local.LocalJourney, name)
    for name in ("Server", "LocalConfig", "child_environment", "allowed_url", "validate_route", "final_isolation_failure"):
        assert getattr(core, name) is getattr(local, name)
    with pytest.raises(core.SafetyStop, match="CSV export"):
        core.CoreJourney.__new__(core.CoreJourney).download_grid(None, "forbidden")


def test_orchestration_retains_all_local_safety_statements():
    # Explicit allowlist of differences: the remaining startup/routing/final
    # statements must be AST-identical, rather than just containing keywords.
    def statements(function):
        tree = ast.parse(inspect.getsource(function)).body[0]
        removed = {"record", "journey", "browser", "context"}
        result = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if ast.unparse(node.targets[0]).split("[")[0] in removed:
                    continue
                result.append(ast.dump(node, include_attributes=False))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if ast.unparse(call.func) in {"record.update", "super"}:
                    continue
                result.append(ast.dump(node, include_attributes=False))
        return result
    assert statements(core.exercise) == statements(local.exercise)
    source = inspect.getsource(core.exercise)
    assert source.index("with sync_playwright()") < source.index("env=child_environment")
    assert 'accept_downloads=False' in source
    assert 'if journey.namespace.exists()' in source
    assert 'OUT.mkdir(parents=True, exist_ok=False)' in source
    assert 'executable_path' not in source


def test_native_journey_not_replaced_by_store_or_csv():
    source = inspect.getsource(core.CoreJourney.run)
    assert "download_grid" not in source and "force=" not in source
    assert source.index('self.button("Save contract directory")') < source.index('self.saved_receipt(contract, "saved")')
    assert source.index('self.page.reload') < source.index('self.saved_receipt(contract, "reloaded")')
    assert source.index('self.button("Check available storage")') < source.index('self.saved_receipt(contract, "after-storage")')
    for text in ('IMPORT_DISCLOSURE', 'STORAGE_DISCLOSURE', 'to_be_disabled()', 'self.confirm_review()', 'set_input_files'):
        assert text in source
    snapshot = inspect.getsource(core.CoreJourney.snapshot)
    assert snapshot.index('super().snapshot') < snapshot.index('self.guard()')
    assert 'path.unlink(missing_ok=True)' in snapshot


def test_workflow_and_cli_remain_separate_pr_only():
    text = (core.ROOT / '.github/workflows/directory-retention-core.yml').read_text()
    for required in ('pull_request:', 'contents: read', 'persist-credentials: false', 'requirements-dev.lock', 'playwright==1.58.0', '--minutes 9', 'github.run_attempt', 'retention-days: 7'):
        assert required in text
    for forbidden in ('workflow_dispatch:', 'push:', 'prodoptin', 'secrets.', 'MONTHLY_QA_PUBLIC_URL'):
        assert forbidden not in text
    assert 'qa_directory_retention_core.py' in text
    assert 'qa_directory_retention_local.py\n' not in text
    source = inspect.getsource(core)
    assert 'if sys.argv[1:]:' in source
    assert '"native_csv_acceptance": False' in source


def test_confirmation_uses_verified_visible_associated_label():
    source = inspect.getsource(core.CoreJourney.confirm_review)
    for required in ('name=CONFIRM, exact=True', 'locator("label").filter(has=checkbox)',
                     'to_have_count(1)', 'to_be_enabled()', 'not_to_be_checked()',
                     'to_be_visible()', 'self.guard()', 'label.click()', 'to_be_checked()'):
        assert required in source
    assert source.index('self.guard()') < source.index('label.click()')
    assert 'force=' not in source and '.evaluate(' not in source


def test_exact_schema_matches_real_read_only_workbook_parser():
    # Independent schema check against the real parser; never calls save or
    # product storage helpers and never creates browser acceptance evidence.
    from dataclasses import asdict
    from app import monthly_report_directory as directory
    raw = core.live.workbook()
    workbook = directory.inspect_workbook(raw)
    sheet = next(s for s in workbook.sheets if s.name == core.SHEET)
    sites = directory.matrix_sites(workbook, sheet, *directory.suggest_matrix(sheet))
    expected = core.expected_state("Synthetic test", raw, "stamp")
    assert json.loads(json.dumps([asdict(site) for site in sites])) == expected["sites"]


@pytest.mark.parametrize("mutation", ["independent-copies", "third-link", "foreign-pair", "source-symlink", "pool-symlink", "manifest-link", "history-link"])
def test_real_product_pool_requires_exact_owned_two_link_pair(store, mutation):
    import os
    j, contract, directory, _ = store
    digest = sha256(j.raw).hexdigest()
    root = j.namespace / "monthly_reports"
    source = root / "directory_sources" / (digest + ".xlsx")
    pool = root / "objects" / digest[:2] / digest
    if mutation == "independent-copies":
        source.unlink()
        source.write_bytes(j.raw)
    elif mutation == "third-link":
        os.link(source, j.base / "unapproved-third-link")
    elif mutation == "foreign-pair":
        source.unlink()
        source.write_bytes(j.raw)
        os.link(source, j.base / "wrong-source-peer")
        os.link(pool, j.base / "wrong-pool-peer")
    elif mutation in {"source-symlink", "pool-symlink"}:
        target, other = (source, pool) if mutation == "source-symlink" else (pool, source)
        target.unlink()
        target.symlink_to(other)
    else:
        target = directory / ("manifest.json" if mutation == "manifest-link" else "history/00000001.json")
        os.link(target, j.base / "unexpected-json-link")
    with pytest.raises((core.SafetyStop, OSError)):
        j.store_receipt(contract, "saved")


@pytest.mark.parametrize("field,value", [("schema", True), ("revision", True), ("archived", 0), ("active", 1)])
def test_schema_rejects_boolean_integer_type_confusion(store, field, value):
    j, contract, directory, state = store
    if field == "active":
        state["sites"][0][field] = value
    else:
        state[field] = value
    for path in (directory / "manifest.json", directory / "history/00000001.json"):
        path.write_text(json.dumps(state))
    with pytest.raises(core.SafetyStop, match="values differ"):
        j.store_receipt(contract, "saved")


def test_retention_clock_is_explicitly_out_of_scope():
    assert "Retention-clock correctness (.imported timestamp) is not verified." in inspect.getsource(core.exercise)


@pytest.mark.parametrize("failure", [None, "initial-guard", "pre-capture-guard", "post-capture-guard", "capture", "count", "visible", "expanded"])
def test_history_panel_capture_guards_unique_visible_expanded_target_and_discards(tmp_path, monkeypatch, failure):
    import sys
    from types import ModuleType
    sync_api = ModuleType("playwright.sync_api")
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    events = []
    journey = core.CoreJourney.__new__(core.CoreJourney)
    journey.output = tmp_path
    journey.page = Mock()
    summary = journey.page.locator.return_value.filter.return_value
    panel = journey.page.get_by_test_id.return_value.filter.return_value
    guard_calls = 0
    def guard():
        nonlocal guard_calls
        guard_calls += 1
        events.append("guard-" + str(guard_calls))
        if failure == {1: "initial-guard", 2: "pre-capture-guard", 3: "post-capture-guard"}[guard_calls]:
            raise core.SafetyStop("guard failed")
    journey.guard = guard
    class Assertions:
        def to_have_count(self, count):
            events.append("count")
            assert count == 1
            if failure == "count":
                raise AssertionError("not unique")
        def to_be_visible(self):
            events.append("visible")
            if failure == "visible":
                raise AssertionError("not visible")
        def to_have_attribute(self, name, value):
            events.append("expanded")
            assert (name, value) == ("open", "")
            if failure == "expanded":
                raise AssertionError("not expanded")
    monkeypatch.setattr(sync_api, "expect", lambda locator: Assertions(), raising=False)
    path = tmp_path / "saved-history-panel.png"
    def screenshot(**kwargs):
        events.append("capture")
        assert kwargs == {"path": str(path)}
        path.write_bytes(b"synthetic mocked image")
        if failure == "capture":
            raise RuntimeError("capture failed")
    panel.screenshot.side_effect = screenshot
    if failure:
        with pytest.raises((core.SafetyStop, AssertionError, RuntimeError)):
            journey.snapshot_history("saved")
        assert not path.exists()
    else:
        journey.snapshot_history("saved")
        assert path.exists()
        assert events[0] == "guard-1"
        assert events[-3:] == ["guard-2", "capture", "guard-3"]
    if failure != "initial-guard":
        journey.page.locator.assert_called_once_with("summary")
        journey.page.get_by_text.assert_called_once_with("History and restoration", exact=True)
        journey.page.locator.return_value.filter.assert_called_once_with(has=journey.page.get_by_text.return_value)
        journey.page.get_by_test_id.assert_called_once_with("stExpander")
        journey.page.get_by_test_id.return_value.filter.assert_called_once_with(has=summary)
    if failure in {"initial-guard", "pre-capture-guard", "count", "visible", "expanded"}:
        panel.screenshot.assert_not_called()


def test_history_panel_capture_keeps_viewport_and_follows_native_receipt():
    source = inspect.getsource(core.CoreJourney.saved_receipt)
    assert source.index('self.expand("History and restoration")') < source.index('self.store_receipt(contract, stage)')
    assert source.index('self.store_receipt(contract, stage)') < source.index('self.snapshot(stage)')
    assert source.index('self.snapshot(stage)') < source.index('self.snapshot_history(stage)')
    capture = inspect.getsource(core.CoreJourney.snapshot_history)
    for forbidden in (".click(", "force=", ".evaluate(", "dispatch_event", "scrollIntoView"):
        assert forbidden not in capture
