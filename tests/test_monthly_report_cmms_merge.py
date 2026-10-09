"""Corrected exports must not create competing work rows or monthly totals."""

from dataclasses import replace

import pytest

from app.monthly_report_cmms import CMMSMapping, map_cmms
from app.monthly_report_model import BlockSpec, ColumnSpec, ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_setup import merge_report_block
from app.monthly_report_sources import SourceTable


PROFILE = synthetic_profiles()[1]
PERIOD = ReportPeriod(2026, 9)
MAPPING = CMMSMapping("Finished", "ID", facility="Facility", description="Task",
                      complete_months=(PERIOD.key,), complete_facilities=("north",))
TABLE = SourceTable("Synthetic", ("ID", "Finished", "Facility", "Task"), (
    ("001", "2026-09-02", "Demo North", "Inspected demonstration pump"),
))


def mapped(table=TABLE, mapping=MAPPING, reference="synthetic-source"):
    return map_cmms(table, mapping, PROFILE, PERIOD, reference)


def test_corrected_work_order_is_rejected_without_changing_saved_content():
    saved = mapped()
    corrected = mapped(replace(TABLE, rows=(
        ("001", "2026-09-02", "Demo North", "Inspected pump and replaced seal"),
        ("002", "2026-09-03", "Demo North", "Repaired demonstration valve"),
    )), reference="corrected-source")
    original = saved.blocks[0]
    with pytest.raises(ValueError, match=r"Conflicting service-call rows.*WO 001.*Task Code-Description"):
        merge_report_block(original, corrected.blocks[0], saved.specs[0], corrected.specs[0])
    assert original.rows == ((PROFILE.facilities[0].title, "001", "2026-09-02", "",
                              "Inspected demonstration pump", ""),)
    assert original.references == ("synthetic-source",)


def test_changed_monthly_total_is_rejected_instead_of_appended():
    saved = mapped()
    corrected = mapped(replace(TABLE, rows=TABLE.rows + (
        ("002", "2026-09-03", "Demo North", "Repaired demonstration valve"),
    )), reference="corrected-source")
    with pytest.raises(ValueError, match=r"Conflicting work-order totals for 2026-09.*Total completed"):
        merge_report_block(saved.blocks[1], corrected.blocks[1], saved.specs[1], corrected.specs[1])
    assert len(saved.blocks[1].rows) == 24
    assert saved.blocks[1].rows[-2][-1] == "1"


def test_regional_exports_fill_unknown_site_totals_without_erasing_known_values():
    north = mapped()
    south_table = replace(TABLE, rows=(("001", "2026-09-04", "Demo South", "Checked demonstration fan"),))
    south = mapped(south_table, replace(MAPPING, complete_facilities=("south",)), "south-source")
    combined = merge_report_block(north.blocks[1], south.blocks[1], north.specs[1], south.specs[1])
    assert len(combined.rows) == 24
    assert combined.rows[-2][-1] == "1"
    assert combined.rows[-1][-1] == "1"
    assert combined.references == ("synthetic-source", "south-source")
    # The same WO number at a different site identifies different work.
    calls = merge_report_block(north.blocks[0], south.blocks[0], north.specs[0], south.specs[0])
    assert len(calls.rows) == 2


def test_blank_work_fields_are_filled_and_identical_reimport_is_a_noop():
    full = mapped()
    row = full.blocks[0].rows[0]
    partial = replace(full.blocks[0], rows=(row[:4] + ("", ""),))
    combined = merge_report_block(partial, full.blocks[0], full.specs[0], full.specs[0])
    assert combined.rows == full.blocks[0].rows
    assert merge_report_block(combined, full.blocks[0], full.specs[0], full.specs[0]) == combined


def test_zero_is_a_known_total_and_cannot_be_replaced_silently():
    full = mapped()
    rows = tuple((*row[:-1], "0") if row[0] == PERIOD.key and row[1] == PROFILE.facilities[0].title
                 else row for row in full.blocks[1].rows)
    zero = replace(full.blocks[1], rows=rows)
    with pytest.raises(ValueError, match="Conflicting work-order totals"):
        merge_report_block(zero, full.blocks[1], full.specs[1], full.specs[1])


def test_custom_imported_columns_do_not_acquire_cmms_identity_semantics():
    custom = BlockSpec("service_calls", "table", columns=(ColumnSpec("c0", "Description"),
                                                         ColumnSpec("c1", "Status")))
    saved = ResolvedBlock("service_calls", "This month", rows=(("Pump", "Inspected"),))
    incoming = replace(saved, rows=(("Pump", "Repaired"),))
    assert merge_report_block(saved, incoming, custom, custom).rows == saved.rows + incoming.rows


def test_incomplete_manually_entered_work_is_preserved_without_inventing_identity():
    full = mapped()
    unfinished = replace(full.blocks[0], rows=(("", "", "", "", "Work awaiting a number", ""),))
    combined = merge_report_block(unfinished, full.blocks[0], full.specs[0], full.specs[0])
    assert combined.rows == unfinished.rows + full.blocks[0].rows
