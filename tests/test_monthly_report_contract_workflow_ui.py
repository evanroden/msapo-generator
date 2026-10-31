"""Native contract-default actions are explicit and bound to their displayed report."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_workflow_standards as workflows
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_contract_workflows import isolated, report, image_block, legacy, file_bytes
from test_monthly_report_workflow_standards import publish

APP = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_workflow_defaults_ui import render_contract_procedure
current = st.session_state['draft']
blocks = {block.key: block for block in current.blocks}
key = 'business_hours_workflow'
block = blocks[key]
block, explicit = render_contract_procedure(current, block, st.session_state['assets'], 'test')
blocks[key] = block
st.session_state['draft'] = replace(current, blocks=tuple(blocks.values()))
st.session_state['explicit'] = explicit
'''


def start(draft=None, assets=None, script=APP):
    if draft is None:
        block, original = image_block()
        draft = report(blocks=(block,))
        assets = original if assets is None else assets
    app = AppTest.from_string(script, default_timeout=20)
    app.session_state['draft'] = draft
    app.session_state['assets'] = assets or {}
    return app.run()


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_passive_render_never_saves_and_explicit_save_is_once():
    app = start()
    initial = app.session_state['draft']
    assert not app.exception and workflows.load_standards('Contract A').revision == 0
    assert any('No approved default for this contract' in c.value for c in app.caption)
    button(app, 'Save as contract default').click().run()
    assert not app.exception and workflows.load_standards('Contract A').revision == 1
    assert app.session_state['draft'] == initial
    before = file_bytes()
    previous_id = button(app, 'Replace contract default').id
    app.run()
    assert not app.exception and file_bytes() == before
    assert button(app, 'Replace contract default').id == previous_id
    assert any('version 1' in c.value and 'source site' in c.value for c in app.caption)


def test_explicit_use_reincludes_an_omitted_picture_and_keeps_notes():
    _, expected, _, _ = publish()
    omitted = replace(expected, source='Omit', text='Keep this report note')
    initial = report(blocks=(omitted, ResolvedBlock('contact_matrix', 'This month', text='Keep contacts')))
    app = start(initial)
    assert not app.exception and app.session_state['draft'] == initial
    before = file_bytes()
    button(app, 'Use contract default in this report').click().run()
    assert not app.exception and app.session_state['explicit']
    current = app.session_state['draft']
    assert current.blocks[0].source == 'This month'
    assert current.blocks[0].text == omitted.text and current.blocks[1] == initial.blocks[1]
    assert file_bytes() == before
    app.run()
    assert app.session_state['draft'] == current and not app.session_state['explicit']


def test_old_save_click_cannot_publish_to_a_new_contract_or_month():
    for changed in ('contract', 'period', 'incarnation'):
        app = start()
        button(app, 'Save as contract default').click()
        initial = app.session_state['draft']
        if changed == 'contract':
            initial = replace(initial, profile=replace(initial.profile, contract='Contract B'))
        elif changed == 'period':
            initial = replace(initial, period=replace(initial.period, month=11))
        else:
            app.session_state['test_rich_text_epoch'] = 'replacement-editor'
        app.session_state['draft'] = initial
        app.run()
        assert not app.exception and any('changed' in w.value for w in app.warning)
        assert workflows.load_standards('Contract A').revision == 0
        assert workflows.load_standards('Contract B').revision == 0
        assert app.session_state['draft'] == initial


def test_stale_contract_version_is_rejected_without_repeating_save():
    draft, block, assets, _ = publish()
    app = start(draft, assets)
    _, _, _, latest = publish(color='red', revision=1)
    before = file_bytes()
    button(app, 'Replace contract default').click().run()
    assert not app.exception and any('changed' in w.value for w in app.warning)
    assert workflows.load_standards('Contract A') == latest and file_bytes() == before
    assert app.session_state['draft'] == draft
    app.run()
    assert file_bytes() == before


def test_legacy_adoption_requires_preview_and_does_not_change_report():
    item = legacy()
    app = start(report(blocks=(ResolvedBlock(item.key, 'Omit'),)))
    original = app.session_state['draft']
    assert not app.exception
    assert button(app, 'Adopt legacy procedure for this contract').disabled
    before = file_bytes()
    button(app, 'Preview legacy procedure').click().run()
    assert not app.exception and len(app.get('imgs')) + len(app.get('image')) >= 1
    assert file_bytes() == before
    button(app, 'Adopt legacy procedure for this contract').click().run()
    assert not app.exception and workflows.load_standards('Contract A').revision == 1
    assert app.session_state['draft'] == original
    assert all(file_bytes()[path] == raw for path, raw in before.items())
    button(app, 'Use contract default in this report').click().run()
    assert app.session_state['draft'].blocks[0].asset_hashes == item.block.asset_hashes


def test_foreign_legacy_metadata_is_not_shown():
    item = legacy()
    before = file_bytes()
    app = start(report('Contract B', (ResolvedBlock(item.key, 'Omit'),)))
    assert not app.exception and file_bytes() == before
    assert not any('legacy' in b.label.casefold() for b in app.button)
    assert not any('old-site' in c.value for c in app.caption)


def test_pending_report_change_rejects_old_default_action_without_losing_the_edit():
    app = start()
    button(app, 'Save as contract default').click()
    current = app.session_state['draft']
    edited = replace(current.blocks[0], text='Delivered report-only note')
    app.session_state['draft'] = replace(current, blocks=(edited,))
    app.run()
    assert not app.exception and app.session_state['draft'].blocks == (edited,)
    assert workflows.load_standards('Contract A').revision == 0
    assert any('changed' in w.value for w in app.warning)


def test_organization_wrapper_keeps_explicit_inclusion_of_identical_omitted_pages():
    _, block, assets, _ = publish()
    block = workflows.load_standards('Contract A').workflows[0].block
    initial = report(blocks=(replace(block, source='Omit'),))
    script = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_organization_ui import render_organization
from app.monthly_report_model import BlockSpec
from app.monthly_report_ui import _field
current = st.session_state['draft']
blocks = {block.key: block for block in current.blocks}
specs = {'business_hours_workflow': BlockSpec('business_hours_workflow', 'image_page')}
updated = render_organization(current, blocks, specs, 'test', st.session_state['assets'], _field,
                              lambda spec, block: block, show_preview=False)
st.session_state['draft'] = replace(current, blocks=tuple(updated.values()))
'''
    app = start(initial, assets, script)
    button(app, 'Edit business-hours outage procedure').click().run()
    assert not app.exception and app.session_state['draft'] == initial
    button(app, 'Use contract default in this report').click().run()
    assert not app.exception and app.session_state['draft'].blocks[0].source == 'This month'
    button(app, 'Done').click().run()
    assert app.session_state['draft'].blocks[0].source == 'This month'
