"""Actual expense UI with invented inputs and forbidden external operations."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from datetime import date
from decimal import Decimal
from hashlib import sha256
import fitz
import streamlit as st
from app import expense_ui
from app.receipt_analyzer import ReceiptAnalysis

st.set_page_config(layout='wide')
def forbidden(*args,**kwargs):
    raise AssertionError('External action forbidden in synthetic expense fixture')
for name in ('start_receipt','prepare_receipt_content','analyze_prepared_receipt','_render_ios_mail_share','_remember_profile','build_expense_package'):
    setattr(expense_ui,name,forbidden)
expense_ui.account_director=lambda account:('Synthetic Director','director@example.invalid')
expense_ui.director_config_problems=lambda accounts:[]
if not st.session_state.get('_fixture_initialized'):
    account='Rochester Regional Health'
    token=sha256(account.encode()).hexdigest()[:10]
    st.session_state['expense_draft_snapshot']={
        f'expense_employee_name_{token}':'Synthetic Employee',
        f'expense_employee_number_{token}':'00042',
        f'expense_approver_name_{token}':'Synthetic Director',
        f'expense_approver_email_{token}':'director@example.invalid',
        f'expense_manager_name_{token}':'Synthetic Manager',
        f'expense_manager_email_{token}':'manager@example.invalid',
    }
    files=[]
    if st.query_params.get('mileage_only')!='1':
        for index in (1,2):
            with fitz.open() as doc:
                for page in (1,2):
                    doc.new_page().insert_text((72,72),f'Synthetic receipt {index}; original page {page}')
                raw=doc.tobytes()
            digest=sha256(raw).hexdigest()
            files.append((f'synthetic-receipt-{index}.pdf',raw,'application/pdf'))
            st.session_state[f'expense_receipt_analysis_{digest}']=ReceiptAnalysis(
                merchant_name=f'Synthetic merchant {index}',transaction_date=date(2026,9,10),
                total_amount='24.50',currency='USD',suggested_description='Synthetic business supplies',confidence='high')
    st.session_state['expense_receipt_files']=files
    st.session_state['_fixture_initialized']=True
st.session_state['_fixture_full_runs']=st.session_state.get('_fixture_full_runs',0)+1
st.caption(f"Synthetic full app runs: {st.session_state['_fixture_full_runs']}")
expense_ui.render_expense_workflow('','America/New_York')
expense_ui.preserve_expense_draft_state()
