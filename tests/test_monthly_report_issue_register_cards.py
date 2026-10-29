"""No silent resolution, row loss or reimport duplication of issue registers."""
from dataclasses import asdict, replace
from io import BytesIO
import json

import pytest

from docx import Document

from app import monthly_report_library as library
from app.monthly_report_docx import assemble_docx
from app.monthly_report_issue_register import mapped_issue_register
from app.monthly_report_issues import canonical_issues, issue_key
from app.monthly_report_followups import problems, seed_followups
from app.monthly_report_model import (
    ReportFollowUp, ReportPeriod, ReportSource, ReportTable, ResolvedBlock,
    default_sections, synthetic_draft, synthetic_profiles,
)
from app.monthly_report_setup import merge_drafts
from app.monthly_report_sources import source_reference


COLUMNS = ("Issue", "Owner", "Reported Date", "Status", "Action", "Client Detail")
ROWS = (
    ("Chiller vibration", "Synthetic Engineer", "2026-09-03", "Open", "Inspect bearings", "Zone A"),
    ("Valve repaired", "Synthetic Tech", "2026-09-16", "Closed", "Verify repair", "Zone B"),
)


def report():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    source = ReportSource(
        "register-source", "synthetic-issue-register.pdf", "f" * 64, ".pdf",
        facility=synthetic_profiles()[0].facilities[0].title,
        page_texts=("Synthetic issue register with two rows.",),
    )
    block = ResolvedBlock("equipment_issues", "Last month",
        extra_tables=(ReportTable(COLUMNS, ROWS, source_reference(source, 1)),),
        references=("docx:" + "f" * 64 + ":word-table-1",))
    return replace(draft,
        sections=tuple(section for section in default_sections() if section.key == "issues"),
        blocks=(block,), sources=(source,))


def test_recognized_open_closed_and_unmapped_columns_are_reviewable():
    original = report()
    review = canonical_issues(original)
    items = [item for item in review.follow_ups if item.category == "issue"]
    assert len(items) == 2
    assert all(item.status == "ongoing" for item in items)
    assert "Status: Closed" in items[1].text
    assert "Client Detail: Zone B" in items[1].text
    assert "Reported Date: 2026-09-16" in items[1].text
    assert "Owner: Synthetic Engineer" in items[0].text
    assert "Action: Inspect bearings" in items[0].text
    assert items[1].evidence_note == ""
    assert items[0].key != items[1].key
    assert review.blocks != original.blocks
    assert not review.blocks[next(i for i,b in enumerate(review.blocks)
                                  if b.key == "equipment_issues")].extra_tables
    assert original.blocks[next(i for i,b in enumerate(original.blocks)
                                if b.key == "equipment_issues")].extra_tables
    assert canonical_issues(review) == review
    docx = Document(BytesIO(assemble_docx(review, acknowledged_fingerprint=review.fingerprint)))
    text = "\n".join(p.text for p in docx.paragraphs)
    for value in ("Chiller vibration", "Valve repaired", "Synthetic Engineer",
                  "2026-09-16", "Zone B", "Verify repair"):
        assert text.count(value) == 1


def test_manual_issue_cards_survive_edits_reimport_and_reopen():
    source = report()
    first = canonical_issues(source)
    manual = ReportFollowUp("manual-issue-01", "issue", "Manually entered pump issue", source.period.key)
    corrected = replace(first.follow_ups[1], text="Operator's corrected valve issue",
                        status="resolved", evidence_note="Synthetic closeout confirmed.")
    edited = replace(first, follow_ups=(first.follow_ups[0], corrected, manual))
    restored = library.draft_from_dict(json.loads(json.dumps(asdict(edited))))
    assert restored == edited
    repeated = canonical_issues(merge_drafts(restored, source))
    assert {item.key for item in repeated.follow_ups} == {
        first.follow_ups[0].key, corrected.key, manual.key}
    assert next(item for item in repeated.follow_ups if item.key == corrected.key).text == corrected.text
    assert next(item for item in repeated.follow_ups if item.key == corrected.key).status == "resolved"
    assert any(item.key == manual.key for item in repeated.follow_ups)


def test_duplicate_source_rows_have_distinct_identities_and_no_second_import():
    original = report()
    repeated = replace(original.blocks[next(i for i,b in enumerate(original.blocks)
                                            if b.key == "equipment_issues")],
        extra_tables=(ReportTable(COLUMNS, (ROWS[0], ROWS[0]), "source:dupes"),))
    draft = replace(original, blocks=tuple(
        repeated if b.key == "equipment_issues" else b for b in original.blocks))
    result = canonical_issues(draft)
    assert len(result.follow_ups) == 2
    assert result.follow_ups[0].text == result.follow_ups[1].text
    assert result.follow_ups[0].key != result.follow_ups[1].key
    assert canonical_issues(result) == result


def test_unknown_ambiguous_schemas_never_guess_status_or_column_roles():
    assert mapped_issue_register(("Description", "Status"), ROWS, "source:schema") is None
    assert mapped_issue_register(("Issue", "Issue", "Status", "Owner"), ROWS, "source:schema") is None
    assert mapped_issue_register(("Equipment", "Finding", "Cost"),
                                 (("Synthetic pump", "Vibration", "100"),),
                                 "source:schema") is None



def legacy_text(row):
    return '; '.join(f'{column}: {value}' for column, value in zip(COLUMNS, row) if value.strip())


def word_register():
    draft = report()
    block = replace(draft.blocks[0], references=(),
                    extra_tables=(ReportTable(COLUMNS, ROWS, ''),))
    return replace(draft, sources=(), blocks=(block,))


@pytest.mark.parametrize('status,included', [('ongoing', True), ('updated', True), ('resolved', True),
                                          ('resolved', False), ('updated', False), ('ongoing', False)])
def test_legacy_row_identity_preserves_operator_edits_and_decisions(status, included):
    original = word_register()
    saved = ReportFollowUp(issue_key(legacy_text(ROWS[0])), 'issue', "Operator's edited description", original.period.key,
                           status=status, included=included, update='Operator update', evidence_note='Verified repair.')
    draft = replace(original, follow_ups=(saved,))
    result = canonical_issues(draft)
    assert result.follow_ups[0] == saved
    assert len(result.follow_ups) == 2
    reopened = library.draft_from_dict(json.loads(json.dumps(asdict(result))))
    repeated = canonical_issues(merge_drafts(reopened, original))
    assert repeated.follow_ups == result.follow_ups


def test_existing_duplicate_legacy_keys_are_preserved_without_guessing_merge():
    original = word_register()
    key = issue_key(legacy_text(ROWS[0]))
    first = ReportFollowUp(key, 'issue', 'First operator edit', original.period.key)
    second = replace(first, text='Different operator edit', included=False)
    result = canonical_issues(replace(original, follow_ups=(first, second)))
    assert result.follow_ups[0] == first
    assert replace(result.follow_ups[1], key=second.key) == second
    assert result.follow_ups[1].key != first.key
    assert len(result.follow_ups) == 3


def test_identical_current_rows_from_different_sources_remain_distinct():
    original = word_register()
    block = replace(original.blocks[0], extra_tables=(
        ReportTable(COLUMNS, (ROWS[0],), 'source:first'),
        ReportTable(COLUMNS, (ROWS[0],), 'source:second')))
    result = canonical_issues(replace(original, blocks=(block,)))
    assert len(result.follow_ups) == 2
    assert result.follow_ups[0].text == result.follow_ups[1].text
    assert result.follow_ups[0].key != result.follow_ups[1].key


def test_different_known_source_does_not_match_legacy_card():
    original = word_register()
    saved = ReportFollowUp(issue_key(legacy_text(ROWS[0])), 'issue', 'Existing different-source edit', original.period.key,
                           references=('source:first',))
    block = replace(original.blocks[0], extra_tables=(ReportTable(COLUMNS, (ROWS[0],), 'source:second'),))
    result = canonical_issues(replace(original, blocks=(block,), follow_ups=(saved,)))
    assert result.follow_ups[0] == saved
    assert len(result.follow_ups) == 2


def test_import_guidance_cannot_satisfy_resolution_or_remove_issue_at_rollover():
    original = word_register()
    draft = canonical_issues(original)
    item = draft.follow_ups[0]
    assert item.evidence_note == ''
    resolved = replace(item, status='resolved')
    assert any('Add evidence' in message for message in problems(resolved, draft))
    changed = replace(draft, follow_ups=(resolved,))
    assert any(candidate.key == item.key for candidate in seed_followups(changed))
    explained = replace(resolved, evidence_note='Operator verified bearing replacement on site.')
    assert not problems(explained, draft)
    assert not seed_followups(replace(draft, follow_ups=(explained,)))


def test_real_issue_ui_requires_operator_resolution_evidence(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_issues import render_issue_cards
from app.monthly_report_ui import _field
st.session_state['draft'] = render_issue_cards(st.session_state['draft'], 'register_review', _field)
''', default_timeout=20)
    app.session_state['draft'] = canonical_issues(word_register())
    app.run()
    assert not app.exception
    next(w for w in app.selectbox if w.label == 'Issue status').set_value('resolved').run()
    assert not app.exception
    note = next(w for w in app.text_area if w.label == 'Evidence or explanation for the status')
    assert note.value == ''
    assert any('Add evidence' in w.value for w in app.warning)
    note.set_value('Operator verified repaired bearings.').run()
    assert not app.exception
    assert not any('Add evidence' in w.value for w in app.warning)
    current = app.session_state['draft']
    assert current.follow_ups[0].evidence_note == 'Operator verified repaired bearings.'
    assert current.follow_ups[0].key not in {item.key for item in seed_followups(current)}
    app.run()
    assert app.session_state['draft'] == current


def test_legacy_source_match_preserves_saved_identity():
    original = report()
    reference = original.blocks[0].extra_tables[0].reference
    saved = ReportFollowUp(issue_key(legacy_text(ROWS[0])), 'issue',
                           'Reviewed source-specific edit', original.period.key,
                           references=(reference,), included=False)
    result = canonical_issues(replace(original, follow_ups=(saved,)))
    assert result.follow_ups[0] == saved
    assert len(result.follow_ups) == 2
