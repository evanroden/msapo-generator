"""Actual Monthly period controls and a native action; no report or saved data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import streamlit as st
from app.monthly_report_model import ReportPeriod
from app.monthly_report_setup import month_selector

st.set_page_config(layout='wide', initial_sidebar_state='collapsed')
st.title('Synthetic period loading')


def field(key, default):
    st.session_state.setdefault(key, default)
    return key


label = ('Synthetic original report with a long descriptive period label'
         if st.query_params.get('long_label') == '1' else 'Reporting')
period = month_selector(field, 'report', ReportPeriod(2026, 9), label=label)
st.space(900)


def received():
    st.session_state['presses'] = st.session_state.get('presses', 0) + 1
    st.session_state['received_period'] = (st.session_state['report_year'], st.session_state['report_month_number'])


st.button('Record synthetic action', key='period_action', on_click=received)
st.text('Native actions: ' + str(st.session_state.get('presses', 0)))
st.text('Received period: ' + str(st.session_state.get('received_period', ())))
st.space(400)
