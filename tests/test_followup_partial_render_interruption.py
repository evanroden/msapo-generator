"""Refs #280: a live callback survives an interruption before its control re-registers.

The seam stops the render just before the source picker registers again, so
the picker on screen still names the original row. Its later delivery is
written exactly as the shared on_change callback writes it. Synthetic only.
"""
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, ReportSource, synthetic_profiles
from app.monthly_report_sources import source_reference

SCRIPT = '''
import streamlit as st
from app import monthly_report_followups as followups
from app import monthly_report_issues as issues
from app.monthly_report_ui import _field
if st.session_state.pop('stop_before_sources', False):
    real = issues._issue_control
    def interrupted(widget, *args, **kwargs):
        if widget is st.multiselect:
            st.stop()
        return real(widget, *args, **kwargs)
    issues._issue_control = interrupted
    try:
        followups.render_followups(st.session_state['draft'], 'partial', _field,
                                   category='proposal', defer_commit=True)
    finally:
        issues._issue_control = real
result = followups.render_followups(st.session_state['draft'], 'partial', _field,
                                    category='proposal', defer_commit=True)
st.session_state['draft'] = result
followups.acknowledge_followup_controls(result, 'partial')
'''


def test_a_source_choice_made_before_its_picker_reregisters_is_applied_with_the_reapplied_edit():
    source = ReportSource('independent', 'independent-evidence.txt', 'b' * 64, '.txt',
                          page_texts=('First inspection.', 'Separate second inspection.'))
    item = ReportFollowUp('row-one', 'proposal', 'Inspect intake damper.', '2026-10', status='pending')
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10), 'Synthetic editor',
                        (), (), sources=(source,), follow_ups=(item,), synthetic=True)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['draft'] = draft
    app.run()
    next(button for button in app.button if button.label == 'Update proposal').click().run()
    assert not app.exception
    picker = next(key for key in app.session_state.filtered_state
                  if '_sources_' in key and key.endswith('_delivery'))
    registration = app.session_state[picker]  # the original row's registration
    # The description edit is captured, then the render stops before the picker re-registers.
    app.session_state['stop_before_sources'] = True
    next(widget for widget in app.text_area if widget.value == item.text).set_value('Inspect both intake dampers.').run()
    assert not app.exception
    assert app.session_state[picker] == registration
    # The picker still on screen delivers against the row it was registered for.
    control, selected = picker.removesuffix('_delivery'), [source_reference(source, 2)]
    app.session_state[control] = selected
    app.session_state[control + '_change'] = {
        'identity': registration['identity'], 'token': registration['token'],
        'before': registration['before'], 'value': selected,
        'source_labels': registration['source_labels']}
    app.run()
    assert not app.exception
    current = app.session_state['draft'].follow_ups[0]
    assert current.text == 'Inspect both intake dampers.'
    assert current.references == tuple(selected), 'The live selection is applied, not set aside.'
    assert not any('Earlier proposal input' in str(widget.label) for widget in app.expander)
