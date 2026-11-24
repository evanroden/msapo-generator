"""Invented data only. Shared compact navigation plus adaptive editor preview."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import streamlit as st
from app.web_ui import CUSTOM_CSS
from app.po_step_spine import po_step_spine, po_step_states
from app.monthly_report_step_spine import monthly_step_spine, monthly_step_states
from app.workspace_layout import workspace, workspace_section, workspace_columns
from app.reference_preview import render_reference
@st.cache_data
def synthetic_pdf():
    import pymupdf
    with pymupdf.open() as pdf:
        page=pdf.new_page()
        page.insert_text((40,70),'INVENTED PREVIEW - NOT CLIENT DATA')
        return pdf.tobytes()

st.set_page_config(layout='wide')
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
choice=st.segmented_control('Workflow', ['Purchase order','Expense reimbursement','Monthly report'],default='Purchase order',key='workflow_mode',label_visibility='collapsed')
if choice != 'Expense reimbursement':
    st.markdown(po_step_spine(po_step_states()) if choice=='Purchase order' else monthly_step_spine(monthly_step_states()),unsafe_allow_html=True)
with workspace({'Monthly report':'monthly','Purchase order':'po','Expense reimbursement':'expense'}[choice],'invented-duo-regression'):
    with workspace_section('duo_entry','Details'):
        st.subheader('Details')
        st.markdown('<div class="metric-card"><span class="metric-value">Invented total</span></div><div class="needs-banner">Review needed</div>',unsafe_allow_html=True)
        st.selectbox('Synthetic site',['Invented A','Invented B'])
        st.checkbox('Synthetic confirmed')
        st.date_input('Synthetic date')
        st.button('Synthetic primary',type='primary')
        edit,preview=workspace_columns('duo_entry')
        with edit:
            st.text_area('Synthetic notes',key='notes')
            st.text_input('Synthetic reference',key='reference')
        with preview:
            render_reference(key='duo',owner_scope='invented',title='Reference',raw=synthetic_pdf(),filename='synthetic.pdf')
