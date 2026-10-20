"""Period review is bound to its editor and each retained picture occurrence.

The old-button cases deliver one recorded Streamlit widget packet after an
observed state replacement. They are AppTest protocol checks, not browser
timing or device acceptance. The picture cases ingest an actual synthetic PDF
and use real snapshot save/readback; they never use customer originals.
"""
from dataclasses import replace

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_asset_instances import (
    asset_instances, new_asset_instance, with_asset_instances,
)
from app.monthly_report_asset_review import (
    approve_all_assets, asset_context, normalize_asset_reviews, pending_asset_indexes,
)
from app.monthly_report_checks import preflight
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections
from app.monthly_report_setup import carried_period, merge_report_block, new_month_draft
from app.monthly_report_source_retirement import retire_contributions
from test_issue_period_truth import JANUARY, confirm_button, editor, original, period_problem
from test_monthly_report_issue_evidence_ui import SCRIPT as ISSUE_EVIDENCE_APP
from test_monthly_report_sources import image_bytes
from test_source_page_occurrences import source_page


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


@pytest.mark.parametrize('replacement', [
    'changed_then_restored', 'edited_then_restored', 'deleted_then_recreated', 'review_rollback',
])
def test_old_issue_confirmation_cannot_rebind_after_an_observed_row_aba(replacement):
    current = new_month_draft(original(), JANUARY)
    app = editor(current)
    earlier_packet = _button_packet(confirm_button(app))
    if replacement == 'changed_then_restored':
        changed = replace(current.follow_ups[0], text='A different observed inspection finding.')
        app.session_state['draft'] = replace(current, follow_ups=(changed,))
        app.run()
        assert app.session_state['draft'].follow_ups[0].text == changed.text
    elif replacement == 'edited_then_restored':
        changed_text = 'A deliberately edited inspection finding.'
        next(widget for widget in app.text_area if widget.label == 'Issue description').set_value(changed_text).run()
        assert not app.exception and app.session_state['draft'].follow_ups[0].text == changed_text
        next(widget for widget in app.text_area if widget.label == 'Issue description').set_value(
            current.follow_ups[0].text).run()
        assert not app.exception and app.session_state['draft'] == current
    elif replacement == 'deleted_then_recreated':
        app.session_state['draft'] = replace(current, follow_ups=())
        app.run()
        assert not app.session_state['draft'].follow_ups
    else:
        confirm_button(app).click().run()
        assert not period_problem(app.session_state['draft'])
        assert app.session_state['draft'].follow_ups[0].reviewed_fingerprint
    assert not app.exception
    app.session_state['draft'] = current
    app.run()
    assert not app.exception and app.session_state['draft'] == current
    assert period_problem(current)
    app._run(earlier_packet)
    assert not app.exception
    assert app.session_state['draft'] == current, (
        'Returning to equal row values does not revive the old confirmation action.')
    assert period_problem(app.session_state['draft'])
    confirm_button(app).click().run()
    assert not app.exception and not period_problem(app.session_state['draft'])


@pytest.mark.parametrize('change', ['rerender', 'other_issue'])
def test_valid_issue_confirmation_survives_an_unchanged_row(change):
    current = new_month_draft(original(), JANUARY)
    if change == 'other_issue':
        sibling = replace(current.follow_ups[0], key='independent-issue', text='An independent ongoing item.',
                          status='ongoing', update='', evidence_note='')
        current = replace(current, follow_ups=(*current.follow_ups, sibling))
    app = editor(current)
    earlier_packet = _button_packet(confirm_button(app))
    if change == 'other_issue':
        sibling = replace(current.follow_ups[1], evidence_note='Independent note added later.')
        current = replace(current, follow_ups=(current.follow_ups[0], sibling))
        app.session_state['draft'] = current
    app.run()
    assert not app.exception and app.session_state['draft'] == current
    app._run(earlier_packet)
    assert not app.exception and not period_problem(app.session_state['draft'])
    assert app.session_state['draft'].follow_ups[1:] == current.follow_ups[1:]


@pytest.mark.parametrize('key,human_first,caption', [
    ('equipment_issues', True, 'Same inspection caption'),
    ('equipment_issues', False, 'Same inspection caption'),
    ('proposals', True, 'Same inspection caption'),
    ('proposals', False, 'Same inspection caption'),
    ('equipment_issues', True, ''),
    ('proposals', False, ''),
    ('equipment_issues_evidence', True, 'Same inspection caption'),
    ('equipment_issues_evidence', False, ''),
])
def test_month_carry_preserves_equal_byte_picture_owners_through_retirement_and_reload(
        monkeypatch, tmp_path, key, human_first, caption):
    profile, content, prepared = source_page(monkeypatch, tmp_path, caption=caption)
    # The source tray prepares only its supported page destinations. This
    # rollover fixture explicitly places that real prepared picture into an
    # existing issue/proposal block; it does not claim a native intake route.
    # The target block receives its own ordinary picture approval fingerprint.
    imported = approve_all_assets(replace(prepared, key=key,
        client_asset_reviews=(), client_reviewed_fingerprint='', reviewed_fingerprint=''))
    original_bytes = sources.source_bytes(profile, content.source)
    reference, = imported.asset_hashes
    human = approve_all_assets(with_asset_instances(
        ResolvedBlock(key, 'This month', asset_hashes=(reference,), asset_captions=(caption,)),
        (new_asset_instance(reference),)))
    first, second = (human, imported) if human_first else (imported, human)
    combined = merge_report_block(first, second, None, None)
    assert combined.asset_hashes == (reference, reference)
    assert combined.asset_captions == (caption, caption)
    assert len({item.key for item in combined.asset_instances}) == 2
    assert not pending_asset_indexes(combined)
    prior = ReportDraft(profile, ReportPeriod(2026, 10), 'Synthetic occurrence reviewer',
                        default_sections(), (combined,), sources=(content.source,))
    saved_prior = library.save_snapshot(prior, expected_revision=0)
    prior = library.load_snapshot(profile.contract, profile.key, prior.period).draft
    current = new_month_draft(prior, ReportPeriod(2026, 11))
    carried = next(value for value in current.blocks if value.key == key)
    assert carried.asset_instances == combined.asset_instances, (
        'Rollover must retain each existing inclusion identity, including equal bytes and captions.')
    assert carried.asset_provenance == combined.asset_provenance
    assert carried.asset_captions == (caption, caption) and not pending_asset_indexes(carried)
    assert current.sources == prior.sources
    first_save = library.save_snapshot(current, expected_revision=0)
    restored = library.load_snapshot(profile.contract, profile.key, current.period)
    assert restored == first_save
    remaining = retire_contributions(next(value for value in restored.draft.blocks if value.key == key), (imported,))
    assert remaining.asset_hashes == (reference,) and remaining.asset_captions == (caption,)
    assert asset_instances(remaining) == human.asset_instances
    assert not asset_context(remaining, 0) and not pending_asset_indexes(remaining)
    changed = replace(restored.draft, blocks=tuple(remaining if value.key == key else value
                                                for value in restored.draft.blocks))
    second_save = library.save_snapshot(changed, expected_revision=first_save.revision)
    assert library.load_snapshot(profile.contract, profile.key, current.period) == second_save
    assert library.load_snapshot(profile.contract, profile.key, prior.period) == saved_prior
    assert retire_contributions(remaining, (imported,)) == remaining
    assert sources.source_bytes(profile, content.source) == original_bytes
