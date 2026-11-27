"""Synthetic direct source emphasis, not inferred past-due classification."""
from dataclasses import asdict, replace
from io import BytesIO
import pytest
from docx import Document
from app.monthly_report_import import inspect_docx
from app.monthly_report_sections import table_without_prices
from app.monthly_report_library import _report_table_from_dict
from app.monthly_report_model import (EmphasizedTable, ReportTable, ReportDraft,
    ReportPeriod, ResolvedBlock, SectionSpec, BlockSpec, synthetic_profiles)
from app.monthly_report_docx import _build_docx


def source(tmp_path, *, mixed=False, revision=False):
    doc = Document()
    table = doc.add_table(rows=3, cols=2)
    for row, values in zip(table.rows, [('Equipment','Status'),('Synthetic A','Review'),('Synthetic B','OK')]):
        for cell, text in zip(row.cells, values):
            cell.text = text
    for cell in table.rows[1].cells:
        for run in cell.paragraphs[0].runs:
            run.bold = True
    if mixed:
        table.rows[1].cells[1].paragraphs[0].runs[0].bold = False
    if revision:
        from docx.oxml import OxmlElement
        table.rows[1].cells[0]._tc.append(OxmlElement('w:del'))
    path = tmp_path / 'synthetic.docx'
    doc.save(path)
    return path


def test_exact_source_rows_and_saved_metadata(tmp_path):
    path = source(tmp_path)
    item = next(i for i in inspect_docx(path).items if i.kind == 'table')
    assert item.table_bold_rows == (1,)
    table, removed = table_without_prices(item)
    assert not removed and type(table) is EmphasizedTable
    assert table.bold_rows == ((0, ('Synthetic A', 'Review')),)
    assert _report_table_from_dict(asdict(table)) == table
    assert type(_report_table_from_dict(asdict(ReportTable(table.columns, table.rows)))) is ReportTable


@pytest.mark.parametrize('mixed,revision', [(True,False),(False,True)])
def test_mixed_and_revision_rows_not_promoted(tmp_path, mixed, revision):
    item = next(i for i in inspect_docx(source(tmp_path,mixed=mixed,revision=revision)).items if i.kind == 'table')
    assert item.table_bold_rows == ()


def render(table):
    spec = BlockSpec('thermal_capacity', 'table')
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026,9), 'Synthetic Editor',
        (SectionSpec('scorecards','1','Scorecards',(spec,)),),
        (ResolvedBlock('thermal_capacity','This month',extra_tables=(table,)),))
    return Document(BytesIO(_build_docx(draft)))


def test_output_bold_only_for_unchanged_source_cells(tmp_path):
    item = next(i for i in inspect_docx(source(tmp_path)).items if i.kind == 'table')
    table, _ = table_without_prices(item)
    doc = render(table)
    target = next(t for t in doc.tables if t.cell(0,0).text == 'Equipment')
    assert all(run.bold for cell in target.rows[1].cells for p in cell.paragraphs for run in p.runs)
    assert not any(run.bold for cell in target.rows[2].cells for p in cell.paragraphs for run in p.runs)
    edited = replace(table, rows=(('Synthetic revised','Pending'),table.rows[1]))
    target = next(t for t in render(edited).tables if t.cell(0,0).text == 'Equipment')
    assert not any(run.bold for cell in target.rows[1].cells for p in cell.paragraphs for run in p.runs)


@pytest.mark.parametrize('entry', [[99,['a','b']], [True,['a','b']], [0,['a']], [0,['a',1]]])
def test_invalid_saved_metadata_rejected(entry):
    with pytest.raises(ValueError):
        _report_table_from_dict({'columns':['A','B'],'rows':[['a','b']],'bold_rows':[entry]})


def test_raw_revision_markup_is_not_promoted():
    from app.monthly_report_word_table_bands import explicit_bold_rows
    from docx.oxml import OxmlElement
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    table.cell(0,0).text = 'Synthetic'
    table.cell(0,0).paragraphs[0].runs[0].bold = True
    assert explicit_bold_rows(table._tbl) == (0,)
    table.cell(0,0)._tc.append(OxmlElement('w:del'))
    assert explicit_bold_rows(table._tbl) == ()


def test_repeated_native_header_does_not_shift_emphasis():
    from app.monthly_report_import import ImportItem
    item = ImportItem('synthetic','table','word/document.xml',1,1,
        rows=(('A','B'),('one','x'),('A','B'),('two','y')),
        table_row_roles=('header','data','repeated_header','data'),table_bold_rows=(3,))
    table, _ = table_without_prices(item)
    assert table.rows == (('one','x'),('two','y'))
    assert table.bold_rows == ((1,('two','y')),)


def test_price_free_projection_keeps_only_nonprice_cells():
    from app.monthly_report_import import ImportItem
    item = ImportItem('synthetic','table','word/document.xml',1,1,section='proposals',
        rows=(('Description','Cost'),('Synthetic replacement','$500')),
        table_bold_rows=(1,))
    table, removed = table_without_prices(item)
    assert removed and table.columns == ('Description',)
    assert table.bold_rows == ((0,('Synthetic replacement',)),)
    assert '$' not in str(asdict(table))


def test_plain_table_historical_record_has_no_new_metadata():
    from app.monthly_report_model import AnchoredTable
    plain = ReportTable(('A',),(('x',),))
    anchored = AnchoredTable(('A',),(('x',),),anchor='Heading')
    assert asdict(plain) == {'columns':('A',),'rows':(('x',),),'reference':''}
    assert 'bold_rows' not in asdict(anchored)
    assert _report_table_from_dict(asdict(anchored)) == anchored


def test_native_edit_and_delete_retire_stale_emphasis_before_save():
    table = EmphasizedTable(('A','B'),(('one','x'),('two','y')),
                            bold_rows=((0,('one','x')),(1,('two','y'))))
    edited = replace(table, rows=(('changed','x'),('two','y')))
    assert edited.bold_rows == ((1,('two','y')),)
    assert _report_table_from_dict(asdict(edited)) == edited
    deleted = replace(table, rows=())
    assert deleted.bold_rows == ()
    assert _report_table_from_dict(asdict(deleted)) == deleted


def test_content_controlled_plain_row_cannot_shift_bold_identity(tmp_path):
    from docx.oxml import OxmlElement
    path = source(tmp_path)
    doc = Document(path)
    table = doc.tables[0]
    # Header, wrapped plain row, direct bold row.
    table.rows[1].cells[0].paragraphs[0].runs[0].bold = False
    table.rows[1].cells[1].paragraphs[0].runs[0].bold = False
    for cell in table.rows[2].cells:
        cell.paragraphs[0].runs[0].bold = True
    row = table.rows[1]._tr
    index = table._tbl.index(row)
    table._tbl.remove(row)
    control = OxmlElement('w:sdt')
    content = OxmlElement('w:sdtContent')
    content.append(row)
    control.append(content)
    table._tbl.insert(index, control)
    doc.save(path)
    item = next(i for i in inspect_docx(path).items if i.kind == 'table')
    assert item.table_bold_rows == (2,)
    table, _ = table_without_prices(item)
    assert table.bold_rows == ((1,('Synthetic B','OK')),)


@pytest.mark.parametrize('value', ['0', 'false', 'off'])
def test_explicitly_visible_bold_source_rows_keep_emphasis(tmp_path, value):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    path = source(tmp_path)
    doc = Document(path)
    for cell in doc.tables[0].rows[1].cells:
        hidden = OxmlElement('w:vanish')
        hidden.set(qn('w:val'), value)
        cell.paragraphs[0].runs[0]._r.get_or_add_rPr().append(hidden)
    doc.save(path)
    item = next(i for i in inspect_docx(path).items if i.kind == 'table')
    assert item.table_bold_rows == (1,)
    table, _ = table_without_prices(item)
    target = next(t for t in render(table).tables if t.cell(0,0).text == 'Equipment')
    assert all(run.bold for cell in target.rows[1].cells for p in cell.paragraphs for run in p.runs)


@pytest.mark.parametrize('value', [None, '1', 'true', 'on'])
def test_enabled_hidden_property_never_promotes_row(value):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from app.monthly_report_word_table_bands import explicit_bold_rows
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    table.cell(0,0).text = 'Synthetic'
    run = table.cell(0,0).paragraphs[0].runs[0]
    run.bold = True
    hidden = OxmlElement('w:vanish')
    if value is not None:
        hidden.set(qn('w:val'), value)
    run._r.get_or_add_rPr().append(hidden)
    assert explicit_bold_rows(table._tbl) == ()
