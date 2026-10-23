"""Synthetic regressions for inherited source-workspace review findings.

These exercise actual preflight and ordinary rich-text edit semantics, not only
manager summary labels. Original bytes and independent human work stay intact.
"""
from dataclasses import asdict, replace

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_checks import preflight
from app.monthly_report_guided import _edited_rich_text
from app.monthly_report_model import used_source_ids
from app.monthly_report_source_scope import contribution_receipt, source_uses
from test_source_readiness_dates import accepted_contribution, reviewed_text

DATE_CODES = {"source_period", "source_date_unknown"}


@pytest.mark.parametrize("when", ["", "unresolved", "2026-08-04"])
@pytest.mark.parametrize("kind", ["totals", "rows"])
def test_period_bound_row_contributions_do_not_reopen_file_date_at_preflight(
        monkeypatch, tmp_path, when, kind):
    draft, content, raw = accepted_contribution(monkeypatch, tmp_path, when, kind)
    assert not [check for check in preflight(draft) if check.code in DATE_CODES]
    restored = library.draft_from_dict(asdict(draft))
    assert not [check for check in preflight(restored) if check.code in DATE_CODES]
    assert sources.source_bytes(draft.profile, content.source) == raw


def test_accepted_rows_do_not_approve_an_additional_wording_use_date(monkeypatch, tmp_path):
    draft, content, _ = accepted_contribution(monkeypatch, tmp_path, "", "totals")
    extra = reviewed_text(content.source, "improvements")
    from app.monthly_report_model import BlockSpec
    draft = replace(draft, blocks=(*draft.blocks, extra), sections=(
        replace(draft.sections[0], blocks=(*draft.sections[0].blocks, BlockSpec(extra.key, "rich_text"))),))
    assert [check.code for check in preflight(draft) if check.code in DATE_CODES] == ["source_date_unknown"]


def test_accepted_rows_do_not_approve_an_additional_original_page_date(monkeypatch, tmp_path):
    draft, content, _ = accepted_contribution(monkeypatch, tmp_path, "", "totals")
    from app.monthly_report_model import BlockSpec, ResolvedBlock
    reference = sources.source_reference(content.source, 1)
    page = ResolvedBlock("water_reports", "This month", asset_hashes=("synthetic-page.png",),
                         references=(reference,), asset_provenance=(("synthetic-page.png", (reference,)),))
    draft = replace(draft, blocks=(*draft.blocks, page), sections=(
        replace(draft.sections[0], blocks=(*draft.sections[0].blocks, BlockSpec(page.key, "pdf_pages"))),))
    assert [check.code for check in preflight(draft) if check.code in DATE_CODES] == ["source_date_unknown"]


def _totals_with_independent_text(monkeypatch, tmp_path):
    draft, content, raw = accepted_contribution(monkeypatch, tmp_path, "2026-09-04", "totals")
    totals = draft.blocks[0].text
    original = replace(draft.blocks[0], text="Independent human note.", references=())
    reference = sources.source_reference(content.source, 1)
    receipt = contribution_receipt(reference, draft.profile, draft.period, original.key,
        text=totals, source=content.source, prior_block=original)
    block = replace(original, text=original.text + "\n\n" + totals, references=(reference, receipt))
    return replace(draft, blocks=(block,)), content, raw, totals


def test_deleting_only_accepted_totals_retires_their_use_not_independent_human_text(monkeypatch, tmp_path):
    draft, content, raw, _ = _totals_with_independent_text(monkeypatch, tmp_path)
    block = _edited_rich_text(draft.blocks[0], "Independent human note.")
    edited = replace(draft, blocks=(block,))
    assert block.text == "Independent human note."
    assert not source_uses(edited, content.source.id)
    assert content.source.id not in used_source_ids(edited)
    assert not [check for check in preflight(edited) if check.code == "source_facility" and check.blocking]
    restored = library.draft_from_dict(asdict(edited))
    assert restored == edited
    assert not source_uses(restored, content.source.id)
    assert sources.source_bytes(draft.profile, content.source) == raw
    from io import BytesIO
    from docx import Document
    from app.monthly_report_docx import assemble_docx
    word = Document(BytesIO(assemble_docx(restored, acknowledged_fingerprint=restored.fingerprint)))
    paragraphs = [paragraph.text for paragraph in word.paragraphs]
    assert "Independent human note." in paragraphs
    assert not any("work orders in the uploaded" in paragraph for paragraph in paragraphs)


def test_editing_accepted_totals_cannot_silently_retire_their_scope_gate(monkeypatch, tmp_path):
    draft, content, _, totals = _totals_with_independent_text(monkeypatch, tmp_path)
    changed = totals.replace("1 total", "99 total")
    assert changed != totals
    block = _edited_rich_text(draft.blocks[0], "Independent human note.\n\n" + changed)
    edited = replace(draft, blocks=(block,))
    assert source_uses(edited, content.source.id)
    assert any(check.code == "source_facility" and check.blocking for check in preflight(edited))


def test_removing_totals_does_not_retire_preexisting_source_narrative(monkeypatch, tmp_path):
    draft, content, _, totals = _totals_with_independent_text(monkeypatch, tmp_path)
    reference = sources.source_reference(content.source, 1)
    original = replace(draft.blocks[0], text="Existing source-linked inspection narrative.", references=(reference,))
    receipt = contribution_receipt(reference, draft.profile, draft.period, original.key,
        text=totals, source=content.source, prior_block=original)
    combined = replace(original, text=original.text + "\n\n" + totals, references=(reference, receipt))
    edited = replace(draft, blocks=(_edited_rich_text(combined, original.text),))
    assert source_uses(edited, content.source.id)
    assert any(check.code == "source_facility" and check.blocking for check in preflight(edited))


def test_deleting_one_sources_totals_keeps_another_sources_reference(monkeypatch, tmp_path):
    draft, content, _, totals = _totals_with_independent_text(monkeypatch, tmp_path)
    other, _ = sources.ingest(draft.profile, "independent-synthetic-note.txt",
                              b"A separate synthetic source note remains.")
    other_ref = sources.source_reference(other.source, 1)
    original = replace(draft.blocks[0], text="Separate source note remains.", references=(other_ref,))
    reference = sources.source_reference(content.source, 1)
    receipt = contribution_receipt(reference, draft.profile, draft.period, original.key,
        text=totals, source=content.source, prior_block=original)
    combined = replace(original, text=original.text + "\n\n" + totals,
                       references=(other_ref, reference, receipt))
    edited = replace(draft, sources=(*draft.sources, other.source),
                     blocks=(_edited_rich_text(combined, original.text),))
    assert not source_uses(edited, content.source.id)
    assert source_uses(edited, other.source.id)
    assert other_ref in edited.blocks[0].references
    assert edited.blocks[0].text == original.text


@pytest.mark.parametrize("kind", ["totals", "rows"])
@pytest.mark.parametrize("change", ["source", "report", "content"])
def test_changed_source_report_or_contribution_does_not_reuse_date_exemption(monkeypatch, tmp_path, kind, change):
    draft, content, raw = accepted_contribution(monkeypatch, tmp_path, "", kind)
    if change == "source":
        draft = replace(draft, sources=(replace(content.source, page_texts=("Changed source extraction.",)),))
    elif change == "report":
        draft = replace(draft, period=replace(draft.period, month=10))
    elif kind == "totals":
        draft = replace(draft, blocks=(replace(draft.blocks[0], text=draft.blocks[0].text.replace("1 total", "99 total")),))
    else:
        block = draft.blocks[0]
        row = (*block.rows[0][:-1], "Changed accepted value")
        draft = replace(draft, blocks=(replace(block, rows=(row, *block.rows[1:])), *draft.blocks[1:]))
    before = asdict(draft)
    assert any(check.code in DATE_CODES for check in preflight(draft))
    assert asdict(draft) == before
    assert sources.source_bytes(draft.profile, content.source) == raw


def test_clear_and_undo_keeps_exact_accepted_provenance(monkeypatch, tmp_path):
    draft, content, _, _ = _totals_with_independent_text(monkeypatch, tmp_path)
    initial = draft.blocks[0]
    cleared = _edited_rich_text(initial, "")
    assert cleared.references == initial.references
    assert not source_uses(replace(draft, blocks=(cleared,)), content.source.id)
    restored = _edited_rich_text(cleared, initial.text)
    assert restored.references == initial.references
    assert source_uses(replace(draft, blocks=(restored,)), content.source.id)
    assert not any(check.code == "source_facility" and check.blocking
                   for check in preflight(replace(draft, blocks=(restored,))))


@pytest.mark.parametrize("mixed", ["rows", "pictures", "ai"])
def test_deleting_totals_keeps_ambiguous_mixed_use_provenance(monkeypatch, tmp_path, mixed):
    draft, content, _, _ = _totals_with_independent_text(monkeypatch, tmp_path)
    block = draft.blocks[0]
    if mixed == "rows":
        block = replace(block, rows=(("Unrelated source-linked row",),))
    elif mixed == "pictures":
        block = replace(block, asset_hashes=("synthetic-page.png",))
    else:
        block = replace(block, ai_written=True)
    edited = _edited_rich_text(block, "Independent human note.")
    assert edited.references == block.references
    assert source_uses(replace(draft, blocks=(edited,)), content.source.id)


@pytest.mark.parametrize("defect", ["wrong key", "missing ownership", "bad version", "malformed"])
def test_ambiguous_receipt_cannot_retire_a_source_reference(monkeypatch, tmp_path, defect):
    from app.monthly_report_source_scope import USE_PREFIX, _decode, _encode
    draft, _, _, _ = _totals_with_independent_text(monkeypatch, tmp_path)
    block = draft.blocks[0]
    origin, receipt = block.references
    record = _decode(receipt[len(USE_PREFIX):])
    if defect == "wrong key": record["key"] = "improvements"
    elif defect == "missing ownership": record.pop("allows_independent_text")
    elif defect == "bad version": record["version"] = 999
    damaged = USE_PREFIX + (_encode(record) if defect != "malformed" else "!")
    block = replace(block, references=(origin, damaged))
    assert _edited_rich_text(block, "Independent human note.").references == block.references


def test_a_remaining_receipt_preserves_its_same_page_reference(monkeypatch, tmp_path):
    draft, content, _, _ = _totals_with_independent_text(monkeypatch, tmp_path)
    block = draft.blocks[0]
    origin = sources.source_reference(content.source, 1)
    second = "Second accepted synthetic totals."
    receipt = contribution_receipt(origin, draft.profile, draft.period, block.key,
        text=second, source=content.source, prior_block=block)
    both = replace(block, text=block.text + "\n\n" + second, references=(*block.references, receipt))
    edited = _edited_rich_text(both, "Independent human note.\n\n" + second)
    assert origin in edited.references and receipt in edited.references
    assert source_uses(replace(draft, blocks=(edited,)), content.source.id)
    assert not any(check.code == "source_facility" and check.blocking
                   for check in preflight(replace(draft, blocks=(edited,))))
