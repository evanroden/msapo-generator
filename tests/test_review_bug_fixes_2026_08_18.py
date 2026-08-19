"""Fixes for six findings from the 2026-08-14 review, verified by reproduction.

These six live in the four modules that the 2026-08-17 remediation (PR #50)
never touched -- receipt_analyzer, eml_builder, smartsheet_store and smartsheet
-- which is why they survived it.

Each test below fails on the parent commit. Two of the twenty-three findings
turned out to be less than claimed and are recorded here as such rather than
quietly "fixed":

  * The _line_items raw-list slice is DELIBERATE bounding, documented in the
    function. Only its note was wrong. The slice is unchanged.
  * build_eml's empty-attachment tolerance was never reachable: the one caller
    already raises first. Enforcing it here is defence in depth.
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
import pytest

import app.receipt_analyzer as receipt_analyzer
from app import memory
from app.eml_builder import build_eml
from app.receipt_analyzer import _MAX_LINE_ITEMS, _line_items
from app.smartsheet import preflight_attachments
from app.smartsheet_store import SubmissionStore


# --- 20: the retry must not sleep after its final attempt ------------------


class _RateLimited(anthropic.APIStatusError):
    def __init__(self):
        self.status_code = 429


class _Dropped(anthropic.APIConnectionError):
    def __init__(self):
        pass


def _client_raising(exc_type):
    class _Client:
        class messages:
            @staticmethod
            def create(**_kwargs):
                raise exc_type()

    return _Client()


def test_a_persistently_rate_limited_receipt_does_not_sleep_after_the_last_try(
    monkeypatch,
):
    """The old loop slept and THEN fell out, so 3 + 6 + 9 = 18 seconds bought an
    answer already available at 9 -- the last 9 spent inside a Streamlit spinner
    with an employee watching it."""
    slept: list[int] = []
    monkeypatch.setattr(receipt_analyzer.time, "sleep", slept.append)

    with pytest.raises(anthropic.APIStatusError):
        receipt_analyzer._call_with_retry(
            _client_raising(_RateLimited), [{"type": "text", "text": "x"}]
        )

    assert slept == [3, 6], "slept after the final attempt"
    assert sum(slept) == 9


def test_a_dropped_connection_is_retried_like_any_other_transient_failure(
    monkeypatch,
):
    """APIConnectionError carries no status code, so it missed the status-only
    except clause and escaped on the FIRST attempt -- the retry contract held
    for a rate limit but not for the flaky network it was written for."""
    slept: list[int] = []
    monkeypatch.setattr(receipt_analyzer.time, "sleep", slept.append)

    with pytest.raises(anthropic.APIConnectionError):
        receipt_analyzer._call_with_retry(
            _client_raising(_Dropped), [{"type": "text", "text": "x"}]
        )

    assert slept == [3, 6], "connection error was not retried"


def test_a_non_transient_status_is_still_not_retried(monkeypatch):
    """A 400 is a property of the request. Retrying it burns the employee's
    time three times over to reach the same answer."""
    slept: list[int] = []
    monkeypatch.setattr(receipt_analyzer.time, "sleep", slept.append)

    class _BadRequest(anthropic.APIStatusError):
        def __init__(self):
            self.status_code = 400

    with pytest.raises(anthropic.APIStatusError):
        receipt_analyzer._call_with_retry(
            _client_raising(_BadRequest), [{"type": "text", "text": "x"}]
        )

    assert slept == []


# --- 21: the truncation note must describe what is actually shown ----------


def test_the_truncation_note_counts_shown_items_not_the_slice_width():
    """70 raw rows, most of them summary rows: 60 are examined, 20 survive. The
    note used to say "the first 60 are shown" beside a 20-row selector, so the
    employee reconciled a promise of 60 against 20 and concluded the tool had
    lost 40 items."""
    rows = [
        {"description": "Subtotal" if index % 3 else f"Item {index}", "amount": "1.00"}
        for index in range(70)
    ]
    notes: list[str] = []
    kept = _line_items(rows, notes)

    assert len(kept) == 20
    note = next(n for n in notes if "rows" in n)
    assert "70 rows" in note
    assert f"first {_MAX_LINE_ITEMS} were examined" in note
    assert "20 usable items" in note


def test_the_raw_slice_bound_is_unchanged():
    """The cap is applied to the RAW list on purpose -- it is what bounds this
    against a response with thousands of junk entries. Only the note changed."""
    rows = [{"description": f"Item {i}", "amount": "1.00"} for i in range(500)]
    notes: list[str] = []
    assert len(_line_items(rows, notes)) == _MAX_LINE_ITEMS


# --- 16: an empty attachment still participates in duplicate detection -----


def test_an_empty_attachment_name_still_counts_as_a_duplicate():
    """The name was registered AFTER the empty-file bail-out, so an empty
    quote.pdf never entered seen_names and a second, valid quote.pdf went
    unreported. The operator fixed the empty file, resubmitted, and only then
    learned about the collision -- one problem per round trip."""
    problems = preflight_attachments([("quote.pdf", b""), ("quote.pdf", b"%PDF-1.7")])

    assert any("empty or unreadable" in problem for problem in problems)
    assert any("duplicated" in problem for problem in problems), (
        "the empty file's name did not join duplicate detection"
    )


def test_a_clean_pair_still_reports_nothing():
    assert preflight_attachments([("quote.pdf", b"a"), ("form.pdf", b"b")]) == ()


# --- 17: the store and the memory module must resolve the SAME directory ---


@pytest.mark.parametrize("configured", [True, False])
def test_the_submission_store_and_memory_resolve_the_same_data_dir(
    monkeypatch, tmp_path, configured
):
    """Duplicate prevention is the one feature whose failure looks exactly like
    success: nothing errors, submissions simply stop being recognised as already
    sent. The store used to fall from EPC_DATA_DIR straight to a CWD-relative
    directory while memory.py probed the /test1 mount in between -- so dropping
    the variable left contract learning working on the persistent disk while
    THIS store quietly went ephemeral.
    """
    if configured:
        monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    else:
        monkeypatch.delenv("EPC_DATA_DIR", raising=False)

    store_dir = SubmissionStore.from_environment().path.parent.resolve()
    memory_dir = memory._data_dir().resolve()

    assert store_dir == memory_dir, (
        "smartsheet_store and memory resolve different data directories; "
        "idempotency state and learned memory would live on different disks"
    )


def test_the_local_fallback_is_not_relative_to_the_working_directory(monkeypatch):
    """A CWD-relative fallback puts the database wherever the process was
    started, which is the same divergence one level further down."""
    monkeypatch.delenv("EPC_DATA_DIR", raising=False)
    assert SubmissionStore.from_environment().path.is_absolute()


# --- 22: a draft that promises an attachment must carry one ----------------


def test_building_a_draft_with_no_attachment_is_refused():
    """Defence in depth: expense_ui._build_expense_eml already raises when there
    is no PDF, so this was never reachable. It is enforced here because the
    obligation was invisible at the call site and the failure it prevents --
    a body telling the approver to review "the attached expense report", with
    nothing attached -- is silent."""
    with pytest.raises(ValueError, match="no attachment"):
        build_eml(
            to="approver@example.invalid",
            subject="Expense report",
            bullets=[("Employee", "Test")],
            attachments=[],
        )


def test_a_draft_with_an_attachment_is_still_built():
    payload = build_eml(
        to="approver@example.invalid",
        subject="Expense report",
        bullets=[("Employee", "Test")],
        attachments=[("expense.pdf", b"%PDF-1.7 x")],
    )
    assert payload.startswith(b"MIME-Version") or b"multipart/mixed" in payload
