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


from dataclasses import replace
from hashlib import sha256

import pytest

from app.monthly_report_reconciliation import CandidateFact, reconcile_candidates

MONTH = "2026-10"
CONTRACT = "SYNTHETIC-DEMO"


def fact(file="synthetic-a.csv", **changes):
    source_hash = sha256(file.encode()).hexdigest()
    defaults = dict(source_hash=source_hash, source_id=file, page=1, item=0, row=1,
                    source_date="2026-10-06", source_period=MONTH,
                    contract=CONTRACT, facility="north", section="activity_summary",
                    quote="Repaired demonstration pump seal", value="Repaired demonstration pump seal",
                    typed_value="repair:pump-seal", confidence=1.0,
                    verification="native", claim="completed", actor="vendor",
                    event_id="WO-0007")
    defaults.update(changes)
    return CandidateFact(**defaults)


def plan(*items, **params):
    return reconcile_candidates(tuple(items), contract=CONTRACT,
                                facilities=("north", "south"), period=MONTH, **params)


def test_same_event_in_csv_pdf_docx_combines_all_provenance_once():
    csv = fact("work.csv", row=7)
    pdf = fact("vendor.pdf", page=3, row=0,
               quote="Vendor says repaired demonstration pump seal")
    docx = fact("site.docx", item=14, row=0)
    other = fact("site.docx", item=15, row=0, event_id="WO-0008",
                 value="Replaced synthetic air filter", typed_value="replace:filter")
    result = plan(csv, pdf, docx, other)
    assert not result.conflicts and not result.exceptions
    assert len(result.accepted) == 2
    target = next(entry for entry in result.accepted if entry.fact.event_id == "WO-0007")
    assert {c.source_id for c in (target.fact, *target.supporting)} == {
        "work.csv", "vendor.pdf", "site.docx"}
    assert len(result.rows("activity_summary")) == 2
    # Duplicate ingestion of byte-identical sources must preserve output and
    # avoid doubling original references.
    repeated = plan(csv, pdf, docx, other, csv, pdf, docx, other)
    assert repeated.accepted == result.accepted
    assert len(repeated.duplicates) == 4
    assert repeated.rows("activity_summary") == result.rows("activity_summary")


def test_distinct_dated_visits_and_facilities_never_collapse():
    first = fact()
    later = replace(first, source_hash=sha256(b"later").hexdigest(),
                    source_id="later.pdf", source_date="2026-10-19",
                    quote="Repaired demonstration pump seal on return visit")
    south = fact("south.csv", facility="south")
    result = plan(first, later, south)
    assert len(result.accepted) == 3
    assert not result.duplicates and not result.conflicts


def test_two_conflicting_real_claims_are_held_for_one_explicit_decision():
    first = fact("work.csv")
    second = fact("vendor.pdf", value="Demonstration pump repair incomplete",
                  typed_value="repair:incomplete",
                  quote="Demonstration pump repair incomplete")
    result = plan(first, second)
    assert result.accepted == ()
    assert len(result.conflicts) == 1
    assert {x.source_id for x in (result.conflicts[0].first, result.conflicts[0].second)} == {
        "work.csv", "vendor.pdf"}
    assert not result.rows("activity_summary")


def test_verified_alias_is_opt_in_and_wrong_contract_never_leaks():
    ambiguous = fact("north.xlsx", facility="Demo North")
    wrong_contract = fact("foreign.csv", contract="OTHER-CONTRACT")
    wrong_site = fact("unknown.csv", facility="unmapped-building")
    result = plan(ambiguous, wrong_contract, wrong_site)
    assert not result.accepted
    assert {x.reason for x in result.exceptions} == {
        "unverified_facility", "other_contract"}
    fixed = plan(ambiguous, verified_aliases=(("Demo North", "north"),))
    assert len(fixed.accepted) == 1
    assert fixed.accepted[0].fact.facility == "north"
    assert fixed.accepted[0].fact.source_hash == ambiguous.source_hash
    with pytest.raises(ValueError, match="one explicitly verified"):
        plan(ambiguous, verified_aliases=(("Demo North", "outside"),))


def test_prior_month_carryover_and_standing_default_are_not_current_work():
    previous = fact("september.docx", source_period="2026-09", source_date="2026-09-10")
    standing = fact("capacity.xlsx", claim="standing", scope="standing",
                    source_period="", source_date="", section="capacity",
                    subject_key="north/cooling/unit-1", event_id="",
                    value="150 tons", typed_value=150)
    current = fact("october.docx", claim="reported", actor="unknown", event_id="",
                   section="capacity", subject_key="north/cooling/unit-1",
                   quote="Current unit capacity 145 tons", value="145 tons",
                   typed_value=145)
    result = plan(previous, standing, current)
    assert [item.reason for item in result.exceptions] == ["other_or_unknown_period"]
    assert len(result.accepted) == 2
    assert result.rows("capacity") == ((current.value, (current.provenance,)),)
    assert not result.rows("activity_summary")


def test_missing_date_pending_status_and_model_only_are_exceptions():
    missing = fact("missing.csv", source_date="")
    pending = fact("pending.pdf", quote="Repair pending approval and scheduled for next month")
    uncertain = fact("model.docx", verification="model", confidence=0.99)
    result = plan(missing, pending, uncertain)
    assert not result.accepted
    assert {item.reason for item in result.exceptions} == {
        "completion_unverified", "needs_source_verification"}


def test_unknown_actor_cannot_be_counted_as_enfra_service():
    unclassified = fact("unknown.csv", actor="unknown")
    vendor = fact("vendor.pdf", actor="vendor")
    enfra = fact("enfra.csv", actor="enfra")
    result = plan(unclassified, vendor, enfra)
    assert "completion_unverified" in {x.reason for x in result.exceptions}
    assert len(result.conflicts) == 1
    assert result.accepted == ()


def test_prices_and_sensitive_contacts_never_reach_technical_output():
    priced = fact("proposal.pdf", section="proposals",
                  quote="Quote to replace valve for $5,100",
                  value="Replace valve $5,100", claim="reported")
    contact = fact("contacts.docx", section="activity_summary",
                   quote="Vendor technician contacted test@example.invalid",
                   value="Vendor technician contacted test@example.invalid",
                   claim="reported")
    good = fact("vendor.pdf")
    result = plan(priced, contact, good)
    assert len(result.accepted) == 1
    assert set(x.reason for x in result.exceptions) == {"sensitive_or_priced"}
    assert all("$" not in row[0] and "@" not in row[0]
               for row in (*result.rows("activity_summary"), *result.rows("proposals")))


def test_manual_exclusion_omitted_section_and_protected_event_survive_reentry():
    edited = fact("edited.pdf", event_id="WO-EDIT")
    removed = fact("removed.csv", event_id="WO-REMOVED")
    omitted = fact("omitted.csv", section="proposals", claim="reported")
    accepted = fact("unrelated.pdf")
    result = plan(edited, removed, omitted, accepted,
                  excluded_locators=frozenset({edited.locator, removed.locator}),
                  omitted_sections=frozenset({"proposals"}))
    assert {x.source_id for x in result.protected} == {
        "edited.pdf", "removed.csv", "omitted.csv"}
    assert len(result.accepted) == 1
    assert result.accepted[0].fact.source_id == "unrelated.pdf"
    assert len(plan(edited, protected_keys=frozenset({
        ("event", CONTRACT, "north", "report", "activity_summary",
         "completed", "2026-10-06", "WO-EDIT")
    })).protected) == 1


def test_missing_event_identity_neither_falsely_merges_nor_publishes_repeats():
    first = fact("unknown-one.pdf", event_id="", claim="reported")
    second = fact("unknown-two.docx", event_id="", claim="reported")
    result = plan(first, second)
    assert not result.accepted and not result.duplicates
    assert [x.reason for x in result.exceptions] == [
        "possible_duplicate_needs_identity", "possible_duplicate_needs_identity"]


def test_same_slot_mutable_status_conflict_does_not_overwrite():
    a = fact("capacity-a.csv", claim="reported", actor="unknown",
             event_id="", subject_key="north/unit-1",
             section="capacity", value="145", typed_value=145)
    b = fact("capacity-b.docx", claim="reported", actor="unknown",
             event_id="", subject_key="north/unit-1",
             section="capacity", value="150", typed_value=150)
    result = plan(a, b)
    assert len(result.conflicts) == 1
    assert result.rows("capacity") == ()


def test_malformed_candidate_is_rejected_before_matching():
    with pytest.raises(ValueError, match="SHA-256"):
        fact(source_hash="not-a-sha")
    with pytest.raises(ValueError, match="ISO"):
        fact(source_date="2026-10-6")
    with pytest.raises(ValueError, match="confidence"):
        fact(confidence=1.1)
    with pytest.raises(ValueError, match="Standing defaults"):
        fact(claim="standing", scope="report")


def test_reviewed_table_noop_and_persisted_replay_remain_unchanged(tmp_path, monkeypatch):
    from app import monthly_report_library as library
    from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    period = ReportPeriod(2026, 10)
    library.save_profile(profile, expected_revision=0,
                         actor="Synthetic Editor", confirmed=True)
    initial = synthetic_draft(profile, period)
    reviewed = ResolvedBlock(
        "proposals", "This month",
        rows=(("Demo North", "Synthetic Vendor", "Inspect pump", "Pending"),),
        references=("synthetic-proposal-source",),
        reviewed_fingerprint="approved-by-human")
    initial = replace(initial, blocks=(*initial.blocks, reviewed))
    first = library.save_snapshot(initial, expected_revision=0)
    restored = library.load_snapshot(profile.contract, profile.key, period)
    block = next(b for b in restored.draft.blocks if b.key == "proposals")
    assert block == reviewed

    # There is no document mutation to persist: both paths return the same
    # object, even with rows, approved edits, and source receipts present.
    assert native_update((), "proposals", block) is block
    read, pages = reader_update((), "proposals", {"items": []}, block)
    assert read is block and pages == {}
    assert restored.draft.fingerprint == initial.fingerprint
    assert library.load_snapshot(profile.contract, profile.key, period).revision == first.revision
