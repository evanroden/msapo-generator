"""The same browser recovers working input without publishing report history."""
from pathlib import Path
from dataclasses import replace

import pytest

from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from test_monthly_report_ui import monthly, choose_report

TOKEN = 'd' * 32
ROOT = Path(__file__).resolve().parents[1]
PERIOD = ReportPeriod(2026, 9)


def _visit(monkeypatch):
    from app import web_ui
    monkeypatch.setattr(web_ui, 'device_token', lambda cookies: TOKEN)


def _value(app, label, kind='text_area'):
    return next(w for w in getattr(app, kind) if w.label == label)


def test_active_activity_and_name_recover_in_a_new_streamlit_session(monkeypatch, tmp_path):
    _visit(monkeypatch)
    app = monthly(monkeypatch, tmp_path)
    _value(app, 'Prepared by', 'text_input').set_value('Synthetic Recovery Editor').run()
    _value(app, 'Activity summary').set_value('Synthetic reviewed pump repair for September.').run()
    journal = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    assert journal is not None and journal.revision >= 1
    assert journal.draft.prepared_by == 'Synthetic Recovery Editor'
    assert next(b for b in journal.draft.blocks if b.key == 'activity_summary').text == 'Synthetic reviewed pump repair for September.'
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) is None

    another = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
    another.segmented_control[0].set_value('Monthly report').run()
    choose_report(another, synthetic_profiles()[0].facilities[0].title)
    assert not another.exception
    assert _value(another, 'Prepared by', 'text_input').value == 'Synthetic Recovery Editor'
    assert _value(another, 'Activity summary').value == 'Synthetic reviewed pump repair for September.'
    assert any('Recovered your unfinished changes' in m.value for m in another.success)
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) is None


def test_failed_browser_journal_write_preserves_current_fields_without_fake_success(monkeypatch, tmp_path):
    _visit(monkeypatch)
    app = monthly(monkeypatch, tmp_path)
    from app import monthly_report_guided as guided
    def broken(*args, **kwargs):
        raise library.LibraryError('Synthetic disk unavailable')
    monkeypatch.setattr(guided.active_work, 'save', broken)
    _value(app, 'Activity summary').set_value('Synthetic partial work should stay visible.').run()
    assert not app.exception
    assert _value(app, 'Activity summary').value == 'Synthetic partial work should stay visible.'
    assert any('Automatic recovery could not keep' in m.value for m in app.error)
    assert not any('Current edits kept for this browser' in m.value for m in app.success)
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) is None


def test_snapshot_change_requires_a_choice_before_restoring_older_browser_work(monkeypatch, tmp_path):
    _visit(monkeypatch)
    app = monthly(monkeypatch, tmp_path)
    _value(app, 'Prepared by', 'text_input').set_value('Synthetic A').run()
    _value(app, 'Activity summary').set_value('Unpublished browser text.').run()
    original = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    assert original is not None and original.base_snapshot_revision == 0
    saved = library.save_snapshot(original.draft, expected_revision=0, entered_editor='Synthetic Other Editor')
    newer = __import__('dataclasses').replace(saved.draft, prepared_by='Synthetic Other Editor')
    library.save_snapshot(newer, expected_revision=1, entered_editor='Synthetic Other Editor')
    another = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
    another.segmented_control[0].set_value('Monthly report').run()
    choose_report(another, synthetic_profiles()[0].facilities[0].title)
    assert not another.exception
    assert any('based on an older saved version' in m.value for m in another.warning)
    assert any(b.label == 'Review draft changes' for b in another.button)
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == original


def test_no_browser_cookie_keeps_manual_save_as_explicit_fallback(monkeypatch, tmp_path):
    from app import web_ui
    monkeypatch.setattr(web_ui, 'device_token', lambda cookies: '')
    app = monthly(monkeypatch, tmp_path)
    _value(app, 'Activity summary').set_value('Current unsaved text.').run()
    assert not app.exception
    assert any('Automatic recovery is unavailable' in x.value for x in app.warning)
    assert any(b.label == 'Save shared version' for b in app.button)


def test_recovered_draft_does_not_silently_upgrade_to_a_later_master(monkeypatch, tmp_path):
    _visit(monkeypatch)
    from app import monthly_report_designs as designs
    original_pin = designs.pin
    calls = []

    def tracked(profile, *, latest_master=False, preserve_legacy=False):
        calls.append((latest_master, preserve_legacy))
        return original_pin(profile, latest_master=latest_master, preserve_legacy=preserve_legacy)

    monkeypatch.setattr(designs, 'pin', tracked)
    app = monthly(monkeypatch, tmp_path)
    _value(app, 'Prepared by', 'text_input').set_value('Synthetic Editor').run()
    _value(app, 'Activity summary').set_value('Unfinished work retains its design.').run()
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) is not None

    calls.clear()
    another = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
    another.segmented_control[0].set_value('Monthly report').run()
    choose_report(another, synthetic_profiles()[0].facilities[0].title)
    assert not another.exception
    assert (False, True) in calls, "Recovered working copies must retain their original design, including the built-in layout."
    assert _value(another, 'Activity summary').value == 'Unfinished work retains its design.'


def _older_draft(monkeypatch, tmp_path):
    _visit(monkeypatch)
    app = monthly(monkeypatch, tmp_path)
    _value(app, 'Prepared by', 'text_input').set_value('Synthetic unfinished author').run()
    _value(app, 'Activity summary').set_value('Unfinished repair wording.').run()
    original = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    shared = replace(original.draft, prepared_by='Synthetic saved author', blocks=tuple(
        replace(block, text='Completed saved wording.') if block.key == 'activity_summary' else block
        for block in original.draft.blocks))
    snapshot = library.save_snapshot(shared, expected_revision=0, entered_editor='Synthetic shared editor')
    return _reopen(), original, snapshot


def _reopen():
    app = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
    app.segmented_control[0].set_value('Monthly report').run()
    choose_report(app, synthetic_profiles()[0].facilities[0].title)
    assert not app.exception
    return app


def _button(app, label):
    return next(item for item in app.button if item.label == label)


def test_older_draft_gate_explains_both_versions_before_a_choice(monkeypatch, tmp_path):
    app, original, snapshot = _older_draft(monkeypatch, tmp_path)
    from app.monthly_report_compare_ui import recovery_time
    captions = '\n'.join(item.value for item in app.caption)
    for value in (recovery_time(original.updated_at), recovery_time(snapshot.generated_at),
                  original.draft.profile.contract, original.draft.profile.title,
                  original.draft.profile.facilities[0].title, PERIOD.label,
                  'Synthetic unfinished author', 'Synthetic shared editor'):
        assert value in captions
    assert not any(item.label == 'Activity summary' for item in app.text_area)
    _button(app, 'Review draft changes').click().run()
    shown = '\n'.join(item.value for item in app.text)
    assert 'Unfinished repair wording.' in shown and 'Completed saved wording.' in shown
    assert not any('reviewed' in item.label.lower() for item in app.checkbox)
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == original
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) == snapshot


@pytest.mark.parametrize('label,expected', [
    ('Continue with unfinished draft', 'Unfinished repair wording.'),
    ('Open saved report', 'Completed saved wording.'),
])
def test_older_draft_choice_is_durable_report_scoped_and_does_not_publish(monkeypatch, tmp_path, label, expected):
    app, original, snapshot = _older_draft(monkeypatch, tmp_path)
    other = replace(original.draft, period=ReportPeriod(2026, 8))
    other_saved = active.save(TOKEN, other, expected_revision=0, base_snapshot_revision=0)
    _button(app, 'Review draft changes').click().run()
    _button(app, label).click().run()
    assert not app.exception
    assert _value(app, 'Activity summary').value == expected
    assert not any(item.label in {'Open saved report', 'Continue with unfinished draft'} for item in app.button)
    assert not any('older saved version' in item.value for item in app.warning)
    journal = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    assert journal.base_snapshot_revision == snapshot.revision
    assert journal.generation == original.generation
    assert next(block.text for block in journal.draft.blocks if block.key == 'activity_summary') == expected
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) == snapshot
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', other.period) == other_saved
    if label == 'Open saved report':
        assert any('Opened saved report version 1' in item.value for item in app.success)
        assert not any('Recovered your unfinished changes' in item.value for item in app.success)
    reopened = _reopen()
    assert _value(reopened, 'Activity summary').value == expected
    assert not any(item.label == 'Review draft changes' for item in reopened.button)


@pytest.mark.parametrize('side', ['browser', 'shared'])
def test_old_entry_choice_cannot_accept_a_changed_pair(monkeypatch, tmp_path, side):
    app, original, snapshot = _older_draft(monkeypatch, tmp_path)
    _button(app, 'Review draft changes').click().run()
    old_button = _button(app, 'Open saved report')
    if side == 'browser':
        active.save(TOKEN, replace(original.draft, prepared_by='Later browser author'),
            expected_revision=original.revision, expected_generation=original.generation,
            base_snapshot_revision=original.base_snapshot_revision)
    else:
        library.save_snapshot(replace(snapshot.draft, prepared_by='Later shared author'),
            expected_revision=snapshot.revision, entered_editor='Later shared editor')
    current = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    shared = library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD)
    old_button.click().run()
    assert not app.exception
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == current
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) == shared
    assert _button(app, 'Open saved report').key != old_button.key
    assert any('A version changed' in item.value for item in app.info)


def test_entry_choice_write_failure_keeps_both_versions_and_can_retry(monkeypatch, tmp_path):
    app, original, snapshot = _older_draft(monkeypatch, tmp_path)
    _button(app, 'Review draft changes').click().run()
    original_save = active.save
    monkeypatch.setattr(active, 'save', lambda *args, **kwargs: (_ for _ in ()).throw(library.LibraryError('Synthetic unavailable')))
    _button(app, 'Open saved report').click().run()
    assert not app.exception
    assert any('Your choice could not be saved' in item.value for item in app.error)
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == original
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) == snapshot
    assert not app.success
    monkeypatch.setattr(active, 'save', original_save)
    _button(app, 'Open saved report').click().run()
    assert _value(app, 'Activity summary').value == 'Completed saved wording.'


def test_entry_gate_explicitly_labels_unavailable_recorded_times(monkeypatch, tmp_path):
    app, original, snapshot = _older_draft(monkeypatch, tmp_path)
    monkeypatch.setattr(active, 'load', lambda *args, **kwargs: replace(original, updated_at=''))
    monkeypatch.setattr(library, 'load_snapshot', lambda *args, **kwargs: replace(snapshot, generated_at=''))
    app.run()
    assert not app.exception
    captions = '\n'.join(item.value for item in app.caption)
    assert captions.count('Time unavailable') == 2


def test_entry_choice_rejects_intervening_browser_write_atomically(monkeypatch, tmp_path):
    app, original, snapshot = _older_draft(monkeypatch, tmp_path)
    _button(app, 'Review draft changes').click().run()
    original_save = active.save
    raced = []

    def race(token, draft, **kwargs):
        if not raced:
            raced.append(original_save(token, replace(original.draft, prepared_by='Intervening browser author'),
                expected_revision=original.revision, expected_generation=original.generation,
                base_snapshot_revision=original.base_snapshot_revision))
        return original_save(token, draft, **kwargs)

    monkeypatch.setattr(active, 'save', race)
    _button(app, 'Open saved report').click().run()
    assert not app.exception
    assert any('A version changed again' in item.value for item in app.error)
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == raced[0]
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) == snapshot


@pytest.mark.parametrize('label,expected', [
    ('Continue with unfinished draft', 'Unfinished repair wording.'),
    ('Open saved report', 'Completed saved wording.'),
])
def test_shared_version_advancing_after_choice_save_requires_a_new_comparison(monkeypatch, tmp_path, label, expected):
    app, original, snapshot = _older_draft(monkeypatch, tmp_path)
    _button(app, 'Review draft changes').click().run()
    original_save = active.save
    writes, later = [], []

    def advance_after_save(token, draft, **kwargs):
        kept = original_save(token, draft, **kwargs)
        writes.append(kept)
        if not later:
            later.append(library.save_snapshot(replace(snapshot.draft,
                prepared_by='Newer shared author', blocks=tuple(
                    replace(block, text='Newer shared report after the explicit choice.')
                    if block.key == 'activity_summary' else block for block in snapshot.draft.blocks)),
                expected_revision=snapshot.revision, entered_editor='Newer shared editor'))
        return kept

    monkeypatch.setattr(active, 'save', advance_after_save)
    _button(app, label).click().run()
    assert not app.exception
    assert len(writes) == 1, 'Rerender must not silently accept or save the advancing shared version.'
    kept = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    assert kept == writes[0]
    assert kept.generation == original.generation
    assert kept.base_snapshot_revision == snapshot.revision
    assert next(block.text for block in kept.draft.blocks if block.key == 'activity_summary') == expected
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) == later[0]
    assert library.load_snapshot_version(RRH_CONTRACT, 'synthetic-guided', PERIOD, snapshot.revision) == snapshot
    assert not any(item.label == 'Activity summary' for item in app.text_area)
    assert any('older saved version' in item.value for item in app.warning)
    _button(app, 'Review draft changes').click().run()
    shown = '\n'.join(item.value for item in app.text)
    assert expected in shown and 'Newer shared report after the explicit choice.' in shown
    assert len(writes) == 1
