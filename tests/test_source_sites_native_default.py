"""Browser-free native protobuf contract; not a hosted browser pass."""
from dataclasses import replace
from datetime import date
import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles

APP = '''
import streamlit as st
from app.monthly_report_upload_ui import render_source_details
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_ui import _field as field, restore_report_draft_state
restore_report_draft_state()
st.session_state['_monthly_source_detail_anchors'] = set()
st.radio('File to review', ['a', 'b'])
st.button('Correct date')
if st.checkbox('Hide source forms'):
    st.stop()
for name in ['a', 'b']:
    st.session_state[name] = render_source_details(st.session_state[name], synthetic_profiles()[1], name, field)
'''

def loaded(monkeypatch, tmp_path, mirror=None, app_source=APP):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[1]
    content, _ = sources.ingest(profile, 'synthetic-default.txt', b'Synthetic source without date.')
    app = AppTest.from_string(app_source)
    app.session_state['a'] = replace(content.source, facility=profile.facilities[0].key, service_date='')
    app.session_state['b'] = replace(content.source, id='b' * 64, facility=profile.facilities[1].key, service_date='')
    if mirror is not None:
        app.session_state['report_draft_mirror'] = mirror
    app.run()
    assert not app.exception
    return app, profile

def selected_default(widget):
    return [widget.proto.options[i] for i in widget.proto.default]

def test_first_and_late_mount_date_reentry_keep_saved_default(monkeypatch, tmp_path):
    app, profile = loaded(monkeypatch, tmp_path)
    widget = app.multiselect[0]
    native_id = widget.proto.id
    assert selected_default(widget) == [profile.facilities[0].title]
    canonical = app.session_state['a']
    app.button[0].click().run()
    assert not app.exception
    widget = app.multiselect[0]
    # A late frontend mount after the one-shot set_value was consumed still
    # has the selected site in its protobuf default.
    assert not widget.proto.set_value
    assert selected_default(widget) == [profile.facilities[0].title]
    assert widget.proto.id == native_id
    assert app.session_state['a'] == canonical
    app.date_input[0].set_value(date(2026, 9, 16))
    app.button[1].click().run()
    assert selected_default(app.multiselect[0]) == [profile.facilities[0].title]
    assert app.multiselect[0].proto.id == native_id
    assert app.session_state['a'].service_date == '2026-09-16'

@pytest.mark.parametrize('clear', [True, False])
def test_pending_site_switch_or_clear_never_resurrects_canonical(monkeypatch, tmp_path, clear):
    app, profile = loaded(monkeypatch, tmp_path)
    pending = [] if clear else [profile.facilities[1].key]
    canonical = app.session_state['a']
    native_id = app.multiselect[0].proto.id
    app.multiselect[0].set_value(pending)
    app.radio[0].set_value('b').run()
    assert app.session_state['a'] == canonical
    app.radio[0].set_value('a').run()
    assert app.multiselect[0].value == pending
    assert selected_default(app.multiselect[0]) == ([profile.facilities[1].title] if pending else [])
    assert app.multiselect[0].proto.id == native_id
    app.button[1].click().run()
    assert app.session_state['a'].facility == (profile.facilities[1].key if pending else '')
    app.run()
    assert app.multiselect[0].value == pending
    assert selected_default(app.multiselect[0]) == ([profile.facilities[1].title] if pending else [])
    assert app.multiselect[0].proto.id == native_id
    assert selected_default(app.multiselect[1]) == [profile.facilities[1].title]

def test_unknown_source_does_not_default_to_first_site(monkeypatch, tmp_path):
    app, _ = loaded(monkeypatch, tmp_path)
    app.session_state['a'] = replace(app.session_state['a'], facility='')
    app.run()
    assert not app.exception
    assert app.multiselect[0].value == []
    assert selected_default(app.multiselect[0]) == []

def test_no_duplicate_default_warning(monkeypatch, tmp_path):
    from streamlit.elements.lib import policies
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    warnings = []
    monkeypatch.setattr(policies._LOGGER, 'warning', lambda *args, **kwargs: warnings.append(args))
    loaded(monkeypatch, tmp_path)
    assert not warnings


def test_external_correction_uses_native_set_value_then_retained_default(monkeypatch, tmp_path):
    app, profile = loaded(monkeypatch, tmp_path)
    native_id = app.multiselect[0].proto.id
    app.multiselect[0].set_value([])
    from streamlit.elements.lib import policies
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    warnings = []
    monkeypatch.setattr(policies._LOGGER, 'warning', lambda *args, **kwargs: warnings.append(args))
    newer = replace(app.session_state['a'], facility=profile.facilities[1].key)
    app.session_state['a'] = newer
    app.button[1].click().run()
    widget = app.multiselect[0]
    assert not app.exception
    assert app.session_state['a'] == newer
    assert any('corrected elsewhere' in item.value for item in app.info)
    assert widget.proto.set_value
    assert list(widget.proto.raw_values) == [profile.facilities[1].title]
    assert not warnings
    assert widget.proto.id == native_id
    app.run()
    widget = app.multiselect[0]
    assert not widget.proto.set_value
    assert selected_default(widget) == [profile.facilities[1].title]
    assert widget.proto.id == native_id


@pytest.mark.parametrize('clear', [True, False])
def test_mirror_restoration_is_native_default_without_duplicate_warning(monkeypatch, tmp_path, clear):
    from streamlit.elements.lib import policies
    profile = synthetic_profiles()[1]
    pending = [] if clear else [profile.facilities[1].key]
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    warnings = []
    monkeypatch.setattr(policies._LOGGER, 'warning', lambda *args, **kwargs: warnings.append(args))
    app, _ = loaded(monkeypatch, tmp_path, {'a_source_details_sites': pending, 'other_field': 'retained'})
    assert not warnings
    assert app.multiselect[0].value == pending
    assert selected_default(app.multiselect[0]) == ([] if clear else [profile.facilities[1].title])
    assert app.session_state['a'].facility == profile.facilities[0].key
    assert app.session_state['other_field'] == 'retained'
    assert 'a_source_details_sites' in app.session_state['report_widget_keys']
    native_id = app.multiselect[0].proto.id
    app.button[0].click().run()
    assert app.multiselect[0].proto.id == native_id
    assert app.multiselect[0].value == pending
    assert not warnings


def test_mirror_is_exact_key_scoped_and_current_native_state_wins(monkeypatch, tmp_path):
    profile = synthetic_profiles()[1]
    app, _ = loaded(monkeypatch, tmp_path, {
        'wrong_report_a_source_details_sites': [],
        'b_source_details_sites': [],
        'other_field': 'retained',
    })
    assert app.multiselect[0].value == [profile.facilities[0].key]
    assert app.multiselect[1].value == []
    # A stale mirror cannot overwrite a current native delivery, even []
    # and even when the canonical source still records the original site.
    app.session_state['report_draft_mirror'] = {'a_source_details_sites': [profile.facilities[1].key]}
    app.multiselect[0].set_value([])
    app.button[0].click().run()
    assert app.multiselect[0].value == []
    assert selected_default(app.multiselect[0]) == []
    assert app.session_state['a'].facility == profile.facilities[0].key


@pytest.mark.parametrize('pending', [[], ['not-a-profile-site']])
def test_mirror_remount_keeps_exact_pending_values_and_unknown_not_first(monkeypatch, tmp_path, pending):
    from streamlit.elements.lib import policies
    app, profile = loaded(monkeypatch, tmp_path, {'a_source_details_sites': pending})
    canonical = app.session_state['a']
    native_id = app.multiselect[0].proto.id
    assert app.multiselect[0].value == pending
    # Model native-widget cleanup between views without changing the mirror.
    # This is a server/default contract, not a browser remount claim.
    app.checkbox[0].set_value(True).run()
    assert not app.multiselect
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    warnings = []
    monkeypatch.setattr(policies._LOGGER, 'warning', lambda *args, **kwargs: warnings.append(args))
    app.checkbox[0].set_value(False).run()
    assert not app.exception
    assert app.multiselect[0].value == pending
    assert selected_default(app.multiselect[0]) == ([] if not pending else ['Outside this report: not-a-profile-site'])
    assert app.multiselect[0].proto.id == native_id
    assert app.session_state['a'] == canonical
    assert not warnings
    if pending:
        app.button[1].click().run()
        assert app.session_state['a'] == canonical
        assert app.error


@pytest.mark.parametrize('clear', [True, False])
def test_preserve_mirror_through_repeated_hidden_renders_and_remount(monkeypatch, tmp_path, clear):
    from streamlit.elements.lib import policies
    # Exercise the real preservation function both after visible rendering and
    # while fields are absent, rather than leaving a manually supplied mirror.
    preserving_app = APP.replace(
        "restore_report_draft_state()\n",
        "from app.monthly_report_ui import preserve_report_draft_state\nrestore_report_draft_state()\n",
    ).replace("    st.stop()", "    preserve_report_draft_state()\n    st.stop()")
    preserving_app += "\npreserve_report_draft_state()\n"
    app, profile = loaded(monkeypatch, tmp_path, app_source=preserving_app)
    pending = [] if clear else [profile.facilities[1].key]
    canonical = app.session_state['a']
    native_id = app.multiselect[0].proto.id
    app.multiselect[0].set_value(pending)
    app.button[0].click().run()
    assert app.session_state['report_draft_mirror']['a_source_details_sites'] == pending
    app.checkbox[0].set_value(True).run()
    app.run()
    app.run()
    assert not app.multiselect
    assert 'a_source_details_sites' not in app.session_state
    assert app.session_state['report_draft_mirror']['a_source_details_sites'] == pending
    assert app.session_state['a'] == canonical
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    warnings = []
    monkeypatch.setattr(policies._LOGGER, 'warning', lambda *args, **kwargs: warnings.append(args))
    app.checkbox[0].set_value(False).run()
    assert not app.exception
    assert not warnings
    assert app.multiselect[0].proto.id == native_id
    assert app.multiselect[0].value == pending
    assert selected_default(app.multiselect[0]) == ([] if clear else [profile.facilities[1].title])
    assert app.session_state['report_draft_mirror']['a_source_details_sites'] == pending
    assert app.session_state['a'] == canonical
