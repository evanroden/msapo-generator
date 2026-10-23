"""Exact-package save labels; no renderer, business writes or genuine fixtures."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app import monthly_report_output_ui as output


PREFIX = "synthetic_output_caption"


@pytest.fixture
def ui(monkeypatch):
    messages = SimpleNamespace(success=[], caption=[], warning=[])
    fake = SimpleNamespace(session_state={PREFIX + "_revision": 2})
    for name in ("success", "caption", "warning"):
        setattr(fake, name, getattr(messages, name).append)
    monkeypatch.setattr(output, "st", fake)
    return fake.session_state, messages


def package(*, fingerprint="synthetic-draft", docx=b"synthetic-word", pdf=b"synthetic-pdf"):
    return SimpleNamespace(fingerprint=fingerprint, docx=docx, pdf=pdf)


def draft(fingerprint="synthetic-draft"):
    return SimpleNamespace(fingerprint=fingerprint, period=SimpleNamespace(label="October 2026"))


def snapshot(revision, fingerprint="synthetic-draft"):
    return SimpleNamespace(revision=revision, draft=draft(fingerprint), generated_at="2026-10-21T03:00:00Z")


def show(ui, files, saved=None):
    state, messages = ui
    before = deepcopy(state)
    retry = output.render_output_status(files, draft(), saved, PREFIX)
    assert state == before, "Displaying a receipt must not save, generate or retire state."
    return retry, messages


@pytest.mark.parametrize("prior", [None, 1, 2, 3])
def test_successful_package_save_wins_over_snapshot_read_before_generation(ui, prior):
    files = package()
    output.record_shared_save(PREFIX, files, saved=snapshot(3))
    retry, messages = show(ui, files, snapshot(prior) if prior is not None else None)
    assert retry is False
    assert messages.caption == ["[Shared version 3](#shared-report-history) · October 2026"]
    assert not messages.warning


@pytest.mark.parametrize("error", ["Synthetic shared write failed", ""])
@pytest.mark.parametrize("prior", [None, 1, 2])
def test_unconfirmed_package_save_is_not_hidden_by_an_older_matching_snapshot(ui, error, prior):
    files = package()
    output.record_shared_save(PREFIX, files, error=error)
    retry, messages = show(ui, files, snapshot(prior) if prior is not None else None)
    assert retry is True
    assert not any("Shared version" in caption for caption in messages.caption)
    assert len(messages.warning) == 1
    assert (error or "No shared-version save was confirmed for these files.") in messages.warning[0]
    assert messages.success == ["Word and PDF ready to download"]


def test_failed_save_retry_updates_the_same_package_without_waiting_for_history(ui):
    files = package()
    output.record_shared_save(PREFIX, files, error="Synthetic temporary failure")
    assert show(ui, files, snapshot(2))[0] is True
    identity = output.package_identity(files)
    output.queue_retry(PREFIX, "save", identity, "synthetic-editor-scope", 2)
    request = output.take_retries(PREFIX)["save"]
    assert output.matches_retry(request, files, "synthetic-editor-scope", 2)
    assert not output.matches_retry(request, files, "synthetic-other-scope", 2)
    assert not output.matches_retry(request, files, "synthetic-editor-scope", 3)
    assert output.take_retries(PREFIX) == {"save": None, "pdf": None}
    output.record_shared_save(PREFIX, files, saved=snapshot(3))
    assert show(ui, files, snapshot(2))[0] is False
    assert ui[1].caption[-1].startswith("[Shared version 3]")
    assert output.package_identity(files) == identity
    assert files.docx == b"synthetic-word" and files.pdf == b"synthetic-pdf"


@pytest.mark.parametrize("outcome", ["success", "failure", "pending", "absent"])
def test_a_later_matching_manual_checkpoint_can_establish_shared_save(ui, outcome):
    files = package()
    if outcome == "success":
        output.record_shared_save(PREFIX, files, saved=snapshot(3))
    elif outcome == "failure":
        output.record_shared_save(PREFIX, files, error="Synthetic failure at version 2")
    elif outcome == "pending":
        output.record_shared_save(PREFIX, files)
    retry, messages = show(ui, files, snapshot(4))
    assert retry is False
    assert messages.caption == ["[Shared version 4](#shared-report-history) · October 2026"]
    assert not messages.warning


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_later_different_content_cannot_relabel_this_package(ui, outcome):
    files = package()
    output.record_shared_save(PREFIX, files, saved=snapshot(3) if outcome == "success" else None,
                              error="" if outcome == "success" else "Synthetic failure")
    retry, messages = show(ui, files, snapshot(4, "other-draft"))
    assert retry is (outcome == "failure")
    if outcome == "success":
        assert messages.caption[0].startswith("[Shared version 3]")
    else:
        assert not any("Shared version" in value for value in messages.caption)


@pytest.mark.parametrize("other", [
    {"fingerprint": "other-draft"},
    {"docx": b"different-word-for-same-draft"},
])
@pytest.mark.parametrize("saved", [False, True])
def test_another_package_receipt_is_not_used(ui, other, saved):
    output.record_shared_save(PREFIX, package(**other), saved=snapshot(9))
    retry, messages = show(ui, package(), snapshot(2) if saved else None)
    assert retry is (not saved)
    assert not any("version 9" in value for value in messages.caption)
    if saved:
        assert messages.caption[0].startswith("[Shared version 2]")


def test_missing_failed_attempt_revision_does_not_guess_that_an_old_snapshot_is_new(ui):
    state, _ = ui
    state.pop(PREFIX + "_revision")
    files = package()
    output.record_shared_save(PREFIX, files, error="Synthetic failure with unknown base")
    assert show(ui, files, snapshot(2))[0] is True


def test_legacy_failed_receipt_remains_actionable_without_a_recorded_base(ui):
    state, _ = ui
    files = package()
    state[PREFIX + "_package_save"] = {
        "identity": output.package_identity(files), "revision": None,
        "saved_at": "", "error": "Synthetic legacy failure",
    }
    assert show(ui, files, snapshot(2))[0] is True


def test_word_only_saved_receipt_is_unchanged_when_pdf_becomes_available(ui):
    files = package(pdf=None)
    output.record_shared_save(PREFIX, files, saved=snapshot(3))
    assert show(ui, files, snapshot(2))[0] is False
    assert ui[1].success[-1] == "Word ready to download"
    assert show(ui, package(), snapshot(2))[0] is False
    assert ui[1].success[-1] == "Word and PDF ready to download"
    assert ui[1].caption[-1].startswith("[Shared version 3]")
