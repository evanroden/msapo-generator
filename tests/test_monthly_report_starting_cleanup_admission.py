"""Starting Report replacements must enter admission before native derivation.

Real synthetic DOCX bytes cross the upload and inspection route. The rendering
slot is instrumented and derivation stops at its boundary; no conversion or
external reader is invoked.
"""
from contextlib import contextmanager
from hashlib import sha256

import pytest

from app import monthly_report_ai as ai
from app import monthly_report_render_jobs as jobs
from app import monthly_report_source_view_runtime as runtime
from app.monthly_report_import import inspect_docx
from test_monthly_report_source_frame_logo_role import source
from test_monthly_report_start_import import report_file
from test_monthly_report_starting_import_failure_ui import _start


@pytest.mark.parametrize("cleanup_failure,busy_first", [
    pytest.param(False, False, id="healthy_cleanup"),
    pytest.param(True, False, id="cleanup_error"),
    pytest.param(True, True, id="cleanup_error_then_busy"),
])
def test_native_replacement_reenters_admission_even_when_old_cleanup_fails(
        monkeypatch, tmp_path, cleanup_failure, busy_first):
    def forbidden_reader(*args, **kwargs):
        raise AssertionError("Starting Report admission must not invoke a paid reader")

    monkeypatch.setattr(ai, "request_json", forbidden_reader)
    monkeypatch.setattr(ai, "reserve_call", forbidden_reader)

    first = report_file(tmp_path, activity=("September 2026 synthetic plain source.",))
    first_raw = first.read_bytes()
    assert not runtime.import_candidate(inspect_docx(first))
    candidate_dir = tmp_path / "native"
    candidate_dir.mkdir()
    candidate = source(candidate_dir, divergent=True)
    candidate_raw = candidate.read_bytes()
    candidate_digest = sha256(candidate_raw).hexdigest()
    assert runtime.import_candidate(inspect_docx(candidate)), "Fixture must need native admission"

    slot_depth = 0
    admissions, derivations, busy_rejections = [], [], []

    @contextmanager
    def tracked_slot(**kwargs):
        nonlocal slot_depth
        assert kwargs == {"preview": True}
        admissions.append(True)
        if busy_first and not busy_rejections:
            busy_rejections.append(True)
            raise jobs.RenderBusy("Synthetic starting report admission busy")
        slot_depth += 1
        try:
            yield
        finally:
            slot_depth -= 1

    def checked_derive(path, inspection):
        if runtime.import_candidate(inspection):
            derivations.append((inspection.sha256, slot_depth))
            assert inspection.sha256 == candidate_digest
            assert path.read_bytes() == candidate_raw
            assert slot_depth > 0, "Native source derivation bypassed work admission"
        return None

    monkeypatch.setattr(jobs, "work_slot", tracked_slot)
    monkeypatch.setattr(runtime, "derive_import_view", checked_derive)
    supplied = {"raw": first_raw}
    app = _start(monkeypatch, tmp_path, supplied)
    stages = [(key, value) for key, value in app.session_state.filtered_state.items()
              if key.endswith("_stage") and isinstance(value, tuple) and len(value) == 3]
    assert len(stages) == 1
    stage_key, previous = stages[0]
    assert previous[2].sha256 == sha256(first_raw).hexdigest()
    assert previous[1].read_bytes() == first_raw
    assert not runtime.import_candidate(previous[2])
    assert not derivations
    admitted_before = len(admissions)
    assert admitted_before == 0, "The initial plain source must not need native admission"
    cleanup = previous[0].cleanup
    cleanup_calls = []

    def old_cleanup():
        cleanup_calls.append(True)
        if cleanup_failure:
            raise OSError("Synthetic obsolete temporary directory busy: /mnt/private/old-review")
        cleanup()

    def cleanup_warnings():
        return [warning.value for warning in app.warning
                if "temporary review could not be removed" in warning.value]

    monkeypatch.setattr(previous[0], "cleanup", old_cleanup)
    supplied["raw"] = candidate_raw
    try:
        app.run()
        assert not app.exception, [error.message for error in app.exception]
        if busy_first:
            # The new stage exists, but its first admission was refused. Its
            # cleanup notice must wait until that stage can actually render.
            assert admissions == [True] and busy_rejections == [True]
            assert not derivations and slot_depth == 0
            assert cleanup_calls == [True] and not cleanup_warnings()
            assert app.session_state[stage_key][2].sha256 == candidate_digest
            assert app.session_state[stage_key][1].read_bytes() == candidate_raw
            assert not any(key.endswith(("_failed_digest", "_failed_notice"))
                           for key in app.session_state.filtered_state)
            app.run()
            assert not app.exception, [error.message for error in app.exception]
            assert len(admissions) == 2 and derivations == [(candidate_digest, 1)]
        assert derivations and all(depth > 0 for _, depth in derivations)
        assert len(admissions) > admitted_before and slot_depth == 0
        assert cleanup_calls == [True]
        current = app.session_state[stage_key]
        assert current[2].sha256 == candidate_digest != previous[2].sha256
        assert current[1].read_bytes() == candidate_raw
        assert not any(key.endswith(("_failed_digest", "_failed_notice"))
                       for key in app.session_state.filtered_state)
        if cleanup_failure:
            assert previous[1].read_bytes() == first_raw
            assert len(cleanup_warnings()) == 1
            assert "/mnt/private" not in cleanup_warnings()[0]
            assert "Synthetic obsolete" not in cleanup_warnings()[0]
        else:
            assert not cleanup_warnings()

        # Every subsequent candidate render still needs admission, without
        # retrying cleanup or turning the successfully installed stage into
        # a failed upload.
        prior_derivations = len(derivations)
        app.run()
        assert not app.exception, [error.message for error in app.exception]
        assert len(derivations) > prior_derivations
        assert all(digest == candidate_digest and depth > 0 for digest, depth in derivations)
        assert slot_depth == 0 and cleanup_calls == [True]
        assert not cleanup_warnings(), "A neutral rerun must not repeat the cleanup warning"
        assert bool(busy_rejections) == busy_first
        assert app.session_state[stage_key][2].sha256 == candidate_digest
        assert app.session_state[stage_key][1].read_bytes() == candidate_raw
        assert not any(key.endswith(("_failed_digest", "_failed_notice"))
                       for key in app.session_state.filtered_state)
        assert first.read_bytes() == first_raw
        assert candidate.read_bytes() == candidate_raw
    finally:
        monkeypatch.setattr(previous[0], "cleanup", cleanup)
        cleanup()
        current = app.session_state[stage_key]
        if current[0] is not None and current[0] is not previous[0]:
            current[0].cleanup()
