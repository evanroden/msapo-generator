"""Recovered PR312 art-only regressions, independent of PR309/310.

Original head e621ccb54621e6504204e41be6571790b26e497b; original test
bodies retained here while occurrence and row-receipt cases remain archived.
AppTest protocol checks do not establish native browser input delivery.
"""
from dataclasses import replace

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_asset_review import normalize_asset_reviews, pending_asset_indexes
from app.monthly_report_checks import preflight
from app.monthly_report_followups import confirmation
from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, ReportTable, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_setup import carried_period, confirm_current_period, new_month_draft
from test_monthly_report_issue_evidence_ui import SCRIPT as ISSUE_EVIDENCE_APP
from test_monthly_report_sources import image_bytes

DECEMBER = ReportPeriod(2026, 12)
JANUARY = ReportPeriod(2027, 1)
SCOPE = 'SF-52 damper remains unreliable.'
OLD_UPDATE = 'The actuator was adjusted; intermittent travel remains.'
OLD_NOTE = 'A December inspection documented the condition.'


def original(*, status='updated', update=OLD_UPDATE, included=True):
    item = ReportFollowUp('issue-sf52', 'issue', SCOPE, DECEMBER.key,
        status=status, update=update, evidence_note=OLD_NOTE, included=included)
    item = replace(item, reviewed_fingerprint=confirmation(item, DECEMBER))
    sections = tuple(replace(section, blocks=tuple(replace(spec, required=False) for spec in section.blocks))
                     for section in default_sections() if section.key == 'issues')
    return ReportDraft(synthetic_profiles()[0], DECEMBER, 'Synthetic period reviewer', sections,
        (ResolvedBlock('equipment_issues', 'This month'),), follow_ups=(item,))


@pytest.mark.parametrize('key', ['equipment_issues', 'equipment_issues_evidence', 'utility_analysis', 'mbcx_status'])
def test_empty_continuation_schema_is_not_a_carried_monthly_claim(key):
    prior = original(status='ongoing', update='')
    empty = ResolvedBlock(key, 'This month', extra_tables=(ReportTable(('Finding',), ()),))
    prior = replace(prior, blocks=tuple(block for block in prior.blocks if block.key != key) + (empty,))
    current = new_month_draft(prior, JANUARY)
    retained = next(block for block in current.blocks if block.key == key)
    assert carried_period(retained, JANUARY) is None
    assert not any(check.code == 'carried_period' for check in preflight(current))


@pytest.mark.parametrize('key', ['equipment_issues', 'equipment_issues_evidence'])
@pytest.mark.parametrize('omitted', [False, True])
def test_issue_art_retains_original_month_bytes_caption_and_individual_review(monkeypatch, tmp_path, key, omitted):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    prior = original(status='ongoing', update='')
    raw = image_bytes()
    reference = library.asset_reference(raw, 'png')
    block = ResolvedBlock(key, 'Omit' if omitted else 'This month', asset_hashes=(reference,),
        asset_captions=('December inspection view',))
    block = replace(block, client_reviewed_fingerprint=block.fingerprint)
    # Save/readback normalizes old whole-block approvals into individual
    # unchanged-image receipts. Begin from that canonical form so the period
    # assertion does not mislabel legitimate legacy normalization as data loss.
    block = normalize_asset_reviews(block)
    prior = replace(prior, blocks=tuple(value for value in prior.blocks if value.key != key) + (block,))
    library.save_snapshot(prior, expected_revision=0, assets=((reference, raw),))
    current = new_month_draft(prior, JANUARY)
    carried = next(value for value in current.blocks if value.key == key)
    assert carried.asset_hashes == block.asset_hashes and carried.asset_captions == block.asset_captions
    assert library.read_asset(prior.profile.contract, prior.profile.key, reference) == raw
    assert not pending_asset_indexes(carried), 'Unchanged picture review is separate from its reporting month.'
    if omitted:
        assert carried.source == 'Omit'
        assert carried_period(carried, JANUARY) is None
    else:
        assert carried.source == 'Last month' and carried_period(carried, JANUARY) == DECEMBER
        assert any(check.blocking and check.code == 'carried_period' and check.block_key == key for check in preflight(current))
        confirmed = confirm_current_period(carried, JANUARY)
        assert not pending_asset_indexes(confirmed)
        assert 'report-origin:2026-12' in confirmed.references and 'report-period:2027-01' in confirmed.references
        current = replace(current, blocks=tuple(confirmed if value.key == key else value for value in current.blocks))
        assert not any(check.code == 'carried_period' for check in preflight(current))
    library.save_snapshot(current, expected_revision=0)
    assert library.load_snapshot(current.profile.contract, current.profile.key, JANUARY).draft == current
    assert library.load_snapshot(prior.profile.contract, prior.profile.key, DECEMBER).draft == prior


@pytest.mark.parametrize('key', ['equipment_issues', 'equipment_issues_evidence'])
def test_carried_issue_art_has_a_reachable_one_action_period_correction(monkeypatch, tmp_path, key):
    from test_monthly_report_issue_evidence_ui import SCRIPT
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    prior = original(status='ongoing', update='')
    raw = image_bytes()
    reference = library.asset_reference(raw, 'png')
    block = ResolvedBlock(key, 'This month', asset_hashes=(reference,),
                          asset_captions=('December inspection view',))
    block = normalize_asset_reviews(replace(block, client_reviewed_fingerprint=block.fingerprint))
    prior = replace(prior, blocks=tuple(value for value in prior.blocks if value.key != key) + (block,))
    current = new_month_draft(prior, JANUARY)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['draft'] = current
    app.session_state['assets'] = {reference: raw}
    app.run()
    assert not app.exception
    actions = [value for value in app.button if value.label == 'This update is correct for January 2027']
    assert len(actions) == 1, 'The actual Issues section must expose its carried-art correction.'
    actions[0].click().run()
    assert not app.exception
    result = next(value for value in app.session_state['draft'].blocks if value.key == key)
    assert carried_period(result, JANUARY) is None
    assert result.asset_hashes == (reference,) and result.asset_captions == block.asset_captions
    assert not pending_asset_indexes(result)
    assert 'report-origin:2026-12' in result.references
    app.run()
    assert not any(value.label == 'This update is correct for January 2027' for value in app.button)
    assert not any(value.code == 'carried_period' for value in preflight(app.session_state['draft']))


def _button_packet(button):
    message = WidgetStates()
    message.widgets.add(id=button.proto.id, trigger_value=True)
    return message


def _art_button(app):
    buttons = [button for button in app.button
               if button.label == 'This update is correct for January 2027']
    assert len(buttons) == 1
    return buttons[0]


def _art_editor(monkeypatch, tmp_path, key):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    prior = original(status='ongoing', update='')
    raw = image_bytes()
    reference = library.asset_reference(raw, 'png')
    block = ResolvedBlock(key, 'This month', asset_hashes=(reference,),
                          asset_captions=('Original December inspection',))
    block = normalize_asset_reviews(replace(block, client_reviewed_fingerprint=block.fingerprint))
    prior = replace(prior, blocks=tuple(value for value in prior.blocks if value.key != key) + (block,))
    app = AppTest.from_string(ISSUE_EVIDENCE_APP, default_timeout=30)
    app.session_state['draft'] = new_month_draft(prior, JANUARY)
    app.session_state['assets'] = {reference: raw}
    app.run()
    assert not app.exception
    current = app.session_state['draft']
    retained = next(value for value in current.blocks if value.key == key)
    assert carried_period(retained, JANUARY) == prior.period
    assert not pending_asset_indexes(retained)
    assert any(check.blocking and check.code == 'carried_period' for check in preflight(current))
    return app, current, retained


@pytest.mark.parametrize('key', ['equipment_issues', 'equipment_issues_evidence'])
@pytest.mark.parametrize('replacement', ['editor', 'qa_generation'])
def test_old_carried_art_confirmation_cannot_cross_an_editor_reset(
        monkeypatch, tmp_path, key, replacement):
    app, current, retained = _art_editor(monkeypatch, tmp_path, key)
    earlier_packet = _button_packet(_art_button(app))
    if replacement == 'editor':
        app.session_state['issue_evidence_rich_text_epoch'] = 'replacement-editor'
    else:
        app.session_state['_monthly_qa_generation'] = 'replacement-isolated-generation'
    app.run()
    assert not app.exception and app.session_state['draft'] == current
    app._run(earlier_packet)
    assert not app.exception
    assert app.session_state['draft'] == current, (
        'A confirmation displayed by the earlier editor must not date the replacement report art.')
    assert carried_period(next(value for value in app.session_state['draft'].blocks
                               if value.key == key), JANUARY) is not None
    _art_button(app).click().run()
    assert not app.exception
    accepted = next(value for value in app.session_state['draft'].blocks if value.key == key)
    assert carried_period(accepted, JANUARY) is None
    assert (accepted.asset_hashes, accepted.asset_captions, accepted.asset_provenance) == (
        retained.asset_hashes, retained.asset_captions, retained.asset_provenance)
    assert not pending_asset_indexes(accepted)


def test_unchanged_art_rerender_keeps_one_valid_confirmation(monkeypatch, tmp_path):
    app, current, _ = _art_editor(monkeypatch, tmp_path, 'equipment_issues_evidence')
    packet = _button_packet(_art_button(app))
    app.run()
    app.run()
    assert not app.exception and app.session_state['draft'] == current
    app._run(packet)
    assert not app.exception
    accepted = next(value for value in app.session_state['draft'].blocks
                    if value.key == 'equipment_issues_evidence')
    assert carried_period(accepted, JANUARY) is None
    assert not pending_asset_indexes(accepted)


@pytest.mark.parametrize('replacement', ['caption', 'omitted', 'deleted', 'review_rollback'])
def test_observed_art_replacement_does_not_revive_an_earlier_confirmation(
        monkeypatch, tmp_path, replacement):
    app, current, retained = _art_editor(monkeypatch, tmp_path, 'equipment_issues_evidence')
    earlier_packet = _button_packet(_art_button(app))
    if replacement == 'review_rollback':
        _art_button(app).click().run()
        accepted = next(block for block in app.session_state['draft'].blocks
                        if block.key == retained.key)
        assert carried_period(accepted, JANUARY) is None
    else:
        if replacement == 'caption':
            changed = replace(retained, asset_captions=('Another observed inspection view',))
        elif replacement == 'omitted':
            changed = replace(retained, source='Omit')
        else:
            changed = None
        app.session_state['draft'] = replace(current, blocks=tuple(
            block for block in current.blocks if block.key != retained.key
        ) + ((changed,) if changed else ()))
        app.run()
    assert not app.exception
    app.session_state['draft'] = current
    app.run()
    assert not app.exception and app.session_state['draft'] == current
    app._run(earlier_packet)
    assert not app.exception and app.session_state['draft'] == current
    _art_button(app).click().run()
    assert not app.exception
    accepted = next(block for block in app.session_state['draft'].blocks
                    if block.key == retained.key)
    assert carried_period(accepted, JANUARY) is None
    assert accepted.asset_hashes == retained.asset_hashes
    assert accepted.asset_captions == retained.asset_captions
    assert not pending_asset_indexes(accepted)
