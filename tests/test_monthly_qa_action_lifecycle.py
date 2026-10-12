"""Phase 1 reset-to-replay acceptance and accepted-action lifecycle regressions.

These tests use only invented QA data and an isolated temp storage root.
The real-browser end-to-end workflow independently exercises Streamlit reruns.
"""
from contextvars import copy_context

import pytest

from app import monthly_report_library as library
from app import monthly_report_qa_fixture as fixture
from app import monthly_report_testing as qa
from app import monthly_report_testing_ui as ui


COOKIE = "e" * 32
OTHER_COOKIE = "f" * 32


def test_replay_callback_keeps_first_accepted_action_during_rerenders(monkeypatch):
    state = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui._queue_fixture_request("replay")
    accepted = dict(state["monthly_qa_fixture_pending"])
    assert accepted["mode"] == "replay" and len(accepted["id"]) == 32
    # A rerun or duplicate click cannot replace an already-accepted request.
    ui._queue_fixture_request("replay")
    ui._queue_fixture_request("prefill")
    assert state["monthly_qa_fixture_pending"] == accepted

    # Compare also keeps one action through rerenders; a later reset must
    # invalidate its receipt together with the current fixture.
    ui._queue_compare_request()
    comparison = dict(state["monthly_qa_compare_pending"])
    assert len(comparison["id"]) == 32
    ui._queue_compare_request()
    assert state["monthly_qa_compare_pending"] == comparison

    # A new user reset cancels the old uncommitted fixture request.
    state["_monthly_qa_reset_receipt"] = {"id": "old"}
    ui._queue_reset_request()
    request = state["monthly_qa_reset_pending"]
    assert len(request["id"]) == 32
    assert "monthly_qa_fixture_pending" not in state
    assert "_monthly_qa_reset_receipt" not in state
    ui._queue_reset_request()
    assert state["monthly_qa_reset_pending"] == request


def test_reset_then_immediate_replay_commits_new_generation_and_keeps_live_unmodified(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = fixture.profile()
    # Identically named live record exists deliberately: QA may not modify it.
    library.save_profile(profile, expected_revision=0, actor="Live Synthetic", confirmed=True)
    live_state = library.load_profile(profile.contract, profile.key)
    with qa.isolated(COOKIE):
        initial = fixture.prepare("prefill")
        assert not initial.sources
        prior = library.load_snapshot(profile.contract, profile.key, fixture.PERIOD)
        assert prior and prior.revision == 1
        old_generation = qa.generation()
        old_task = copy_context()
        qa.reset(tmp_path)
        with pytest.raises(OSError, match="reset|changed"):
            old_task.run(library.load_snapshot, profile.contract, profile.key, fixture.PERIOD)
    # A new Streamlit rerun re-enters isolated() before the replay request.
    with qa.isolated(COOKIE):
        assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None
        assert qa.generation() != old_generation
        replay = fixture.prepare("replay")
        committed = library.load_snapshot(profile.contract, profile.key, fixture.PERIOD)
        assert committed and committed.revision == 1
        assert committed.draft.fingerprint == replay.fingerprint
        assert {s.filename for s in committed.draft.sources} == {
            "synthetic-workorders.csv", "synthetic-activity.txt"}
        checks = fixture.compare(committed.draft)["checks"]
        assert len(checks) == 18 and all(checks.values()), checks
        # Old generation is still forbidden from writing this replacement.
        with pytest.raises(OSError, match="changed|reset"):
            old_task.run(library.load_snapshot, profile.contract, profile.key, fixture.PERIOD)
        qa.reset(tmp_path)
    with qa.isolated(COOKIE):
        assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None
    with qa.isolated(OTHER_COOKIE):
        assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None
    assert library.load_profile(profile.contract, profile.key) == live_state
    assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None


def test_rejected_replay_write_remains_retryable_without_false_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with qa.isolated(COOKIE):
        original = library.save_snapshot
        attempts = []

        def fail_once(*args, **kwargs):
            attempts.append(True)
            raise OSError("Invented isolated write rejection.")

        monkeypatch.setattr(library, "save_snapshot", fail_once)
        with pytest.raises(OSError, match="Invented isolated write rejection"):
            fixture.prepare("replay")
        assert attempts
        assert library.load_snapshot(fixture.CONTRACT, fixture.profile().key,
                                     fixture.PERIOD) is None

        monkeypatch.setattr(library, "save_snapshot", original)
        replay = fixture.prepare("replay")
        saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        assert saved and saved.draft.fingerprint == replay.fingerprint
        assert len(saved.draft.sources) == 2
        assert all(fixture.compare(saved.draft)["checks"].values())


def test_browser_replay_waits_for_durable_state_not_a_static_button():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "scripts" /
              "qa_monthly_live.py").read_text()
    assert 'await_fixture_state(page, "empty", previous_generation=' in source
    assert 'QA reset acknowledged: empty fixture' in source
    assert 'QA fixture action accepted and committed:' in source
    assert 'QA comparison completed:' in source
    assert 'page.get_by_role("button", name="Replay synthetic source files", exact=True).wait_for' not in source
    assert 'reset_fixture(page, replay_state, "final")' in source



def test_known_value_activity_input_is_hydrated_and_journaled_before_live_edit():
    """Prevent constructing a new edit from a transient blank textarea.

    On fd759... the failed browser artifact had saved SHA 212afb... for the
    original prefill but the harness expected c0803d... for a leading-newline
    edit: its initial editor.input_value() was sampled before hydration.
    """
    from hashlib import sha256
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "scripts" /
              "qa_monthly_live.py").read_text()
    initial = "Three September work orders: 3 total, 2 completed, 1 open (66.7%)."
    assert sha256(initial.encode()).hexdigest().startswith("212afbc65093")
    assert sha256(("\\nSynthetic owner edit retained through a browser refresh.").encode()).hexdigest().startswith("c0803dd4bbb5")
    assert 'expect(editor).to_have_value(expected_seed, timeout=60000)' in script
    assert 'page.get_by_text(seeded, exact=True).wait_for(timeout=60000)' in script
    assert script.index("expect(editor).to_have_value(expected_seed") < script.index("original = editor.input_value()")
