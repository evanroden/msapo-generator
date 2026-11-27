"""Retained Chromium request fields and Close share the original empty snapshot."""
from dataclasses import replace
import pytest
import streamlit as st
from app import monthly_report_row_cards_ui as cards
from test_monthly_report_row_cards_ui import workspace,button


@pytest.mark.parametrize('extra',[False,True])
@pytest.mark.parametrize('acknowledged',[False,True])
@pytest.mark.parametrize('independent',[False,True])
def test_new_request_stale_close_keeps_delivered_values(monkeypatch,acknowledged,independent,extra):
    app=workspace('rfi_matrix',(),extra=extra)
    original=app.session_state['block']
    def with_rows(rows):
        return (replace(original,extra_tables=(replace(original.extra_tables[0],rows=rows),))
                if extra else replace(original,rows=rows))
    def rows():
        block=app.session_state['block']
        return block.extra_tables[0].rows if extra else block.rows
    button(app,'Add request').click().run()
    state=dict(app.session_state.filtered_state)
    key=next(k for k,v in state.items() if isinstance(v,dict) and v.get('group_args'))
    expected,tokens,token,fields=state[key]['group_args']
    with monkeypatch.context() as patch:
        patch.setattr(st,'session_state',state)
        state[fields[0][0]]='Synthetic North'
        cards._queue(key,expected,tokens,token,fields,group=(key,))
        first=state[key]['pending']['result']
    app.session_state[key]=state[key]
    app.session_state[fields[0][0]]='Synthetic North'
    if acknowledged:app.session_state['block']=with_rows(first)
    app.run()
    state=dict(app.session_state.filtered_state)
    with monkeypatch.context() as patch:
        patch.setattr(st,'session_state',state)
        state[fields[1][0]]='Synthetic complete request scope.'
        cards._queue(key,expected,tokens,token,fields,group=(key,))
        cards._queue(key,expected,tokens,token,fields,'close',group=(key,))
    app.session_state[key]=state[key]
    if independent:app.session_state['block']=with_rows((('Other','Independent request.',''),))
    app.run()
    assert not app.exception
    if independent:
        assert any('Both versions are kept' in x.value for x in app.warning)
        assert rows()==(('Other','Independent request.',''),)
    else:
        assert not app.warning and not app.text_input and not app.text_area
        assert rows()==(('Synthetic North','Synthetic complete request scope.',''),)
