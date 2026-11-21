"""A52: isolated, synthetic page receipts and fault-injected reader tests."""
from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace
import json

import httpx
import pytest

from app import api_retry, monthly_report_ai as ai
from app import monthly_report_ai_items as items
from app import monthly_report_ai_ui as ui
from app import monthly_report_library as library
from app.monthly_report_model import (
    ReportPeriod, ReportSource, synthetic_profiles, synthetic_draft
)
from app.monthly_report_sources import SourceContent


@pytest.fixture
def sample(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    period = ReportPeriod(2026, 9)
    source = ReportSource(
        "synthetic-a52", "three-pages.txt", "7" * 64, ".txt",
        page_texts=tuple(f"Serviced unit {n}." for n in (1, 2, 3)),
    )
    return profile, period, source, synthetic_draft(profile, period)


def _page_key(source, page):
    # A51 scopes each page read to the report's contract, site and month, and
    # the UI derives keys that way; the receipts these tests inspect must use
    # the same key as the `sample` draft (synthetic site 0, September 2026).
    return ai.extraction_request(source, (page,), profile=synthetic_profiles()[0],
                                 period=ReportPeriod(2026, 9))[0]


def test_two_session_claim_is_atomic_and_fencing_prevents_stale_overwrite(sample):
    profile, period, source, _ = sample
    key = _page_key(source, 1)
    assert items.status(profile, period, key) == "unread"
    root = library._profile_path(profile.contract, profile.key) / "ai" / "budgets"
    assert not root.exists()  # Viewing progress does not create receipt/lock files.
    state, first = items.claim(profile, period, key)
    assert state == "claimed" and first
    assert items.claim(profile, period, key) == ("pending", None)
    assert items.status(profile, period, key) == "pending"
    root = library._profile_path(profile.contract, profile.key) / "ai" / "budgets"
    assert library._read(root / (period.key + ".json"))["calls"] == 1
    result = {"facts": [{"page": 1, "kind": "action",
                         "text": "Serviced unit 1.", "quote": "Serviced unit 1."}]}
    assert items.accept(profile, period, key, "other-session-token", result) is False
    assert items.accept(profile, period, key, first, result) is True
    assert items.status(profile, period, key) == "accepted"
    assert items.claim(profile, period, key) == ("accepted", None)
    assert items.fail(profile, period, key, first) is False
    assert ai.cached(profile, "extraction", key) == result
    assert library._read(root / (period.key + ".json"))["calls"] == 1
    with pytest.raises(ValueError, match="identity"):
        items.claim(profile, period, "not-a-sha")


def test_failure_receipt_retry_and_expired_token_do_not_replace_success(sample, monkeypatch):
    profile, period, source, _ = sample
    key = _page_key(source, 2)
    _, first = items.claim(profile, period, key)
    assert items.fail(profile, period, key, first)
    assert items.status(profile, period, key) == "failed"
    _, second = items.claim(profile, period, key)
    assert first != second
    good = {"facts": []}
    assert not items.accept(profile, period, key, first, {"facts": [{"bad": True}]})
    assert items.accept(profile, period, key, second, good)
    assert ai.cached(profile, "extraction", key) == good
    # A new month can reuse the same immutable source reading, but human
    # approval and report state are not moved to that month.
    assert items.status(profile, ReportPeriod(2026, 10), key) == "accepted"
    other_site = replace(profile, key="synthetic-a52-other")
    assert items.status(other_site, period, key) == "unread"


@pytest.mark.parametrize("failure", ["socket", "malformed", "malformed_json"])
def test_page_batch_keeps_two_successes_and_only_retries_the_failure(
    sample, monkeypatch, failure
):
    profile, period, source, draft = sample
    state = {"unit_evidence": (SourceContent(source),)}
    notices = []
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        session_state=state, warning=notices.append,
        info=notices.append, rerun=lambda: None,
    ))
    calls = []
    fail_once = [True]

    def fake_start(prepare, read):
        content = prepare()
        number = json.loads(content[0]["text"].split("\n")[-1])["pages"][0]["page"]
        calls.append(number)
        future = Future()
        if number == 2 and fail_once[0]:
            fail_once[0] = False
            if failure == "socket":
                future.set_exception(httpx.ConnectError("synthetic disconnect"))
            elif failure == "malformed_json":
                future.set_exception(ValueError("The document reader returned malformed JSON."))
            else:
                future.set_result({"facts": [{"page": 2, "kind": "action",
                                              "text": "Invented work.",
                                              "quote": "not present"}]})
        else:
            future.set_result({"facts": [{
                "page": number, "kind": "action",
                "text": f"Serviced unit {number}.",
                "quote": f"Serviced unit {number}.",
            }]})
        return future

    monkeypatch.setattr(ui, "start_receipt", fake_start)

    def run_jobs():
        for _ in range(8):
            ui._finish_job(draft, "unit")
            ui._advance_page_reads(draft, "unit")
            if "unit_ai_job" not in state and "unit_ai_page_batch" not in state:
                return
        pytest.fail("page queue did not settle")

    ui._queue_page_reads(draft, "unit", source, (1, 2, 3))
    run_jobs()
    assert calls == [1, 2, 3]  # failure did not restart sibling pages
    assert [items.status(profile, period, _page_key(source, n))
            for n in (1, 2, 3)] == ["accepted", "failed", "accepted"]
    assert {fact.page for fact in state["unit_ai_facts"][2]} == {1, 3}
    assert notices and "Reading was not applied" in " ".join(notices)

    ui._queue_page_reads(draft, "unit", source, (1, 2, 3), failed_only=True)
    run_jobs()
    assert calls == [1, 2, 3, 2]
    assert {fact.page for fact in state["unit_ai_facts"][2]} == {1, 2, 3}
    assert all(items.status(profile, period, _page_key(source, n)) == "accepted"
               for n in (1, 2, 3))
    ui._queue_page_reads(draft, "unit", source, (1, 2, 3))
    run_jobs()
    assert calls == [1, 2, 3, 2]  # repeat click is free
    # A second Streamlit session reloads the accepted page receipts from disk.
    # There is no new paid call and no automatic approval into saved report data.
    fresh = {"unit_evidence": (SourceContent(source),)}
    ui.st.session_state = fresh
    ui._queue_page_reads(draft, "unit", source, (1, 2, 3))
    assert calls == [1, 2, 3, 2]
    assert {fact.page for fact in fresh["unit_ai_facts"][2]} == {1, 2, 3}
    assert source.facts == ()


def test_human_accepted_fact_is_not_overwritten_by_same_id(sample, monkeypatch):
    profile, period, source, draft = sample
    candidate = ai.normalize_facts(
        {"facts": [{"page": 1, "kind": "action",
                    "text": "Serviced unit 1.", "quote": "Serviced unit 1."}]},
        source, (1,), profile, period,
    )[0]
    edited = replace(candidate, flags=("Human reviewed original wording",))
    current = replace(source, facts=(edited,))
    state = {
        "unit_evidence": (SourceContent(current),),
        "unit_ai_facts": (current.id, current.fingerprint, (candidate,)),
        "unit_ai_source": current.id,
    }
    state["unit_pending_fact_approval"] = ui._fact_approval(draft, "unit", current, (candidate,))
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        session_state=state, warning=lambda _: pytest.fail("unexpected stale approval"),
    ))
    ui._apply_pending_fact_approval(draft, "unit")
    assert state["unit_evidence"][0].source.facts == (edited,)


def test_missing_and_unsupported_page_selection_is_not_billed(sample):
    profile, period, source, _ = sample
    for selection in ((), (4,), ("1",), (False,)):
        with pytest.raises(ValueError):
            ai.extraction_request(source, selection)
    key = _page_key(source, 1)
    assert items.status(profile, period, key) == "unread"


def test_jittered_transients_are_bounded_and_nontransients_do_not_retry(monkeypatch):
    class FakeStatus(Exception):
        def __init__(self, code):
            self.status_code = code
            super().__init__(f"HTTP {code}")

    monkeypatch.setattr(api_retry.anthropic, "APIStatusError", FakeStatus)
    clock = [0.0]
    delays = []
    monkeypatch.setattr(api_retry.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api_retry.time, "sleep",
                        lambda s: (delays.append(s), clock.__setitem__(0, clock[0] + s)))
    monkeypatch.setattr(api_retry.random, "uniform", lambda a, b: 1.0)
    sequence = [FakeStatus(429), FakeStatus(503)]

    def work(timeout):
        if sequence:
            raise sequence.pop(0)
        return "ok"

    assert api_retry.request_with_retry(work, until=30.0) == "ok"
    assert delays == [3.0, 6.0] and clock[0] == 9.0

    delays.clear()
    sequence[:] = [httpx.ReadError("socket disconnect")]
    assert api_retry.request_with_retry(work, until=30.0) == "ok"
    assert delays == [3.0]

    def unauthorized(timeout):
        raise FakeStatus(401)

    with pytest.raises(FakeStatus):
        api_retry.request_with_retry(unauthorized, until=30.0)
    assert delays == [3.0]  # 401 has no retry


def test_incomplete_response_cannot_claim_success(sample):
    from app.api_retry import IncompleteResponseError, complete_response_text
    with pytest.raises(IncompleteResponseError):
        complete_response_text(SimpleNamespace(stop_reason="max_tokens", content=[]))
    profile, period, source, _ = sample
    key = _page_key(source, 1)
    _, token = items.claim(profile, period, key)
    assert items.fail(profile, period, key, token)
    assert ai.cached(profile, "extraction", key) is None


def test_completed_page_from_stale_generation_cannot_apply(sample, monkeypatch):
    profile, period, source, draft = sample
    key = _page_key(source, 1)
    _, token = items.claim(profile, period, key)
    future = Future()
    future.set_result({"facts": [{
        "page": 1, "kind": "action", "text": "Serviced unit 1.",
        "quote": "Serviced unit 1.",
    }]})
    warnings = []
    state = {
        "unit_evidence": (SourceContent(source),),
        "_monthly_qa_generation": "new-fixture-run",
        "unit_ai_job": {
            "kind": "extraction", "page_job": True, "key": key,
            "source_id": source.id, "source_fingerprint": source.fingerprint,
            "pages": (1,), "scope": (profile.contract, profile.key, period.key, "retired-run"),
            "profile": profile, "period": period, "token": token,
            "future": future,
        },
    }
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        session_state=state, warning=warnings.append,
    ))
    ui._finish_job(draft, "unit")
    assert "unit_ai_facts" not in state and "unit_ai_job" not in state
    assert items.status(profile, period, key) == "failed"
    assert ai.cached(profile, "extraction", key) is None
    assert any("Source details changed" in message for message in warnings)


def test_other_session_pending_page_does_not_stall_its_successful_siblings(
    sample, monkeypatch
):
    profile, period, source, draft = sample
    first_key = _page_key(source, 1)
    _, first_token = items.claim(profile, period, first_key)
    state = {"unit_evidence": (SourceContent(source),)}
    calls = []
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        session_state=state, info=lambda _: None,
        warning=lambda _: None, rerun=lambda: None,
    ))

    def start(prepare, read):
        content = prepare()
        page = json.loads(content[0]["text"].split("\n")[-1])["pages"][0]["page"]
        calls.append(page)
        future = Future()
        future.set_result({"facts": [{
            "page": page, "kind": "action",
            "text": f"Serviced unit {page}.",
            "quote": f"Serviced unit {page}.",
        }]})
        return future

    monkeypatch.setattr(ui, "start_receipt", start)
    ui._queue_page_reads(draft, "unit", source, (1, 2, 3))
    for _ in range(5):
        ui._finish_job(draft, "unit")
        ui._advance_page_reads(draft, "unit")
    assert calls == [2, 3]  # no duplicate call for page 1
    assert items.status(profile, period, first_key) == "pending"
    assert {fact.page for fact in state["unit_ai_facts"][2]} == {2, 3}
    answer = {"facts": [{"page": 1, "kind": "action",
                         "text": "Serviced unit 1.",
                         "quote": "Serviced unit 1."}]}
    assert items.accept(profile, period, first_key, first_token, answer)
    ui._queue_page_reads(draft, "unit", source, (1, 2, 3))
    assert calls == [2, 3] and {f.page for f in state["unit_ai_facts"][2]} == {1, 2, 3}


def test_exhausted_budget_blocks_only_new_pages_not_cached_siblings(
    sample, monkeypatch
):
    profile, period, source, _ = sample
    old_key = _page_key(source, 1)
    _, owner = items.claim(profile, period, old_key)
    assert items.accept(profile, period, old_key, owner, {"facts": []})
    monkeypatch.setattr(ai, "MAX_CALLS", 1)
    assert items.claim(profile, period, old_key) == ("accepted", None)
    with pytest.raises(ValueError, match="allowance"):
        items.claim(profile, period, _page_key(source, 2))
    assert items.status(profile, period, old_key) == "accepted"
    assert items.status(profile, period, _page_key(source, 2)) == "unread"


def test_blank_page_has_explicit_error_and_preserves_accepted_cache(sample):
    profile, period, source, _ = sample
    valid = _page_key(source, 1)
    _, owner = items.claim(profile, period, valid)
    assert items.accept(profile, period, valid, owner, {"facts": []})
    blank = replace(source, page_texts=(source.page_texts[0], "  "))
    with pytest.raises(ValueError, match="No readable text"):
        ai.extraction_request(blank, (2,))
    assert items.status(profile, period, valid) == "accepted"


def test_empty_middle_page_does_not_omit_surrounding_eligible_pages(
    sample, monkeypatch
):
    profile, period, original, draft = sample
    source = replace(original, page_texts=("Serviced unit 1.", " ", "Serviced unit 3."))
    state = {"unit_evidence": (SourceContent(source),)}
    warnings, calls = [], []
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        session_state=state, warning=warnings.append,
        info=lambda _: None, rerun=lambda: None,
    ))

    def start(prepare, read):
        content = prepare()
        page = json.loads(content[0]["text"].split("\n")[-1])["pages"][0]["page"]
        calls.append(page)
        future = Future()
        future.set_result({"facts": [{
            "page": page, "kind": "action",
            "text": f"Serviced unit {page}.",
            "quote": f"Serviced unit {page}.",
        }]})
        return future

    monkeypatch.setattr(ui, "start_receipt", start)
    ui._queue_page_reads(draft, "unit", source, (1, 2, 3))
    for _ in range(4):
        ui._finish_job(draft, "unit")
        ui._advance_page_reads(draft, "unit")
    assert calls == [1, 3]
    assert {f.page for f in state["unit_ai_facts"][2]} == {1, 3}
    assert any("Page 2: No readable text" in w for w in warnings)
    assert source.page_texts[1] == " "


def test_deliberate_reread_repairs_only_an_unsupported_saved_date(sample, monkeypatch):
    profile, period, original, draft = sample
    source = replace(original, page_texts=(
        "Serviced unit 1. September 17, 2026.",
        *original.page_texts[1:],
    ))
    verified = ai.normalize_facts(
        {"facts": [{"page": 1, "kind": "action",
                    "text": "Serviced unit 1.", "quote": "Serviced unit 1.",
                    "date": "2026-09-17"}]},
        source, (1,), profile, period,
    )[0]
    legacy = replace(verified, date="2026-09-01")
    current = replace(source, facts=(legacy,))
    assert ai.fact_date_problems((legacy,), (current,))
    assert not ai.fact_date_problems((verified,), (current,))
    state = {
        "unit_evidence": (SourceContent(current),),
        "unit_ai_facts": (current.id, current.fingerprint, (verified,)),
        "unit_ai_source": current.id,
    }
    state["unit_pending_fact_approval"] = ui._fact_approval(
        draft, "unit", current, (verified,))
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        session_state=state,
        warning=lambda message: pytest.fail(f"unexpected rejection: {message}"),
    ))
    ui._apply_pending_fact_approval(draft, "unit")
    repaired = state["unit_evidence"][0].source
    assert repaired.facts == (verified,)
    assert repaired.facts[0].id == legacy.id
    assert not ai.fact_date_problems(repaired.facts, (repaired,))
