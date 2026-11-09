"""Synthetic regression: imported rows without headings must never vanish in Word."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest

from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable,
    ResolvedBlock, default_sections,
)


def _draft(block, *, included=True):
    section = next(s for s in default_sections() if s.key == "capital")
    profile = ReportProfile("Synthetic Headerless Contract", "north",
                            "Synthetic North", (Facility("north", "Synthetic North"),))
    return ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic reviewer",
                       (replace(section, included=included),), (block,), synthetic=True)


def _missing(draft):
    return tuple(c for c in preflight(draft) if c.code == "table_missing_columns")


def test_populated_headerless_table_blocks_create_and_keeps_source_rows():
    source = ReportTable((), (("BOILER-01", "Pending renewal"),), "original:page:7")
    block = ResolvedBlock("capital_renewal", "This month",
                          text="Independent report note.", extra_tables=(source,))
    draft = _draft(block)
    checks = _missing(draft)
    assert len(checks) == 1
    assert checks[0].blocking is True and checks[0].block_key == "capital_renewal"
    assert "Imported table 1" in checks[0].message
    assert "no column headings" in checks[0].message
    assert "Add headings" in checks[0].message
    with pytest.raises(ValueError, match="no column headings"):
        assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    assert draft.blocks == (block,)
    assert block.extra_tables[0].rows == source.rows
    assert source.reference == "original:page:7"


def test_second_headerless_table_is_identified_without_blocking_healthy_sibling():
    good = ReportTable(("Asset", "Status"), (("PUMP-01", "Open"),), "original:1")
    bad = ReportTable((), (("BOILER-02", "Replace"),), "original:2")
    block = ResolvedBlock("capital_renewal", "This month", extra_tables=(good, bad))
    checks = _missing(_draft(block))
    assert len(checks) == 1
    assert "Imported table 2" in checks[0].message
    assert block.extra_tables == (good, bad)
    assert good.rows == (("PUMP-01", "Open"),)


def test_reviewed_headings_restore_complete_word_output_without_rewriting_rows():
    good = ReportTable(("Asset", "Status"), (("PUMP-01", "Open"),), "original:1")
    raw = ReportTable((), (("BOILER-02", "Replace"),), "original:2")
    block = ResolvedBlock("capital_renewal", "This month",
                          text="Independent report note.", extra_tables=(good, raw))
    assert _missing(_draft(block))
    corrected = replace(raw, columns=("Asset", "Recommendation"))
    ready = _draft(replace(block, extra_tables=(good, corrected)))
    assert _missing(ready) == ()
    output = Document(BytesIO(assemble_docx(
        ready, acknowledged_fingerprint=ready.fingerprint)))
    assert len(output.tables) == 2
    assert tuple(c.text for c in output.tables[0].rows[1].cells) == ("PUMP-01", "Open")
    assert tuple(c.text for c in output.tables[1].rows[1].cells) == ("BOILER-02", "Replace")
    assert "Independent report note." in "\n".join(p.text for p in output.paragraphs)
    assert raw.columns == () and raw.rows == corrected.rows
    assert raw.reference == corrected.reference


def test_empty_and_whitespace_only_headerless_rows_remain_optional():
    blank = ReportTable((), (), "empty")
    spaces = ReportTable((), (("", " \t"), ("", "")), "spaces")
    draft = _draft(ResolvedBlock("capital_renewal", "This month",
                                 extra_tables=(blank, spaces)))
    assert _missing(draft) == ()
    output = Document(BytesIO(assemble_docx(
        draft, acknowledged_fingerprint=draft.fingerprint)))
    assert len(output.tables) == 0


def test_omitted_and_excluded_sections_keep_the_original_without_blocking():
    raw = ReportTable((), (("Asset-77", "Undecided"),), "immutable:2")
    block = ResolvedBlock("capital_renewal", "This month", extra_tables=(raw,))
    assert _missing(_draft(block))
    omitted = _draft(replace(block, source="Omit"))
    excluded = _draft(block, included=False)
    for draft in (omitted, excluded):
        assert _missing(draft) == ()
        assert draft.blocks[0].extra_tables == (raw,)
    assert _missing(_draft(block))  # Re-inclusion restores the review gate.


def test_wide_rows_and_pricing_remain_independent_blockers():
    wide = ReportTable(("Asset", "Status"), (("A", "Open", "extra"),))
    draft = _draft(ResolvedBlock("capital_renewal", "This month",
                                 extra_tables=(wide,)))
    codes = {c.code for c in preflight(draft) if c.blocking}
    assert "table_columns" in codes and "table_missing_columns" not in codes
    priced = ReportTable((), (("Invoice amount: $1000",),), "priced:4")
    draft = _draft(ResolvedBlock("capital_renewal", "This month",
                                 extra_tables=(priced,)))
    codes = {c.code for c in preflight(draft) if c.blocking}
    assert "table_missing_columns" in codes and "pricing" in codes


def test_snapshot_reopen_retains_unheaded_values_and_the_same_blocker(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = ReportTable((), (("NORTH", "Boiler check"), ("SOUTH", "Pump service")),
                      "original:sheet:1")
    block = ResolvedBlock("capital_renewal", "This month",
                          text="Report-only note stays.", extra_tables=(raw,))
    draft = _draft(block)
    assert _missing(draft)
    library.save_snapshot(draft, expected_revision=0)
    loaded = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.revision == 1
    assert loaded.draft.blocks == (block,)
    assert loaded.draft.blocks[0].extra_tables[0].rows == raw.rows
    assert loaded.draft.blocks[0].extra_tables[0].reference == raw.reference
    assert loaded.draft.blocks[0].text == "Report-only note stays."
    assert len(_missing(loaded.draft)) == 1
