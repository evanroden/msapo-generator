"""Synthetic native Word continuation rows must not become invented headings."""
from dataclasses import replace
from io import BytesIO
from docx import Document
import pytest
from app.monthly_report_import import ImportItem,inspect_docx
from app.monthly_report_sections import table_without_prices
from app.monthly_report_checks import preflight
from app.monthly_report_model import ReportDraft,ReportProfile,Facility,ReportPeriod,ResolvedBlock,default_sections


def _draft(table):
    section=replace(next(s for s in default_sections() if s.key=='rfi'),included=True)
    profile=ReportProfile('Synthetic continuation','north','Synthetic North',(Facility('north','Synthetic North'),))
    return ReportDraft(profile,ReportPeriod(2026,11),'Synthetic reviewer',(section,),(ResolvedBlock('rfi_matrix','This month',extra_tables=(table,)),),synthetic=True)


@pytest.mark.parametrize('rows',[
    (('16','Training program',''),('17','Electrical diagram','X')),
    (('17','Permits','X'),('18','Safety plan','X')),
    (('16','Price: $250',''),('17','Electrical diagram','X')),
])
def test_explicit_data_first_row_is_preserved_and_gated(rows):
    item=ImportItem('continuation','table','word/document.xml',2,1,'rfi','rfi_matrix',rows=rows,table_row_roles=('data','data'))
    table,removed=table_without_prices(item)
    assert table.columns==() and table.rows==rows and removed==()
    assert item.rows==rows
    checks=preflight(_draft(table))
    assert any(c.code=='table_missing_columns' and c.blocking for c in checks)
    if '$250' in str(rows):assert any(c.code=='pricing' and c.blocking for c in checks)


def test_native_two_frame_source_keeps_the_continuation_first_record(tmp_path):
    doc=Document();doc.add_heading('RFI Matrix',1)
    for rows in [ (('#','Requested Items','Synthetic North'),('15','Service history','')), (('16','Training program',''),('17','Electrical diagram','X')) ]:
        t=doc.add_table(rows=0,cols=3)
        for row in rows:
            for c,text in zip(t.add_row().cells,row):c.text=text
    path=tmp_path/'synthetic-continuation.docx';doc.save(path);original=path.read_bytes()
    inspected=inspect_docx(path);items=[i for i in inspected.items if i.kind=='table']
    assert len(items)==2 and items[1].table_row_roles[0]=='data'
    first,_=table_without_prices(items[0]);tail,_=table_without_prices(items[1])
    assert first.columns==('#','Requested Items','Synthetic North')
    assert tail.columns==() and tail.rows[0]==('16','Training program','')
    assert tail.rows==items[1].rows
    assert path.read_bytes()==original


def test_explicit_header_and_metadata_free_legacy_inputs_keep_existing_behavior():
    rows=(('Item','Requested information','Status'),('16','Training program',''))
    item=ImportItem('headed','table','word/document.xml',2,1,'rfi','rfi_matrix',rows=rows,table_row_roles=('header','data'))
    for source in [item,replace(item,table_row_roles=())]:
        table,removed=table_without_prices(source)
        assert table.columns==rows[0] and table.rows==rows[1:] and removed==()


def test_reviewed_rfi_heading_repair_saves_reopens_and_exports_every_row(tmp_path,monkeypatch):
    from app import monthly_report_library as library
    from app.monthly_report_docx import assemble_docx
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'private-store'))
    rows=(('16','Training program',''),('17','Electrical diagram','X'))
    item=ImportItem('continuation','table','word/document.xml',2,1,'rfi','rfi_matrix',rows=rows,table_row_roles=('data','data'))
    raw,_=table_without_prices(item)
    blocked=_draft(raw)
    with pytest.raises(ValueError,match='no column headings'):
        assemble_docx(blocked,acknowledged_fingerprint=blocked.fingerprint)
    repaired=replace(raw,columns=('#','Requested Items','Synthetic North'))
    ready=_draft(repaired)
    assert not [c for c in preflight(ready) if c.code=='table_missing_columns']
    library.save_snapshot(ready,expected_revision=0)
    reopened=library.load_snapshot(ready.profile.contract,ready.profile.key,ready.period)
    assert reopened.draft.blocks==ready.blocks
    output=Document(BytesIO(assemble_docx(reopened.draft,acknowledged_fingerprint=reopened.draft.fingerprint)))
    exported=[tuple(c.text for c in row.cells) for row in output.tables[0].rows]
    assert exported==[repaired.columns,*rows]
    assert raw.columns==() and raw.rows==rows and item.rows==rows


EDITOR_APP = '''
import streamlit as st
from pathlib import Path
from app.monthly_report_import import ImportItem
from app.monthly_report_sections import ImportSection
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field
from app.monthly_report_model import ReportPeriod
rows=st.session_state.get('source_rows',(('16','Training program',''),('17','Electrical diagram','X')))
item=ImportItem('continuation','table','word/document.xml',2,1,'rfi','rfi_matrix',rows=rows,table_row_roles=tuple('data' for row in rows))
plans=st.session_state.setdefault('plans',{})
_section_card(ImportSection('rfi','Information requests',(item,)),Path('synthetic.docx'),None,ReportPeriod(2026,11),'continuation',_field,plans,True)
'''


@pytest.mark.parametrize('mode',['Keep and review','Edit text or change pictures'])
def test_actual_section_card_keeps_unresolved_rows_blocked_until_explicit_headings(mode,tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_library as library
    from app.monthly_report_docx import assemble_docx
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'private-store'))
    app=AppTest.from_string(EDITOR_APP).run()
    app.radio[0].set_value(mode).run()
    assert not app.exception
    original=(('16','Training program',''),('17','Electrical diagram','X'))
    def plan():return app.session_state['plans']['rfi']
    def table():return plan()['tables']['continuation']
    assert table().columns==() and table().rows==original
    assert not plan()['approved']
    assert all(frame.proto.id=='' for frame in app.dataframe)
    for headings in [('#','','Status'),('#','Item','#')]:
        for control,title in zip(app.text_input,headings):control.set_value(title)
        app.run()
        assert next(b for b in app.button if b.label=='Use these column names').disabled
        assert table().rows==original and table().columns==()
    for control,title in zip(app.text_input,('#','Requested Items','Synthetic North')):control.set_value(title)
    app.run()
    assert table().columns==() and not plan()['approved']
    next(b for b in app.button if b.label=='Use these column names').click().run()
    app.run()
    assert not app.exception
    assert table().columns==('#','Requested Items','Synthetic North')
    assert table().rows==original and plan()['approved']
    ready=_draft(table())
    library.save_snapshot(ready,expected_revision=0)
    reopened=library.load_snapshot(ready.profile.contract,ready.profile.key,ready.period).draft
    assert reopened.blocks==ready.blocks
    output=Document(BytesIO(assemble_docx(reopened,acknowledged_fingerprint=reopened.fingerprint)))
    assert [tuple(c.text for c in row.cells) for row in output.tables[0].rows]==[table().columns,*original]


def test_heading_repair_does_not_hide_price_or_rewrite_source_rows():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string(EDITOR_APP)
    rows=(('16','Price: $250',''),('17','Electrical diagram','X'))
    app.session_state['source_rows']=rows
    app.run()
    app.radio[0].set_value('Edit text or change pictures').run()
    for control,title in zip(app.text_input,('#','Requested Items','Synthetic North')):control.set_value(title)
    app.run()
    next(b for b in app.button if b.label=='Use these column names').click().run()
    app.run()
    plan=app.session_state['plans']['rfi']
    assert plan['tables']['continuation'].rows==rows
    assert not plan['approved']
    assert any('pricing' in node.value for node in app.error)
