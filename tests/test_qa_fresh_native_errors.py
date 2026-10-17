"""Unfiltered native-window evidence fails independently of Playwright pageerror."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.qa_fresh_native_error_checks import (
    capture_native_window_errors, require_no_native_window_errors,
)


@pytest.fixture(scope="module")
def actual_collector_model():
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("qa_fresh_native_errors_test.cjs")),
         str(project / "scripts/qa_fresh_native_errors.js")],
        check=True, capture_output=True, text=True, timeout=15,
    )
    return json.loads(result.stdout)


def snapshot(evidence, stage="final"):
    return {"stage": stage, "evidence": deepcopy(evidence)}


def test_actual_js_collector_preserves_native_defaults_and_exact_origin_boundary(actual_collector_model):
    for field in ("exact_origin_guards", "duplicate_install_idempotent",
                  "existing_default_handlers_preserved", "no_prevent_default_or_observer_timer_event_api_use"):
        assert actual_collector_model[field] is True
    require_no_native_window_errors([snapshot(actual_collector_model["clean"])])


def test_actual_js_resizeobserver_error_fails_gate_when_pageerror_is_empty(actual_collector_model):
    assert actual_collector_model["page_errors"] == []
    observed = actual_collector_model["ro_only"]
    assert observed["total"] == 1 and "ResizeObserver loop" in observed["errors"][0]["message"]
    with pytest.raises(AssertionError, match="Native window errors were observed"):
        require_no_native_window_errors([snapshot(observed)])


def test_first_site_collector_requires_its_exact_explicit_origin(actual_collector_model):
    row = snapshot(actual_collector_model["clean"])
    row["evidence"]["origin"] = "http://127.0.0.1:8526"
    with pytest.raises(AssertionError, match="this fixture"):
        require_no_native_window_errors([row])
    require_no_native_window_errors([row], origin="http://127.0.0.1:8526")
    with pytest.raises(AssertionError, match="this fixture"):
        require_no_native_window_errors([row], origin="http://127.0.0.1:8535")


def test_resource_errors_rejections_and_first16_overflow_all_fail(actual_collector_model):
    mixed, bounded = actual_collector_model["mixed"], actual_collector_model["bounded"]
    assert [row["kind"] for row in mixed["errors"]] == ["error", "unhandledrejection", "error"]
    assert mixed["errors"][-1]["target"] == "IMG"
    assert bounded["total"] == 20 and bounded["overflow"] == 4
    assert len(bounded["errors"]) == 16
    with pytest.raises(AssertionError, match="window errors"):
        require_no_native_window_errors([snapshot(mixed)])
    with pytest.raises(AssertionError, match="overflowed"):
        require_no_native_window_errors([snapshot(bounded)])


@pytest.mark.parametrize("mutation", [
    "missing-evidence", "null-evidence", "wrong-schema", "not-installed", "wrong-origin", "wrong-limit",
    "boolean-total", "negative-total", "string-overflow", "negative-overflow", "malformed-buffer",
    "excessive-buffer", "error-with-zero-total", "total-with-empty-buffer", "capture-error", "missing-final",
])
def test_missing_or_inconsistent_capture_fails_closed(actual_collector_model, mutation):
    row = snapshot(actual_collector_model["clean"])
    value = row["evidence"]
    if mutation == "missing-evidence":
        row.pop("evidence")
    elif mutation == "null-evidence":
        row["evidence"] = None
    elif mutation == "wrong-schema":
        value["schema"] = "unrelated-collector"
    elif mutation == "not-installed":
        value["installed"] = False
    elif mutation == "wrong-origin":
        value["origin"] = "http://127.0.0.1:8535"
    elif mutation == "wrong-limit":
        value["limit"] = 17
    elif mutation == "boolean-total":
        value["total"] = False
    elif mutation == "negative-total":
        value["total"] = -1
    elif mutation == "string-overflow":
        value["overflow"] = "0"
    elif mutation == "negative-overflow":
        value["overflow"] = -1
    elif mutation == "malformed-buffer":
        value["errors"] = ""
    elif mutation == "excessive-buffer":
        value["errors"] = [{}] * 17
    elif mutation == "error-with-zero-total":
        value["errors"] = [{"kind": "error", "message": "missed count"}]
    elif mutation == "total-with-empty-buffer":
        value["total"] = 1
    elif mutation == "capture-error":
        row["capture_error"] = "RuntimeError: native state could not be read"
    elif mutation == "missing-final":
        row["stage"] = "first-failure"
    with pytest.raises(AssertionError):
        require_no_native_window_errors([row])


@pytest.mark.parametrize("snapshots", [None, [], ["not a snapshot"], [{}, {}, {}]])
def test_missing_malformed_or_excessive_snapshots_cannot_pass(snapshots):
    with pytest.raises(AssertionError):
        require_no_native_window_errors(snapshots)


def test_later_clean_snapshot_cannot_erase_first_observed_native_error(actual_collector_model):
    rows = [snapshot(actual_collector_model["ro_only"], "first-failure"),
            snapshot(actual_collector_model["clean"])]
    with pytest.raises(AssertionError, match="Native window errors were observed"):
        require_no_native_window_errors(rows)


class FakePage:
    def __init__(self, evidence):
        self.evidence = evidence
        self.evaluations = []

    def evaluate(self, expression):
        self.evaluations.append(expression)
        assert "__enfraFreshNativeErrors" in expression
        return deepcopy(self.evidence)


def test_capture_is_read_only_bounded_and_preserves_first_and_latest(actual_collector_model):
    page, record = FakePage(actual_collector_model["clean"]), {}
    first = capture_native_window_errors(page, record, "first-failure")
    capture_native_window_errors(page, record, "final")
    require_no_native_window_errors(record["native_window_errors"])
    latest = capture_native_window_errors(page, record, "final")
    rows = record["native_window_errors"]
    assert len(rows) == 2 and rows[0] is first and rows[-1] is latest
    assert latest["stage"] == "final" and latest["capture_overflow"] == 1
    assert len(page.evaluations) == 3
    with pytest.raises(AssertionError, match="snapshot limit"):
        require_no_native_window_errors(rows)


def test_actual_fresh_exercise_preserves_primary_failure_when_native_capture_fails(monkeypatch, tmp_path):
    from scripts import qa_water_fresh_page_journey as fresh

    class FailedPage:
        def on(self, *_):
            pass

        def route(self, *_):
            pass

        def add_init_script(self, source):
            assert "__enfraFreshNativeErrors" in source

        def goto(self, *_args, **_kwargs):
            raise LookupError("first task failure")

        def evaluate(self, _expression):
            raise RuntimeError("diagnostic read failure")

        def screenshot(self, **_kwargs):
            pass

    class Context:
        closed = False

        def __init__(self):
            def no_trace(**_kwargs):
                raise RuntimeError("Synthetic tracing unavailable")
            self.tracing = SimpleNamespace(start=no_trace)

        def new_page(self):
            return FailedPage()

        def close(self):
            self.closed = True

    context = Context()
    browser = SimpleNamespace(new_context=lambda **_kwargs: context)
    monkeypatch.setattr(fresh, "OUT", tmp_path / "output")
    monkeypatch.setattr(fresh, "observe_frontend_delivery", lambda *_args: None)

    def unreachable_expect(*_args, **_kwargs):
        pytest.fail("The original navigation failure must stop the task before any business assertion.")

    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(expect=unreachable_expect))
    record = {}
    with pytest.raises(LookupError, match="first task failure"):
        fresh.exercise(browser, "fake-engine", tmp_path / "empty-storage", record)
    saved = json.loads((fresh.OUT / "fake-engine/task.json").read_text())
    assert saved["result"] == "fail" and saved["error_type"] == "LookupError"
    assert saved["error"] == "first task failure"
    assert saved["browser_errors"] == []
    assert [row["stage"] for row in saved["native_window_errors"]] == ["first-failure", "final"]
    assert all("diagnostic read failure" in row["capture_error"] for row in saved["native_window_errors"])
    assert context.closed
