"""A source quote must match whole words/numbers, not a token prefix.

Synthetic examples cover equipment labels, truncated meter readings, and
ordinary valid excerpts. The fact reader is deterministic; no paid/external
reader, source rewrite or implicit review approval occurs.
"""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest

from app import monthly_report_ai as ai
from app import monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, ReportSource, synthetic_profiles


PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)


def source(*pages):
    return ReportSource(
        "synthetic-quote-source", "synthetic-source.pdf", "c" * 64, ".pdf",
        page_texts=tuple(pages), selected_pages=tuple(range(1, len(pages) + 1)),
    )


def read(source_value, quote, *, text=None, page=1):
    return ai.normalize_facts(
        {"facts": [{"page": page, "kind": "action",
                    "text": text if text is not None else quote, "quote": quote}]},
        source_value, tuple(range(1, len(source_value.page_texts) + 1)), PROFILE, PERIOD)


@pytest.mark.parametrize("page,quote", (
    ("Replaced filter F-20 during service.", "Replaced filter F-2"),
    ("The motor in AHU-12 was inspected.", "The motor in AHU-1"),
    ("Pressure measured 400psi at the pump.", "Pressure measured 40"),
    ("Pressure measured 40.0 psi at the pump.", "Pressure measured 40"),
    ("Energy use was 1,200,000 kWh.", "Energy use was 1,200"),
    ("Measured -40C at the outlet.", "40"),
    ("Inspected valve V-4-A during service.", "Inspected valve V-4"),
    ("Inspected pump P-22 and restarted.", "Inspected pump P-2"),
    ("Only full-page label 1234 is present.", "123"),
    ("Calibration record includes part R410A.", "R410"),
))
def test_partial_source_identifier_or_numeric_prefix_is_not_a_valid_fact_quote(page, quote):
    original = source(page)
    # Old normalization accepted these quotes because all match a substring
    # and the proposed facts' quantities match their own truncated quotes.
    assert " ".join(quote.split()).casefold() in " ".join(page.split()).casefold()
    with pytest.raises(ValueError, match="evidence quote was not found on its page"):
        read(original, quote)
    assert original.page_texts == (page,) and original.facts == ()


@pytest.mark.parametrize("page,quote", (
    ("Inspected filter F-2 for damage.", "Inspected filter F-2"),
    ("The motor in AHU-1 was inspected.", "The motor in AHU-1"),
    ("Pressure measured 40psi.", "Pressure measured 40psi"),
    ("Energy use was 1,200 kWh.", "Energy use was 1,200"),
    ("The feed pump was stopped by an operator.", "feed pump was"),
    ("Inspected pump P-2; checked valve V-3.", "Inspected pump P-2"),
    ("THE TEAM INSPECTED \n FILTER F-2.", "team inspected filter F-2"),
    ("Technician checked valve V-2, then signed.", "valve V-2"),
))
def test_whole_valid_excerpt_is_accepted_with_same_source_page(page, quote):
    original = source(page)
    facts = read(original, quote)
    assert len(facts) == 1
    fact, = facts
    assert fact.source_id == original.id
    assert fact.page == 1
    assert fact.quote == quote
    assert fact.text == quote
    assert not fact.flags
    assert original.facts == ()
    assert original.page_texts == (page,)


def test_later_valid_quote_on_same_page_survives_earlier_prefix_collision():
    original = source(
        "Replaced filter F-20 on first call. Replaced filter F-2 on second call.")
    facts = read(original, "Replaced filter F-2")
    assert len(facts) == 1 and facts[0].quote == "Replaced filter F-2"
    assert facts[0].page == 1


def test_page_evidence_cannot_substitute_an_identical_prefix_on_wrong_page():
    original = source("Inspected fan EF-20.", "Inspected fan EF-2.")
    with pytest.raises(ValueError, match="evidence quote"):
        read(original, "Inspected fan EF-2", page=1)
    accepted = read(original, "Inspected fan EF-2", page=2)
    assert accepted[0].page == 2
    assert accepted[0].source_id == original.id
    assert original.facts == ()


@pytest.mark.parametrize("source_text,quote", (
    ("Pressure measured +40psi.", "40"),
    ("Valve rated 2.5bar.", "Valve rated 2"),
    ("Unit V-2/3 was offline.", "Unit V-2"),
))
def test_numeric_sign_decimal_and_compound_token_are_not_silent_support(source_text, quote):
    with pytest.raises(ValueError, match="evidence quote"):
        read(source(source_text), quote)


def test_existing_price_and_fact_page_gates_remain_unchanged():
    original = source("Inspected pump P-1. Invoice: $900.")
    with pytest.raises(ValueError, match="pricing"):
        read(original, "Inspected pump P-1", text="Invoice: $900")
    with pytest.raises(ValueError, match="page that was not read"):
        ai.normalize_facts(
            {"facts": [{"page": 3, "kind": "action",
                        "text": "Inspected pump P-1", "quote": "Inspected pump P-1"}]},
            original, (1,), PROFILE, PERIOD)
    assert original.page_texts == ("Inspected pump P-1. Invoice: $900.",)


def test_synthetic_pdf_import_rejection_preserves_source_bytes_and_other_report_notes(
        monkeypatch, tmp_path):
    from app.monthly_report_library import save_snapshot, load_snapshot
    from app.monthly_report_model import BlockSpec, ReportDraft, ResolvedBlock, SectionSpec

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with fitz.open() as document:
        for paragraph in ("Inspected pump P-20 on September 18, 2026.",
                          "Inspected pump P-2 on September 18, 2026."):
            page = document.new_page()
            page.insert_text((45, 55), paragraph, fontsize=11)
        raw = document.tobytes()
    content, _ = sources.ingest(PROFILE, "synthetic-quote-pages.pdf", raw)
    saved_bytes = sources.source_bytes(PROFILE, content.source)
    assert saved_bytes == raw

    with pytest.raises(ValueError, match="evidence quote"):
        read(content.source, "Inspected pump P-2", page=1)
    valid = read(content.source, "Inspected pump P-2", page=2)
    assert valid[0].page == 2

    manual = ResolvedBlock(
        "activity_summary", "This month",
        text="Independent human-authored equipment note remains unchanged.",
    )
    current_source = replace(content.source, facts=valid)
    draft = ReportDraft(
        PROFILE, PERIOD, "Synthetic Reviewer",
        (SectionSpec("activity", "2", "Monthly Activity Summary",
                     (BlockSpec("activity_summary", "rich_text"),)),),
        (manual,), sources=(current_source,),
    )
    checkpoint = save_snapshot(draft, expected_revision=0,
                               entered_editor="Synthetic Reviewer")
    opened = load_snapshot(PROFILE.contract, PROFILE.key, PERIOD)
    assert opened.revision == checkpoint.revision
    assert opened.draft == draft
    assert opened.draft.blocks[0] == manual
    assert opened.draft.sources[0].facts == valid
    assert sources.source_bytes(PROFILE, content.source) == raw
