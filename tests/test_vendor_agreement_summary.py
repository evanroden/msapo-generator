from streamlit.testing.v1 import AppTest
from app.monthly_report_contact_cards_ui import _vendor_summary


def test_literal_imported_vendor_and_agreement_values():
    cols=('Discipline','Example Hospital','MSA')
    assert _vendor_summary(cols,('HVAC','Example Vendor','X'),'HVAC') == 'HVAC · Example Hospital: Example Vendor · MSA: X'
    assert _vendor_summary(cols,('Electrical','Example Vendor',''),'Electrical') == 'Electrical · Example Hospital: Example Vendor · MSA: Not provided'
    assert _vendor_summary(('Vendor','MSA'),('Example Vendor','In progress'),'Example Vendor') == 'Example Vendor · MSA: In progress'
    assert _vendor_summary(('Vendor','MSA'),('Vendor',False),'Vendor') == 'Vendor · MSA: False'


def test_vendor_cards_show_status_without_changing_table():
    app=AppTest.from_string('''
import streamlit as st
from app.monthly_report_model import ReportTable
from app.monthly_report_contact_cards_ui import edit_contact_tables
from app.monthly_report_visual_ui import _contact_label
original=ReportTable(('Discipline','Example Hospital','MSA'),(('HVAC','Example Vendor','X'),('Electrical','Other Vendor','')),'synthetic:test')
def field(k,v):
    st.session_state.setdefault(k,v)
    return k
result,_=edit_contact_tables((original,), 'vendor_summary_test',field,_contact_label,vendor=True)
st.session_state['same']=result==(original,)
''').run()
    assert not app.exception
    assert app.session_state['same']
    text=' '.join(x.value for x in app.markdown)
    assert 'Example Hospital: Example Vendor' in text and 'MSA: X' in text
    assert 'Example Hospital: Other Vendor' in text and 'MSA: Not provided' in text
    app.run()
    assert app.session_state['same'] and not app.exception
