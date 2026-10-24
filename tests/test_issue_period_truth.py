"""Refs #281: prior issues stay recoverable without becoming current updates.

The confirmation rule follows the decision on #281: carried update wording that
nobody edited needs one visible current-period confirmation; a direct edit of
the update is this month's review and stamps it with the report month.

These are synthetic model/AppTest, persisted-snapshot and actual editable
Word/LibreOffice PDF checks. They do not establish native browser delivery,
authentic source fidelity or native Microsoft Word acceptance.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

from docx import Document
import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_asset_review import normalize_asset_reviews, pending_asset_indexes
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx, generate_report
from app.monthly_report_followups import confirmation, problems
from app.monthly_report_issues import clear_issues
from app.monthly_report_model import ReportTable, ReportDraft, ReportFollowUp, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app import monthly_report_followups as followups
from app.monthly_report_setup import carried_period, confirm_current_period, new_month_draft
from tests.conftest import requires_libreoffice
from test_monthly_report_sources import image_bytes

DECEMBER = ReportPeriod(2026, 12)
JANUARY = ReportPeriod(2027, 1)
FEBRUARY = ReportPeriod(2027, 2)
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


def period_problem(draft):
    return [check for check in preflight(draft) if check.blocking
            and check.code == 'follow_up' and 'current for' in check.message]


def output_path(tmp_path):
    path = Path(os.environ.get('INDEPENDENT_OUTPUT', str(tmp_path))) / 'issue-period-truth'
    path.mkdir(parents=True, exist_ok=True)
    return path


def retain_package(package, directory, stem, draft):
    assert package.docx and package.pdf, package.pdf_error
    (directory / (stem + '.docx')).write_bytes(package.docx)
    (directory / (stem + '.pdf')).write_bytes(package.pdf)
    with fitz.open(stream=package.pdf, filetype='pdf') as document:
        text = '\n'.join(page.get_text() for page in document)
        for number, page in enumerate(document, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(directory / f'{stem}-{number:02}.png')
        pages = len(document)
    (directory / (stem + '.json')).write_text(json.dumps({
        'tested_revision': os.environ.get('MSAPO_SHA', 'unrecorded'),
        'report_period': draft.period.key, 'draft_fingerprint': draft.fingerprint,
        'docx_bytes': len(package.docx), 'docx_sha256': sha256(package.docx).hexdigest(),
        'pdf_bytes': len(package.pdf), 'pdf_sha256': sha256(package.pdf).hexdigest(),
        'pdf_pages': pages, 'scope': 'Synthetic persisted state, editable DOCX and LibreOffice PDF.'}, indent=2) + '\n')
    return text


@requires_libreoffice
def test_december_update_cannot_generate_as_january_before_explicit_current_review(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    prior = original()
    library.save_snapshot(prior, expected_revision=0)
    current = new_month_draft(library.load_snapshot(prior.profile.contract, prior.profile.key, DECEMBER).draft, JANUARY)
    saved = library.save_snapshot(current, expected_revision=0)
    restored = library.load_snapshot(current.profile.contract, current.profile.key, JANUARY)
    assert restored.revision == saved.revision == 1 and restored.draft == current
    item, = current.follow_ups
    assert (item.text, item.status, item.update, item.evidence_note) == (SCOPE, 'updated', OLD_UPDATE, OLD_NOTE)
    assert not item.reviewed_fingerprint and item.carried_from == DECEMBER.key
    checks = period_problem(current)
    directory = output_path(tmp_path)
    # Keep actual undesired before-output if the old policy permits it. A
    # failing desired assertion after generation is evidence, not a pass.
    if not checks:
        package = generate_report(current, acknowledged_fingerprint=current.fingerprint)
        retain_package(package, directory, 'unconfirmed-before', current)
    assert checks, 'The old Updated claim reached January without a current-period review.'
    assert all(check.block_key == item.key and 'January 2027' in check.message for check in checks)
    with pytest.raises(ValueError, match='current for January 2027'):
        assemble_docx(current, acknowledged_fingerprint=current.fingerprint)
    assert library.load_snapshot(prior.profile.contract, prior.profile.key, DECEMBER).draft == prior


@pytest.mark.parametrize('status,update,requires', [
    ('ongoing', '', False), ('ongoing', OLD_UPDATE, True), ('updated', '', True), ('updated', OLD_UPDATE, True),
])
def test_only_carried_claims_need_period_confirmation(status, update, requires):
    prior = original(status=status, update=update)
    assert new_month_draft(prior, DECEMBER) == prior
    assert not period_problem(prior)
    current = new_month_draft(prior, JANUARY)
    assert bool(period_problem(current)) == requires
    item = current.follow_ups[0]
    confirmed = replace(item, reviewed_fingerprint=confirmation(item, JANUARY))
    current = replace(current, follow_ups=(confirmed,))
    assert not problems(confirmed, current)
    assert bool(period_problem(new_month_draft(current, FEBRUARY))) == requires
    # Existing evidence notes remain data, and are not invented printed work.
    assert current.follow_ups[0].evidence_note == OLD_NOTE


def test_resolved_drops_but_report_only_clear_keeps_unresolved_history():
    assert not new_month_draft(original(status='resolved'), JANUARY).follow_ups
    prior = clear_issues(original())
    assert not prior.follow_ups[0].included
    current = new_month_draft(prior, JANUARY)
    assert current.follow_ups[0].included and current.follow_ups[0].status == 'updated'
    assert period_problem(current)
    omitted = clear_issues(current)
    assert not period_problem(omitted)
    assert omitted.follow_ups[0].update == OLD_UPDATE


@pytest.mark.parametrize('key', ['equipment_issues', 'equipment_issues_evidence', 'utility_analysis', 'mbcx_status'])
def test_empty_continuation_schema_is_not_a_carried_monthly_claim(key):
    prior = original(status='ongoing', update='')
    empty = ResolvedBlock(key, 'This month', extra_tables=(ReportTable(('Finding',), ()),))
    prior = replace(prior, blocks=tuple(block for block in prior.blocks if block.key != key) + (empty,))
    current = new_month_draft(prior, JANUARY)
    retained = next(block for block in current.blocks if block.key == key)
    assert carried_period(retained, JANUARY) is None
    assert not any(check.code == 'carried_period' for check in preflight(current))


APP = '''
import streamlit as st
from app.monthly_report_followups import render_followups
from app.monthly_report_ui import _field
st.session_state['draft'] = render_followups(st.session_state['draft'], 'period_issue', _field, category='issue')
'''


def editor(draft):
    app = AppTest.from_string(APP, default_timeout=20)
    app.session_state['draft'] = draft
    app.run()
    assert not app.exception
    return app


def confirm_button(app):
    values = [button for button in app.button if button.label == 'Confirm update for January 2027']
    assert len(values) == 1, 'The carried issue needs one visible native current-period correction.'
    return values[0]


INTERRUPTED_APP = '''
import inspect
import streamlit as st
from app import monthly_report_followups as followups
from app import monthly_report_issues as issues
from app.monthly_report_ui import _field
kwargs = {'category': 'issue'}
if 'defer_commit' in inspect.signature(followups.render_followups).parameters:
    kwargs['defer_commit'] = True
result = followups.render_followups(st.session_state['draft'], 'period_issue', _field, **kwargs)
if st.session_state.pop('interrupt_once', False):
    st.session_state['interrupted_result'] = result
    st.stop()
st.session_state['draft'] = result
# The guided workspace acknowledges both proposal and issue edits.
followups.acknowledge_followup_controls(result, 'period_issue')
issues.acknowledge_issue_controls(result, 'period_issue')
'''


def interrupted_confirmation():
    current = new_month_draft(original(), JANUARY)
    app = AppTest.from_string(INTERRUPTED_APP, default_timeout=30)
    app.session_state['draft'] = current
    app.run()
    assert not app.exception
    next(widget for widget in app.text_area if widget.label == 'Evidence or explanation for the status').set_value(
        'January inspection confirmed this continuing finding.')
    app.session_state['interrupt_once'] = True
    confirm_button(app).click().run()
    assert not app.exception and app.session_state['draft'] == current
    accepted = app.session_state['interrupted_result']
    assert accepted.follow_ups[0].update_period == JANUARY.key
    return app, current, accepted


def test_one_confirmation_survives_an_interrupted_outer_commit_and_reload(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    app, current, accepted = interrupted_confirmation()
    app.run()
    assert not app.exception
    assert app.session_state['draft'] == accepted
    assert not period_problem(accepted)
    assert not any(button.label == 'Confirm update for January 2027' for button in app.button)
    library.save_snapshot(accepted, expected_revision=0)
    restored = library.load_snapshot(accepted.profile.contract, accepted.profile.key, JANUARY)
    assert restored.draft == accepted
    assert editor(restored.draft).session_state['draft'] == accepted
    # A successfully acknowledged action cannot approve a later rollback.
    app.session_state['draft'] = current
    app.run()
    assert not app.exception and app.session_state['draft'] == current
    assert period_problem(current)


@pytest.mark.parametrize('replacement', ['row', 'period', 'deleted', 'editor'])
def test_interrupted_confirmation_never_approves_a_later_replacement(replacement):
    app, current, _ = interrupted_confirmation()
    if replacement == 'row':
        current = replace(current, follow_ups=(replace(current.follow_ups[0], text='A newer independent finding.'),))
    elif replacement == 'period':
        current = replace(current, period=FEBRUARY)
    elif replacement == 'deleted':
        current = replace(current, follow_ups=())
    else:
        app.session_state['period_issue_rich_text_epoch'] = 'later-editor-incarnation'
    app.session_state['draft'] = current
    app.run()
    assert not app.exception and app.session_state['draft'] == current
    assert all(item.update_period != JANUARY.key for item in current.follow_ups)


@requires_libreoffice
def test_one_current_confirmation_captures_delivered_note_saves_and_prints(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    prior = original()
    library.save_snapshot(prior, expected_revision=0)
    current = new_month_draft(prior, JANUARY)
    library.save_snapshot(current, expected_revision=0)
    app = editor(current)
    reviewed_note = 'A January inspection confirmed the entered update remains accurate.'
    next(widget for widget in app.text_area if widget.label == 'Evidence or explanation for the status').set_value(reviewed_note)
    confirm_button(app).click().run()
    assert not app.exception
    accepted = app.session_state['draft']
    item, = accepted.follow_ups
    assert item.evidence_note == reviewed_note and item.update == OLD_UPDATE
    assert item.update_period == JANUARY.key
    assert not period_problem(accepted)
    assert not any(button.label == 'Confirm update for January 2027' for button in app.button)
    saved = library.save_snapshot(accepted, expected_revision=1)
    restored = library.load_snapshot(accepted.profile.contract, accepted.profile.key, JANUARY)
    assert restored.draft == accepted and saved.revision == restored.revision == 2
    reopened = editor(restored.draft)
    assert reopened.session_state['draft'] == accepted and not period_problem(accepted)
    package = generate_report(accepted, acknowledged_fingerprint=accepted.fingerprint)
    pdf_text = retain_package(package, output_path(tmp_path), 'confirmed-current', accepted)
    word_text = '\n'.join(paragraph.text for paragraph in Document(BytesIO(package.docx)).paragraphs)
    for text in (word_text, pdf_text):
        text = ' '.join(text.split())
        assert text.count(SCOPE) == 1 and text.count(OLD_UPDATE) == 1
        assert 'January 2027' in text and OLD_NOTE not in text and reviewed_note not in text
    assert library.load_snapshot(prior.profile.contract, prior.profile.key, DECEMBER).draft == prior
    assert library.load_snapshot_version(current.profile.contract, current.profile.key, JANUARY, 1).draft == current


@pytest.mark.parametrize('replacement', ['row', 'period', 'deleted', 'editor'])
def test_stale_confirmation_cannot_approve_a_changed_row_or_report(replacement):
    current = new_month_draft(original(), JANUARY)
    app = editor(current)
    old_button = confirm_button(app)
    if replacement == 'row':
        current = replace(current, follow_ups=(replace(current.follow_ups[0], text='A different current finding.'),))
    elif replacement == 'period':
        current = replace(current, period=FEBRUARY)
    elif replacement == 'deleted':
        current = replace(current, follow_ups=())
    else:
        app.session_state['period_issue_rich_text_epoch'] = 'new-editor-incarnation'
    app.session_state['draft'] = current
    old_button.click().run()
    assert not app.exception
    assert app.session_state['draft'] == current
    assert all(item.update_period != JANUARY.key for item in current.follow_ups)


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


def test_a_direct_update_edit_is_this_months_review():
    current = new_month_draft(original(), JANUARY)
    assert current.follow_ups[0].update_period == DECEMBER.key
    app = editor(current)
    confirm_button(app)
    edited = 'January: the actuator was replaced and travel is now full.'
    next(widget for widget in app.text_area if widget.label == 'Issue update').set_value(edited).run()
    assert not app.exception
    item, = app.session_state['draft'].follow_ups
    assert item.update == edited and item.update_period == JANUARY.key
    assert not period_problem(app.session_state['draft'])
    assert not any(button.label == 'Confirm update for January 2027' for button in app.button)
    # The stamp is January's: February asks again about the same wording.
    assert period_problem(new_month_draft(app.session_state['draft'], FEBRUARY))


def test_a_status_edit_alone_leaves_the_carried_update_unconfirmed():
    current = new_month_draft(original(), JANUARY)
    app = editor(current)
    next(widget for widget in app.selectbox if widget.label == 'Issue status').set_value('ongoing').run()
    assert not app.exception
    item, = app.session_state['draft'].follow_ups
    assert item.status == 'ongoing' and item.update == OLD_UPDATE
    assert item.update_period == DECEMBER.key
    assert period_problem(app.session_state['draft'])
    confirm_button(app)


def test_an_empty_month_stamp_keeps_saved_fingerprints_and_confirmations():
    """Reports saved before the stamp existed keep their digests and approvals."""
    item = ReportFollowUp('proposal-a', 'proposal', 'Replace the AHU-2 belts.', DECEMBER.key)
    values = {key: value for key, value in vars(item).items()
              if key not in ('reviewed_fingerprint', 'update_period')}
    assert confirmation(item, DECEMBER) == followups._digest((values, DECEMBER.key))
    draft = original(status='ongoing', update='')
    legacy = dict(vars(draft.follow_ups[0]))
    del legacy['update_period']
    record = json.loads(json.dumps({'follow_ups': [legacy]}))
    assert ReportFollowUp(**{**record['follow_ups'][0], 'references': ()}) == draft.follow_ups[0]
    stamped = replace(draft, follow_ups=(replace(draft.follow_ups[0], update_period=DECEMBER.key),))
    assert stamped.fingerprint != draft.fingerprint


@pytest.mark.parametrize('replacement', ['row', 'editor'])
def test_a_held_confirmation_clicked_after_the_replacement_renders_never_confirms_it(replacement):
    """A native click can arrive after a replacement row has rendered its own button."""
    current = new_month_draft(original(), JANUARY)
    app = editor(current)
    held = confirm_button(app)
    if replacement == 'row':
        current = replace(current, follow_ups=(replace(current.follow_ups[0], update='A different carried update.'),))
    else:
        app.session_state['period_issue_rich_text_epoch'] = 'replacement-editor-incarnation'
    app.session_state['draft'] = current
    app.run()
    assert not app.exception
    confirm_button(app)  # The replacement still needs its own confirmation.
    held.click().run()
    assert not app.exception
    assert app.session_state['draft'] == current
    assert period_problem(current)
