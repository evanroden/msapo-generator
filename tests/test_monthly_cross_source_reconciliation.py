"""Synthetic A10 regression: reviewed no-op source replays must be unchanged.

Refs #270, #277, #281, #287, #297. No real site or report data.
"""
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_structured_uploads import native_update, reader_update


def test_native_reimport_of_no_new_evidence_preserves_exact_approved_block():
    saved = ResolvedBlock("activity_summary", "This month",
                          text="Manually corrected synthetic pump note.",
                          references=("source:page:approved",),
                          reviewed_fingerprint="approved-human-edit")
    assert native_update((), "activity_summary", saved) is saved


def test_reader_replay_without_new_evidence_preserves_exact_approved_block():
    saved = ResolvedBlock("activity_summary", "This month",
                          text="Manually corrected synthetic pump note.",
                          references=("source:page:approved",),
                          reviewed_fingerprint="approved-human-edit")
    updated, pages = reader_update((), "activity_summary", {"items": []}, saved)
    assert updated is saved
    assert pages == {}
