"""Keyed boundaries preserve widget values without calling business code."""
import subprocess
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.workspace_layout import _key

ROOT = Path(__file__).resolve().parents[1]


def test_owned_identifier_validation_rejects_selectors_and_private_labels():
    assert _key('monthly_activity') == 'monthly_activity'
    for value in ('x" onclick="oops','../../site','Monthly report','',None):
        with pytest.raises(ValueError):
            _key(value)


def test_workspace_keeps_one_editor_and_its_stable_key_across_reruns():
    app = AppTest.from_string('''
import streamlit as st
from app.workspace_layout import workspace, workspace_section, workspace_columns
with workspace('monthly','synthetic-identity'):
    with workspace_section('monthly_activity','Activity'):
        edit, reference = workspace_columns('monthly_activity')
        with edit:
            st.text_area('Work',key='canonical_work')
        with reference:
            st.text(st.session_state.get('canonical_work',''))
st.button('Unrelated rerun')
''').run()
    assert not app.exception
    assert len(app.text_area) == 1
    app.text_area[0].set_value('A current manual correction').run()
    app.button[0].click().run()
    assert not app.exception
    assert app.text_area[0].value == 'A current manual correction'
    assert len(app.text_area) == 1
    assert len(app.get('bidi_component')) == 1


@pytest.mark.parametrize('script', ['tests/workspace_geometry_test.cjs', 'tests/preview_view_lifecycle_test.cjs',
                                   'tests/source_review_navigation_test.cjs',
                                   'tests/workspace_navigation_test.cjs'])
def test_browser_logic_regressions_execute_in_node(script):
    result = subprocess.run(['node','--test',script],cwd=ROOT,text=True,capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
