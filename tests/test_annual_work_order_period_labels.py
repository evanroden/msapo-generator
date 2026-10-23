"""Synthetic annual header coordinates must not waive dated operational facts."""
from dataclasses import replace

import pytest

from app.monthly_report_checks import _annual_work_order_month_cells, preflight
from app.monthly_report_model import (BlockSpec, ReportDraft, ReportPeriod, ReportTable,
                                    ResolvedBlock, SectionSpec, synthetic_profiles)


def grid():
    first = ('Jan.', 'Feb.', 'Mar.', 'Apr.', 'May', 'June')
    second = ('July ', 'Aug.', 'Sep.', 'Oct.', 'Nov.', 'Dec.')
    return ReportTable(('WO Received', *first), (
        ('', '11', '12', '13', '14', '15', '16'),
        ('', *second), ('', 'Pending', 'Pending', 'Pending', '', '', ''),
        ('Closed', *first), ('', '1', '2', '3', '4', '5', '6'),
        ('', *second), ('', 'Pending', 'Pending', 'Pending', '', '', '')))


def draft(table=None, *, key='work_orders', text='', title='Work orders'):
    block = ResolvedBlock(key, 'This month', text=text, extra_tables=(table or grid(),))
    return ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10), 'Synthetic reviewer',
        (SectionSpec('activity', '3', title, (BlockSpec(key, 'rich_text'),)),), (block,))


def periods(d):
    return tuple(c for c in preflight(d) if c.code == 'period')


def changed(table, row, column, value):
    rows = list((table.columns, *table.rows))
    cells = list(rows[row]); cells[column] = value; rows[row] = tuple(cells)
    return replace(table, columns=rows[0], rows=tuple(rows[1:]))


def test_complete_annual_grid_labels_are_structural_without_mutation():
    d = draft(); before = d.fingerprint
    assert len(_annual_work_order_month_cells('work_orders', grid())) == 24
    assert periods(d) == ()
    assert d.fingerprint == before
    assert d.blocks[0].extra_tables[0] == grid()


@pytest.mark.parametrize('value', ['September maintenance completed', 'Sep 2026',
    '2026-09-14', 'September', 'Pending September data'])
@pytest.mark.parametrize('row', [1, 3, 5, 7])
def test_dated_data_adjacent_to_labels_remains_reviewable(value, row):
    table = changed(grid(), row, 2, value)
    assert len(_annual_work_order_month_cells('work_orders', table)) == 24
    checks = periods(draft(table))
    assert len(checks) == 1 and checks[0].block_key == 'work_orders'


@pytest.mark.parametrize('value', ['Sep 2026', 'September completed', '2026-09-14',
                                    'Sep / Oct', 'August', ''])
def test_invalid_or_reordered_band_fails_closed(value):
    table = changed(grid(), 2, 3, value)
    assert not _annual_work_order_month_cells('work_orders', table)
    assert periods(draft(table))


@pytest.mark.parametrize('table', [replace(grid(), rows=grid().rows[:-1]),
    replace(grid(), columns=grid().columns[:-1]),
    replace(grid(), rows=(*grid().rows, ('',) * 7)),
    replace(grid(), columns=(*grid().columns, 'Extra')), changed(grid(), 0, 0, 'September report'),
    changed(grid(), 4, 0, 'Other measure')])
def test_unknown_partial_schema_is_not_exempt(table):
    assert not _annual_work_order_month_cells('work_orders', table)
    assert periods(draft(table))


def test_identical_other_block_and_narrative_and_section_title_keep_date_checks():
    assert periods(draft(key='service_calls'))
    assert len(periods(draft(text='September work completed'))) == 1
    assert len(periods(draft(title='September report'))) == 1


def test_multiple_tables_and_repeated_bands_do_not_hide_actual_data():
    first = changed(grid(), 3, 2, 'September work completed')
    second = changed(grid(), 7, 4, 'August repair completed')
    d = draft(first)
    d = replace(d, blocks=(replace(d.blocks[0], extra_tables=(first, second)),))
    checks = periods(d)
    assert len(checks) == 2
    assert any('September' in c.message for c in checks)
    assert any('August' in c.message for c in checks)


def test_pricing_and_placeholder_gates_remain_in_structural_table():
    d = draft(changed(grid(), 3, 2, '$123.45'))
    assert any(c.code == 'pricing' and c.blocking for c in preflight(d))
    d = draft(changed(grid(), 3, 2, 'Insert image'))
    assert any(c.code == 'placeholder' and c.blocking for c in preflight(d))


@pytest.mark.parametrize('label', ['WO\nReceived', 'WO\r\nReceived', 'WO\tReceived',
                                  ' WO  Received ', 'WO\u00a0Received'])
def test_wrapped_measure_heading_preserves_structural_month_coordinates(label):
    table = changed(grid(), 0, 0, label)
    d = draft(table)
    before = d.fingerprint
    assert len(_annual_work_order_month_cells('work_orders', table)) == 24
    assert periods(d) == ()
    assert d.fingerprint == before
    assert d.blocks[0].extra_tables[0].columns[0] == label
    historical = changed(table, 3, 2, 'September work completed')
    assert len(periods(draft(historical))) == 1
    assert periods(draft(table, key='service_calls'))


@pytest.mark.parametrize('label', ['WO\nReceived September', 'WOReceived',
                                  'WO\n2026\nReceived', 'WO\nClosed'])
def test_wrapped_measure_heading_does_not_relax_identity(label):
    table = changed(grid(), 0, 0, label)
    assert not _annual_work_order_month_cells('work_orders', table)
    assert periods(draft(table))


def compact_grid():
    # The legacy editor removed the two entirely blank Jan–June value rows.
    table = changed(grid(), 0, 0, 'WO\nReceived')
    return replace(table, rows=tuple(table.rows[i] for i in (1, 2, 3, 5, 6)))


def test_exact_compact_saved_grid_labels_without_restoring_or_mutating_cells():
    table = compact_grid()
    d = draft(table)
    before = d.fingerprint
    assert len(_annual_work_order_month_cells('work_orders', table)) == 24
    assert periods(d) == ()
    assert d.fingerprint == before
    assert d.blocks[0].extra_tables[0] == table
    assert len(table.rows) == 5


@pytest.mark.parametrize('value', ['September repair completed', 'Sep 2026', '2026-09-14'])
@pytest.mark.parametrize('row', [2, 5])
def test_compact_saved_grid_real_values_remain_reviewable(value, row):
    assert len(periods(draft(changed(compact_grid(), row, 2, value)))) == 1


@pytest.mark.parametrize('table', [
    replace(compact_grid(), rows=compact_grid().rows[:-1]),
    replace(compact_grid(), rows=(*compact_grid().rows, ('',) * 7)),
    replace(compact_grid(), columns=(*compact_grid().columns, 'Extra')),
    changed(compact_grid(), 1, 2, 'September'),
    changed(compact_grid(), 3, 0, 'Other measure'),
    changed(compact_grid(), 4, 3, 'Sep 2026'),
])
def test_unknown_or_partial_compact_grid_still_warns(table):
    assert not _annual_work_order_month_cells('work_orders', table)
    assert periods(draft(table))


def test_compact_grid_other_blocks_and_pricing_placeholders_keep_gates():
    assert periods(draft(compact_grid(), key='service_calls'))
    assert periods(draft(compact_grid(), text='September work completed'))
    assert periods(draft(compact_grid(), title='September report'))
    for value, code in [('$123.45', 'pricing'), ('Insert image', 'placeholder')]:
        assert any(c.code == code and c.blocking for c in preflight(
            draft(changed(compact_grid(), 2, 2, value))))
