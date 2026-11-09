"""Empty photo intake reserves only its native, collapsed-label skeleton."""
import hashlib

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_native_loading as loading
from app.monthly_report_model import ResolvedBlock
from test_monthly_photo_disclosures import photo_app


def css_for(visibility, selected=False):
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_native_loading import reserve_empty_uploader
if st.session_state.get('selected'):
    st.session_state['photo_upload'] = ['existing file']
reserve_empty_uploader('photo_upload', 'Progress photos',
                       label_visibility=st.session_state['visibility'])
''')
    app.session_state['visibility'] = visibility
    app.session_state['selected'] = selected
    app.run()
    assert not app.exception
    return [item.proto.body for item in app.get('html')]


def test_collapsed_label_reserves_dropzone_only_at_both_widths():
    css, = css_for('collapsed')
    assert '::before' not in css and 'Progress photos' not in css
    assert '::after{content:"";display:block;height:4.25rem;}' in css
    assert '(width < 23rem)' in css and '::after{height:6.15rem;}' in css
    assert '.st-key-photo_upload > [data-testid="stSkeleton"]' in css
    assert '<input' not in css and 'scroll' not in css


def test_visible_label_retains_exact_existing_styles():
    css, = css_for('visible')
    # Frozen baseline bytes protect existing shared source upload slots.
    assert hashlib.sha256(css.encode()).hexdigest() == BASELINE_VISIBLE_SHA


@pytest.mark.parametrize('visibility', ['visible', 'collapsed'])
def test_selected_files_never_receive_empty_geometry(visibility):
    assert css_for(visibility, selected=True) == []


def test_unknown_label_mode_and_unreviewed_runtime_reserve_nothing(monkeypatch):
    assert css_for('hidden') == []
    monkeypatch.setattr(loading.st, '__version__', 'future-unreviewed')
    assert css_for('collapsed') == []


def test_photo_intake_reserves_its_same_native_input_without_content_changes(monkeypatch):
    reserve = loading.reserve_empty_uploader
    monkeypatch.setattr(loading, 'reserve_empty_uploader', lambda *args, **kwargs: None)
    block = ResolvedBlock('improvements', 'This month')
    app = photo_app(block)
    uploader = app.get('file_uploader')[0]
    identity, key = uploader.proto.id, uploader.key
    monkeypatch.setattr(loading, 'reserve_empty_uploader', reserve)
    app.run()
    assert not app.exception
    assert app.get('file_uploader')[0].proto.id == identity
    assert app.get('file_uploader')[0].key == key
    assert len(app.get('file_uploader')) == 1
    styles = [item.proto.body for item in app.get('html')
              if '.st-key-' + key + ' > [data-testid="stSkeleton"]' in item.proto.body]
    assert len(styles) == 1 and '::before' not in styles[0]
    assert app.session_state.photos_draft.blocks[0] == block
    assert next(x for x in app.expander if x.label == 'Add photos').proto.expanded

BASELINE_VISIBLE_SHA = '8ea303d78617e3f478119e0cc37c4b6b6f7f88284979ec6083c3909c584c6952'
