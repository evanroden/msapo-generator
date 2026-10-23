"""Invented missing readings must not turn engineering columns into prices."""
from dataclasses import asdict, replace
from io import BytesIO

import pytest
from docx import Document

from app.monthly_report_content_policy import (
    _table_headings, ambiguous_price_columns, price_free_table,
    schema_price_columns, table_has_pricing, table_price_columns,
)
from app.monthly_report_import import inspect_docx
from app.monthly_report_master_tables import from_inspection
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, Facility, ReportDraft, ReportPeriod, ReportProfile,
    ReportTable, ResolvedBlock, default_sections,
)
from app.monthly_report_native_layout import build_native_docx
from conftest import requires_libreoffice


@pytest.mark.parametrize('dash', ('-', '–', '—', '  —  ', '\t-\n'))
@pytest.mark.parametrize('unit', ('Tons', 'MBH'))
def test_missing_reading_does_not_change_complete_engineering_heading(dash, unit):
    columns = ('Facility', f'Est. Peak Coincident Load ({unit})', 'Cost')
    rows = (('Demo Missing', dash, dash), ('Demo Reading', '2837', '9517'))
    before = (columns, rows)
    assert _table_headings(columns, rows)[1] == columns[1]
    assert table_price_columns(columns, rows) == (2,)
    assert schema_price_columns(columns, rows) == (2,)
    assert table_has_pricing(columns, rows)
    spec = BlockSpec('thermal_capacity', 'table', columns=tuple(
        ColumnSpec(str(i), title) for i, title in enumerate(columns)))
    block = ResolvedBlock('thermal_capacity', 'This month', rows=rows,
                          extra_tables=(ReportTable(columns, rows),))
    original = asdict(block)
    safe_spec, safe, removed = price_free_table(spec, block)
    assert tuple(c.title for c in safe_spec.columns) == columns[:2]
    assert safe.rows == tuple(row[:2] for row in rows)
    assert safe.extra_tables[0].rows == safe.rows
    assert removed == ('Cost',)
    assert asdict(block) == original and (columns, rows) == before


def test_split_headings_remain_inferred_around_missing_value_markers():
    columns = ('Facility', 'Est.', 'Unit')
    rows = (('', 'Peak Coincident Load (MBH)', 'Price'),
            ('Demo Missing', '—', '—'), ('Demo Reading', '2837', '9517'))
    assert table_price_columns(columns, rows) == (2,)
    assert schema_price_columns(columns, rows) == ()
    assert _table_headings(columns, rows)[1] == 'Est. Peak Coincident Load (MBH)'


@pytest.mark.parametrize('value', ('-12', '12–18', '$9517', 'Cost', 'Unit Price', '— Cost'))
def test_nonstandalone_dash_and_financial_continuations_are_not_ignored(value):
    columns = ('Facility', 'Est. Peak Coincident Load (MBH)')
    rows = (('Demo Missing', value), ('Demo Reading', '2837'))
    if any(c.isdigit() for c in value):
        assert _table_headings(columns, rows)[1] == columns[1]
        assert table_has_pricing(columns, rows) == value.startswith('$')
    else:
        assert value in _table_headings(columns, rows)[1]
        assert table_price_columns(columns, rows) == (1,)


@pytest.mark.parametrize('price', ('9517', '$9517', '—'))
def test_mixed_readings_never_hide_a_real_price_column(price):
    columns = ('Facility', 'Est. Peak Coincident Load (MBH)', 'Unit Price')
    rows = (('Demo Mixed', '—', price), ('Demo Reading', '2837', '9518'))
    assert table_price_columns(columns, rows) == (2,)
    assert schema_price_columns(columns, rows) == (2,)
    assert table_has_pricing(columns, rows)


def test_raw_currency_and_ambiguous_financial_guards_remain():
    engineering = ('Facility', 'Est. Peak Coincident Load (MBH)')
    rows = (('Demo Missing', '—'), ('Demo Reading', '2837'))
    assert schema_price_columns(engineering, rows, kinds=('text', 'currency')) == (1,)
    mixed = ('Facility', 'Description / Est. Peak Coincident Load (MBH) / Cost')
    assert ambiguous_price_columns(mixed, rows) == (1,)
    assert table_has_pricing(mixed, rows)
    for title in ('Cost / tons', 'Unit Price / kWh', 'Estimate', 'Amount', 'Rate'):
        assert table_price_columns(('Facility', title), rows) == (1,)


def _native_grid(tmp_path):
    columns = ('Campus', 'Capacity (MBH)', 'Available (MBH)',
               'Est. Peak Coincident Load (MBH)', 'Pressure (psi)', 'Units', 'Status')
    rows = (('Demo Missing', '—', '—', '—', '—', '—', '—'),) + tuple(
        (f'Demo Campus {i}', str(6000+i), str(5000+i), str(2837+i), str(100+i), '2', 'Ready')
        for i in range(1, 7))
    source = Document()
    source.add_heading('MONTHLY SCORECARDS', 1)
    source.add_paragraph('Steam')
    grid = source.add_table(rows=8, cols=7)
    for native_row, values in zip(grid.rows, (columns, *rows)):
        for cell, value in zip(native_row.cells, values):
            cell.text = value
    path = tmp_path / 'synthetic-steam.docx'
    source.save(path)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    item, = (item for item in inspection.items if item.kind == 'table')
    reference = f'docx:{inspection.sha256}:{item.id}'
    profile = ReportProfile('Synthetic contract', 'demo', 'Demo Plant',
                            (Facility('demo', 'Demo Plant'),))
    draft = ReportDraft(profile, ReportPeriod(2026, 10), 'Synthetic Editor', default_sections(), (
        ResolvedBlock('thermal_capacity', 'This month', extra_tables=(
            ReportTable(columns, rows, reference),)),), synthetic=True)
    before = asdict(draft)
    # Model the final client projection, not a destructive edit to the saved draft.
    _, client_block, _ = price_free_table(
        BlockSpec('thermal_capacity', 'table'), draft.blocks[0])
    raw = build_native_docx(replace(draft, blocks=(client_block,)), path)
    (tmp_path / 'generated.docx').write_bytes(raw)
    assert asdict(draft) == before and path.read_bytes() == original
    return raw, (columns, *rows)


def _assert_grid(raw, expected):
    tables = Document(BytesIO(raw)).tables
    assert len(tables) == 1
    actual = tuple(tuple(cell.text for cell in row.cells) for row in tables[0].rows)
    assert actual == expected  # All 56 cells, including heading, dash and six loads.


def test_saved_complete_grid_survives_native_projection_without_mutation(tmp_path):
    raw, expected = _native_grid(tmp_path)
    _assert_grid(raw, expected)
    shape, = from_inspection(inspect_docx(tmp_path / 'synthetic-steam.docx'))
    assert shape.indices == tuple(range(7))


@requires_libreoffice
def test_native_pdf_preserves_six_loads_and_missing_reading(tmp_path):
    import fitz
    from app.pdf_converter import convert_to_pdf

    raw, expected = _native_grid(tmp_path)
    pdf_path = convert_to_pdf(tmp_path / 'generated.docx')
    pdf_bytes = pdf_path.read_bytes()
    (tmp_path / 'generated.pdf').write_bytes(pdf_bytes)
    with fitz.open(stream=pdf_bytes, filetype='pdf') as pdf:
        text = '\n'.join(page.get_text() for page in pdf)
    for row in expected[2:]:
        assert row[3] in text
    assert '—' in text
    _assert_grid(raw, expected)


def _saved_legacy_import(monkeypatch, tmp_path):
    """Reproduce the old importer, then restore the real candidate policy."""
    import re
    from app import monthly_report_content_policy as policy
    from app import monthly_report_library as library
    from app.monthly_report_import import imported_draft
    from app.monthly_report_sections import build_section_import
    from app.monthly_report_setup import design_profile

    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    _, expected = _native_grid(tmp_path)
    path = tmp_path / 'synthetic-steam.docx'
    inspection = inspect_docx(path)
    items = tuple(item for item in inspection.items if item.kind == 'table')
    plans = ({'key': 'scorecards', 'target': 'scorecards', 'approved': True,
              'selected': [item.id for item in items]},)
    profile = ReportProfile('Synthetic replay contract', 'replay-demo', 'Demo Plant',
                            (Facility('demo', 'Demo Plant'),))
    period = ReportPeriod(2026, 10)

    def ingest():
        mapped, mappings = build_section_import(path, inspection, plans)
        return imported_draft(design_profile(profile, inspection, mappings),
                              period, 'Synthetic Editor', mapped)

    def legacy_headings(columns, rows):
        header_rows = [policy.logical_table_columns(columns)]
        for row in rows[:3]:
            if any(re.search(r'\d', str(cell)) for cell in row):
                break
            header_rows.append(row)
        return tuple(' '.join(row[i] for row in header_rows if i < len(row))
                     for i in range(len(columns)))

    with monkeypatch.context() as legacy:
        legacy.setattr(policy, '_table_headings', legacy_headings)
        old = ingest()
    library.save_report_setup(old.profile, old, path,
        {'sha256': inspection.sha256, 'period': period.key}, assets=(),
        expected_revision=0, actor='Synthetic Editor', confirmed=True,
        source_draft=old)
    note = ResolvedBlock('utility_analysis', 'This month',
                         text='Invented current authored note must survive replay.')
    current = replace(old, blocks=(*old.blocks, note))
    saved = library.save_snapshot(current, expected_revision=0,
                                  entered_editor='Synthetic Editor')
    restored = library.load_snapshot(profile.contract, profile.key, period)
    assert restored == saved
    previous, verified = library.starting_contribution(
        profile.contract, profile.key, period, inspection.sha256)
    assert verified and previous == old
    return path, expected, restored, previous, ingest(), note


def test_saved_six_column_draft_requires_explicit_verified_source_replay(monkeypatch, tmp_path):
    from app import monthly_report_library as library
    from app.monthly_report_start_replay import merge_starting_drafts

    path, expected, saved, previous, incoming, note = _saved_legacy_import(monkeypatch, tmp_path)
    original = path.read_bytes()
    before = asdict(saved)
    old_block = next(b for b in saved.draft.blocks if b.key == 'thermal_capacity')
    assert len(old_block.extra_tables[0].columns) == 6
    # Policy changes must not fabricate missing saved cells from source data.
    old_output = Document(BytesIO(build_native_docx(saved.draft, path)))
    assert len(old_output.tables[0].columns) == 6
    replayed = merge_starting_drafts(saved.draft, incoming, previous, verified=True)
    assert note in replayed.blocks
    _assert_grid(build_native_docx(replayed, path), expected)
    assert merge_starting_drafts(replayed, incoming, incoming, verified=True) == replayed
    updated = library.save_snapshot(replayed, expected_revision=saved.revision,
                                    entered_editor='Synthetic Editor')
    assert updated.revision == saved.revision + 1
    assert library.load_snapshot_version(saved.draft.profile.contract,
        saved.draft.profile.key, saved.draft.period, saved.revision) == saved
    assert asdict(saved) == before and path.read_bytes() == original
    assert library.imported_original(saved.draft.profile.contract,
        saved.draft.profile.key).read_bytes() == original


@pytest.mark.parametrize('conflict', ('manual_table_edit', 'unverified_contribution'))
def test_missing_column_replay_does_not_override_manual_edits_or_unverified_source(
        monkeypatch, tmp_path, conflict):
    from app.monthly_report_start_replay import merge_starting_drafts

    path, _, saved, previous, incoming, note = _saved_legacy_import(monkeypatch, tmp_path)
    current = saved.draft
    if conflict == 'manual_table_edit':
        block = next(b for b in current.blocks if b.key == 'thermal_capacity')
        table = block.extra_tables[0]
        edited = replace(table, rows=(('Invented manual campus edit', *table.rows[0][1:]),
                                      *table.rows[1:]))
        current = replace(current, blocks=tuple(
            replace(b, extra_tables=(edited,)) if b.key == block.key else b for b in current.blocks))
    before, source_bytes = asdict(current), path.read_bytes()
    with pytest.raises(ValueError, match='Thermal capacity differs'):
        merge_starting_drafts(current, incoming, previous,
                              verified=conflict != 'unverified_contribution')
    assert asdict(current) == before and note in current.blocks
    assert path.read_bytes() == source_bytes
