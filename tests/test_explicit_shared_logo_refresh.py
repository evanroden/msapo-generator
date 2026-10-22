"""Optional current-draft refresh is explicit and bound to the current review."""
from dataclasses import replace
from pathlib import Path
import json
import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_branding as branding, monthly_report_library as library
from test_monthly_report_branding_reuse import shared_logos


APP = '''
import streamlit as st
from app.monthly_report_branding_ui import offer_logo
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
block = st.session_state.setdefault("block", ResolvedBlock("brand_logo", "Replace once", asset_hashes=("custom.png",)))
assets = st.session_state.setdefault("assets", {})
scope = st.session_state.setdefault("scope", "first-editor")
with st.expander("About this report"):
    st.session_state["block"] = offer_logo(block, synthetic_profiles()[0].contract, "refresh", assets, scope=scope)
'''


def action(app):
    return next(button for button in app.button if button.label in ('Use this logo in this report', 'Add this logo to this report'))


def files():
    root = library._root()
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def test_opening_refresh_changes_nothing_and_explicit_use_changes_only_working_block(shared_logos):
    _, logos, assets = shared_logos
    before = files()
    app = AppTest.from_string(APP).run()
    original = app.session_state['block']
    assert not app.exception and original.asset_hashes == ('custom.png',)
    assert app.session_state['assets'] == {} and files() == before
    action(app).click().run()
    assert not app.exception
    selected = branding.find_logo('', brand=True)
    block = app.session_state['block']
    assert block.asset_hashes == (selected.asset,)
    assert block.client_reviewed_fingerprint == block.fingerprint
    assert app.session_state['assets'] == {selected.asset: assets[selected.asset]}
    assert files() == before
    app.run()
    assert not app.button


@pytest.mark.parametrize('change', ['scope', 'block', 'omit'])
def test_stale_click_cannot_replace_a_new_editor_or_choice(shared_logos, change):
    app = AppTest.from_string(APP).run()
    old = action(app)
    if change == 'scope':
        app.session_state['scope'] = 'second-editor'
    else:
        app.session_state['block'] = replace(app.session_state['block'], source='Omit' if change == 'omit' else 'Replace once', asset_hashes=() if change == 'omit' else ('new-custom.png',))
    expected = app.session_state['block']
    old.click().run()
    assert not app.exception
    assert app.session_state['block'] == expected and app.session_state['assets'] == {}


def test_reverting_after_current_artwork_was_selected_does_not_reactivate_old_button(shared_logos):
    app = AppTest.from_string(APP).run()
    original = app.session_state['block']; old = action(app)
    logo = branding.find_logo('', brand=True)
    app.session_state['block'] = replace(original, asset_hashes=(logo.asset,))
    app.run()
    assert not app.button
    app.session_state['block'] = original
    app.run()
    assert action(app).key != old.key
    old.click().run()
    assert app.session_state['block'] == original and app.session_state['assets'] == {}


def test_catalog_metadata_revision_invalidates_old_review_even_when_pixels_match(shared_logos):
    _, _, assets = shared_logos
    app = AppTest.from_string(APP).run(); old = action(app)
    original = app.session_state['block']
    current = branding.load_branding()
    changed = tuple(replace(logo, source_note='New synthetic approval') if logo.key == 'enfra' else logo for logo in current.logos)
    branding.save_branding(changed, assets, expected_revision=current.revision, actor='Synthetic reviewer', confirmed=True)
    old.click().run()
    assert not app.exception
    assert app.session_state['block'] == original and app.session_state['assets'] == {}
    assert action(app).key != old.key


def test_missing_shared_logo_does_not_change_or_break_current_report(shared_logos):
    app = AppTest.from_string(APP).run(); original = app.session_state['block']
    logo = branding.find_logo('', brand=True)
    (library._root() / 'branding' / 'assets' / logo.asset).unlink()
    app.run()
    assert not app.exception and not app.button
    assert app.session_state['block'] == original and app.session_state['assets'] == {}
    assert any('stays unchanged' in caption.value for caption in app.caption)


def test_catalog_change_between_review_and_apply_is_rejected(shared_logos, monkeypatch):
    app = AppTest.from_string(APP).run(); original = app.session_state['block']; old = action(app)
    current = branding.load_branding(); calls = []
    def changing():
        calls.append(True)
        return current if len(calls) == 1 else replace(current, revision=current.revision + 1)
    monkeypatch.setattr(branding, 'load_branding', changing)
    old.click().run()
    assert not app.exception
    assert app.session_state['block'] == original and app.session_state['assets'] == {}
    assert app.warning


def test_real_guided_entry_is_inside_optional_about_and_source_pending_guard():
    source = Path('app/monthly_report_guided.py').read_text()
    start = source.index('with st.expander("About this report")')
    end = source.index('with preview_column:', start)
    excerpt = source[start:end]
    assert 'if not source_pending and "brand_logo" in blocks:' in excerpt
    assert 'blocks["brand_logo"] = offer_logo(' in excerpt
    assert 'scope=_rich_text_scope(prefix)' in excerpt
    assert source.count('= offer_logo(') == 1


def test_explicit_use_retires_previous_unconfirmed_library_save(shared_logos):
    app = AppTest.from_string(APP).run()
    old = replace(app.session_state['block'], source='Replace and save to library', pending_library_save=True)
    app.session_state['block'] = old
    app.run()
    assert app.session_state['block'] == old
    action(app).click().run()
    assert not app.exception
    assert app.session_state['block'].source == 'Replace once'
    assert not app.session_state['block'].pending_library_save


@pytest.mark.parametrize('fault',['bad-json','bad-schema','missing-logos','missing-revision','missing-actor','missing-time'])
def test_unreadable_or_incomplete_catalog_does_not_break_optional_current_report(shared_logos,fault):
    app=AppTest.from_string(APP).run();old=app.session_state['block'];old_assets=dict(app.session_state['assets'])
    path=library._root()/'branding'/'manifest.json';value=json.loads(path.read_text())
    if fault=='bad-json':raw=b'not json'
    elif fault=='bad-schema':value['schema']=99;raw=json.dumps(value).encode()
    else:
        key={'missing-logos':'logos','missing-revision':'revision','missing-actor':'actor','missing-time':'updated_at'}[fault]
        value.pop(key);raw=json.dumps(value).encode()
    path.unlink();path.write_bytes(raw)
    app.run()
    assert not app.exception
    assert app.session_state['block']==old and app.session_state['assets']==old_assets
    assert not app.button




def test_incomplete_catalog_during_apply_is_contained(shared_logos,monkeypatch):
    app=AppTest.from_string(APP).run();old=action(app);original=app.session_state['block'];load=branding.load_branding;calls=[]
    def changing():
        calls.append(True)
        if len(calls)>1:raise KeyError('logos')
        return load()
    monkeypatch.setattr(branding,'load_branding',changing)
    old.click().run()
    assert not app.exception and app.session_state['block']==original and app.session_state['assets']=={}


