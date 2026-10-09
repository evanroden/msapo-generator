from streamlit.testing.v1 import AppTest


APP = '''
import streamlit as st
from app.monthly_report_model import ReportTable
from app.monthly_report_ui import _field
from app.monthly_report_table_review_ui import review_table_headings
from app.monthly_report_content_policy import table_has_pricing
original = ReportTable(('Equipment Description End of Useful Cost Summary of deficiency Life', 'Column 2', 'Column 3', 'Column 4'), (('Synthetic pump', '2030', '$500', 'Worn casing'),))
old = st.session_state.get('saved', original)
result = review_table_headings(old, 'report_table_review', _field)
st.session_state['saved'] = result
st.session_state['original'] = original
st.session_state['blocked'] = table_has_pricing(result.columns, result.rows)
'''


def test_ambiguous_columns_stay_intact_until_names_confirmed():
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert app.session_state['saved'].rows[0][0] == 'Synthetic pump'
    assert app.session_state['blocked']
    assert app.button[0].disabled
    for control, title in zip(app.text_input, ('Equipment', 'Replacement timing', 'Cost', 'Recommendation')):
        control.set_value(title)
    app.run()
    assert app.session_state['blocked']
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state['saved'].rows == (('Synthetic pump', '2030', 'Worn casing'),)
    assert app.session_state['original'].rows[0][2] == '$500'
    assert not app.session_state['blocked']
    app.run()
    assert app.session_state['saved'].columns == ('Equipment', 'Replacement timing', 'Recommendation')
    assert not app.text_input


def test_import_editor_reuses_corrected_schema_without_replaying_old_cells():
    script = '''
import streamlit as st
from pathlib import Path
from app.monthly_report_model import ReportPeriod
from app.monthly_report_import import ImportItem
from app.monthly_report_sections import ImportSection
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field
item = ImportItem('table', 'table', 'word/document.xml', 1, 1, 'capital', rows=(('Equipment Description End of Useful Cost Summary of deficiency Life', '', '', ''), ('Synthetic pump', '2030', '$500', 'Worn casing')))
plans = st.session_state.setdefault('plans', {})
_section_card(ImportSection('capital', 'Equipment plans', (item,)), Path('synthetic.docx'), None, ReportPeriod(2026,9), 'report_header', _field, plans, True)
'''
    app = AppTest.from_string(script).run()
    app.radio[0].set_value('Edit text or change pictures').run()
    assert not app.exception
    for control, title in zip([w for w in app.text_input if w.label.endswith('heading')], ('Equipment', 'Replacement timing', 'Cost', 'Recommendation')):
        control.set_value(title)
    app.run()
    next(b for b in app.button if b.label == 'Use these column names').click().run()
    app.run()
    assert not app.exception
    table = app.session_state['plans']['capital']['tables']['table']
    assert table.columns == ('Equipment', 'Replacement timing', 'Recommendation')
    assert table.rows == (('Synthetic pump', '2030', 'Worn casing'),)
