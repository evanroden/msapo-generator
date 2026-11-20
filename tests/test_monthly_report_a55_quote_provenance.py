"""A55 synthetic source-bound AI evidence acceptance, with no paid reader.

This tests the persisted citation and user-correction contract, not a served report.
"""
from dataclasses import asdict, replace
import hashlib
import json

import pytest

from app import monthly_report_ai as ai, monthly_report_library as library
from app.monthly_report_model import (
    ReportPeriod, ReportSource, ResolvedBlock, synthetic_draft, synthetic_profiles
)


PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)
PAGES = (
    "September 18, 2026: Vendor inspected pump P-2. Pressure about 40 psi; "
    "repair did not start and a return visit is scheduled.",
    "September 19, 2026: Vendor inspected pump P-20; no repair was completed.",
)
SOURCE = ReportSource(
    "source-a55", "synthetic-vendor.pdf", "a" * 64, ".pdf",
    page_texts=PAGES, selected_pages=(1, 2),
)
QUOTE = "Pressure about 40 psi; repair did not start and a return visit is scheduled."
VALUE = {"facts": [{
    "source_id": SOURCE.id, "source_sha256": SOURCE.sha256,
    "page": 1, "kind": "finding",
    "text": "Pressure about 40 psi; repair did not start and a return visit is scheduled.",
    "quote": QUOTE, "date": "2026-09-18",
}]}


def normalize(source=SOURCE, changes=None):
    entry = {**VALUE["facts"][0], **(changes or {})}
    return ai.normalize_facts({"facts": [entry]}, source, (1, 2), PROFILE, PERIOD)


def test_exact_quote_source_sha_and_page_are_persisted_and_reloaded(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    fact, = normalize()
    assert fact.source_id == SOURCE.id and fact.page == 1
    assert fact.source_sha256 == SOURCE.sha256
    assert fact.page_sha256 == hashlib.sha256(PAGES[0].encode("utf-8")).hexdigest()
    assert fact.quote == QUOTE and fact.date == "2026-09-18"
    source = replace(SOURCE, facts=(fact,))
    suggestion = ai.normalize_draft(
        {"paragraphs": [{"text": fact.text, "fact_ids": [fact.id]}]},
        "activity_summary", source.facts, (source,)
    )
    assert ai.reviewed_block(suggestion, (source,)).reviewed
    human = ResolvedBlock("equipment_issues", "This month",
                          text="Human reviewed note; no completion inferred.",
                          references=("docx:manual:A55",))
    draft = replace(synthetic_draft(PROFILE, PERIOD), sources=(source,),
                    blocks=(human, suggestion))
    result = library.save_snapshot(draft, expected_revision=0,
                                   entered_editor="Synthetic Author")
    loaded = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD)
    assert loaded.revision == result.revision
    assert loaded.draft == draft
    assert loaded.draft.blocks[0] == human
    assert loaded.entered_editor == "Synthetic Author"
    assert loaded.draft.sources[0].facts[0] == fact
    assert json.loads(json.dumps(asdict(fact)))["source_sha256"] == SOURCE.sha256


@pytest.mark.parametrize("changes,message", [
    ({"source_id": "unrelated-site"}, "source"),
    ({"source_sha256": "b" * 64}, "source"),
    ({"page": 2}, "evidence quote"),
    ({"quote": "Pressure exactly 40 psi; repair did not start and a return visit is scheduled."}, "evidence quote"),
    ({"quote": QUOTE.upper()}, "evidence quote"),
    ({"quote": "Pressure about 40 psi; repair did not start; and a return visit is scheduled."}, "evidence quote"),
    ({"quote": ""}, "incomplete"),
    ({"text": "Pressure about 40 psi; repair started and a return visit is scheduled."}, "negation"),
    ({"text": "Pressure 40 psi; repair did not start and a return visit is scheduled."}, "approx"),
    ({"text": "Pressure about 40 gpm; repair did not start and a return visit is scheduled."}, "unit"),
    ({"text": "Pressure about 40 psi; repair did not start and a return visit is scheduled in October."}, "date qualifier"),
    ({"text": "Pressure about 40 psi; repair did not start and a return visit was completed."}, "scheduled"),
])
def test_wrong_source_page_transformed_quote_and_qualifiers_rejected(changes, message):
    with pytest.raises(ValueError, match=message):
        normalize(changes=changes)


def test_plausible_fabricated_repair_rejected_after_a_valid_inspection_quote():
    excerpt = "Vendor inspected pump P-2."
    original = ai.normalize_facts({"facts": [{"page": 1, "kind": "action",
        "text": excerpt, "quote": excerpt}]}, SOURCE, (1,), PROFILE, PERIOD)[0]
    source = replace(SOURCE, facts=(original,))
    good = ai.normalize_draft(
        {"paragraphs": [{"text": excerpt, "fact_ids": [original.id]}]},
        "activity_summary", (original,), (source,))
    assert good.ai_paragraphs[0].text == excerpt
    with pytest.raises(ValueError, match="unsupported completed work"):
        ai.normalize_draft(
            {"paragraphs": [{"text": "Vendor repaired pump P-2.",
                            "fact_ids": [original.id]}]},
            "activity_summary", (original,), (source,))
    assert source.facts == (original,)


def test_explicitly_negated_completion_remains_valid_after_drafting():
    statement = "no repair was completed."
    original = ai.normalize_facts({"facts": [{"page": 2, "kind": "finding",
        "text": statement, "quote": statement}]},
        SOURCE, (2,), PROFILE, PERIOD)[0]
    source = replace(SOURCE, facts=(original,))
    block = ai.normalize_draft(
        {"paragraphs": [{"text": "No repair was completed.", "fact_ids": [original.id]}]},
        "equipment_issues", (original,), (source,))
    assert block.ai_paragraphs[0].text == "No repair was completed."
    assert source.facts == (original,)


def test_saved_quote_cannot_be_reused_after_page_rewrite_or_source_swap():
    fact, = normalize()
    source = replace(SOURCE, facts=(fact,))
    restored = replace(source, page_texts=(PAGES[0] + " Corrected reading.", PAGES[1]))
    assert restored.sha256 == SOURCE.sha256  # Same original; corrected extracted text.
    with pytest.raises(ValueError, match="source page"):
        ai.normalize_draft(
            {"paragraphs": [{"text": fact.text, "fact_ids": [fact.id]}]},
            "activity_summary", (fact,), (restored,)
        )
    with pytest.raises(ValueError, match="source"):
        ai.normalize_draft(
            {"paragraphs": [{"text": fact.text, "fact_ids": [fact.id]}]},
            "activity_summary", (fact,), (replace(source, sha256="c" * 64),)
        )


def test_legacy_source_fingerprint_remains_identical_to_previous_schema():
    from app.monthly_report_model import EvidenceFact
    old = EvidenceFact("legacy-a55", SOURCE.id, 1, "finding", "Pump inspected.",
                       "Vendor inspected pump P-2.")
    source = replace(SOURCE, facts=(old,))
    historical = asdict(source)
    historical["facts"][0].pop("source_sha256")
    historical["facts"][0].pop("page_sha256")
    # Fields the schema gained later (A43 attachment identity among them) are
    # absent from the previous schema; empty values must not change the digest.
    for key in ("scope_review", "pdf_text_blocks", "financial_source_review",
                "financial_page_reviews", "attachment_parent_sha256", "attachment_index"):
        historical.pop(key, None)
    assert source.fingerprint == hashlib.sha256(
        json.dumps(historical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def test_legacy_human_fact_is_preserved_and_not_upgraded_by_implication():
    from app.monthly_report_model import EvidenceFact
    old = EvidenceFact("legacy-human", SOURCE.id, 1, "finding",
                       "Human reference to inspected pump.", "Vendor inspected pump P-2.")
    assert old.source_sha256 == "" and old.page_sha256 == ""
    source = replace(SOURCE, facts=(old,))
    block = ai.normalize_draft(
        {"paragraphs": [{"text": "Vendor inspected pump P-2.", "fact_ids": [old.id]}]},
        "activity_summary", (old,), (source,)
    )
    assert block.ai_paragraphs[0].fact_ids == (old.id,)
    assert source.facts == (old,)


def test_sensitive_quotes_not_exposed_in_correction_preview():
    assert ai.fact_quote_for_display("Visit per manager@example.com: pressure 40 psi.") == (
        "Visit per [contact omitted]: pressure 40 psi."
    )
    assert "900" not in ai.fact_quote_for_display("Repair quote $900: valve P-2.")
