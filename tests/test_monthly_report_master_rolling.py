"""Synthetic native frame labels and same-pin historic values without hidden resets."""
from dataclasses import replace

import pytest

from app import monthly_report_master_tables as master
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable,
    ResolvedBlock, profile_sections,
)
from app.monthly_report_work_order_rolling import rolling_labels


OLD = ReportPeriod(2026, 12)
NEW = ReportPeriod(2027, 1)


def test_only_a_complete_ordered_thirteen_month_frame_can_keep_native_headings():
    headers = ("PM Received", *rolling_labels(OLD))
    assert master._verified_work_order_month_frame(headers)
    assert master._verified_work_order_month_frame(
        ("Non-PM Closed", *("Feb", "Mar", "Apr", "May", "Jun", "Jul",
                            "Aug", "Sep", "Oct", "Nov", "Dec", "Jan")))
    assert master._heading(headers[0], 0, set(), slot="work_orders") == "PM Received"
    assert [master._heading(value, number, set(), slot="work_orders")
            for number, value in enumerate(headers[1:], 1)] == list(headers[1:])
    assert not master._verified_work_order_month_frame(
        ("PM Received", *reversed(rolling_labels(OLD))))
    assert not master._verified_work_order_month_frame(
        ("PM Received", *rolling_labels(OLD)[:11], "Jan 2027"))
    assert not master._verified_work_order_month_frame(
        ("PM Received", *rolling_labels(OLD)[:11], "Price"))
    assert not master._verified_work_order_month_frame(
        ("Unreviewed Site", *rolling_labels(OLD)))
    # Rejected month names or client-specific headings are not automatically safe.
    assert master._heading("North", 0, set(), slot="work_orders") == "Detail 1"
    assert master._heading("May", 5, set()) == "Detail 6"


def make_draft(facilities, *, prior_rows, columns=("PM Received", *rolling_labels(OLD))):
    profile = ReportProfile("Synthetic contract", "synthetic-profile", "Synthetic",
        tuple(facilities), scope_type="multi_site",
        template="enfra_master:" + "a" * 64)
    frames = tuple(ReportTable(columns, (), f"master-table:synthetic:{i}")
                   for i in range(len(prior_rows)))
    older = ResolvedBlock("work_orders", "This month", extra_tables=tuple(
        ReportTable(columns, (row,), table.reference)
        for row, table in zip(prior_rows, frames)))
    current = ResolvedBlock("work_orders", "This month", extra_tables=tuple(
        replace(table, reference="") for table in frames))
    draft = ReportDraft(profile, NEW, "Synthetic editor", profile_sections(profile),
                        (current,), synthetic=True)
    shapes = tuple(master.MasterTable("work_orders", i, t.reference, t.columns,
                     tuple(range(13)), 13) for i, t in enumerate(frames))
    return draft, older, shapes


def row(site, month_index=11, value="7"):
    values = ["" for _ in range(12)]
    values[month_index] = value
    return (site, *values)


def test_rebind_preserves_two_explicit_locations_and_original_month_history(monkeypatch):
    draft, older, shapes = make_draft((Facility("n", "North"), Facility("s", "South")),
        prior_rows=(row("North"), row("South", 10, "0")))
    monkeypatch.setattr(master, "for_profile", lambda _: shapes)
    original = draft
    earlier = older
    result = master.rebind_carried_master_tables(draft,
        {"work_orders": older}, draft.profile.template)
    tables = result.blocks[0].extra_tables
    assert original == draft and earlier == older
    assert [t.reference for t in tables] == [s.reference for s in shapes]
    assert all(t.columns[1:] == rolling_labels(NEW) for t in tables)
    assert tables[0].rows[0][0] == "North"
    assert tables[0].rows[0][11] == "7"  # December 2026 stays December.
    assert tables[1].rows[0][10] == "0"  # November 2026 genuine zero survives.
    assert tables[0].rows[0][-1] == ""   # January 2027 is not guessed.
    assert tables[1].rows[0][-1] == ""
    # Rebinding is deterministic; the prior draft itself remains unchanged.
    again = master.rebind_carried_master_tables(draft,
        {"work_orders": older}, draft.profile.template)
    assert again == result


def test_one_physical_grid_carries_two_verified_site_rows(monkeypatch):
    sites = (Facility("n", "North", ("N",)), Facility("s", "South"))
    draft, older, shapes = make_draft(sites, prior_rows=(row("N"),))
    previous = replace(older.extra_tables[0], rows=(row("N"), row("South", 10, "0")))
    older = replace(older, extra_tables=(previous,))
    monkeypatch.setattr(master, "for_profile", lambda _: shapes)
    result = master.rebind_carried_master_tables(draft, {"work_orders": older}, draft.profile.template)
    table = result.blocks[0].extra_tables[0]
    assert [r[0] for r in table.rows] == ["North", "South"]
    assert table.rows[0][11] == "7" and table.rows[1][10] == "0"
    assert all(r[-1] == "" for r in table.rows)
    duplicate = replace(older, extra_tables=(replace(previous, rows=(row("N"), row("North"))),))
    with pytest.raises(ValueError, match="same historical site"):
        master.rebind_carried_master_tables(draft, {"work_orders": duplicate}, draft.profile.template)


def test_ambiguous_or_wrong_site_is_blocked_without_cross_site_copy(monkeypatch):
    sites = (Facility("n", "West Plant", ("Shared",)),
             Facility("shared", "South"))
    draft, older, shapes = make_draft(sites, prior_rows=(row("Shared"),))
    monkeypatch.setattr(master, "for_profile", lambda _: shapes)
    with pytest.raises(ValueError, match="ambiguous"):
        master.rebind_carried_master_tables(draft, {"work_orders": older},
                                             draft.profile.template)
    wrong = replace(older, extra_tables=(replace(older.extra_tables[0],
        rows=(row("Outside"),)),))
    with pytest.raises(ValueError, match="missing or ambiguous"):
        master.rebind_carried_master_tables(draft, {"work_orders": wrong},
                                             draft.profile.template)


def test_undated_historical_headers_need_review_and_previous_values_survive(monkeypatch):
    undated = ("PM Received", *("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))
    draft, older, shapes = make_draft((Facility("n", "North"),),
        prior_rows=(row("North"),), columns=undated)
    monkeypatch.setattr(master, "for_profile", lambda _: shapes)
    with pytest.raises(ValueError, match="explicit years"):
        master.rebind_carried_master_tables(draft, {"work_orders": older},
                                             draft.profile.template)
    assert older.extra_tables[0].rows[0][12] == "7"


def test_three_site_rollover_requires_layout_without_dropping_rows(monkeypatch):
    sites = tuple(Facility(key, title) for key, title in
                  (("n", "North"), ("s", "South"), ("e", "East")))
    draft, older, shapes = make_draft(sites,
        prior_rows=(row("North"), row("South"), row("East")))
    monkeypatch.setattr(master, "for_profile", lambda _: shapes)
    with pytest.raises(ValueError, match="overflow"):
        master.rebind_carried_master_tables(draft, {"work_orders": older},
                                             draft.profile.template)
    assert len(older.extra_tables) == 3


def test_unrelated_master_shape_and_manual_values_are_not_copied(monkeypatch):
    draft, older, shapes = make_draft((Facility("n", "North"),),
        prior_rows=(row("North"),))
    monkeypatch.setattr(master, "for_profile", lambda _: shapes)
    mismatch = replace(draft, profile=replace(draft.profile,
        template="enfra_master:" + "b" * 64))
    with pytest.raises(ValueError, match="pinned master changed"):
        master.rebind_carried_master_tables(mismatch,
            {"work_orders": older}, draft.profile.template)
    omitted = replace(draft, blocks=(replace(draft.blocks[0], source="Omit"),))
    carried = master.rebind_carried_master_tables(omitted,
        {"work_orders": older}, draft.profile.template)
    assert not carried.blocks[0].extra_tables[0].rows


DETAIL_COLUMNS = ("#", "Work order #", "Date", *(f"Detail {n}" for n in range(4, 14)))
DETAIL_ROW = ("1", "WO-7", "2026-12-03", *("" for _ in range(10)))


def with_detail_table(draft, older, shapes):
    """Add a populated 13-column detail table beside whatever the block holds."""
    detail = ReportTable(DETAIL_COLUMNS, (), "master-table:synthetic:detail")
    older = replace(older, extra_tables=(*older.extra_tables,
                                         replace(detail, rows=(DETAIL_ROW,))))
    current = replace(draft.blocks[0], extra_tables=(
        *draft.blocks[0].extra_tables, replace(detail, reference="")))
    shapes = (*shapes, master.MasterTable("work_orders", 9, detail.reference,
                                          detail.columns, tuple(range(13)), 13))
    return replace(draft, blocks=(current,)), older, shapes, detail


def test_only_metric_or_month_headed_grids_count_as_month_history():
    grid = ReportTable(("PM Received", *rolling_labels(OLD)), (row("North"),), "")
    undated = replace(grid, columns=("PM Received", *"Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()))
    relabelled = replace(grid, columns=("Detail 1", *rolling_labels(OLD)))
    detail = ReportTable(DETAIL_COLUMNS, (DETAIL_ROW,), "")
    assert all(master.is_work_order_history_grid(t) for t in (grid, undated, relabelled))
    assert not master.is_work_order_history_grid(detail)
    assert not master.is_work_order_history_grid(replace(grid, rows=()))
    assert not master.is_work_order_history_grid(replace(detail, columns=DETAIL_COLUMNS[:7]))


def test_thirteen_column_detail_table_is_cleared_beside_carried_history(monkeypatch):
    draft, older, shapes = make_draft((Facility("n", "North"),), prior_rows=(row("North"),))
    draft, older, shapes, detail = with_detail_table(draft, older, shapes)
    monkeypatch.setattr(master, "for_profile", lambda _: shapes)
    result = master.rebind_carried_master_tables(draft, {"work_orders": older},
                                                  draft.profile.template)
    grid, plain = result.blocks[0].extra_tables
    assert grid.columns[1:] == rolling_labels(NEW) and grid.rows[0][11] == "7"
    # The ordinary table keeps its pinned region and columns but no old row.
    assert plain.rows == () and plain.columns == DETAIL_COLUMNS
    assert plain.reference == detail.reference
    assert older.extra_tables[1].rows == (DETAIL_ROW,)


def test_next_month_clears_a_thirteen_column_detail_table_without_blocking(monkeypatch):
    from app.monthly_report_setup import WorkOrderRolloverError, new_month_draft

    def previous_month(*, grid_columns=None):
        options = {} if grid_columns is None else {"columns": grid_columns}
        draft, older, shapes = make_draft((Facility("n", "North"),),
                                          prior_rows=(row("North"),), **options)
        draft, older, shapes, detail = with_detail_table(draft, older, shapes)
        monkeypatch.setattr(master, "for_profile", lambda _: shapes)
        return replace(draft, period=OLD, blocks=(older,)), detail

    # Alone, the detail table takes the ordinary path: emptied, not rebound.
    previous, detail = previous_month()
    only_detail = replace(previous, blocks=(replace(previous.blocks[0],
        extra_tables=previous.blocks[0].extra_tables[1:]),))
    alone = new_month_draft(only_detail, NEW).blocks[0].extra_tables
    assert [(t.columns, t.rows, t.reference) for t in alone] == [(DETAIL_COLUMNS, (), "")]

    # Beside real month history, the history is carried and the detail cleared.
    grid, plain = new_month_draft(previous, NEW).blocks[0].extra_tables
    assert grid.rows[0][11] == "7" and grid.columns[1:] == rolling_labels(NEW)
    assert plain.rows == () and plain.reference == detail.reference

    # A real grid without explicit years still stops instead of being cleared.
    undated, _ = previous_month(grid_columns=(
        "PM Received", *"Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()))
    with pytest.raises(WorkOrderRolloverError, match="explicit years"):
        new_month_draft(undated, NEW)
    assert undated.blocks[0].extra_tables[0].rows[0][12] == "7"
