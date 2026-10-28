"""AI source-quote monetary privacy: reject new and quarantine legacy facts.

These are synthetic inputs; no external model, paid reader, real customer
document or manual contact information is accessed or rewritten.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json

from docx import Document
import pymupdf as fitz
import pytest

from app import monthly_report_ai as ai
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import (
    BlockSpec, EvidenceFact, ReportDraft, ReportPeriod, ReportSource,
    ResolvedBlock, SectionSpec, synthetic_profiles,
)


PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)
SAFE = "Inspected pump P-1 and recorded 480 V and 40 psi."
PRICED = "Invoice amount: $500. Inspected pump P-1."


def source(*pages):
    return ReportSource(
        "synthetic-priced-fact", "synthetic-service.pdf", "a" * 64, ".pdf",
        page_texts=tuple(pages), selected_pages=tuple(range(1, len(pages)+1)),
    )


def fact(quote, *, page=1, wording="Inspected pump P-1."):
    return {"facts": [{
        "page": page, "kind": "action", "text": wording, "quote": quote,
    }]}


@pytest.mark.parametrize("page,quote", (
    (PRICED, PRICED),
    ("Repair estimate: $6,875. Inspected pump P-1.",
     "Repair estimate: $6,875. Inspected pump P-1."),
    ("Not-to-exceed amount: $29,450. Replaced valve V-3.",
     "Not-to-exceed amount: $29,450. Replaced valve V-3."),
    ("Inspected pump P-1; Quote amount: $18,675.50",
     "Inspected pump P-1; Quote amount: $18,675.50"),
))
def test_new_price_free_fact_cannot_reference_price_bearing_evidence_quote(page, quote):
    original = source(page)
    assert ai.contains_price(quote), "Test must actually exercise the monetary policy."
    with pytest.raises(ValueError, match="evidence quote contains pricing"):
        ai.normalize_facts(fact(quote), original, (1,), PROFILE, PERIOD)
    assert original.facts == ()
    assert original.page_texts == (page,)


def test_technical_quote_has_quantities_but_no_money_and_is_still_accepted():
    original = source(SAFE)
    assert not ai.contains_price(SAFE)
    accepted = ai.normalize_facts(
        fact(SAFE, wording=SAFE), original, (1,), PROFILE, PERIOD)
    assert len(accepted) == 1
    assert accepted[0].text == accepted[0].quote == SAFE
    assert accepted[0].source_id == original.id and accepted[0].page == 1


def test_existing_fact_text_pricing_error_and_number_guard_do_not_change():
    original = source("Inspected pump P-1 with pressure of 40 psi.")
    with pytest.raises(ValueError, match="A suggested fact included pricing or unsupported numbers"):
        ai.normalize_facts(fact("Inspected pump P-1",
                                wording="Invoice amount: $500."), original,
                           (1,), PROFILE, PERIOD)
    with pytest.raises(ValueError, match="A suggested fact included pricing or unsupported numbers"):
        ai.normalize_facts(fact("Inspected pump P-1",
                                wording="Inspected pump P-1 at 400 psi."), original,
                           (1,), PROFILE, PERIOD)


def legacy_fact(src, quote, page=1, *, kind="action", suffix="legacy"):
    return EvidenceFact("fact-synthetic-" + suffix, src.id, page, kind,
                        "Inspected pump P-1.", quote)


def test_only_price_free_historical_facts_reach_drafting_prompt_and_originals_are_untouched():
    src = source(PRICED, SAFE)
    priced = legacy_fact(src, PRICED)
    clean = ai.normalize_facts(
        fact(SAFE, page=2, wording=SAFE), src, (2,), PROFILE, PERIOD)[0]
    old = replace(src, facts=(priced, clean))
    before = old
    key, content, facts = ai.drafting_request(
        "activity_summary", (old,), PERIOD)
    assert key and len(content) == 1
    assert facts == (clean,)
    encoded = content[0]["text"].split("\n")[-1]
    payload = json.loads(encoded)
    assert payload["facts"] == [vars(clean)]
    assert priced.id not in encoded
    assert "$500" not in encoded and "Invoice amount" not in encoded
    assert old == before and old.facts == (priced, clean)
    # Cached responses can cite only the facts supplied to this request.
    block = ai.normalize_draft(
        {"paragraphs": [{"text": "Inspected pump P-1 at 480 V.",
                         "fact_ids": [clean.id]}]},
        "activity_summary", facts, (old,))
    assert block.ai_paragraphs[0].fact_ids == (clean.id,)
    assert not any(priced.id in p.fact_ids for p in block.ai_paragraphs)


def test_only_historical_priced_facts_fail_before_any_drafting_payload_exists():
    src = source(PRICED)
    old = replace(src, facts=(legacy_fact(src, PRICED),))
    with pytest.raises(ValueError, match="All available facts.*contain pricing"):
        ai.drafting_request("activity_summary", (old,), PERIOD)
    assert old.facts[0].quote == PRICED


def test_cached_model_paragraph_citing_historical_priced_fact_is_not_accepted():
    src = source(PRICED)
    priced = legacy_fact(src, PRICED)
    old = replace(src, facts=(priced,))
    response = {"paragraphs": [
        {"text": "Inspected pump P-1.", "fact_ids": [priced.id]}
    ]}
    with pytest.raises(ValueError, match="cited fact or source quote contains pricing"):
        ai.normalize_draft(response, "activity_summary", (priced,), (old,))
    assert old.facts == (priced,)


def test_priced_quote_in_unrelated_kind_is_not_sent_to_this_destination():
    src = source(PRICED, SAFE)
    priced = legacy_fact(src, PRICED, kind="proposal", suffix="proposal")
    clean = ai.normalize_facts(fact(SAFE, page=2, wording=SAFE),
                               src, (2,), PROFILE, PERIOD)[0]
    stored = replace(src, facts=(priced, clean))
    _, content, facts = ai.drafting_request("activity_summary", (stored,), PERIOD)
    assert facts == (clean,)
    assert "$500" not in content[0]["text"]


def test_imported_pdf_and_manual_report_remain_byte_identical_with_legacy_fact_filtered(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with fitz.open() as pdf:
        for value in (PRICED, SAFE):
            page = pdf.new_page()
            page.insert_text((48, 75), value, fontsize=11)
        raw = pdf.tobytes()
    content, _ = sources.ingest(PROFILE, "synthetic-monetary-source.pdf", raw)
    assert sources.source_bytes(PROFILE, content.source) == raw
    assert content.source.sha256 == sha256(raw).hexdigest()
    assert len(content.source.page_texts) == 2

    with pytest.raises(ValueError, match="evidence quote contains pricing"):
        ai.normalize_facts(fact(PRICED), content.source,
                           (1,), PROFILE, PERIOD)
    allowed = ai.normalize_facts(fact(SAFE, page=2, wording=SAFE),
                                 content.source, (2,), PROFILE, PERIOD)[0]
    old = legacy_fact(content.source, PRICED)
    saved_source = replace(content.source, facts=(old, allowed))
    manual = ResolvedBlock(
        "activity_summary", "This month",
        text="Human-maintained operational summary; needs further review.")
    draft = ReportDraft(
        PROFILE, PERIOD, "Synthetic Reviewer",
        (SectionSpec("activity", "2", "Monthly Activity Summary",
                     (BlockSpec("activity_summary", "rich_text"),)),),
        (manual,), sources=(saved_source,),
    )
    saved = library.save_snapshot(draft, expected_revision=0,
                                  entered_editor=draft.prepared_by)
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD)
    assert reopened.revision == saved.revision and reopened.draft == draft
    assert sources.source_bytes(PROFILE, content.source) == raw
    _, outgoing, facts = ai.drafting_request(
        "activity_summary", reopened.draft.sources, PERIOD)
    assert facts == (allowed,)
    assert "$500" not in outgoing[0]["text"]
    assert reopened.draft.sources[0].facts == (old, allowed)
    assert reopened.draft.blocks[0] == manual

    from app.monthly_report_docx import _build_docx
    word = Document(BytesIO(_build_docx(reopened.draft)))
    text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    assert manual.text in text
    assert "Invoice amount" not in text and "$500" not in text
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == saved
