"""A51: repeat reading, scope isolation and provider caching. Synthetic only."""

from dataclasses import replace
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app import monthly_report_ai as ai
from app.monthly_report_model import ReportPeriod, ReportSource, synthetic_profiles


PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)
SOURCE = ReportSource(
    id="synthetic-source-a",
    filename="synthetic.pdf",
    sha256="a" * 64,
    suffix=".pdf",
    page_texts=(
        "Synthetic pump P-1 was inspected on September 3 2026.",
        "Synthetic pump P-2 was tested on September 7 2026.",
    ),
)


def test_cache_key_requires_exact_source_identity_scope_and_version(monkeypatch):
    def key(source=SOURCE, profile=PROFILE, period=PERIOD):
        return ai.extraction_request(source, (1,), profile=profile, period=period)[0]

    control = key()
    assert control == key()
    assert control != key(replace(SOURCE, id="synthetic-source-b"))
    assert control != key(replace(SOURCE, sha256="b" * 64))
    assert control != key(replace(SOURCE, service_date="human corrected"))
    assert control != key(profile=replace(PROFILE, key="synthetic-other-site"))
    assert control != key(profile=replace(PROFILE, contract="synthetic-other-contract"))
    assert control != key(period=ReportPeriod(2026, 10))
    monkeypatch.setattr(ai, "ANTHROPIC_MODEL", "claude-sonnet-new-synthetic")
    assert control != key()
    monkeypatch.setattr(ai, "EXTRACT_PROMPT", ai.EXTRACT_PROMPT + "\nSynthetic policy change.")
    assert control != key()


def test_canonical_page_selection_does_not_rebill_for_reordered_pages():
    key, content = ai.extraction_request(SOURCE, (2, 1, 2), profile=PROFILE, period=PERIOD)
    repeated = ai.extraction_request(SOURCE, (1, 2), profile=PROFILE, period=PERIOD)
    assert (key, content) == repeated
    with pytest.raises(ValueError, match="real source pages"):
        ai.extraction_request(SOURCE, (True,), profile=PROFILE, period=PERIOD)
    with pytest.raises(ValueError, match="real source pages"):
        ai.extraction_request(SOURCE, (), profile=PROFILE, period=PERIOD)


def test_draft_cache_changes_after_human_correction_model_policy_or_site(monkeypatch):
    fact = ai.normalize_facts(
        {"facts": [{"page": 1, "kind": "action",
                    "text": "Pump was inspected.", "quote": "pump P-1 was inspected"}]},
        SOURCE, (1,), PROFILE, PERIOD,
    )[0]
    source = replace(SOURCE, facts=(fact,))
    def key(src=source, profile=PROFILE):
        return ai.drafting_request("activity_summary", (src,), PERIOD, profile=profile)[0]
    control = key()
    assert control == key()
    assert control != key(replace(source, service_date="edited by reviewer"))
    assert control != key(profile=replace(PROFILE, key="another-site"))
    assert control != ai.drafting_request(
        "activity_summary", (source,), PERIOD, profile=PROFILE,
        report_revision="human-edited-paragraph",
    )[0]
    monkeypatch.setattr(ai, "ANTHROPIC_MODEL", "claude-sonnet-new-synthetic")
    assert control != key()
    monkeypatch.setattr(ai, "DRAFT_PROMPT", ai.DRAFT_PROMPT + "\nSynthetic policy update.")
    assert control != key()


def _reply(usage=None):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text='{"facts": []}')],
        usage=usage or SimpleNamespace(input_tokens=10, cache_creation_input_tokens=0,
                                       cache_read_input_tokens=0),
    )


def test_provider_cache_marks_long_claude_request_and_records_mock_usage(monkeypatch):
    seen = []
    class Client:
        def __init__(self, api_key, **kw):
            self.messages = self
            assert kw["max_retries"] == 0
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kw):
            seen.append(kw)
            return _reply(SimpleNamespace(input_tokens=5, cache_creation_input_tokens=0,
                                         cache_read_input_tokens=2200))
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(ai, "ANTHROPIC_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(ai, "make_client", Client)
    tokens = {}
    original = [{"type": "text", "text": "Synthetic long evidence. " * 700}]
    assert ai.request_json(original, usage_stats=tokens) == {"facts": []}
    assert "cache_control" not in original[0]  # immutable caller payload
    assert seen[0]["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert tokens["cache_read_input_tokens"] == 2200
    assert tokens["input_tokens"] == 5


def test_short_and_unrecognized_model_request_remain_uncached(monkeypatch):
    seen = []
    class Client:
        def __init__(self, api_key, **kw): self.messages = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kw):
            seen.append(kw)
            return _reply()
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(ai, "make_client", Client)
    monkeypatch.setattr(ai, "ANTHROPIC_MODEL", "claude-sonnet-4-6")
    ai.request_json([{"type": "text", "text": "brief"}])
    monkeypatch.setattr(ai, "ANTHROPIC_MODEL", "third-party-model")
    ai.request_json([{"type": "text", "text": "Synthetic evidence " * 900}])
    assert all("cache_control" not in x["messages"][0]["content"][0] for x in seen)


def test_unsupported_provider_cache_falls_back_and_stays_disabled(monkeypatch):
    seen = []
    class Client:
        def __init__(self, api_key, **kw): self.messages = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kw):
            seen.append(kw)
            if len(seen) == 1:
                raise anthropic.BadRequestError(
                    "cache_control is not supported",
                    response=httpx.Response(400, request=httpx.Request("POST", "https://example.test/messages")),
                    body={"error": {"message": "cache_control unsupported"}},
                )
            return _reply()
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(ai, "ANTHROPIC_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(ai, "make_client", Client)
    monkeypatch.setattr(ai, "_UNSUPPORTED_PROMPT_CACHES", set())
    content = [{"type": "text", "text": "Synthetic evidence " * 900}]
    assert ai.request_json(content) == {"facts": []}
    assert ai.request_json(content) == {"facts": []}
    assert len(seen) == 3
    assert "cache_control" in seen[0]["messages"][0]["content"][0]
    assert all("cache_control" not in x["messages"][0]["content"][0] for x in seen[1:])


def test_unrelated_400_never_triggers_noncached_retry(monkeypatch):
    seen = []
    class Client:
        def __init__(self, api_key, **kw): self.messages = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kw):
            seen.append(kw)
            raise anthropic.BadRequestError(
                "invalid max_tokens",
                response=httpx.Response(400, request=httpx.Request("POST", "https://example.test/messages")),
                body={"error": {"message": "invalid max_tokens"}},
            )
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(ai, "ANTHROPIC_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(ai, "make_client", Client)
    with pytest.raises(ai.ReaderNetworkError):
        ai.request_json([{"type": "text", "text": "Synthetic evidence " * 900}])
    assert len(seen) == 1


def test_disk_cache_is_scoped_to_source_and_period(tmp_path, monkeypatch):
    from app import monthly_report_library as library
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    source_b = replace(SOURCE, id="synthetic-source-b")
    key_a = ai.extraction_request(SOURCE, (1,), profile=PROFILE, period=PERIOD)[0]
    key_b = ai.extraction_request(source_b, (1,), profile=PROFILE, period=PERIOD)[0]
    key_next = ai.extraction_request(
        SOURCE, (1,), profile=PROFILE, period=ReportPeriod(2026, 10),
    )[0]
    result = {"facts": []}
    ai.save_cache(PROFILE, "extraction", key_a, result)
    assert ai.cached(PROFILE, "extraction", key_a) == result
    assert ai.cached(PROFILE, "extraction", key_b) is None
    assert ai.cached(PROFILE, "extraction", key_next) is None
    assert library._read(ai.cache_path(PROFILE, "extraction", key_a))["result"] == result


def test_foundry_capability_cache_and_endpoint_isolation(monkeypatch):
    seen = []
    class Client:
        def __init__(self, api_key, **kw): self.messages = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kw):
            seen.append(kw)
            if len(seen) == 1:
                raise anthropic.BadRequestError(
                    "cache_control unsupported by Foundry endpoint",
                    response=httpx.Response(400, request=httpx.Request("POST", "https://example.test/messages")),
                    body={"error": {"message": "cache_control unsupported"}},
                )
            return _reply()
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(ai, "ANTHROPIC_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(ai, "make_client", Client)
    monkeypatch.setattr(ai, "_UNSUPPORTED_PROMPT_CACHES", set())
    monkeypatch.setattr(
        ai, "foundry_settings",
        lambda: SimpleNamespace(address="https://synthetic.services.ai.azure.com/anthropic/"),
    )
    payload = [{"type": "text", "text": "Synthetic evidence " * 900}]
    assert ai.request_json(payload) == {"facts": []}
    assert ai.request_json(payload) == {"facts": []}
    assert "cache_control" in seen[0]["messages"][0]["content"][0]
    assert "cache_control" not in seen[1]["messages"][0]["content"][0]
    assert "cache_control" not in seen[2]["messages"][0]["content"][0]
    monkeypatch.setattr(ai, "foundry_settings", lambda: None)
    assert ai.request_json(payload) == {"facts": []}
    assert "cache_control" in seen[3]["messages"][0]["content"][0]


@pytest.mark.parametrize("kind", ["extraction", "draft", "ocr"])
def test_stale_inflight_completion_cannot_cross_period(monkeypatch, kind):
    from concurrent.futures import Future
    from app import monthly_report_ai_ui as ui
    from app.monthly_report_model import synthetic_draft

    warnings = []
    state = {}
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        session_state=state, warning=warnings.append,
    ))
    prefix = "a51_test"
    draft = synthetic_draft(PROFILE, PERIOD)
    current_scope = ui._approval_scope(draft, prefix)
    future = Future()
    future.set_result({"facts": []})
    state[prefix + "_evidence"] = (SimpleNamespace(source=SOURCE),)
    state[prefix + "_ai_job"] = {
        "kind": kind, "future": future,
        "approval_scope": current_scope,
        "source_id": SOURCE.id, "source_fingerprint": SOURCE.fingerprint,
        "pages": (1,), "key": "f" * 64,
    }
    ui._finish_job(replace(draft, period=ReportPeriod(2026, 10)), prefix)
    assert warnings and "context changed" in warnings[0]
    assert prefix + "_ai_facts" not in state
    assert prefix + "_ai_job" not in state


def test_synthetic_cold_warm_cache_measurement(tmp_path, monkeypatch):
    """Actual Python/disk timing; not a paid-provider or browser benchmark."""
    import json
    import os
    from pathlib import Path
    import time
    try:
        import resource
    except ImportError:
        resource = None

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    # Two realistic-size but synthetic page bodies; within the 60k reader cap.
    source = replace(
        SOURCE, page_texts=(
            "Synthetic P-1 inspection 2026-09-03. " * 600,
            "Synthetic P-2 inspection 2026-09-07. " * 600,
        ),
    )
    def snapshot():
        return {"wall_ns": time.perf_counter_ns(), "cpu_ns": time.process_time_ns(),
                "rss_kib": (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                            if resource is not None else None)}
    def delta(start, end):
        return {"wall_ms": round((end["wall_ns"] - start["wall_ns"]) / 1e6, 4),
                "cpu_ms": round((end["cpu_ns"] - start["cpu_ns"]) / 1e6, 4),
                "peak_rss_kib": end["rss_kib"]}
    cold_start = snapshot()
    key, content = ai.extraction_request(source, (2, 1), profile=PROFILE, period=PERIOD)
    assert ai.cached(PROFILE, "extraction", key) is None
    ai.save_cache(PROFILE, "extraction", key, {"facts": []})
    cold_end = snapshot()

    warm_start = snapshot()
    again, repeated_content = ai.extraction_request(source, (1, 2), profile=PROFILE, period=PERIOD)
    result = ai.cached(PROFILE, "extraction", again)
    warm_end = snapshot()
    assert result == {"facts": []}
    assert key == again and content == repeated_content

    # On pre-fix main, same pages in opposite order yielded distinct keys.
    old_first = ai.digest((ai.PROMPT_VERSION, source.sha256, [
        {"page": 2, "text": source.page_texts[1]},
        {"page": 1, "text": source.page_texts[0]},
    ]))
    old_second = ai.digest((ai.PROMPT_VERSION, source.sha256, [
        {"page": 1, "text": source.page_texts[0]},
        {"page": 2, "text": source.page_texts[1]},
    ]))
    assert old_first != old_second
    metrics = {
        "fixture": "synthetic-two-page-ordered-extraction",
        "pages": 2, "characters": sum(map(len, source.page_texts)),
        "cold": delta(cold_start, cold_end),
        "warm": delta(warm_start, warm_end),
        "old_ordered_keys_equal": False,
        "new_canonical_keys_equal": key == again,
        "warm_provider_requests": 0,
        "queue_ms": None,
        "cpu_quota": "unrestricted runner; 0.5 CPU control not exercised",
        "memory_limit": "unrestricted runner; 512 MiB control not exercised",
        "provider_usage": "mocked in separate tests; no real spend",
    }
    destination = os.getenv("INDEPENDENT_OUTPUT", "")
    if destination:
        path = Path(destination) / "a51-synthetic-prompt-cache-metrics.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    assert metrics["warm_provider_requests"] == 0


def test_long_redraft_reuses_stable_evidence_prefix_not_changed_notes(monkeypatch):
    from app.monthly_report_model import EvidenceFact
    evidence = "Synthetic pump checked; pending follow-up. " * 35
    source = replace(SOURCE, page_texts=(evidence,) + SOURCE.page_texts[1:],
                     facts=tuple(
                         EvidenceFact(
                             f"synthetic-fact-{n}", SOURCE.id, 1, "action",
                             evidence, evidence,
                         ) for n in range(7)
                     ))
    key_a, body_a, facts = ai.drafting_request(
        "activity_summary", (source,), PERIOD, instruction="Use a short summary.",
        profile=PROFILE,
    )
    key_b, body_b, _ = ai.drafting_request(
        "activity_summary", (source,), PERIOD, instruction="Use bullet points.",
        profile=PROFILE,
    )
    assert len(facts) == 7 and len(body_a) == len(body_b) == 2
    assert key_a != key_b
    assert body_a[0] == body_b[0] and body_a[1] != body_b[1]
    assert "redrafting_notes" not in body_a[0]["text"]
    assert "Use a short summary." in body_a[1]["text"]
    marked = ai._provider_cached_content(body_a)
    assert marked is not None and marked[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in marked[1]
    assert "cache_control" not in body_a[0]
