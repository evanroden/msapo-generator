"""A65: one-file source retry preserves siblings, report edits and original identity.

The fixture is intentionally synthetic; native AppTest is not a served-browser claim.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources, monthly_report_library as library
from app import monthly_report_upload_ui as ui
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_source_recovery import failed_source_retries, retry_failed_source
from test_monthly_source_intake_recovery import APP
from test_monthly_report_sources import pdf_bytes


@pytest.fixture
def scope(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0], ReportPeriod(2026, 9)


def _file(name, raw):
    value = BytesIO(raw)
    value.name = name
    return value


@pytest.mark.parametrize("name,raw", (
    ("damaged.pdf", b"%PDF-1.7\ninvalid body"),
    ("damaged.docx", b"not a Word package"),
    ("damaged.png", b"not an image"),
    ("damaged.xlsx", b"not a workbook"),
    ("damaged.csv", b"\xff\xfe\xff"),
    ("damaged.eml", b"From: example@example.invalid\n\nContent"),
))
def test_actual_malformed_good_bad_good_isolated_without_rejected_blob(scope, monkeypatch, name, raw):
    profile, period = scope
    if name.endswith(".eml"):
        monkeypatch.setattr(sources, "_email", lambda value:
                            (_ for _ in ()).throw(LookupError("unknown character set")))
    uploaded = (("first.txt", b"Water treatment first synthetic note."),
                (name, raw),
                ("last.txt", b"Water treatment last synthetic note."))
    accepted, errors = sources.ingest_batch(profile, uploaded)
    assert [item.source.filename for item in accepted] == ["first.txt", "last.txt"]
    assert any("Not read: " + name in item for item in errors)
    requests = failed_source_retries(profile, period, 4, uploaded, accepted)
    assert len(requests) == 1 and requests[0].sha256 == sha256(raw).hexdigest()
    assert requests[0].filename == name
    original_ids = tuple(item.source.id for item in accepted)
    again, failure = retry_failed_source(profile, period, 4, uploaded, accepted, requests[0])
    assert again == accepted and any("Not read:" in item for item in failure)
    assert tuple(item.source.id for item in again) == original_ids
    assert not sources._path(profile, sha256(raw).hexdigest(),
                             "." + name.rsplit(".", 1)[-1]).exists()
    assert not sources._path(profile, sha256(raw).hexdigest(), ".json").exists()


def test_same_filename_different_bytes_is_replacement_not_duplicate_and_preserves_review(scope):
    profile, period = scope
    bad = b"\xff\xfe\xff"
    good = b"Facility,Observation\nDemo North,Synthetic inspect pending\n"
    first = ("sibling.txt", b"Water treatment: checked synthetic valve.")
    last = ("last.txt", b"Water treatment: checked synthetic pump.")
    selection = (first, ("report.csv", bad), last)
    accepted, _ = sources.ingest_batch(profile, selection)
    reviewed = replace(accepted[0], source=replace(accepted[0].source,
                              findings="Human note stays", vendor="Synthetic reviewer"))
    accepted = (reviewed, accepted[1])
    old_request, = failed_source_retries(profile, period, 8, selection, accepted)
    new_selection = (first, ("report.csv", good), last)
    with pytest.raises(ValueError, match="changed"):
        retry_failed_source(profile, period, 8, new_selection, accepted, old_request)
    replacement, messages = sources.ingest_batch(profile, (("report.csv", good),), accepted)
    assert not any("Not read:" in item for item in messages)
    assert replacement[:2] == accepted
    assert replacement[2].source.filename == "report.csv"
    assert replacement[2].source.id == sha256(good).hexdigest()
    assert replacement[2].source.id != old_request.sha256
    assert failed_source_retries(profile, period, 8, new_selection, replacement) == ()
    assert sources.source_bytes(profile, reviewed.source) == first[1]
    assert not sources._path(profile, old_request.sha256, ".csv").exists()

    # The report version, attached human correction and original hashes survive
    # an ordinary shared snapshot/reopen; a rejected raw is never materialized.
    human = ResolvedBlock("equipment_issues", "Synthetic issue",
                          text="Keep this confirmed manual finding.")
    draft = replace(synthetic_draft(profile, period),
                    sources=tuple(content.source for content in replacement),
                    blocks=(human,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(profile.contract, profile.key, period)
    assert reopened == saved and reopened.draft == draft
    assert reopened.draft.blocks == (human,)
    assert reopened.draft.sources[0] == reviewed.source
    assert tuple(source.sha256 for source in reopened.draft.sources) == tuple(
        content.source.sha256 for content in replacement)


def test_missing_input_and_duplicate_hash_never_create_ghost_retry(scope):
    profile, period = scope
    assert failed_source_retries(profile, period, 0, (), ()) == ()
    raw = b"Synthetic original remains."
    content, _ = sources.ingest(profile, "original.txt", raw)
    accepted, messages = sources.ingest_batch(profile, (("renamed.txt", raw),), (content,))
    assert accepted == (content,) and any("Duplicate skipped" in item for item in messages)
    assert failed_source_retries(profile, period, 0, (("renamed.txt", raw),), accepted) == ()


def test_stale_revision_scope_and_sibling_change_refuse_without_mutation(scope, monkeypatch):
    profile, period = scope
    selection = (("good.txt", b"Synthetic accepted text"), ("bad.csv", b"\xff\xfe\xff"))
    accepted, _ = sources.ingest_batch(profile, selection)
    request, = failed_source_retries(profile, period, 3, selection, accepted)
    calls = []
    monkeypatch.setattr(sources, "ingest_batch", lambda *a, **k: calls.append(1))
    with pytest.raises(ValueError, match="changed"):
        retry_failed_source(profile, period, 4, selection, accepted, request)
    with pytest.raises(ValueError, match="changed"):
        retry_failed_source(profile, ReportPeriod(2026, 10), 3, selection, accepted, request)
    with pytest.raises(ValueError, match="changed"):
        retry_failed_source(profile, period, 3, selection + (("extra.txt", b"new"),), accepted, request)
    with pytest.raises(ValueError, match="changed"):
        retry_failed_source(profile, period, 3, selection, (), request)
    assert calls == []


def test_managed_intake_retry_only_failed_file_after_unrelated_manual_edit(scope, monkeypatch):
    profile, period = scope
    uploads = [
        _file("water-first.txt", b"Water treatment first synthetic note."),
        _file("recover.pdf", pdf_bytes(1)),
        _file("water-last.txt", b"Water treatment last synthetic note."),
    ]
    original_ingest = sources.ingest
    attempts = []
    def flaky(profile_, name, raw):
        attempts.append(name)
        if name == "recover.pdf" and attempts.count(name) == 1:
            raise OSError("synthetic transient read error")
        return original_ingest(profile_, name, raw)
    monkeypatch.setattr(sources, "ingest", flaky)
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *args, **kwargs:
                        uploads if label == "Add source files" else None)
    app = AppTest.from_string(APP, default_timeout=35).run()
    assert not app.exception
    assert len(app.session_state["sources"]) == 2
    before = app.session_state["sources"]
    assert [source.filename for source in before] == ["water-first.txt", "water-last.txt"]
    retry = [button for button in app.button
             if button.label == "Retry failed file · recover.pdf"]
    assert len(retry) == 1
    assert attempts == ["water-first.txt", "recover.pdf", "water-last.txt"]
    manual = ResolvedBlock("equipment_issues", "Synthetic issue",
                           text="Human edit in another section remains.")
    app.session_state["blocks"]["equipment_issues"] = manual
    app.run()
    assert attempts == ["water-first.txt", "recover.pdf", "water-last.txt"]
    next(button for button in app.button
         if button.label == "Retry failed file · recover.pdf").click().run()
    assert not app.exception
    assert attempts == ["water-first.txt", "recover.pdf", "water-last.txt", "recover.pdf"]
    after = app.session_state["sources"]
    assert len(after) == 3 and after[:2] == before
    assert after[2].sha256 == sha256(uploads[1].getvalue()).hexdigest()
    assert app.session_state["blocks"]["equipment_issues"] == manual
    assert all(source.sha256 != sha256(b"synthetic transient read error").hexdigest()
               for source in after)
    assert not any(b.label.startswith("Retry failed file") for b in app.button)
    app.run()
    assert attempts == ["water-first.txt", "recover.pdf", "water-last.txt", "recover.pdf"]


def test_finished_old_reader_cannot_apply_after_same_name_new_bytes(scope, monkeypatch):
    """Late mocked external result is discarded before current new source commits."""
    from concurrent.futures import Future
    from app import monthly_report_ai as ai, monthly_report_structured_uploads as structured
    from app import receipt_jobs
    profile, period = scope
    original = pdf_bytes(1)
    updated = pdf_bytes(2)
    assert sha256(original).hexdigest() != sha256(updated).hexdigest()
    uploads = [_file("service.pdf", original)]
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *args, **kwargs:
                        uploads if label == "Add source files" else None)
    monkeypatch.setattr(ai, "configured", lambda: True)
    monkeypatch.setattr(ai, "cached", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai, "reserve_call", lambda *args, **kwargs: None)
    future = Future()
    monkeypatch.setattr(receipt_jobs, "start_receipt", lambda prepare, reader: future)
    applied = []
    real_update = structured.reader_update
    def monitor(*args, **kwargs):
        applied.append(1)
        return real_update(*args, **kwargs)
    monkeypatch.setattr(structured, "reader_update", monitor)
    app = AppTest.from_string(APP, default_timeout=35).run()
    assert not app.exception
    assert any(button.label == "Read selected files" for button in app.button)
    next(button for button in app.button if button.label == "Read selected files").click().run()
    assert not app.exception
    manual = ResolvedBlock("equipment_issues", "Synthetic issue",
                           text="Manual edit made during external reading.")
    app.session_state["blocks"]["equipment_issues"] = manual
    future.set_result({"items": [{"source": sha256(original).hexdigest(), "page": 1,
                                 "text": "STale old reader result must never apply"}]})
    uploads[:] = [_file("service.pdf", updated)]
    app.run()
    assert not app.exception
    assert not applied, "The old job must be rejected before its reader_update is called."
    assert app.session_state["blocks"]["equipment_issues"] == manual
    assert any(source.sha256 == sha256(updated).hexdigest()
               for source in app.session_state["sources"])
    assert any("earlier reading was not applied" in w.value for w in app.warning)


def test_deliberately_removed_bytes_are_not_mistaken_for_failed_upload(scope):
    """A native uploader can retain bytes after Remove; only actual errors retry."""
    from app.monthly_report_source_recovery_ui import render_failed_file_retries
    profile, period = scope
    raw = b"Synthetic retained native chooser selection."
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_model import synthetic_profiles, ReportPeriod
from app.monthly_report_source_recovery_ui import render_failed_file_retries
profile = synthetic_profiles()[0]
render_failed_file_retries(profile, ReportPeriod(2026, 9), 0, "fixture",
                           (("removed.txt", b"synthetic removed"),), (),
                           messages=())
""").run()
    assert not app.exception
    assert not any(b.label.startswith("Retry failed file") for b in app.button)
    app = AppTest.from_string("""
from app.monthly_report_model import synthetic_profiles, ReportPeriod
from app.monthly_report_source_recovery_ui import render_failed_file_retries
profile = synthetic_profiles()[0]
render_failed_file_retries(profile, ReportPeriod(2026, 9), 0, "fixture",
                           (("failed.txt", b"synthetic failure"),), (),
                           messages=("Not read: failed.txt. Storage or file reader was unavailable; retry this file.",))
""").run()
    assert not app.exception
    assert any(b.label == "Retry failed file · failed.txt" for b in app.button)


def test_failed_original_keeps_single_source_workspace_pending_then_clears(scope):
    """A failed chooser item stays actionable even if every sibling is resolved."""
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_model import synthetic_profiles, ReportPeriod
from app.monthly_report_source_recovery_ui import render_failed_file_retries
from app.monthly_report_source_manager_ui import _pending_source_selection
profile = synthetic_profiles()[0]
raw = b"synthetic rejected csv"
selected = st.session_state.get("selected", True)
render_failed_file_retries(profile, ReportPeriod(2026,9), 0,
    "report_evidence_structured_activity_summary",
    (("broken.csv", raw),) if selected else (), (),
    messages=("Not read: broken.csv. Invalid CSV.",) if selected else ())
st.session_state["workspace_has_pending_source"] = _pending_source_selection("report")
""").run()
    assert not app.exception
    assert app.session_state["workspace_has_pending_source"] is True
    assert any(b.label == "Retry failed file · broken.csv" for b in app.button)
    app.session_state["selected"] = False
    app.run()
    assert not app.exception
    assert app.session_state["workspace_has_pending_source"] is False
    assert not any(b.label.startswith("Retry failed file") for b in app.button)
