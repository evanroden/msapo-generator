"""A91 synthetic regressions: issue registers must append, not replace, reviewed cards."""
from dataclasses import asdict, replace
from io import BytesIO
from docx import Document
import pytest
import hashlib
import json

from app import monthly_report_library as library
from app.monthly_report_issue_register import mapped_issue_register
from app.monthly_report_docx import assemble_docx
from app.monthly_report_issues import canonical_issues
from app.monthly_report_model import (
    ReportFollowUp, ReportPeriod, ReportSource, ReportTable, ResolvedBlock,
    default_sections, synthetic_draft, synthetic_profiles,
)
from app.monthly_report_setup import merge_drafts
from app.monthly_report_sources import source_reference


COLUMNS = ("Facility Name", "Issue Summary", "Work Status", "Assigned To",
           "Priority Level", "Date Opened", "Update Due", "Additional", "Additional",
           "Quoted Price")
ROWS = (
    ("Synthetic Site", "Pump vibration", "Open", "Operator A", "High",
     "2026-09-03", "2026-10-01", "Unit A", "Vendor observation", "$125"),
    ("Synthetic Site", "Valve leak", "Closed", "Operator B", "Low",
     "2026-09-07", "2026-09-30", "Unit B", "Needs verification", "$250"),
)


def fixture(columns=COLUMNS, rows=ROWS, *, source_id="register-a", fill="a"):
    profile = synthetic_profiles()[0]
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    source = ReportSource(source_id, "synthetic-register.pdf", fill * 64, ".pdf",
                          facility=profile.facilities[0].title,
                          page_texts=("Synthetic issue register.",))
    block = ResolvedBlock(
        "equipment_issues", "This month",
        extra_tables=(ReportTable(columns, rows, source_reference(source, 1)),),
    )
    return replace(draft, sections=tuple(section for section in default_sections()
                                        if section.key == "issues"),
                   blocks=(block,), sources=(source,))


def test_confident_renamed_columns_and_duplicate_unknown_headings_keep_every_safe_cell():
    draft = fixture()
    review = canonical_issues(draft)
    items = review.follow_ups
    assert len(items) == 2
    assert all(item.status == "ongoing" for item in items)
    assert items[0].text.startswith("Pump vibration")
    assert "Facility Name: Synthetic Site" in items[0].text
    assert "Priority Level: High" in items[0].text
    assert "Date Opened: 2026-09-03" in items[0].text
    assert "Update Due: 2026-10-01" in items[0].text
    assert "Additional: Unit A" in items[0].text
    assert "Additional (2): Vendor observation" in items[0].text
    assert "Quoted Price" not in items[0].text
    assert "$125" not in items[0].text
    assert "Work Status: Closed" in items[1].text
    assert items[1].evidence_note == ""
    assert canonical_issues(review).follow_ups == items
    document = Document(BytesIO(assemble_docx(
        review, acknowledged_fingerprint=review.fingerprint)))
    output = "\\n".join(paragraph.text for paragraph in document.paragraphs)
    assert output.count("Pump vibration") == 1
    assert output.count("Valve leak") == 1
    assert output.count("Vendor observation") == 1
    assert "$125" not in output and "$250" not in output


def test_source_status_and_header_remapping_do_not_recreate_operator_edited_card():
    initial = fixture()
    accepted = canonical_issues(initial)
    first = accepted.follow_ups[0]
    changed = replace(first, text="Operator verified noise still present",
                      status="updated", update="Reinspection required",
                      included=False)
    retained = library.draft_from_dict(json.loads(json.dumps(
        asdict(replace(accepted, follow_ups=(changed, accepted.follow_ups[1]))))))
    revised_columns = ("Site", "Finding", "Current Status", "Owner", "Severity",
                       "Identified Date", "Notes")
    revised_rows = (
        ("Synthetic Site", "Pump vibration", "Pending", "Operator A", "High",
         "2026-09-03", "Unit A"),
        ("Synthetic Site", "Valve leak", "Closed", "Operator B", "Low",
         "2026-09-07", "Unit B"),
    )
    updated_source = replace(initial.sources[0], findings="Reclassified source metadata")
    changed_revision = source_reference(updated_source, 1)
    assert changed_revision != initial.blocks[0].extra_tables[0].reference
    same_source_block = replace(initial.blocks[0], extra_tables=(
        ReportTable(revised_columns, revised_rows, changed_revision),))
    remapped = canonical_issues(replace(retained, blocks=(same_source_block,),
                                        sources=(updated_source,)))
    assert len(remapped.follow_ups) == 2
    assert remapped.follow_ups[0] == changed
    assert remapped.follow_ups[1] == accepted.follow_ups[1]
    assert remapped.follow_ups[0].references == first.references
    assert not remapped.follow_ups[0].included


def test_second_source_appends_without_replacing_manual_card_and_reimport_is_idempotent():
    initial = fixture()
    accepted = canonical_issues(initial)
    manual = ReportFollowUp("manual-issue-A91", "issue",
                            "Manually entered observation", initial.period.key,
                            update="Operator note")
    adjusted = replace(accepted.follow_ups[0], text="Human-edited pump finding",
                       status="updated", update="Monitoring", included=False)
    saved = library.draft_from_dict(json.loads(json.dumps(asdict(
        replace(accepted, follow_ups=(adjusted, accepted.follow_ups[1], manual))))))
    second = fixture(rows=(ROWS[0],), source_id="register-b", fill="b")
    joined = merge_drafts(saved, second)
    joined = replace(joined, sources=(*saved.sources, *second.sources))
    reviewed = canonical_issues(joined)
    assert len(reviewed.follow_ups) == 4
    assert reviewed.follow_ups[:3] == saved.follow_ups
    new = reviewed.follow_ups[-1]
    assert new.key != adjusted.key
    assert new.references == (second.blocks[0].extra_tables[0].reference,)
    readded = replace(reviewed, blocks=(replace(second.blocks[0],
        extra_tables=second.blocks[0].extra_tables * 2),))
    again = canonical_issues(readded)
    assert again.follow_ups == reviewed.follow_ups
    reopened = library.draft_from_dict(json.loads(json.dumps(asdict(again))))
    assert reopened.follow_ups == reviewed.follow_ups


def test_duplicate_source_issue_rows_are_distinct_but_reimport_once_per_source():
    source = fixture(rows=(ROWS[0], ROWS[0]))
    reviewed = canonical_issues(source)
    assert len(reviewed.follow_ups) == 2
    assert reviewed.follow_ups[0].key != reviewed.follow_ups[1].key
    again = canonical_issues(replace(reviewed, blocks=source.blocks))
    assert again.follow_ups == reviewed.follow_ups


def test_ambiguous_or_empty_registers_do_not_guess_roles_or_drop_generic_rows():
    assert mapped_issue_register((), (), "source:none") is None
    assert mapped_issue_register(COLUMNS, (), "source:empty") is None
    assert mapped_issue_register(("Issue", "Issue", "Status", "Owner"),
                                 (("A", "B", "Open", "Operator"),), "source:ambiguous") is None
    fallback = fixture(columns=("Issue", "Issue", "Status", "Owner"),
                       rows=(("A", "B", "Open", "Operator"),))
    result = canonical_issues(fallback)
    assert len(result.follow_ups) == 1
    assert "Issue: A" in result.follow_ups[0].text
    assert "Issue: B" in result.follow_ups[0].text


def test_old_register_row_key_still_protects_saved_review_decisions():
    draft = fixture()
    reference = draft.blocks[0].extra_tables[0].reference
    old_hash = hashlib.sha256(json.dumps(
        ["issue-register-v1", reference, 0, COLUMNS, ROWS[0]],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    saved = ReportFollowUp("follow-" + old_hash, "issue",
                           "Previously reviewed operator correction", draft.period.key,
                           references=(reference,), included=False)
    remapped = canonical_issues(replace(draft, follow_ups=(saved,)))
    assert remapped.follow_ups[0] == saved
    assert len(remapped.follow_ups) == 2


def test_description_missing_is_explicit_not_silently_skipped():
    draft = fixture(rows=(("Synthetic Site", "", "Open", "Operator A", "High",
                           "2026-09-03", "2026-10-01", "Unknown", "Check", ""),))
    result = canonical_issues(draft)
    assert len(result.follow_ups) == 1
    assert "Unresolved issue-register row" in result.follow_ups[0].text
    assert "Assigned To: Operator A" in result.follow_ups[0].text

def test_explicit_duplicate_role_heading_remains_ambiguous_even_when_numbered():
    assert mapped_issue_register(
        ("Issue", "Issue (2)", "Current Status", "Owner"),
        (("A", "B", "Open", "Operator"),),
        "source:role-ambiguous") is None
    assert mapped_issue_register(
        ("Issue 2026", "Status", "Owner"),
        (("A", "Open", "Operator"),),
        "source:year-is-not-a-duplicate-suffix") is None


def test_source_linked_photo_provenance_survives_card_migration():
    draft = fixture()
    source_ref = draft.blocks[0].extra_tables[0].reference
    photo_block = replace(draft.blocks[0], asset_hashes=("synthetic-photo.png",),
                          asset_captions=("Synthetic inspection",),
                          asset_provenance=(("synthetic-photo.png", (source_ref,)),))
    review = canonical_issues(replace(draft, blocks=(photo_block,)))
    assert review.blocks[0].asset_hashes == photo_block.asset_hashes
    assert review.blocks[0].asset_captions == photo_block.asset_captions
    assert review.blocks[0].asset_provenance == photo_block.asset_provenance
    assert review.follow_ups[0].references == (source_ref,)

def test_preexisting_generic_card_is_not_recreated_when_schema_becomes_recognized():
    draft = fixture()
    reference = draft.blocks[0].extra_tables[0].reference
    generic_identity = hashlib.sha256(json.dumps(
        ("issue-table-row-v1", reference, 0, COLUMNS, ROWS[0]),
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    generic_digest = hashlib.sha256(json.dumps(
        (generic_identity, 0), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    prior = ReportFollowUp("follow-" + generic_digest, "issue",
                           "Manually reviewed legacy generic issue", draft.period.key,
                           references=(reference,), status="updated", included=False)
    imported = canonical_issues(replace(draft, follow_ups=(prior,)))
    assert imported.follow_ups[0] == prior
    assert len(imported.follow_ups) == 2
    assert imported.follow_ups[1].text.startswith("Valve leak")

def test_other_month_and_profile_cannot_merge_issue_register_cards():
    saved = canonical_issues(fixture())
    new_source = fixture(source_id="register-other", fill="c")
    with pytest.raises(ValueError, match="same confirmed profile and month"):
        merge_drafts(saved, replace(new_source, period=ReportPeriod(2026, 10)))
    other_profile = replace(new_source.profile, key=new_source.profile.key + "-other")
    with pytest.raises(ValueError, match="same confirmed profile and month"):
        merge_drafts(saved, replace(new_source, profile=other_profile))

def test_distinct_same_page_tables_are_not_dropped_merely_for_equal_cell_values():
    draft = fixture(rows=(ROWS[0],))
    original = draft.blocks[0].extra_tables[0]
    alternative = ReportTable(
        ("Facility", "Finding", "Status", "Owner", "Priority", "Date Reported",
         "Due Date", "External", "External", "Quoted Price"),
        (ROWS[0],), original.reference)
    reviewed = canonical_issues(replace(draft, blocks=(
        replace(draft.blocks[0], extra_tables=(original, alternative)),)))
    assert len(reviewed.follow_ups) == 2
    assert reviewed.follow_ups[0].key != reviewed.follow_ups[1].key
    assert reviewed.follow_ups[0].references == reviewed.follow_ups[1].references


def test_shared_unverified_reference_retains_separate_physical_tables():
    # A shared display reference without a matching uploaded original is not
    # evidence that two physically present issue-register tables are one.
    draft = fixture(rows=(ROWS[0], ROWS[0]))
    table = ReportTable(COLUMNS, (ROWS[0], ROWS[0]), "source:shared")
    block = replace(draft.blocks[0], extra_tables=(table, table))
    source = replace(draft, blocks=(block,), sources=())
    reviewed = canonical_issues(source)
    assert len(reviewed.follow_ups) == 4
    assert len({item.key for item in reviewed.follow_ups}) == 4
    replayed = canonical_issues(replace(reviewed, blocks=(block,)))
    assert replayed.follow_ups == reviewed.follow_ups
