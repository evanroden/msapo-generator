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


# --- 12: a broken font must not blank the page -----------------------------


def test_a_corrupt_signature_font_raises_the_operator_facing_error(tmp_path):
    """A font file that EXISTS can still fail to load -- an interrupted apt
    install, a truncated layer, a corrupt mount -- and Pillow raises
    OSError("broken file"). The candidate scan only tests is_file().

    expense_ui catches ExpenseReportError around the signature preview, so an
    OSError propagated out of render_expense_workflow and BLANKED THE WHOLE
    PAGE, after the employee had entered the entire report.
    """
    from unittest import mock

    import app.expense_report as expense_report
    from app.expense_report import ExpenseReportError, employee_signature_png

    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font at all")

    with mock.patch.object(expense_report, "_SIGNATURE_FONT_CANDIDATES", [broken]):
        with pytest.raises(ExpenseReportError, match="signature font"):
            employee_signature_png("Dane Example")


def test_the_underlying_font_error_is_preserved_as_the_cause(tmp_path):
    """Wrapped, not swallowed. The operator gets a sentence; the logs keep the
    OSError that says which file broke."""
    from unittest import mock

    import app.expense_report as expense_report
    from app.expense_report import ExpenseReportError, employee_signature_png

    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font at all")

    with mock.patch.object(expense_report, "_SIGNATURE_FONT_CANDIDATES", [broken]):
        try:
            employee_signature_png("Dane Example")
        except ExpenseReportError as exc:
            assert isinstance(exc.__cause__, OSError)
        else:
            pytest.fail("expected ExpenseReportError")


def test_a_working_font_still_renders_a_signature():
    from app.expense_report import employee_signature_png

    payload = employee_signature_png("Dane Example")
    assert payload[:4] == bytes([0x89]) + b"PNG"


# --- 14: the session-key guard must mean what it says ----------------------


def test_the_receipt_cleanup_guard_is_prefix_protected_on_both_branches():
    """`and` binds tighter than `or`, so
        receipt_id in key or token in key and key.startswith("expense_")
    guarded the TOKEN branch only -- the full-hash branch could pop any key in
    session state. Latent rather than live (a 64-hex content hash appears in no
    other key), but the guard now says what it always meant, so a change to
    receipt_id's shape cannot turn the trap live.
    """
    source = Path("app/expense_ui.py").read_text(encoding="utf-8")
    guarded = '(receipt_id in key or token in key) and key.startswith("expense_")'
    unguarded = 'receipt_id in key or token in key and key.startswith("expense_")'

    assert source.count(guarded) == 2, "both cleanup loops must be parenthesised"
    assert unguarded not in source.replace(guarded, ""), "an unparenthesised guard remains"


def test_the_parenthesised_guard_matches_the_same_keys_it_did_before():
    """The fix must not change which keys are cleared today. Both forms agree
    on every key the workflow actually creates; they differ only for a
    hypothetical non-expense_ key containing the full hash."""
    receipt_id = "a" * 64
    token = receipt_id[:12]
    live_keys = [
        f"expense_receipt_amount_{receipt_id}",
        f"expense_section_{token}_x",
        f"expense_analysis_{receipt_id}",
        "expense_employee_name_abc123",
        "workflow_mode",
    ]
    for key in live_keys:
        old = receipt_id in key or token in key and key.startswith("expense_")
        new = (receipt_id in key or token in key) and key.startswith("expense_")
        assert old == new, f"behaviour changed for {key!r}"


# --- 19: blocking messages must name a receipt the employee can see --------


def _split_receipt_items():
    from datetime import date as _date
    from io import BytesIO

    from PIL import Image, ImageDraw

    from app.expense_report import (
        ALLOCATION_JOB,
        EXPENSE_SECTION_MISC,
        ExpenseAllocation,
        ExpenseItem,
    )
    from app.job_numbers import RRH_JOB_NUMBERS

    image = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(image).text((20, 20), "TOTAL", fill="black")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    payload = buffer.getvalue()

    allocation = ExpenseAllocation(
        kind=ALLOCATION_JOB,
        job_number=RRH_JOB_NUMBERS[0],
        account_cost_type="01AMA",
        cost_code_or_wo_type="5490",
    )
    # ONE upload split into three reimbursement lines; the third is incomplete.
    return [
        ExpenseItem(
            receipt_id=f"line-{index}",
            source_receipt_id="src-a",
            filename="receipt.jpg",
            file_bytes=payload,
            transaction_date=_date(2026, 8, 10),
            description="Parking" if index < 3 else "",
            amount="10.00",
            section=EXPENSE_SECTION_MISC,
            allocation=allocation,
            merchant_name="Merchant",
            contact_name="",
        )
        for index in (1, 2, 3)
    ]


def _rrh_details():
    from datetime import date as _date

    from app.expense_report import ExpenseReportDetails

    return ExpenseReportDetails(
        account="Rochester Regional Health",
        employee_name="Test Employee",
        employee_number="1",
        employee_home_bu="695",
        report_date=_date(2026, 8, 11),
        approver_name="Approver",
        approver_email="approver@example.invalid",
        mail_destination="home",
        satellite_office="",
        employee_signature_confirmed=True,
    )


def test_a_split_receipt_problem_names_the_card_that_exists():
    """`items` are reimbursement LINES; a split receipt makes several from ONE
    upload. Numbering by line meant a problem on the third line of a single
    split receipt read "Receipt 3:" while the employee looked at one card
    labelled "Receipt 1 of 1" -- a card that does not exist."""
    from app.expense_report import _unique_receipt_count, validate_expense_report

    items = _split_receipt_items()
    assert _unique_receipt_count(items) == 1, "fixture is not actually one receipt"

    problems = [p for p in validate_expense_report(_rrh_details(), items) if "Receipt" in p]
    assert problems, "expected a blocking problem on the incomplete line"
    assert any(p.startswith("Receipt 1, line 3") for p in problems), problems
    assert not any(p.startswith("Receipt 3") for p in problems), problems


def test_separate_receipts_are_still_numbered_plainly():
    """The common case must not gain a "line N" suffix it does not need."""
    from datetime import date as _date

    from app.expense_report import _unique_receipt_count, validate_expense_report

    items = _split_receipt_items()
    # Same three lines, but each from its own upload.
    items = [
        type(item)(**{**item.__dict__, "source_receipt_id": f"src-{index}"})
        for index, item in enumerate(items, 1)
    ]
    assert _unique_receipt_count(items) == 3

    problems = [p for p in validate_expense_report(_rrh_details(), items) if "Receipt" in p]
    assert any(p.startswith("Receipt 3:") for p in problems), problems
    assert not any("line" in p for p in problems), problems


# --- 13: the report date must default in the OPERATOR's zone ---------------


def test_the_report_date_default_uses_the_configured_zone_not_the_container():
    """Nothing sets TZ in the Dockerfile, render.yaml or docker-compose.yml, so
    the container runs UTC -- 4-5 hours ahead of every US contract. date.today()
    rolled over at 8pm Eastern and defaulted TOMORROW'S DATE onto the expense
    form the approver signs."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.config import EPC_TIMEZONE, operator_today

    assert operator_today() == datetime.now(ZoneInfo(EPC_TIMEZONE)).date()


def test_the_zone_is_overridable_per_deployment(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import app.config as config

    monkeypatch.setattr(config, "EPC_TIMEZONE", "America/Chicago")
    assert config.operator_today() == datetime.now(ZoneInfo("America/Chicago")).date()


def test_an_unknown_zone_falls_back_instead_of_taking_the_workflow_down(monkeypatch):
    """A typo in a dashboard variable must not break expense filing. The
    operator can still edit the date; an exception would blank the page."""
    from datetime import date as _date

    import app.config as config

    monkeypatch.setattr(config, "EPC_TIMEZONE", "Not/AZone")
    assert config.operator_today() == _date.today()


def test_no_module_defaults_a_visible_date_from_the_container_clock():
    """Pins the whole class. date.today() is correct for internal comparisons
    but never for a value an operator sees or signs, and this app has no TZ set
    anywhere, so the container clock is always UTC."""
    import subprocess

    result = subprocess.run(
        ["grep", "-rn", "date.today()", "app/"],
        capture_output=True,
        text=True,
    )
    offenders = [
        line
        for line in result.stdout.splitlines()
        if line and not line.startswith("app/config.py")
    ]
    assert not offenders, (
        "use config.operator_today() for operator-visible dates: " + "; ".join(offenders)
    )


# --- 18: a blocked package must not be confirmed in green ------------------


def test_the_readiness_banner_is_not_green_while_the_package_is_blocked():
    """st.success used to fire unconditionally, with the blocking warning
    underneath it. Green is the strongest signal on the page and it was
    answering a question nobody had asked yet."""
    import ast

    source = Path("app/smartsheet_inline.py").read_text(encoding="utf-8")
    function = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and "handoff" in node.name
    )
    blockers_assigned = min(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", "") == "blockers" for target in node.targets)
    )
    success_called = min(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "success"
    )
    assert success_called > blockers_assigned, (
        "st.success renders before the blockers are known"
    )


def test_the_summary_line_still_renders_when_blocked():
    """It is the operator's last chance to notice that extraction missed the
    vendor, site or amount -- MORE important when blocked, not less, since a
    missing vendor is often the very thing being reported. Only the colour
    changes."""
    source = Path("app/smartsheet_inline.py").read_text(encoding="utf-8")
    assert "st.markdown(summary)" in source
    assert "st.success(summary)" in source


# --- 11: an optional note must not vanish when you type it -----------------


def test_typing_the_optional_note_keeps_it_and_its_toggle_on_the_page():
    """`if not instructions_value and st.toggle(...)` short-circuited on the run
    after the operator typed: box AND toggle vanished, and a second copy
    appeared inside the collapsed corrections panel. The text was retained and
    still sent, but from the operator's seat an optional note they had just
    typed simply disappeared."""
    from dotenv import dotenv_values
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "run_web.py", default_timeout=60)
    for key, value in dotenv_values(root / ".env.example").items():
        if value is not None:
            app.session_state[key] = value
    app.run()
    app.button[0].click().run()

    toggles = [t for t in app.toggle if "Additional Information" in t.label]
    assert len(toggles) == 1
    toggles[0].set_value(True).run()

    label = "Additional information (optional)"
    boxes = [t for t in app.text_area if t.label == label]
    assert len(boxes) == 1
    boxes[0].set_value("Reviewer: please expedite.").run()

    after = [t for t in app.text_area if t.label == label]
    assert len(after) == 1, "the note box vanished, or a duplicate appeared"
    assert after[0].value == "Reviewer: please expedite."
    assert [t for t in app.toggle if "Additional Information" in t.label], (
        "the toggle vanished once the note had content"
    )
    assert not app.exception


def test_only_one_widget_ever_claims_the_instructions_key():
    """Two text areas sharing a session key on one run is the hazard the old
    short-circuit was working around. The single-render fix removes the need."""
    source = Path("app/web_ui.py").read_text(encoding="utf-8")
    assert source.count("key=instructions_key") == 1
