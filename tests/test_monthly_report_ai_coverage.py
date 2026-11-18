"""A09: deterministic coverage proofs; all model responses are simulated.

No external provider is contacted. These tests prove planner/validator contracts,
not real-service accuracy, authentic-source ingestion or served UI performance.
"""
from dataclasses import asdict, replace
import json
import time
from threading import Lock

import pytest

from app import monthly_report_ai as ai
from app import monthly_report_ai_coverage as cover
from app.monthly_report_model import ReportPeriod, ReportSource, synthetic_profiles

PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)
TEXT = "Synthetic vendor inspected pump on 2026-09-03."


def source(pages, *, needs_vision=(), text=TEXT):
    return ReportSource(
        id="a" * 64, filename="synthetic-coverage.pdf",
        sha256="b" * 64, suffix=".pdf",
        page_texts=tuple(text for _ in range(pages)),
        selected_pages=tuple(range(1, pages + 1)),
        needs_vision=tuple(needs_vision),
    )


def fake_reply(payload, *, with_fact=True):
    text = payload[0]["text"]
    data = json.loads(text.split("\n")[-1])
    facts = [
        {"source": data["source_id"], "region": region["id"],
         "page": region["page"], "kind": "finding",
         "text": "inspected pump", "quote": "inspected pump"}
        for region in data["regions"]
        if with_fact and "inspected pump" in region["text"]
    ]
    return {"reviewed_regions": [r["id"] for r in data["regions"]],
            "unsupported_regions": [], "facts": facts}


def result_for(plan, original, *, read=fake_reply):
    prepared_value = {
        "cached": (),
        "requests": tuple((batch.key, cover._payload(batch, original))
                          for batch in plan.batches),
        "unavailable": (),
    }
    return cover.run(prepared_value, read=read)


@pytest.mark.parametrize("count,batches", [(1, 1), (20, 1), (21, 2), (96, 5)])
def test_every_native_page_accounted_under_bounded_chunks(count, batches):
    original = source(count)
    before = asdict(original)
    planned = cover.plan(original)
    assert len(planned.pages) == count and len(planned.batches) == batches
    assert {r.page for b in planned.batches for r in b.regions} == set(range(1, count + 1))
    assert all(len(b.regions) <= 20 and sum(len(r.text) for r in b.regions) <= 48_000
               for b in planned.batches)
    completed = cover.collect(
        planned, result_for(planned, original), original, PROFILE, PERIOD)
    assert len(completed["inventory"]) == count
    assert all(v == "ready" for v in completed["inventory"].values())
    assert len(completed["facts"]) == count
    assert all(f.source_id == original.id and f.quote == "inspected pump"
               and f.page in planned.pages for f in completed["facts"])
    assert len({f.id for f in completed["facts"]}) == count, "Repeated text on different pages is distinct evidence."
    assert before == asdict(original), "Upload identities and originals are immutable."


def test_single_oversized_page_is_losslessly_split_not_rejected():
    text = ("A" * 60_001) + " inspected pump"
    original = source(1, text=text)
    with pytest.raises(ValueError, match="60,000"):
        ai.extraction_request(original, (1,))  # Documented main failure-before.
    planned = cover.plan(original)
    regions = [r for b in planned.batches for r in b.regions]
    assert len(regions) >= 4
    assert "".join(r.text for r in regions) == text
    assert all(len(r.text) <= 20_000 for r in regions)
    done = cover.collect(
        planned, result_for(planned, original), original, PROFILE, PERIOD)
    assert done["inventory"] == {1: "ready"}
    assert len(done["facts"]) == 1  # Only the last region has this quote.


def test_bad_claims_remain_accounted_but_are_not_promoted():
    original = source(21)
    planned = cover.plan(original)

    def invented(payload):
        result = fake_reply(payload, with_fact=False)
        data = json.loads(payload[0]["text"].split("\n")[-1])
        region = data["regions"][0]
        result["facts"] = [
            {"source": original.id, "region": region["id"], "page": region["page"],
             "kind": "action", "quote": "inspected pump",
             "text": "Completed 600 pump repairs.", "vendor": "Unknown vendor"},
            {"source": original.id, "region": region["id"], "page": region["page"],
             "kind": "action", "quote": "fabricated source quote",
             "text": "Completed work."},
        ]
        return result

    done = cover.collect(
        planned, result_for(planned, original, read=invented),
        original, PROFILE, PERIOD)
    assert len(done["inventory"]) == 21
    assert done["facts"] == ()
    assert done["rejected_claims"] == 4
    assert all(status == "needs_review" for status in done["inventory"].values())


def test_pending_maintenance_not_recast_as_completed_work():
    original = source(1, text="Synthetic contractor repair scheduled for 2026-09-03.")
    planned = cover.plan(original)

    def misleading(payload):
        data = json.loads(payload[0]["text"].split("\n")[-1])
        return {
            "reviewed_regions": [data["regions"][0]["id"]],
            "unsupported_regions": [],
            "facts": [{
                "source": original.id, "region": "1.1", "page": 1,
                "kind": "action", "quote": "repair scheduled",
                "text": "Repaired pump.", "vendor": ""}],
        }

    done = cover.collect(
        planned, result_for(planned, original, read=misleading),
        original, PROFILE, PERIOD)
    assert done["facts"] == () and done["rejected_claims"] == 1
    assert done["inventory"][1] == "needs_review"


@pytest.mark.parametrize("mode", ["timeout", "truncated_json", "missing_region"])
def test_partial_or_incomplete_reply_preserves_successful_siblings(mode):
    original = source(21)
    planned = cover.plan(original)
    first_region = planned.batches[0].regions[0].identity

    def partly_failing(payload):
        data = json.loads(payload[0]["text"].split("\n")[-1])
        if first_region in [r["id"] for r in data["regions"]]:
            if mode == "timeout":
                raise TimeoutError("simulated model timeout")
            if mode == "truncated_json":
                raise ValueError("simulated truncated JSON")
            return {"reviewed_regions": [], "unsupported_regions": [],
                    "facts": []}
        return fake_reply(payload)

    result = result_for(planned, original, read=partly_failing)
    done = cover.collect(planned, result, original, PROFILE, PERIOD)
    assert len(done["inventory"]) == 21
    assert done["inventory"][21] == "ready"
    assert all(done["inventory"][n] == "retry" for n in range(1, 21))
    assert len(done["facts"]) == 1
    assert len(done["cacheable"]) == 1
    assert len(result["responses"]) == len(planned.batches)


def test_visual_required_and_blank_page_cannot_be_mislabeled_completed():
    original = replace(source(3, needs_vision=(2,)),
                       page_texts=(TEXT, "", ""))
    planned = cover.plan(original)
    assert set(planned.pages) == {1, 2, 3}
    assert planned.empty_pages == (3,)
    visual = [r for b in planned.batches for r in b.regions if r.visual]
    assert len(visual) == 1 and visual[0].page == 2
    done = cover.collect(
        planned, result_for(planned, original), original, PROFILE, PERIOD)
    assert done["inventory"] == {
        1: "ready", 2: "visual_review", 3: "needs_review"}
    assert all(f.page == 1 for f in done["facts"])


def test_cache_hits_and_quota_exhaustion_preserve_all_missing_pages(monkeypatch):
    original = source(96)
    planned = cover.plan(original)
    cache = {}
    admitted = []
    monkeypatch.setattr(cover, "prepare_batch",
                        lambda batch, content, profile: cover._payload(batch, content.source))

    class Quota:
        _date_supported = staticmethod(ai._date_supported)
        normalize_facts = staticmethod(ai.normalize_facts)

        @staticmethod
        def cached(profile, kind, key):
            return cache.get(key)

        @staticmethod
        def reserve_call(profile, period):
            if len(admitted) >= 2:
                raise ValueError("Monthly reader allowance exhausted")
            admitted.append(1)

    content = type("Content", (), {"source": original})()
    prepared_value = cover.prepare_run(
        planned, content, PROFILE, PERIOD, ai_module=Quota)
    assert len(prepared_value["requests"]) == 2
    assert len(prepared_value["unavailable"]) == 3
    first = cover.collect(
        planned, cover.run(prepared_value, read=fake_reply),
        original, PROFILE, PERIOD)
    assert len(first["inventory"]) == 96 and len(first["facts"]) == 40
    assert all(s == "ready" for s in list(first["inventory"].values())[:40])
    assert all(s == "needs_review" for s in list(first["inventory"].values())[40:])
    for key, value in first["cacheable"]:
        cache[key] = value
    repeated = cover.prepare_run(planned, content, PROFILE, PERIOD, ai_module=Quota)
    assert len(repeated["cached"]) == 2 and not repeated["requests"]
    assert len(admitted) == 2, "Cache reuse cannot spend allowance again."


def test_bounded_concurrency_exact_receipts_and_model_cache_partition():
    original = source(96)
    planned = cover.plan(original)
    active, peak = 0, 0
    lock = Lock()

    def measured(payload):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(active, peak)
        try:
            time.sleep(0.01)
            return fake_reply(payload)
        finally:
            with lock:
                active -= 1

    result = result_for(planned, original, read=measured)
    assert 1 <= peak <= cover.MAX_PARALLEL_READS
    assert result["first_response_seconds"] is not None
    assert result["total_seconds"] >= result["first_response_seconds"]
    assert len({b.key for b in planned.batches}) == len(planned.batches)
    assert [b.key for b in cover.plan(original, model="other-model").batches] != [
        b.key for b in planned.batches]
    assert [b.key for b in cover.plan(replace(original, sha256="c" * 64)).batches] != [
        b.key for b in planned.batches]
    assert result["responses"] and all(not error for _, _, error, _ in result["responses"])


def test_unsupported_regions_are_explicit_and_unlisted_regions_never_ready():
    original = source(21)
    planned = cover.plan(original)

    def unsupported(payload):
        data = json.loads(payload[0]["text"].split("\n")[-1])
        regions = data["regions"]
        return {"reviewed_regions": [],
                "unsupported_regions": [
                    {"region": r["id"], "reason": "No technical work evidenced"}
                    for r in regions],
                "facts": []}

    done = cover.collect(
        planned, result_for(planned, original, read=unsupported),
        original, PROFILE, PERIOD)
    assert all(status == "ready" for status in done["inventory"].values())
    assert done["facts"] == ()


def test_missing_invalid_or_duplicate_page_identifiers_are_rejected():
    original = source(2)
    for selection in ((), (0,), (3,), (1, True)):
        with pytest.raises(ValueError):
            cover.plan(original, selection)
    assert cover.plan(original, (1, 1, 2)).pages == (1, 2)

def test_dense_table_rows_are_kept_whole_and_types_are_advisory():
    lines = [f"2026-09-03 inspected pump on row {n}" for n in range(135)]
    original = source(1, text="\n".join(lines))
    planned = cover.plan(original)
    regions = [r for batch in planned.batches for r in batch.regions]
    assert len(regions) >= 4
    assert "".join(r.text for r in regions) == original.page_texts[0]
    assert all(len([line for line in r.text.splitlines() if line.strip()]) <= 40
               for r in regions)
    assert all("action" in cover._candidate_kinds(r.text) for r in regions)
    assert all(sum(cover._candidate_line_count(r.text) for r in batch.regions) <= 80
               for batch in planned.batches)


def test_sensitive_quote_rejection_keeps_technical_sibling():
    original = source(2, text=(
        "Synthetic vendor inspected pump. technician@example.net "
        "Phone 800-222-3333. Quote total $900."))
    # Both pages contain the same original, but one response quotes only safe
    # technical wording while another quotes source contact/pricing.
    planned = cover.plan(original)

    def reply(payload):
        data = json.loads(payload[0]["text"].split("\n")[-1])
        return {
            "reviewed_regions": [r["id"] for r in data["regions"]],
            "unsupported_regions": [],
            "facts": [
                {"source": original.id, "region": region["id"],
                 "page": region["page"], "kind": "finding",
                 "text": "inspected pump", "quote": (
                     "inspected pump" if region["page"] == 1
                     else "technician@example.net")}
                for region in data["regions"]
            ],
        }

    finished = cover.collect(
        planned, result_for(planned, original, read=reply),
        original, PROFILE, PERIOD)
    assert len(finished["facts"]) == 1 and finished["facts"][0].page == 1
    assert finished["inventory"] == {1: "ready", 2: "needs_review"}
    assert finished["rejected_claims"] == 1


def test_reviewed_human_facts_do_not_invalidate_native_page_cache():
    original = source(21)
    first = cover.plan(original)
    valid = cover.collect(
        first, result_for(first, original), original, PROFILE, PERIOD)
    reviewed_source = replace(original, facts=(valid["facts"][0],))
    assert reviewed_source.fingerprint != original.fingerprint
    assert [b.key for b in cover.plan(reviewed_source).batches] == [
        b.key for b in first.batches]
    assert reviewed_source.facts[0].quote == "inspected pump"


def test_unverified_identity_date_and_status_on_another_page_never_promoted():
    original = source(21)
    planned = cover.plan(original)

    def loose_reply(payload):
        data = json.loads(payload[0]["text"].split("\n")[-1])
        return {
            "reviewed_regions": [r["id"] for r in data["regions"]],
            "unsupported_regions": [],
            "facts": [{
                "source": original.id, "region": r["id"], "page": r["page"],
                "kind": "action", "text": "Completed scheduled work",
                "quote": "inspected pump", "date": "2026-09-08",
                "facility": "Other Hospital", "vendor": "New Contractor",
            } for r in data["regions"]],
        }

    checked = cover.collect(
        planned, result_for(planned, original, read=loose_reply),
        original, PROFILE, PERIOD)
    assert checked["facts"] == ()
    assert checked["rejected_claims"] == 21
    assert len(checked["inventory"]) == 21

def test_joined_two_source_read_keeps_exact_page_and_source_references():
    first = source(21)
    second = replace(source(1), id="d" * 64, sha256="e" * 64)
    first_plan, second_plan = cover.plan(first), cover.plan(second)
    combined = cover.join_prepared((
        {"cached": (), "requests": tuple(
            (b.key, cover._payload(b, first)) for b in first_plan.batches),
         "unavailable": ()},
        {"cached": (), "requests": tuple(
            (b.key, cover._payload(b, second)) for b in second_plan.batches),
         "unavailable": ()},
    ))
    outcome = cover.run(combined, read=fake_reply)
    one = cover.collect(first_plan, outcome, first, PROFILE, PERIOD)
    two = cover.collect(second_plan, outcome, second, PROFILE, PERIOD)
    assert set(one["inventory"]) == set(range(1, 22))
    assert two["inventory"] == {1: "ready"}
    assert len(one["facts"]) == 21 and len(two["facts"]) == 1
    assert all(f.source_id == first.id for f in one["facts"])
    assert all(f.source_id == second.id for f in two["facts"])
    assert one["admitted_calls"] == 2 and two["admitted_calls"] == 1


def test_reviewed_source_survives_synthetic_disk_serialization(tmp_path):
    from app import monthly_report_library as library
    from app.monthly_report_model import synthetic_draft
    original = source(21)
    planned = cover.plan(original)
    completed = cover.collect(
        planned, result_for(planned, original), original, PROFILE, PERIOD)
    reviewed_source = replace(original, facts=completed["facts"])
    draft = replace(synthetic_draft(PROFILE, PERIOD), sources=(reviewed_source,))
    target = tmp_path / "reviewed-source.json"
    target.write_text(json.dumps(asdict(draft)), encoding="utf-8")
    reloaded = library.draft_from_dict(json.loads(target.read_text(encoding="utf-8")))
    assert reloaded.sources[0] == reviewed_source
    assert [b.key for b in cover.plan(reloaded.sources[0]).batches] == [
        b.key for b in planned.batches]

@pytest.mark.parametrize(
    "original_text,claimed,kind",
    [
        ("Vendor did not inspect pump.", "Inspected pump.", "action"),
        ("Vendor scheduled training for the team.", "Team attended training.", "training"),
        ("Vendor repaired pump.", "ENFRA technician repaired pump.", "action"),
        ("Contractor was not able to start the repair.", "Started repair.", "action"),
    ],
)
def test_negative_vendor_and_future_work_is_never_recast_as_completed(
        original_text, claimed, kind):
    original = source(1, text=original_text)
    planned = cover.plan(original)
    def simulated(payload):
        data = json.loads(payload[0]["text"].split("\n")[-1])
        return {"reviewed_regions": ["1.1"], "unsupported_regions": [],
                "facts": [{"source": original.id, "region": "1.1",
                           "page": 1, "kind": kind, "text": claimed,
                           "quote": original_text}]}
    done = cover.collect(
        planned, result_for(planned, original, read=simulated),
        original, PROFILE, PERIOD)
    assert done["facts"] == ()
    assert done["rejected_claims"] == 1
    assert done["inventory"] == {1: "needs_review"}
