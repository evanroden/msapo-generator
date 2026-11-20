"""Synthetic request-time receipts for optional AI writing choices (A60).

These tests use actual normalization and evidence guards; no network, client
report, paid model response, shared storage or production session is involved.
"""
from dataclasses import replace

import pytest

from app import monthly_report_ai as ai
from app.monthly_report_ai_suggestion_action import (
    SuggestionConflict, accept, capture, finish_receipt, request_receipt)
from app.monthly_report_model import (
    EvidenceFact, ReportPeriod, ReportSource, ResolvedBlock,
    synthetic_draft, synthetic_profiles,
)


def fixture():
    source = ReportSource(
        "synthetic-a60-original", "synthetic-a60.txt", "a" * 64, ".txt",
        page_texts=("Inspected the synthetic pump and replaced two seals on 2026-09-03.",))
    fact = EvidenceFact(
        "synthetic-a60-fact", source.id, 1, "action",
        "Inspected the synthetic pump and replaced two seals.",
        "Inspected the synthetic pump and replaced two seals on 2026-09-03.")
    source = replace(source, facts=(fact,))
    draft = replace(
        synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)),
        sources=(source,))
    block = ResolvedBlock("activity_summary", "This month", text="Prior manual note.")
    suggestion = ai.normalize_draft(
        {"paragraphs": [{"text": fact.text, "fact_ids": [fact.id]}]},
        block.key, (fact,), (source,))
    return draft, block, suggestion


def test_first_action_accept_persists_exact_visible_text_and_preserves_manual_evidence():
    draft, block, proposal = fixture()
    receipt = capture(draft, block, proposal, "synthetic-scope")
    accepted = accept(draft, block, proposal, receipt, "synthetic-scope",
                      (proposal.ai_paragraphs[0].text,))
    assert accepted.text == "Prior manual note.\n- " + proposal.ai_paragraphs[0].text
    assert accepted.ai_paragraphs == proposal.ai_paragraphs
    assert accepted.reviewed
    assert accepted.references and accepted.ai_evidence_fingerprint
    assert draft.sources[0].facts[0].quote in draft.sources[0].page_texts[0]
    # JSON/native model serialization of a saved/reopened block retains choice.
    from app.monthly_report_model import _digest
    assert _digest(accepted) == _digest(replace(accepted))
    assert block.text == "Prior manual note."


def test_request_receipt_is_created_before_slow_read_and_not_rebased_on_late_manual_edit():
    draft, block, proposal = fixture()
    request = request_receipt(draft, block, proposal.key, "synthetic-scope")
    new_manual = replace(block, text="Operator typed while the model was reading.")
    delivered = finish_receipt(request, proposal)
    with pytest.raises(SuggestionConflict, match="section changed"):
        accept(draft, new_manual, proposal, delivered, "synthetic-scope",
               (proposal.ai_paragraphs[0].text,), append=False)
    assert new_manual.text == "Operator typed while the model was reading."


@pytest.mark.parametrize("change", ["source", "other_month", "other_scope", "paragraph", "different_target"])
def test_stale_source_report_or_proposal_is_not_accepted(change):
    draft, block, proposal = fixture()
    receipt = capture(draft, block, proposal, "synthetic-scope")
    scope = "synthetic-scope"
    if change == "source":
        draft = replace(draft, sources=(replace(draft.sources[0],
                      page_texts=("An unrelated updated page.",)),))
    elif change == "other_month":
        draft = replace(draft, period=ReportPeriod(2026, 10))
    elif change == "other_scope":
        scope = "unrelated-session"
    elif change == "paragraph":
        proposal = replace(proposal, text="- Different", ai_paragraphs=(
            replace(proposal.ai_paragraphs[0], text="Different"),))
    elif change == "different_target":
        proposal = replace(proposal, key="improvements")
    with pytest.raises(SuggestionConflict):
        accept(draft, block, proposal, receipt, scope,
               (proposal.ai_paragraphs[0].text,))
    assert block.text == "Prior manual note."


def test_pending_native_input_is_stronger_than_a_matching_old_action():
    draft, block, proposal = fixture()
    with pytest.raises(SuggestionConflict, match="newer manual edit"):
        accept(draft, block, proposal, capture(draft, block, proposal, "scope"),
               "scope", (proposal.ai_paragraphs[0].text,), pending_manual=True)


@pytest.mark.parametrize("text", ["", "   ", "Wrote a $90 quote.", "Inspected 500 synthetic pumps.", "A" * 2001,
                                   "Call 716-555-0199."])
def test_missing_unsupported_sensitive_or_malformed_wording_never_wins(text):
    draft, block, proposal = fixture()
    with pytest.raises(ValueError):
        accept(draft, block, proposal, capture(draft, block, proposal, "scope"),
               "scope", (text,))
    assert block.text == "Prior manual note."


def test_edit_is_a_direct_choice_without_copy_paste_and_duplicate_append_is_rejected():
    draft, block, proposal = fixture()
    edited = "Inspected the synthetic pump and replaced two seals."
    accepted = accept(draft, block, proposal, capture(draft, block, proposal, "scope"),
                      "scope", (edited,), append=False)
    assert accepted.text == "- " + edited
    with pytest.raises(SuggestionConflict, match="already in the report"):
        accept(draft, accepted, proposal, capture(draft, accepted, proposal, "scope"),
               "scope", (edited,))
    assert accepted.reviewed


def test_wrong_paragraph_count_and_unknown_receipt_are_explicit_conflicts():
    draft, block, proposal = fixture()
    receipt = capture(draft, block, proposal, "scope")
    with pytest.raises(ValueError, match="missing paragraphs"):
        accept(draft, block, proposal, receipt, "scope", ())
    with pytest.raises(SuggestionConflict, match="no current revision receipt"):
        accept(draft, block, proposal, None, "scope",
               (proposal.ai_paragraphs[0].text,))


def test_shared_snapshot_reload_equals_the_accepted_visible_choice(monkeypatch, tmp_path):
    from app import monthly_report_library as library

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft, block, suggestion = fixture()
    display = suggestion.ai_paragraphs[0].text
    accepted = accept(draft, block, suggestion,
                      capture(draft, block, suggestion, "synthetic-scope"),
                      "synthetic-scope", (display,))
    # A synthetic report snapshot captures the final normal editor block, not
    # an AI panel/cache object. No original source bytes are rewritten.
    to_save = replace(draft, blocks=(*draft.blocks, accepted))
    library.save_snapshot(to_save, expected_revision=0)
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reopened is not None
    persisted = next(b for b in reopened.draft.blocks if b.key == "activity_summary")
    assert persisted.text == "Prior manual note.\n- " + display
    assert persisted.ai_paragraphs == accepted.ai_paragraphs
    assert persisted.reviewed and persisted.references == accepted.references
    assert reopened.draft.sources == draft.sources
