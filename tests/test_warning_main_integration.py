"""Interactions of reviewed warning routes with merged-main owner hydration."""
from datetime import date
import pytest
from streamlit.testing.v1 import AppTest
from test_monthly_report_mbcx_financial_pages import APP


@pytest.mark.parametrize('prior_consent',[False,True])
def test_financial_native_choice_mirror_hide_date_change_clear_never_grants(monkeypatch,tmp_path,prior_consent):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    script=APP.replace('import streamlit as st','''import streamlit as st
from datetime import date
from app.monthly_report_ui import preserve_report_draft_state,restore_report_draft_state
preserve_report_draft_state();restore_report_draft_state()''')
    script=script.replace('period=ReportPeriod(2026,9)', '''chosen=st.date_input('Synthetic report month',value=date(2026,9,1))
period=ReportPeriod(chosen.year,chosen.month)''')
    before,body=script.split('handled,c,batch=',1)
    script=before+"if st.checkbox('Show existing financial editor',value=True):\n"+'\n'.join('    '+line for line in ('handled,c,batch='+body).splitlines())+'\npreserve_report_draft_state(finalize=True)\n'
    app=AppTest.from_string(script).run()
    def check(label):return next(w for w in app.checkbox if w.label==label)
    def pages():return next(w for w in app.multiselect if w.label=='Pages to review together')
    check('Review client-facing ENFRA financial pages').check().run()
    original=app.session_state['content']
    pages().set_value([1]).run()
    key=pages().key
    assert key in app.session_state['report_widget_keys']
    assert app.session_state['report_draft_mirror'][key]==[1]
    if prior_consent:
        check('This is an ENFRA report intended for the client').check().run()
        next(w for w in app.checkbox if w.label.startswith('I reviewed these pages:')).check().run()
    check('Show existing financial editor').uncheck().run();app.run()
    check('Show existing financial editor').check().run()
    assert pages().value==[1] and list(pages().proto.default)==[0]
    assert app.session_state['content']==original
    next(w for w in app.date_input if w.label=='Synthetic report month').set_value(date(2026,10,1)).run()
    assert not app.exception
    assert pages().value==[1] and list(pages().proto.default)==[0]
    assert not check('This is an ENFRA report intended for the client').value
    assert not next(w for w in app.checkbox if w.label.startswith('I reviewed these pages:')).value
    assert next(b for b in app.button if b.label=='Include reviewed financial pages').disabled
    pages().set_value([]).run()
    check('Show existing financial editor').uncheck().run();app.run()
    check('Show existing financial editor').check().run()
    assert not app.exception
    assert pages().value==[] and list(pages().proto.default)==[]
    assert app.session_state['report_draft_mirror'][key]==[]
    assert app.session_state['content']==original
    assert not original.source.financial_page_reviews and original.source.financial_source_review is None
    assert not app.session_state.filtered_state.get('blocks',{})
