"""Native completed-work suggestions must not truncate wrapped source qualifiers.

The normal reviewed Activity narrative retains the full source event, including
negative outcomes; this separate automatic completed-action list may include
only a safe, complete positive claim from the exact selected page.

All files, sites and source facts here are synthetic.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, SectionSpec, synthetic_profiles,
)
from app.monthly_report_structured_uploads import native_update
from test_monthly_report_activity_wrap_integrity import ingest_lines
from conftest import requires_libreoffice


def report_source(*pages, selected=None):
    return ReportSource(
        "synthetic-pdf", "synthetic-service-report.pdf", "a" * 64, ".pdf",
        page_texts=tuple(pages),
        selected_pages=tuple(range(1, len(pages) + 1)) if selected is None else selected,
        classification="Vendor service",
    )


@pytest.mark.parametrize("opening,tail", (
    ("Inspected pump P-1 and confirmed it", "did not start."),
    ("Inspected valve IV-8 and verified it", "would not close."),
    ("Replaced a controller but the unit was", "not yet returned to service."),
    ("Completed inspection of fan F-3 but", "the drive failed."),
    ("Repaired pump P-1 and", "the unit remains locked out."),
))
def test_wrapped_negative_vendor_event_never_becomes_positive_completed_action(opening, tail):
    source = report_source("Service report\n" + opening + "\n" + tail)
    assert sources.native_action_lines(source) == ()
    after = sources.suggest_facts(source, synthetic_profiles()[0])
    assert after.actions == ""
    # An old, truncated suggestion must not keep a stale "supported" citation
    # on a valid selected page after this source-corrected classification.
    old = replace(after, actions=opening)
    accepted, needs_review = sources.action_evidence(old)
    assert accepted == ()
    assert needs_review == (opening,)
    assert source.page_texts == after.page_texts


@pytest.mark.parametrize("opening,tail", (
    ("Replaced filter F-1 and confirmed the", "unit returned to service."),
    ("Inspected the pump and", "confirmed the seal was intact."),
    ("Completed inspection of valve IV-1 but", "the return line was clean."),
))
def test_wrapped_positive_event_is_preserved_whole_with_exact_page(opening, tail):
    source = report_source("Maintenance report\n" + opening + "\n" + tail)
    event = opening + " " + tail
    assert sources.native_action_lines(source) == ((event, (1,)),)
    suggested = sources.suggest_facts(source, synthetic_profiles()[0])
    assert suggested.actions == event
    accepted, unresolved = sources.action_evidence(suggested)
    assert accepted == ((event, (1,)),)
    assert unresolved == ()


def test_independent_events_and_bullets_are_never_merged_or_duplicated():
    source = report_source(
        "Service report\n"
        "- Inspected the condenser drive belt.\n"
        "- Replaced filter F-2.\n"
        "Repaired isolation valve IV-9."
    )
    expected = (("- Inspected the condenser drive belt.", (1,)),
                ("- Replaced filter F-2.", (1,)),
                ("Repaired isolation valve IV-9.", (1,)))
    assert sources.native_action_lines(source) == expected
    assert sources.suggest_facts(source, synthetic_profiles()[0]).actions == "\n".join(x[0] for x in expected)


def test_same_completed_event_on_multiple_selected_pages_retains_distinct_page_origins():
    source = report_source(
        "Service report\nInspected pump P-1.",
        "Service report\nRepaired valve V-2.",
        "Service report\nInspected pump P-1.",
        selected=(1, 3),
    )
    assert sources.native_action_lines(source) == (("Inspected pump P-1.", (1, 3)),)
    accepted, unresolved = sources.action_evidence(
        replace(source, actions="Inspected pump P-1.\nRepaired valve V-2."))
    assert accepted == (("Inspected pump P-1.", (1, 3)),)
    assert unresolved == ("Repaired valve V-2.",)


def test_priced_and_unselected_pages_do_not_authorize_a_completion():
    source = report_source(
        "Service report\nReplaced filter F-3.\nInvoice: $500",
        "Service report\nInspected safe valve IV-3.",
        "Service report\nInspected excluded valve IV-4.",
        selected=(1, 2),
    )
    assert sources.native_action_lines(source) == (
        ("Inspected safe valve IV-3.", (2,)),)
    assert "excluded" not in sources.suggest_facts(source, synthetic_profiles()[0]).actions


def test_existing_labeled_native_vendor_spans_are_not_concatenated_by_fallback():
    from app.monthly_report_vendor_passages import VendorPassage
    source = report_source("Actions: Inspected pump P-1.\nActions: Replaced filter F-3.")
    # For a verified label+block path the precise source spans already form
    # independent occurrences. Do not join them using raw PDF wrap rules.
    labeled = {1: ((VendorPassage(1, 9, 29, "actions", "Inspected pump P-1."),
                    VendorPassage(1, 39, 59, "actions", "Replaced filter F-3.")), False)}
    assert sources.native_action_lines(source, passage_pages=labeled) == (
        ("Inspected pump P-1.", (1,)), ("Replaced filter F-3.", (1,)))


def test_ingested_unlabeled_pdf_retains_complete_negative_narrative_and_original(
        monkeypatch, tmp_path):
    profile, content = ingest_lines(monkeypatch, tmp_path, (
        "Inspected pump P-1 and confirmed it", "did not start."))
    original = sources.source_bytes(profile, content.source)
    assert sources.native_action_lines(content.source) == ()
    assert not content.source.actions, "No positive completion should be suggested."
    block = native_update((content,), "activity_summary")
    assert "Inspected pump P-1 and confirmed it did not start." in block.text
    assert block.text.count("did not start.") == 1
    assert sources.source_bytes(profile, content.source) == original
    assert not content.source.facts, "Native input cannot invent a model fact."


@requires_libreoffice
def test_wrapped_negative_event_survives_saved_word_and_pdf_without_false_action(
        monkeypatch, tmp_path):
    from app import monthly_report_library as library
    from app.monthly_report_docx import generate_report
    import pymupdf as fitz

    profile, content = ingest_lines(monkeypatch, tmp_path, (
        "Inspected pump P-1 and confirmed it", "did not start."))
    assert not content.source.actions
    original = sources.source_bytes(profile, content.source)
    block = native_update((content,), "activity_summary")
    draft = ReportDraft(
        profile, ReportPeriod(2026, 9), "Synthetic Reviewer",
        (SectionSpec("activity", "2", "Monthly Activity Summary",
                     (BlockSpec("activity_summary", "rich_text"),)),),
        (block,), sources=(content.source,),
    )
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Reviewer")
    reopened = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert reopened.revision == saved.revision and reopened.draft == draft
    package = generate_report(reopened.draft,
                              acknowledged_fingerprint=reopened.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    expected = "Inspected pump P-1 and confirmed it did not start."
    word = "\n".join(p.text for p in Document(BytesIO(package.docx)).paragraphs)
    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        pdf_text = " ".join(" ".join(page.get_text().split()) for page in pdf)
    assert word.count(expected) == pdf_text.count(expected) == 1
    assert sources.source_bytes(profile, content.source) == original
