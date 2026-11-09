"""Ordinary Starting Report names only the real first known DOCX rejection.

Synthetic Word files exercise actual staged upload/ZIP parsing. The ordinary
report remains intact across failed selection, neutral reruns and explicit
retry. No authentic client data, external reader or source rewrite is used.
"""
from io import BytesIO
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_import as importer
from app import monthly_report_library as library
from app import monthly_report_import_ui as stage
from app import monthly_report_section_ui as section_ui
from app.monthly_report_upload_limits import docx_size_error
from test_monthly_report_start_import import report_file, save_start


@pytest.mark.parametrize("error,expected", (
    (importer.ImportError("Expanded DOCX exceeds 256 MB. Split it before importing."),
     "256 MiB parsing limit"),
    (importer.ImportError("The DOCX contains an oversized or encrypted part."),
     "64 MiB or an encrypted part"),
    (importer.ImportError("DOCX XML exceeds the safe parsing budget."),
     "32 MiB per XML part; 64 MiB total"),
    (importer.ImportError("DOCX XML complexity exceeds the parsing budget."),
     "too many nested XML elements"),
    (importer.ImportError("Document exceeds the item/text/table review budget. Split it and retry; nothing was saved."),
     "more items, text or table cells"),
    (importer.ImportError("The DOCX contains an unsafe package path."),
     "unsafe internal package path"),
    (importer.ImportError("The DOCX contains too many or duplicate package parts."),
     "too many or duplicate package parts"),
    (importer.ImportError("Choose a valid Word DOCX document."),
     "not a valid Word DOCX"),
    (importer.ImportError("Table is too wide to review safely."),
     "table is too wide"),
    (importer.ImportError("DOCX exceeds the 128 MB import limit. Split the source document and retry."),
     "128 MiB DOCX import limit"),
    (importer.ImportError("This DOCX could not be safely read. No library content was changed."),
     "Export a fresh Word copy"),
))
def test_known_docx_rejections_identify_actionable_layer_without_internal_text(error, expected):
    from app.monthly_report_starting_errors import starting_docx_failure_notice
    message = starting_docx_failure_notice(error)
    assert expected in message
    assert "original file and existing report were not changed" in message


@pytest.mark.parametrize("limit_attr,error,expected", (
    ("MAX_EXPANDED_BYTES", "Expanded DOCX exceeds 256 MB. Split it before importing.",
     "7 MiB parsing limit"),
    ("MAX_MEMBER_BYTES", "The DOCX contains an oversized or encrypted part.",
     "3 MiB or an encrypted part"),
    ("MAX_XML_TOTAL", "DOCX XML exceeds the safe parsing budget.",
     "32 MiB per XML part; 2 MiB total"),
    ("MAX_XML_BYTES", "DOCX XML exceeds the safe parsing budget.",
     "4 MiB per XML part; 64 MiB total"),
    ("MAX_DOCX_BYTES", "DOCX exceeds the 128 MB import limit. Split the source document and retry.",
     "5 MiB DOCX import limit"),
))
def test_effective_parser_limits_follow_real_runtime_settings(
        monkeypatch, limit_attr, error, expected):
    from app.monthly_report_starting_errors import starting_docx_failure_notice
    from app.monthly_report_upload_limits import MIB
    with monkeypatch.context() as context:
        context.setattr(importer, limit_attr, {"MAX_EXPANDED_BYTES": 7,
                                                  "MAX_MEMBER_BYTES": 3,
                                                  "MAX_XML_TOTAL": 2,
                                                  "MAX_XML_BYTES": 4,
                                                  "MAX_DOCX_BYTES": 5}[limit_attr] * MIB)
        assert expected in starting_docx_failure_notice(importer.ImportError(error))


def test_streamed_upload_limit_uses_starting_route_not_template_shelf(monkeypatch):
    from app.monthly_report_starting_errors import starting_docx_failure_notice
    from app.monthly_report_upload_limits import MIB
    with monkeypatch.context() as context:
        context.setattr(stage, "MAX_DOCX_BYTES", 2*MIB)
        message = starting_docx_failure_notice(ValueError(docx_size_error(stage.MAX_DOCX_BYTES)))
        assert "2 MiB Starting Report upload limit" in message
        assert "512" not in message
        assert "existing report were not changed" in message


@pytest.mark.parametrize("error", (
    ValueError("Parser failed opening /mnt/private/client.docx: secret@example.invalid"),
    OSError("Disk failure: /mnt/private/customer/invoice.txt"),
    importer.ImportError("Malicious XML at /mnt/private/contact.xlsx"),
    importer.ImportError("DOCX XML exceeds safe parsing budget: /etc/passwd"),
    OSError("Expanded DOCX exceeds 256 MB. Split it before importing."),
))
def test_unknown_errors_never_expose_untrusted_exception_strings(error):
    from app.monthly_report_starting_errors import starting_docx_failure_notice
    text = starting_docx_failure_notice(error)
    assert text == ("This report could not be analyzed. Choose a valid DOCX or retry; "
                    "your existing work was preserved.")
    assert "/mnt/" not in text and "private" not in text


def _uploaded(raw):
    stream = BytesIO(raw)
    stream.name, stream.size = "synthetic-starting.docx", len(raw)
    return stream


def _start(monkeypatch, tmp_path, supplied, *, working_draft=None, working_revision=None):
    """One ordinary native Starting Report route, no preseeded fixture data."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    original_uploader = section_ui.st.file_uploader
    monkeypatch.setattr(section_ui.st, "file_uploader",
        lambda label, *a, **k: (_uploaded(supplied["raw"]) if supplied["raw"] is not None else None) if label == "Starting report"
        else original_uploader(label, *a, **k))
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_ui import _field
profile = synthetic_profiles()[0]
render_section_setup(profile.contract, ReportPeriod(2026,9),
                     "Synthetic Editor", _field, identity=profile,
                     state=st.session_state.get("synthetic_library"),
                     working_draft=st.session_state.get("synthetic_working_draft"),
                     working_revision=st.session_state.get("synthetic_working_revision"))
""", default_timeout=35)
    if working_draft is not None:
        app.session_state["synthetic_working_draft"] = working_draft
        app.session_state["synthetic_working_revision"] = working_revision
        app.session_state["synthetic_library"] = library.load_profile(
            working_draft.profile.contract, working_draft.profile.key)
    app.run()
    assert not app.exception
    return app


def _fail_message(app):
    warnings = [node.value for node in app.warning
                if "DOCX" in node.value or "report could not be analyzed" in node.value]
    assert len(warnings) == 1, warnings
    return warnings[0]


@pytest.mark.parametrize("attr,limit,expected", (
    ("MAX_EXPANDED_BYTES", 2000, "2,000 bytes parsing limit"),
    ("MAX_XML_TOTAL", 2000, "2,000 bytes total"),
))
def test_real_docx_admission_displays_first_rejecting_layer_and_durable_retry(
        monkeypatch, tmp_path, attr, limit, expected):
    path = report_file(tmp_path, activity=("September 2026 inspected synthetic pump.",))
    original = path.read_bytes()
    supplied = {"raw": original}
    main_value = getattr(importer, attr)
    stage_calls = []
    native_stage = section_ui._stage

    def counted_stage(upload):
        stage_calls.append(upload.getvalue())
        return native_stage(upload)

    monkeypatch.setattr(section_ui, "_stage", counted_stage)
    with monkeypatch.context() as limited:
        limited.setattr(importer, attr, limit)
        app = _start(monkeypatch, tmp_path, supplied)
        initial = _fail_message(app)
        assert expected in initial
        assert "original file and existing report were not changed" in initial
        assert any(b.label == "Retry report analysis" for b in app.button)
        assert not any(b.label == "Continue to this month’s updates" for b in app.button)
        digest_keys = [key for key in app.session_state.filtered_state if key.endswith("_failed_digest")]
        notice_keys = [key for key in app.session_state.filtered_state if key.endswith("_failed_notice")]
        assert len(digest_keys) == len(notice_keys) == 1
        assert stage_calls == [original], "The failed upload is parsed only once."
        saved_digest = app.session_state[digest_keys[0]]
        # The first visible Retry must work without a passive rerun first.
        next(b for b in app.button if b.label == "Retry report analysis").click().run()
        assert not app.exception and _fail_message(app) == initial
        assert sum(b.label == "Retry report analysis" for b in app.button) == 1
        assert stage_calls == [original, original]
        app.run()
        assert not app.exception and _fail_message(app) == initial
        assert app.session_state[digest_keys[0]] == saved_digest
        assert stage_calls == [original, original], "Neutral reruns must not repeat parsing."
        assert path.read_bytes() == original

    # A real source parsed with its ordinary budget now works. The same-file
    # retry is explicit; a passive rerun under failed status never reruns
    # expensive inspection.
    assert getattr(importer, attr) == main_value
    next(b for b in app.button if b.label == "Retry report analysis").click().run()
    assert not app.exception
    assert stage_calls == [original] * 3, "Each explicit retry parses the same bytes exactly once."
    assert all(not key.endswith("_failed_notice") for key in app.session_state.filtered_state)
    assert all(not key.endswith("_failed_digest") for key in app.session_state.filtered_state)
    stages = [(key, val) for key, val in app.session_state.filtered_state.items()
              if key.endswith("_stage") and isinstance(val, tuple) and len(val) == 3]
    assert len(stages) == 1
    assert stages[0][1][1].read_bytes() == original
    assert path.read_bytes() == original
    assert not any("2,000 bytes" in warning.value for warning in app.warning)


def test_unreadable_new_source_retains_prior_staged_original_and_exact_error(
        monkeypatch, tmp_path):
    first = report_file(tmp_path, activity=("September 2026 previous synthetic work.",))
    first_raw = first.read_bytes()
    other_dir = tmp_path / "alternative"
    other_dir.mkdir()
    second = report_file(other_dir, activity=("September 2026 alternate source.",))
    second_raw = second.read_bytes()
    assert second_raw != first_raw
    supplied = {"raw": first_raw}
    app = _start(monkeypatch, tmp_path, supplied)
    stages = [(k,v) for k,v in app.session_state.filtered_state.items()
              if k.endswith("_stage") and isinstance(v, tuple) and len(v) == 3]
    assert len(stages) == 1
    stage_key, prior = stages[0]
    assert prior[1].read_bytes() == first_raw

    def damaged(upload):
        raise importer.ImportError("Expanded DOCX exceeds 256 MB. Split it before importing.")

    with monkeypatch.context() as failure:
        failure.setattr(section_ui, "_stage", damaged)
        supplied["raw"] = second_raw
        app.run()
        assert not app.exception
        assert "256 MiB parsing limit" in _fail_message(app)
        assert app.session_state[stage_key] == prior
        assert prior[1].read_bytes() == first_raw
        app.run()
        assert "256 MiB parsing limit" in _fail_message(app)
        assert app.session_state[stage_key] == prior
    assert first.read_bytes() == first_raw and second.read_bytes() == second_raw
    assert prior[1].read_bytes() == first_raw


def test_internal_error_in_native_upload_remains_generic_and_does_not_leak_path(
        monkeypatch, tmp_path):
    path = report_file(tmp_path, activity=("Synthetic work.",))
    raw = path.read_bytes()
    supplied = {"raw": raw}
    with monkeypatch.context() as error:
        error.setattr(section_ui, "_stage",
             lambda *_: (_ for _ in ()).throw(
                 ValueError("XML: /mnt/private/directory/client-email@example.invalid")))
        app = _start(monkeypatch, tmp_path, supplied)
        notice = _fail_message(app)
        assert notice.startswith("This report could not be analyzed")
        assert "/mnt/" not in notice and "client-email" not in notice
        app.run()
        assert _fail_message(app) == notice
    assert raw == path.read_bytes()


def test_remove_and_replace_rejected_upload_clear_failure_state_without_passive_parsing(
        monkeypatch, tmp_path):
    path = report_file(tmp_path, activity=("September 2026 synthetic retry.",))
    raw = path.read_bytes()
    supplied = {"raw": raw}
    calls = []
    native_stage = section_ui._stage

    def counted_stage(upload):
        calls.append(upload.getvalue())
        return native_stage(upload)

    monkeypatch.setattr(section_ui, "_stage", counted_stage)
    with monkeypatch.context() as limited:
        limited.setattr(importer, "MAX_EXPANDED_BYTES", 2000)
        app = _start(monkeypatch, tmp_path, supplied)
        initial = _fail_message(app)
        assert "2,000 bytes parsing limit" in initial
        supplied["raw"] = None
        app.run()
        assert not app.exception and calls == [raw]
        assert not any(k.endswith(("_failed_digest", "_failed_notice"))
                       for k in app.session_state.filtered_state)
        assert not any(b.label == "Retry report analysis" for b in app.button)
        supplied["raw"] = raw
        app.run()
        assert not app.exception and _fail_message(app) == initial
        assert calls == [raw, raw], "Reselecting after removal is an explicit new import"
    other = tmp_path / "replacement"
    other.mkdir()
    replacement = report_file(other, activity=("September 2026 changed source.",))
    changed = replacement.read_bytes()
    supplied["raw"] = changed
    app.run()
    assert not app.exception and calls == [raw, raw, changed]
    assert not any(k.endswith(("_failed_digest", "_failed_notice"))
                   for k in app.session_state.filtered_state)
    assert not any(b.label == "Retry report analysis" for b in app.button)
    assert path.read_bytes() == raw and replacement.read_bytes() == changed


def test_cleanup_failure_keeps_successful_replacement_reviewable_and_savable(
        monkeypatch, tmp_path):
    first = report_file(tmp_path, activity=("September 2026 previous synthetic work.",))
    first_raw = first.read_bytes()
    supplied = {"raw": first_raw}
    calls = []
    native_stage = section_ui._stage

    def counted_stage(upload):
        calls.append(upload.getvalue())
        return native_stage(upload)

    monkeypatch.setattr(section_ui, "_stage", counted_stage)
    app = _start(monkeypatch, tmp_path, supplied)
    stage_key = next(k for k in app.session_state.filtered_state if k.endswith("_stage"))
    prior = app.session_state[stage_key]
    cleanup = prior[0].cleanup
    cleanup_calls = []

    def cannot_remove():
        cleanup_calls.append(True)
        raise OSError("Synthetic private path: /mnt/private/previous-review")

    monkeypatch.setattr(prior[0], "cleanup", cannot_remove)
    other = tmp_path / "replacement"
    other.mkdir()
    replacement = report_file(other, activity=("September 2026 replacement synthetic work.",))
    changed = replacement.read_bytes()
    supplied["raw"] = changed
    try:
        app.run()
        assert not app.exception
        assert not any(k.endswith(("_failed_digest", "_failed_notice"))
                       for k in app.session_state.filtered_state)
        current = app.session_state[stage_key]
        assert current[2].sha256 != prior[2].sha256
        assert current[1].read_bytes() == changed
        assert prior[1].read_bytes() == first_raw
        assert any("temporary review could not be removed" in w.value for w in app.warning)
        assert not any("/mnt/private" in w.value for w in app.warning)
        assert any(b.label == "Continue to this month’s updates" and not b.disabled
                   for b in app.button)
        app.run()
        assert not app.exception and calls == [first_raw, changed]
        assert cleanup_calls == [True]
        draft = save_start(app)
        activity = next(b.text for b in draft.blocks if b.key == "activity_summary")
        assert "replacement synthetic work" in activity
        assert "previous synthetic work" not in activity
        assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == changed
        assert first.read_bytes() == first_raw and replacement.read_bytes() == changed
    finally:
        monkeypatch.setattr(prior[0], "cleanup", cleanup)
        cleanup()


def test_different_rejected_source_replaces_notice_and_digest_once(monkeypatch, tmp_path):
    first = report_file(tmp_path, activity=("September 2026 first synthetic work.",))
    first_raw = first.read_bytes()
    other = tmp_path / "replacement"
    other.mkdir()
    second = report_file(other, activity=("September 2026 second synthetic work.",))
    second_raw = second.read_bytes()
    supplied = {"raw": first_raw}
    calls = []

    def rejected(upload):
        raw = upload.getvalue()
        calls.append(raw)
        reason = ("Expanded DOCX exceeds 256 MB. Split it before importing."
                  if raw == first_raw else "DOCX XML exceeds the safe parsing budget.")
        raise importer.ImportError(reason)

    monkeypatch.setattr(section_ui, "_stage", rejected)
    app = _start(monkeypatch, tmp_path, supplied)
    assert "256 MiB parsing limit" in _fail_message(app)
    key = next(k for k in app.session_state.filtered_state if k.endswith("_failed_digest"))
    first_digest = app.session_state[key]
    supplied["raw"] = second_raw
    app.run()
    assert not app.exception and calls == [first_raw, second_raw]
    assert app.session_state[key] != first_digest
    notice = _fail_message(app)
    assert "32 MiB per XML part; 64 MiB total" in notice
    assert "256 MiB" not in notice
    assert sum(b.label == "Retry report analysis" for b in app.button) == 1
    app.run()
    assert not app.exception and _fail_message(app) == notice
    assert calls == [first_raw, second_raw]
    assert first.read_bytes() == first_raw and second.read_bytes() == second_raw


def test_failed_existing_report_replacement_preserves_saved_and_unsaved_work(
        monkeypatch, tmp_path):
    first = report_file(tmp_path, activity=("September 2026 saved synthetic work.",))
    first_raw = first.read_bytes()
    supplied = {"raw": first_raw}
    initial_app = _start(monkeypatch, tmp_path, supplied)
    draft = save_start(initial_app)
    library.save_snapshot(draft, expected_revision=0)
    profile = draft.profile
    saved = library.load_snapshot(profile.contract, profile.key, draft.period)
    state = library.load_profile(profile.contract, profile.key)
    original = library.imported_original(profile.contract, profile.key)
    working = replace(draft, blocks=tuple(
        replace(block, text=block.text + "\nKeep this independent unsaved edit.")
        if block.key == "activity_summary" else block for block in draft.blocks))
    other = tmp_path / "replacement"
    other.mkdir()
    second = report_file(other, activity=("September 2026 rejected replacement work.",))
    supplied["raw"] = second.read_bytes()
    with monkeypatch.context() as limited:
        limited.setattr(importer, "MAX_EXPANDED_BYTES", 2000)
        app = _start(monkeypatch, tmp_path, supplied,
                     working_draft=working, working_revision=saved.revision)
        for _ in range(2):
            assert not app.exception
            assert app.session_state["synthetic_working_draft"] == working
            assert library.load_snapshot(profile.contract, profile.key, draft.period) == saved
            assert library.load_profile(profile.contract, profile.key) == state
            assert original.read_bytes() == first_raw
            assert "2,000 bytes parsing limit" in _fail_message(app)
            app.run()
    assert first.read_bytes() == first_raw
