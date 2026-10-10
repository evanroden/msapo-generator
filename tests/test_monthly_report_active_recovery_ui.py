"""The same browser recovers working input without publishing report history."""
from pathlib import Path

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
    assert any(b.label == 'Review my unfinished work' for b in another.button)
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == original


def test_no_browser_cookie_keeps_manual_save_as_explicit_fallback(monkeypatch, tmp_path):
    from app import web_ui
    monkeypatch.setattr(web_ui, 'device_token', lambda cookies: '')
    app = monthly(monkeypatch, tmp_path)
    _value(app, 'Activity summary').set_value('Current unsaved text.').run()
    assert not app.exception
    assert any('Automatic recovery is unavailable' in x.value for x in app.warning)
    assert any(b.label == 'Save progress' for b in app.button)


def test_recovered_draft_does_not_silently_upgrade_to_a_later_master(monkeypatch, tmp_path):
    _visit(monkeypatch)
    from app import monthly_report_designs as designs
    original_pin = designs.pin
    calls = []

    def tracked(profile, *, latest_master=False):
        calls.append(latest_master)
        return original_pin(profile, latest_master=latest_master)

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
    assert False in calls, "Recovered working copies must not auto-install the latest master."
    assert _value(another, 'Activity summary').value == 'Unfinished work retains its design.'
