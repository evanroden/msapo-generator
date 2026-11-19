"""A83: synthetic month rollover must not revoke a human omission.

AUTH01 (older same-site report), AUTH02 (other site, same contract), and
AUTH03 (unfinished correct month) are isolated model/storage controls.
They are not genuine client imports, served-browser journeys, or live exports.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document

from app import monthly_report_library as library
from app.monthly_report_docx import assemble_docx
from app.monthly_report_followups import confirmation, problems, seed_followups
from app.monthly_report_model import (
    ReportDraft, ReportFollowUp, ReportPeriod, ReportSource, ReportTable,
    ResolvedBlock, default_sections, synthetic_draft, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft
from app.monthly_report_sources import source_reference
from app.monthly_report_start import design_seed, latest_saved_draft


DECEMBER = ReportPeriod(2026, 12)
JANUARY = ReportPeriod(2027, 1)
FEBRUARY = ReportPeriod(2027, 2)


def _fixture():
    """Invented names and dates; no real facility, personnel, or source bytes."""
    source = ReportSource(
        "a83-december-evidence", "synthetic-december-note.txt", "e" * 64, ".txt",
        service_date="2026-12-17", page_texts=("December 17: observed only; repair pending.",),
        selected_pages=(1,),
    )
    proof = source_reference(source, 1)
    old = synthetic_draft(synthetic_profiles()[0], DECEMBER)
    old = replace(old, blocks=(
        ResolvedBlock("contact_matrix", "This month",
                      rows=(("Synthetic Manager", "555-0100"),)),
        ResolvedBlock("thermal_capacity", "This month",
                      extra_tables=(ReportTable(("Asset", "Capacity"), (("Synthetic Plant", "12 MW"),)),)),
        ResolvedBlock("activity_summary", "This month",
                      text="December synthetic inspection completed."),
        ResolvedBlock("vendor_reports", "This month",
                      text="December vendor visit; not an ENFRA technician service call."),
        ResolvedBlock("training_summary", "This month",
                      extra_tables=(ReportTable(("Course", "Completed"), (("Synthetic Fire Safety", "2026-12-12"),),
                                                "historical-training"),)),
        ResolvedBlock("equipment_issues", "Omit", text="Excluded prior issue statement."),
        ResolvedBlock("proposals", "Omit", text="Excluded prior proposal statement."),
    ), sources=(source,), follow_ups=(
        ReportFollowUp("issue-hidden", "issue", "Synthetic motor vibration", DECEMBER.key,
                       status="updated", update="December 17: inspection only",
                       update_period=DECEMBER.key, references=(proof,), included=False),
        ReportFollowUp("proposal-hidden", "proposal", "Synthetic replacement estimate",
                       DECEMBER.key, status="pending", included=False),
        ReportFollowUp("issue-visible", "issue", "Synthetic valve remains under observation",
                       DECEMBER.key, status="ongoing"),
    ))
    return old, source, proof


def _followup_map(draft):
    return {item.key: item for item in draft.follow_ups}


def test_auth01_prior_month_clears_activity_but_retains_standing_and_omission_receipts():
    previous, source, proof = _fixture()
    baseline = previous.fingerprint
    january = new_month_draft(previous, JANUARY)
    entries = _followup_map(january)
    assert JanuarySafety(entries, source, proof)
    for key in ("contact_matrix", "thermal_capacity"):
        assert next(b for b in january.blocks if b.key == key) == next(
            b for b in previous.blocks if b.key == key)
    for key in ("activity_summary", "vendor_reports", "training_summary"):
        current = next(b for b in january.blocks if b.key == key)
        assert not current.text and not current.rows
        assert not any(table.rows for table in current.extra_tables)
    assert previous.fingerprint == baseline
    assert next(b for b in previous.blocks if b.key == "training_summary").extra_tables[0].rows


def JanuarySafety(entries, source, proof):
    """Assert the exact inherited decisions, source receipt and period."""
    assert set(entries) == {"issue-hidden", "proposal-hidden", "issue-visible"}
    assert entries["issue-hidden"].included is False
    assert entries["proposal-hidden"].included is False
    assert entries["issue-visible"].included is True
    assert entries["issue-hidden"].status == "updated"
    assert entries["issue-hidden"].update == "December 17: inspection only"
    assert entries["issue-hidden"].update_period == DECEMBER.key
    assert entries["issue-hidden"].references == (proof,)
    assert entries["issue-hidden"].reviewed_fingerprint == ""
    return True



def test_repeated_source_claim_is_not_reintroduced_as_included_after_omission():
    previous, _, _ = _fixture()
    january = new_month_draft(previous, JANUARY)
    # Exclusion controls output, not an unconfirmed proposal's decision receipt.
    assert any("Confirm this proposal" in message for message in
               problems(_followup_map(january)["proposal-hidden"], january))
    # Reprocessed identical text must match its existing omission receipt,
    # not create a second printable proposal with a new generated key.
    replay = replace(january, blocks=tuple(
        replace(block, source="This month", text="Synthetic replacement estimate")
        if block.key == "proposals" else block for block in january.blocks))
    followups = seed_followups(replay)
    proposals = [item for item in followups if item.category == "proposal"]
    assert [(item.key, item.included) for item in proposals] == [("proposal-hidden", False)]

def test_auth01_two_successive_saves_reloads_and_second_rollover_preserve_old_snapshot(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    previous, source, proof = _fixture()
    library.save_profile(previous.profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    old_saved = library.save_snapshot(previous, expected_revision=0, entered_editor="Synthetic Editor")
    january = new_month_draft(old_saved.draft, JANUARY)
    first = library.save_snapshot(january, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(previous.profile.contract, previous.profile.key, JANUARY)
    assert reopened.draft == first.draft
    amended = replace(reopened.draft, prepared_by="Synthetic Second Editor")
    second = library.save_snapshot(amended, expected_revision=first.revision,
                                   entered_editor="Synthetic Second Editor")
    assert second.revision == first.revision + 1
    assert library.load_snapshot(previous.profile.contract, previous.profile.key, JANUARY).draft == amended
    assert library.load_snapshot_version(
        previous.profile.contract, previous.profile.key, JANUARY, first.revision).draft == january
    assert library.load_snapshot(previous.profile.contract, previous.profile.key, DECEMBER).draft == previous
    february = new_month_draft(second.draft, FEBRUARY)
    JanuarySafety(_followup_map(february), source, proof)
    assert february.sources == (source,)
    assert february.sources[0].service_date == "2026-12-17"
    assert february.follow_ups[0].carried_from == DECEMBER.key


def test_auth02_other_site_same_contract_gets_design_only_not_prior_source_values(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    previous, _, _ = _fixture()
    # Generic demo_* section slots are not a persisted editable design schema.
    # Use standard specifications for the cross-site design-only check.
    previous = replace(previous, sections=default_sections())
    source_state = library.save_profile(previous.profile, expected_revision=0,
                                        actor="Synthetic Editor", confirmed=True)
    library.save_snapshot(previous, expected_revision=0, entered_editor="Synthetic Editor")
    target = replace(synthetic_profiles()[1], key="a83-independent-site-group")
    assert target.contract == previous.profile.contract
    assert {f.key for f in target.facilities} != {f.key for f in previous.profile.facilities}
    seeded, _ = design_seed(target, JANUARY, "Synthetic Target Editor", source_state)
    assert seeded.profile.facilities == target.facilities
    assert seeded.period == JANUARY and seeded.follow_ups == ()
    all_blocks = " ".join(str(block) for block in seeded.blocks)
    for foreign in ("Synthetic Manager", "Synthetic Plant", "motor vibration",
                    "December synthetic inspection", "Synthetic Fire Safety"):
        assert foreign not in all_blocks
    assert all(not block.rows for block in seeded.blocks)


def test_auth03_half_finished_correct_month_is_reopened_not_rolled_over(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    previous, _, _ = _fixture()
    library.save_profile(previous.profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    library.save_snapshot(previous, expected_revision=0, entered_editor="Synthetic Editor")
    partial = replace(synthetic_draft(previous.profile, JANUARY), blocks=(
        ResolvedBlock("activity_summary", "This month",
                      text="January inspection scheduled; completion not established."),
        ResolvedBlock("contact_matrix", "This month",
                      rows=(("Synthetic January Contact", "555-0111"),)),
    ), omitted_sections=("training",))
    library.save_snapshot(partial, expected_revision=0, entered_editor="Synthetic Editor")
    picked = latest_saved_draft(previous.profile.contract, previous.profile.key, JANUARY)
    assert picked == partial
    assert new_month_draft(picked, JANUARY) == partial
    assert picked.omitted_sections == ("training",)
    assert "scheduled" in picked.blocks[0].text and "completed" not in picked.blocks[0].text
    assert library.load_snapshot(previous.profile.contract, previous.profile.key, DECEMBER).draft == previous


def test_omitted_issue_and_proposal_do_not_reappear_in_native_word_export():
    previous, _, _ = _fixture()
    minimal = replace(previous,
        sections=tuple(s for s in default_sections() if s.key in ("issues", "proposals")),
        blocks=(ResolvedBlock("equipment_issues", "This month"),
                ResolvedBlock("proposals", "This month")),
        sources=(),
        follow_ups=tuple(replace(item, references=(),
            evidence_note="Synthetic prior inspection memo" if item.key == "issue-hidden"
            else item.evidence_note) for item in previous.follow_ups))
    current = new_month_draft(minimal, JANUARY)
    assert not _followup_map(current)["issue-hidden"].included
    assert not _followup_map(current)["proposal-hidden"].included
    approved = replace(current, follow_ups=tuple(
        replace(item, reviewed_fingerprint=confirmation(item, JANUARY))
        if item.included else item for item in current.follow_ups))
    output = assemble_docx(approved, acknowledged_fingerprint=approved.fingerprint)
    document = Document(BytesIO(output))
    text = "\n".join([*(p.text for p in document.paragraphs),
                      *(cell.text for table in document.tables for row in table.rows for cell in row.cells)])
    assert "Synthetic valve remains under observation" in text
    assert "Synthetic motor vibration" not in text
    assert "Synthetic replacement estimate" not in text
    assert "December 17: inspection only" not in text
