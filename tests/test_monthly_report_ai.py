"""Synthetic evidence, mocked network responses; no paid calls or private data."""

from dataclasses import asdict, replace
import json

import pytest

from app import monthly_report_ai as ai, monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_model import ReportPeriod, ReportSource, synthetic_draft, synthetic_profiles, default_sections
from app.monthly_report_prompts import copilot_prompt, parse_copilot, COPILOT_TARGETS


PROFILE = replace(synthetic_profiles()[0], asset_tags=("PMP-1",))
PERIOD = ReportPeriod(2026, 9)
SOURCE = ReportSource("source-abc", "synthetic.pdf", "a" * 64, ".pdf", page_texts=(
    "Synthetic Service inspected PMP-1 and replaced 2 seals on 09/03/2026.",
    "Terms and conditions. Total cost $900.",
), selected_pages=(1,))
VALUE = {"facts": [{"page": 1, "kind": "action", "text": "Replaced 2 seals.",
                     "quote": "replaced 2 seals", "tags": ["pmp-1"], "date": "2026-09-03"}]}


def prepared():
    facts = ai.normalize_facts(VALUE, SOURCE, (1,), PROFILE, PERIOD)
    source = replace(SOURCE, facts=facts)
    block = ai.normalize_draft({"paragraphs": [{"text": "Replaced 2 seals.", "fact_ids": [facts[0].id]}]},
                               "activity_summary", facts, (source,))
    return source, block


def test_copilot_fills_all_placeholders_and_removes_permission_for_prices():
    prompt = copilot_prompt(PROFILE, PERIOD, ("Synthetic Service",), PROFILE.asset_tags)
    assert "{" not in prompt and "}" not in prompt
    assert "September 2026" in prompt and "2026-09-30" in prompt
    assert "Synthetic Service" in prompt and "PMP-1" in prompt
    assert "Include dollar amounts" not in prompt and "Do not include prices" in prompt


def test_copilot_mixed_bullets_missing_sections_and_chatter_remain_visible():
    lines, extra = parse_copilot("Here are the results:\n## 1. WORK COMPLETED\n- 09/03 Repaired pump [email from vendor, 09/03]\n6) TRAINING\n* 09/07 Safety briefing [meeting: safety, 09/07]\n8. UPCOMING / FOLLOW-UPS\nNone found\nPlease check these.")
    assert [l.section for l in lines] == [1, 6]
    assert len(extra) == 2 and extra[0][0] == 1
    assert COPILOT_TARGETS[6] == ("training_summary",)


def test_fact_extraction_is_page_bounded_quote_supported_and_conservative():
    key, content = ai.extraction_request(SOURCE, (1,))
    assert len(key) == 64 and "Total cost" not in content[0]["text"]
    fact = ai.normalize_facts(VALUE, SOURCE, (1,), PROFILE, PERIOD)[0]
    assert fact.tags == ("PMP-1",) and not fact.flags
    for changes in ({"page": 99}, {"quote": "invented claim"}, {"text": "Replaced 30 seals."}, {"text": "Cost $900."}):
        with pytest.raises(ValueError):
            ai.normalize_facts({"facts": [{**VALUE["facts"][0], **changes}]}, SOURCE, (1,), PROFILE, PERIOD)
    with pytest.raises(ValueError, match="60,000"):
        ai.extraction_request(replace(SOURCE, page_texts=("x" * 60_001,)), (1,))


def test_mixed_period_facility_unknown_tag_and_uncertainty_are_flagged():
    value = {"facts": [{**VALUE["facts"][0], "date": "2026-08-31", "facility": "Another synthetic site", "tags": ["UNKNOWN"], "uncertain": True}]}
    fact = ai.normalize_facts(value, SOURCE, (1,), PROFILE, PERIOD)[0]
    assert len(fact.flags) == 4


def test_draft_requires_real_evidence_and_review_invalidates_after_changes():
    source, block = prepared()
    assert not block.reviewed
    reviewed = ai.reviewed_block(block, (source,))
    assert reviewed.reviewed
    draft = replace(synthetic_draft(PROFILE, PERIOD), sections=default_sections(), sources=(source,), blocks=(reviewed,))
    assert not any(c.code == "ai_evidence" for c in preflight(draft))
    changed = replace(source, findings="Corrected reading")
    assert any(c.code == "ai_evidence" for c in preflight(replace(draft, sources=(changed,))))
    with pytest.raises(ValueError, match="Evidence changed"):
        ai.reviewed_block(block, (changed,))
    with pytest.raises(ValueError, match="nonexistent"):
        ai.normalize_draft({"paragraphs": [{"text": "A claim", "fact_ids": ["fake"]}]}, "activity_summary", source.facts, (source,))


def test_unsupported_numbers_block_review_and_pricing_is_rejected():
    source, _ = prepared()
    data = {"paragraphs": [{"text": "Replaced 800 seals.", "fact_ids": [source.facts[0].id]}]}
    block = ai.normalize_draft(data, "activity_summary", source.facts, (source,))
    with pytest.raises(ValueError, match="numerical"):
        ai.reviewed_block(block, (source,))
    data["paragraphs"][0]["text"] = "Replaced seals for $90."
    with pytest.raises(ValueError, match="prices"):
        ai.normalize_draft(data, "activity_summary", source.facts, (source,))


def test_serialization_pins_facts_paragraphs_and_asset_list(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    source, block = prepared()
    draft = replace(synthetic_draft(PROFILE, PERIOD), profile=PROFILE, sources=(source,), blocks=(block,))
    assert library.draft_from_dict(json.loads(json.dumps(asdict(draft)))) == draft
    key, _ = ai.extraction_request(SOURCE, (1,))
    ai.save_cache(PROFILE, "extraction", key, VALUE)
    assert ai.cached(PROFILE, "extraction", key) == VALUE
    assert "monthly_reports" in str(ai.cache_path(PROFILE, "extraction", key))
    monkeypatch.setattr(ai, "MAX_CALLS", 1)
    ai.reserve_call(PROFILE, PERIOD)
    with pytest.raises(ValueError, match="allowance"):
        ai.reserve_call(PROFILE, PERIOD)
    assert ai.cached(PROFILE, "extraction", key) == VALUE


def test_vendor_spellings_come_from_explicit_vendor_column():
    draft = synthetic_draft(PROFILE, PERIOD)
    from app.monthly_report_model import ResolvedBlock
    draft = replace(draft, sections=default_sections(), blocks=(ResolvedBlock("subcontractor_matrix", "Library", rows=(("Demo", "Mechanical", "Synthetic Service", "Role", "", "Yes"),)),))
    assert ai.vendor_names(draft) == ("Synthetic Service",)


def test_request_is_strict_json_and_uses_retry_policy(monkeypatch):
    from types import SimpleNamespace
    seen = []
    class Client:
        def __init__(self, **kw):
            assert kw["max_retries"] == 0
            self.messages = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kw):
            seen.append(kw)
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text='{"facts": []}')])
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(ai.anthropic, "Anthropic", Client)
    assert ai.request_json([{"type": "text", "text": "synthetic"}]) == {"facts": []}
    assert seen[0]["timeout"] and seen[0]["model"] == ai.ANTHROPIC_MODEL
