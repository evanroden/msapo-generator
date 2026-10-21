"""An interrupted render must not make a delivered edit require a totals retry.

AppTest retains the prior native button across the interruption. Browser timing
and physical-device acceptance remain separate from this server regression.
"""
from dataclasses import replace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided
from test_monthly_report_activity_intake_commit import APP, activity, draft, editor
from test_monthly_report_activity_review_guards import workorder_app


def interrupted_edit(monkeypatch, tmp_path, manual, *, unrelated=None):
    app, _, original_uploader = workorder_app(monkeypatch, tmp_path)
    editor(app).set_value('Initial operator wording.').run()
    accept = next(b for b in app.button if b.label == 'Add totals to summary')
    render = guided._render_ordered_section

    def stop_before_activity(report, section, *args, **kwargs):
        if section.key == 'activity':
            st.stop()
        return render(report, section, *args, **kwargs)

    # The working draft commits the delivered edit before section rendering.
    # A premature stop retains native widget metadata and the old callback;
    # unlike st.rerun(), it does not clean up unrendered widgets.
    monkeypatch.setattr(guided, '_render_ordered_section', stop_before_activity)
    editor(app).set_value(manual).run()
    assert not app.exception and activity(app).text == manual
    if unrelated is not None:
        current = draft(app)
        key = next(k for k, v in app.session_state.filtered_state.items()
                   if k.endswith('_draft') and v == current)
        app.session_state[key] = replace(current, blocks=tuple(
            replace(b, text=unrelated) if b.key == 'activity_summary' else b
            for b in current.blocks))
    monkeypatch.setattr(guided, '_render_ordered_section', render)
    accept.click().run()
    assert not app.exception
    return app, original_uploader


@pytest.mark.parametrize('manual', [
    'Operator confirmed the isolation remains in place.',
    '',
    '  Deliberate leading spaces and a trailing newline.\n',
])
def test_totals_accept_delivered_edit_after_interrupted_render(monkeypatch, tmp_path, manual):
    app, original_uploader = interrupted_edit(monkeypatch, tmp_path, manual)
    expected = activity(app).text
    assert expected.startswith(manual + '\n\n' if manual else 'October 2026')
    assert expected.count('2 total, 1 completed, 1 open') == 1
    assert editor(app).value == expected
    assert not any('report changed after you reviewed' in w.value for w in app.warning)
    assert not any(b.label == 'Apply interrupted edit' for b in app.button)

    monkeypatch.setattr(st, 'file_uploader', original_uploader)
    resumed = AppTest.from_string(APP, default_timeout=45).run()
    assert not resumed.exception
    assert activity(resumed).text == expected and editor(resumed).value == expected


def test_interrupted_old_control_still_refuses_unrelated_newer_wording(monkeypatch, tmp_path):
    newer = 'A separately recovered revision must remain untouched.'
    app, _ = interrupted_edit(monkeypatch, tmp_path, 'Delivered manual edit.', unrelated=newer)
    assert activity(app).text == newer
    assert any('report changed after you reviewed' in w.value for w in app.warning)
