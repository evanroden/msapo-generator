"""A59: reviewed extraction carries exact source-bound receipts, not model output.

These fixtures contain invented text; no paid reader, real client source or
external credential is used. The saved snapshot is reloaded on each replay.
"""
from dataclasses import replace
from hashlib import sha256

import pytest

from app import monthly_report_ai as ai
from app import monthly_report_library as library
from app.monthly_report_ai_replay import (
    ReviewedReplay, record_acceptance, replay_reviewed_facts,
)
from app.monthly_report_model import EvidenceFact, ReportPeriod, ReportSource, synthetic_draft, synthetic_profiles
from app.monthly_report_sources import _path as source_path, source_bytes


SEPTEMBER = ReportPeriod(2026, 9)
OCTOBER = ReportPeriod(2026, 10)
NOVEMBER = ReportPeriod(2026, 11)


def sample(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    text = ("Site: " + profile.facilities[0].title
            + "\nMaintain the documented pump inspection sequence."
            + "\nInspected the pump on September 3.\n")
    raw = text.encode()
    digest = sha256(raw).hexdigest()
    source = ReportSource(
        "synthetic-" + digest[:16], "synthetic-reviewed.txt", digest, ".txt",
        facility=profile.facilities[0].title, page_texts=(text,), selected_pages=(1,),
    )
    path = source_path(profile, source.sha256, source.suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    recommendation = EvidenceFact(
        "fact-static-corrected", source.id, 1, "recommendation",
        "Maintain the pump inspection sequence.",
        "Maintain the documented pump inspection sequence.",
    )
    work = EvidenceFact(
        "fact-completed", source.id, 1, "action",
        "Inspected the pump on September 3.", "Inspected the pump on September 3.",
    )
    return profile, source, (recommendation, work), path


def historical(profile, source, facts, period=SEPTEMBER):
    return replace(synthetic_draft(profile, period),
                   sources=(replace(source, facts=tuple(facts)),))


def test_same_exact_original_replays_corrected_words_without_paid_reader(monkeypatch, tmp_path):
    profile, source, facts, path = sample(monkeypatch, tmp_path)
    assert record_acceptance(profile, source, facts)
    corrected = replace(facts[0], text="Maintain the documented pump inspection sequence.")
    old = historical(profile, source, (corrected, facts[1]))
    library.save_snapshot(old, expected_revision=0, entered_editor="Synthetic Reviewer")
    assert library.load_snapshot(profile.contract, profile.key, SEPTEMBER).draft.sources[0].facts == (corrected, facts[1])
    new = historical(profile, source, (), period=OCTOBER)
    calls = []
    monkeypatch.setattr(ai, "request_json", lambda payload: calls.append(payload))
    result = replay_reviewed_facts(new, source)
    assert result == ReviewedReplay((corrected,), (facts[1],), SEPTEMBER.key)
    assert result.reusable[0].text == "Maintain the documented pump inspection sequence."
    assert not any(fact.kind == "action" for fact in result.reusable)
    assert source_bytes(profile, source) == path.read_bytes()
    assert calls == []  # Pure accepted-receipt path cannot launch paid extraction.
    assert replay_reviewed_facts(new, source) == result  # Idempotent warm replay.


def test_changed_digest_or_other_site_cannot_reuse_accepted_fact(monkeypatch, tmp_path):
    profile, source, facts, _ = sample(monkeypatch, tmp_path)
    assert record_acceptance(profile, source, facts)
    library.save_snapshot(historical(profile, source, facts), expected_revision=0)
    modified = replace(source, sha256=sha256(b"different original").hexdigest(),
                       page_texts=("different original",), facts=())
    assert replay_reviewed_facts(historical(profile, modified, (), OCTOBER), modified) == ReviewedReplay()
    second = synthetic_profiles()[1]
    # An individual report must have exactly one facility; use the other site.
    alien = replace(profile, facilities=(second.facilities[1],))
    assert replay_reviewed_facts(historical(alien, source, (), OCTOBER), source) == ReviewedReplay()


def test_explicit_latest_month_removal_beats_older_acceptance(monkeypatch, tmp_path):
    profile, source, facts, _ = sample(monkeypatch, tmp_path)
    record_acceptance(profile, source, facts)
    library.save_snapshot(historical(profile, source, facts), expected_revision=0)
    # An operator deliberately removed that source in the latest saved month.
    library.save_snapshot(replace(synthetic_draft(profile, OCTOBER), sources=()), expected_revision=0)
    assert replay_reviewed_facts(historical(profile, source, (), NOVEMBER), source) == ReviewedReplay()


def test_changed_corrected_fact_text_in_snapshot_is_not_reverted(monkeypatch, tmp_path):
    profile, source, facts, _ = sample(monkeypatch, tmp_path)
    record_acceptance(profile, source, facts)
    updated = replace(facts[0], text="Maintain the documented pump inspection sequence.")
    library.save_snapshot(historical(profile, source, (updated, facts[1])), expected_revision=0)
    result = replay_reviewed_facts(historical(profile, source, (), OCTOBER), source)
    assert result.reusable == (updated,)
    assert result.historical == (facts[1],)


def test_missing_original_refuses_replay_without_mutation(monkeypatch, tmp_path):
    profile, source, facts, path = sample(monkeypatch, tmp_path)
    record_acceptance(profile, source, facts)
    library.save_snapshot(historical(profile, source, facts), expected_revision=0)
    path.unlink()
    with pytest.raises((OSError, ValueError)):
        replay_reviewed_facts(historical(profile, source, (), OCTOBER), source)
    assert library.load_snapshot(profile.contract, profile.key, SEPTEMBER).draft.sources[0].facts == facts


def test_malformed_or_wrong_quote_journal_fails_closed(monkeypatch, tmp_path):
    profile, source, facts, _ = sample(monkeypatch, tmp_path)
    from app.monthly_report_ai_replay import _path, _scope
    record_acceptance(profile, source, facts)
    library.save_snapshot(historical(profile, source, facts), expected_revision=0)
    journal = _path(profile, _scope(profile, source))
    value = library._read(journal)
    value["facts"][facts[0].id]["quote_sha256"] = "f" * 64
    journal.write_bytes(library._json(value))
    replay = replay_reviewed_facts(historical(profile, source, (), OCTOBER), source)
    assert not replay.reusable and replay.historical == (facts[1],)
    value["scope"]["sha256"] = "0" * 64
    journal.write_bytes(library._json(value))
    with pytest.raises(library.LibraryError, match="scope changed"):
        replay_reviewed_facts(historical(profile, source, (), OCTOBER), source)


def test_flagged_or_unproved_model_claim_is_not_an_acceptance_receipt(monkeypatch, tmp_path):
    profile, source, facts, _ = sample(monkeypatch, tmp_path)
    flagged = replace(facts[0], flags=("Reader marked this fact uncertain",))
    assert record_acceptance(profile, source, (flagged,)) is False
    asserted = replace(facts[1], quote="Invented work, not on source page")
    assert record_acceptance(profile, source, (asserted,)) is False
    # The reader cache alone has no approval authority.
    key, _ = ai.extraction_request(source, (1,))
    ai.save_cache(profile, "extraction", key, {"facts": [dict(
        page=1, kind="action", text="Inspected the pump on September 3.",
        quote="Inspected the pump on September 3.",
    )]})
    library.save_snapshot(historical(profile, source, ()), expected_revision=0)
    assert replay_reviewed_facts(historical(profile, source, (), OCTOBER), source) == ReviewedReplay()


def test_repeated_approval_does_not_duplicate_content(monkeypatch, tmp_path):
    profile, source, facts, _ = sample(monkeypatch, tmp_path)
    assert record_acceptance(profile, source, facts)
    assert record_acceptance(profile, source, facts)
    library.save_snapshot(historical(profile, source, facts), expected_revision=0)
    result = replay_reviewed_facts(historical(profile, source, (), OCTOBER), source)
    assert len(result.reusable) == len(result.historical) == 1
