"""Imported work-order blank rows survive native editing without migration."""
from dataclasses import replace
from io import BytesIO

from docx import Document
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportTable, ResolvedBlock
from app.monthly_report_native_layout import _table

APP = '''
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec
from app.monthly_report_ui import _field
if not st.session_state.get('show',True):
    st.stop()
b=st.session_state['block']
st.session_state['block']=_edit_content(BlockSpec(b.key,'rich_text'),b,None,'row_probe',{},_field)
'''


def table():
    first=('Jan','Feb','Mar','Apr','May','June')
    second=('July','Aug','Sep','Oct','Nov','Dec')
    return ReportTable(('WO\nReceived',*first), (
        ('',)*7, ('',*second), ('','Pending','Pending','Pending','','',''),
        ('Closed',*first), ('',)*7, ('',*second),
        ('','Pending','Pending','Pending','','','')), 'synthetic:annual')


def launch(t=None, key='work_orders'):
    a=AppTest.from_string(APP)
    a.session_state['block']=ResolvedBlock(key,'Last month',extra_tables=(t or table(),))
    a.run()
    assert not a.exception
    return a


def current(a):
    return a.session_state['block'].extra_tables[0]


def edit(a, *, edited=None, added=None, deleted=None):
    key=next(k for k,v in a.session_state.filtered_state.items()
             if k.startswith('row_probe_edit_') and isinstance(v,dict) and 'edited_rows' in v)
    a.session_state[key]={'edited_rows':edited or {},'added_rows':added or [],'deleted_rows':deleted or []}
    a.run()
    assert not a.exception


def native_rows(t):
    document=Document()
    native=document.add_table(rows=8,cols=7)
    _table(native._tbl,t.columns,t.rows)
    raw=BytesIO();document.save(raw);raw.seek(0)
    return tuple(tuple(c.text for c in r.cells) for r in Document(raw).tables[0].rows)


def test_noop_and_rerun_preserve_original_rows_and_native_output():
    original=table();a=launch(original)
    assert current(a)==original
    a.run();assert not a.exception
    assert current(a)==original
    assert native_rows(current(a))==(original.columns,*original.rows)


def test_value_edit_preserves_other_blank_rows_and_native_output():
    a=launch();edit(a,edited={0:{'Jan':'42'}})
    expected=list(table().rows);expected[0]=('','42','','','','','')
    assert current(a).rows==tuple(expected)
    assert native_rows(current(a))==(table().columns,*expected)
    a.run();assert current(a).rows==tuple(expected)


def test_explicit_delete_and_add_are_not_restored_or_filtered():
    a=launch();edit(a,deleted=[0])
    assert current(a).rows==table().rows[1:]
    assert len(native_rows(current(a)))==7
    a=launch();edit(a,added=[dict.fromkeys(table().columns,'')])
    assert current(a).rows==(*table().rows,('',)*7)
    assert len(native_rows(current(a)))==9
    a=launch();edit(a,deleted=list(range(7)))
    assert current(a).rows==()
    a.run();assert current(a).rows==()


def test_empty_artificial_seed_is_not_content_but_explicit_added_rows_are():
    a=launch(replace(table(),rows=()))
    assert current(a).rows==()
    a.run();assert current(a).rows==()
    edit(a,added=[{'Jan':'9'}])
    assert current(a).rows==(('', '9','','','','',''),)
    a.run();assert current(a).rows==(('', '9','','','','',''),)
    a=launch(replace(table(),rows=()))
    edit(a,deleted=[0],added=[dict.fromkeys(table().columns,'')])
    assert current(a).rows==(('',)*7,)


def test_saved_compact_table_is_not_silently_restored_and_other_blocks_unchanged():
    compact=replace(table(),rows=tuple(r for r in table().rows if any(r)))
    assert current(launch(compact))==compact
    assert len(current(launch(key='utility_analysis')).rows)==5


def test_artificial_slot_deleted_or_filled_stays_retired_after_unmount():
    for added in [dict.fromkeys(table().columns,''), {'Jan':'9'}]:
        a=launch(replace(table(),rows=()))
        edit(a,deleted=[0],added=[added])
        expected=current(a)
        a.session_state['show']=False;a.run();assert not a.exception
        a.session_state['show']=True;a.run();assert not a.exception
        assert current(a)==expected
    a=launch(replace(table(),rows=()))
    edit(a,edited={0:{'Jan':'9'}})
    a.session_state['show']=False;a.run()
    a.session_state['show']=True;a.run()
    edit(a,edited={0:{'Jan':''}})
    assert current(a).rows==(('',)*7,)


def test_untouched_artificial_slot_does_not_become_content_on_reopen():
    for added in [None, {'Jan':'9'}]:
        a=launch(replace(table(),rows=()))
        if added:
            edit(a,added=[added])
        expected=current(a)
        a.session_state['show']=False;a.run();assert not a.exception
        a.session_state['show']=True;a.run();assert not a.exception
        assert current(a)==expected
