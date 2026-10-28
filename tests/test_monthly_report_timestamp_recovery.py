"""UTC-overflow metadata must not strand readable saved Monthly work.

The ISO timestamps below parse, but their UTC instants exceed Python's year
range. Tests model those existing metadata fields on synthetic saved records;
ordinary saves still record the real current time.
"""

from dataclasses import replace
from datetime import datetime
from html import escape
import json
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active, monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_compare_ui import recovery_time
from app.monthly_report_history_ui import _saved_at
from app.monthly_report_save_status import _saved_time
from test_monthly_report_active_recovery_ui import PERIOD, TOKEN, _older_draft, _reopen
from test_monthly_report_identity_history_ui import history_tables, widget


OVERFLOW_TIMES = (
    "0001-01-01T00:00:00+01:00",
    "9999-12-31T23:59:00-01:00",
)


@pytest.mark.parametrize("timestamp", OVERFLOW_TIMES, ids=("utc-underflow", "utc-overflow"))
@pytest.mark.parametrize("formatter,fallback", (
    pytest.param(_saved_time, "Time unavailable", id="save-status"),
    pytest.param(recovery_time, "Time unavailable", id="recovery-comparison"),
    pytest.param(_saved_at, None, id="history-recorded-value"),
))
def test_unrepresentable_utc_instant_uses_existing_display_fallback(timestamp, formatter, fallback):
    assert formatter(timestamp) == (timestamp if fallback is None else fallback)


@pytest.mark.parametrize("timestamp,utc", (
    ("0001-01-01T01:00:00+01:00", datetime(1, 1, 1)),
    ("0001-01-01T00:00:00+00:00", datetime(1, 1, 1)),
    ("9999-12-31T22:59:59-01:00", datetime(9999, 12, 31, 23, 59, 59)),
    ("9999-12-31T23:59:59+00:00", datetime(9999, 12, 31, 23, 59, 59)),
    ("2026-10-17T17:45:01-05:00", datetime(2026, 10, 17, 22, 45, 1)),
    ("2026-10-17T22:45:01Z", datetime(2026, 10, 17, 22, 45, 1)),
), ids=("near-minimum", "minimum-utc", "near-maximum", "maximum-utc", "ordinary-offset", "ordinary-z"))
def test_representable_instants_keep_existing_utc_formats(timestamp, utc):
    # Expected UTC instants are explicit; retain platform year-1 formatting.
    assert _saved_time(timestamp) == utc.strftime("%H:%M UTC")
    assert recovery_time(timestamp) == utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    assert _saved_at(timestamp) == utc.strftime("%b %d, %Y · %H:%M UTC")


def _recorded_timestamp(path, field, value):
    payload = json.loads(path.read_bytes())
    payload[field] = value
    path.write_bytes(library._json(payload))


def _json_records(root):
    return {path: path.read_bytes() for path in root.rglob("*.json")}


@pytest.fixture
def stored_copies(monkeypatch, tmp_path):
    app, browser, saved = _older_draft(monkeypatch, tmp_path)
    draft = browser.draft
    raw = b"Inspected synthetic pump. Follow-up observation remains pending."
    content, _ = sources.ingest(draft.profile, "synthetic-timestamp-evidence.txt", raw)
    reviewed = replace(content.source, findings="Reviewed synthetic source finding.",
                       captions=((1, "Synthetic reviewed caption."),))
    browser = active.save(TOKEN, replace(draft, sources=(reviewed,)),
                          expected_revision=browser.revision, expected_generation=browser.generation,
                          base_snapshot_revision=browser.base_snapshot_revision)
    saved = library.save_snapshot(replace(saved.draft, sources=(reviewed,)),
                                  expected_revision=saved.revision, entered_editor=saved.entered_editor)
    identity = draft.profile.contract, draft.profile.key, draft.period
    directory = library._profile_path(*identity[:2], snapshots=True)
    return SimpleNamespace(
        app=app, browser=browser, saved=saved, identity=identity,
        journal=active._directory(TOKEN, *identity) / "working.json",
        directory=directory, head=directory / (PERIOD.key + ".json"),
        latest=directory / "history" / f"{PERIOD.key}-{saved.revision:08d}.json",
        oldest=directory / "history" / f"{PERIOD.key}-00000001.json",
        source=reviewed, original=sources._path(draft.profile, reviewed.sha256, reviewed.suffix), raw=raw,
    )


@pytest.mark.parametrize("side,timestamp", (
    ("browser", OVERFLOW_TIMES[0]), ("shared", OVERFLOW_TIMES[1]),
))
@pytest.mark.parametrize("choice", ("Continue with unfinished draft", "Open saved report"))
def test_actual_recovery_choices_preserve_both_copies_until_explicit_action(stored_copies, tmp_path, side, timestamp, choice):
    stored = stored_copies
    if side == "browser":
        _recorded_timestamp(stored.journal, "updated_at", timestamp)
    else:
        for path in (stored.head, stored.latest):
            _recorded_timestamp(path, "generated_at", timestamp)
    browser = active.load(TOKEN, *stored.identity)
    saved = library.load_snapshot(*stored.identity)
    records = _json_records(tmp_path)
    history = _json_records(stored.directory)
    standing = library.load_profile(*stored.identity[:2])

    app = stored.app.run()
    assert not app.exception
    assert any("Time unavailable" in item.value for item in app.caption)
    assert _json_records(tmp_path) == records
    widget(app, "button", "Review draft changes").click().run()
    assert not app.exception
    shown = "\n".join(item.value for item in app.text)
    assert "Unfinished repair wording." in shown and "Completed saved wording." in shown
    for label in ("Continue with unfinished draft", "Open saved report"):
        assert not widget(app, "button", label).disabled
    assert _json_records(tmp_path) == records

    widget(app, "button", choice).click().run()
    assert not app.exception
    kept = active.load(TOKEN, *stored.identity)
    expected = browser.draft if choice == "Continue with unfinished draft" else saved.draft
    assert kept.draft == expected
    assert kept.revision == browser.revision + 1
    assert kept.generation == browser.generation
    assert kept.base_snapshot_revision == saved.revision
    assert kept.draft.sources == (stored.source,)
    assert library.load_snapshot(*stored.identity) == saved
    assert library.load_profile(*stored.identity[:2]) == standing
    assert _json_records(stored.directory) == history
    assert stored.original.read_bytes() == stored.raw
    reopened = _reopen()
    assert widget(reopened, "text_area", "Activity summary").value == next(
        block.text for block in expected.blocks if block.key == "activity_summary")
    assert active.load(TOKEN, *stored.identity) == kept


def _history_surface(token, contract, key, year, month):
    from app import monthly_report_active_work as active, monthly_report_library as library
    from app.monthly_report_history_ui import render_snapshot_history
    from app.monthly_report_model import ReportPeriod
    period = ReportPeriod(year, month)
    browser = active.load(token, contract, key, period)
    saved = library.load_snapshot(contract, key, period)
    render_snapshot_history(browser.draft, "synthetic-history", {}, saved)


@pytest.mark.parametrize("timestamp", OVERFLOW_TIMES)
def test_history_lists_recorded_time_and_inspects_versions_without_writes(stored_copies, tmp_path, timestamp):
    stored = stored_copies
    _recorded_timestamp(stored.oldest, "generated_at", timestamp)
    records = _json_records(tmp_path)
    browser = active.load(TOKEN, *stored.identity)
    head = library.load_snapshot(*stored.identity)
    old = library.load_snapshot_version(*stored.identity, 1)
    app = AppTest.from_function(_history_surface, args=(
        TOKEN, *stored.identity[:2], PERIOD.year, PERIOD.month)).run()
    assert not app.exception
    table, = history_tables(app)
    rows = [[cell.text_content() for cell in row] for row in table.xpath("./tbody/tr")]
    assert [row[0] for row in rows] == ["2", "1"]
    assert rows[0][1] == _saved_at(head.generated_at)
    assert rows[1][1] == timestamp
    widget(app, "selectbox", "Inspect a saved version").set_value(1).run()
    assert not app.exception
    assert any(item.value == "Saved: Time unavailable" for item in app.caption)
    shown = "\n".join(item.value for item in app.text)
    assert "Unfinished repair wording." in shown and "Completed saved wording." in shown
    widget(app, "selectbox", "Inspect a saved version").set_value(2).run()
    assert not app.exception
    assert any(item.value == "Saved: " + recovery_time(head.generated_at) for item in app.caption)
    assert not any(item.label in {"Open saved report", "Continue with unfinished draft"} for item in app.button)
    assert _json_records(tmp_path) == records
    assert active.load(TOKEN, *stored.identity) == browser
    assert library.load_snapshot(*stored.identity) == head
    assert library.load_snapshot_version(*stored.identity, 1) == old
    assert stored.original.read_bytes() == stored.raw


def _status_surface(token, contract, key, year, month):
    from app import monthly_report_active_work as active
    from app.monthly_report_model import ReportPeriod
    from app.monthly_report_save_status import SaveStatus
    browser = active.load(token, contract, key, ReportPeriod(year, month))
    SaveStatus("synthetic-status", recovery_available=True).browser_saved(browser.updated_at)


@pytest.mark.parametrize("timestamp", (*OVERFLOW_TIMES, '<synthetic time="unknown">&'))
def test_saved_acknowledgment_keeps_raw_escaped_title_and_persisted_state(stored_copies, tmp_path, timestamp):
    stored = stored_copies
    _recorded_timestamp(stored.journal, "updated_at", timestamp)
    records = _json_records(tmp_path)
    browser = active.load(TOKEN, *stored.identity)
    app = AppTest.from_function(_status_surface, args=(
        TOKEN, *stored.identity[:2], PERIOD.year, PERIOD.month)).run()
    assert not app.exception
    markup, = (item.value for item in app.markdown if 'class="enfra-browser-save-status"' in item.value)
    assert "Browser draft<br>Last saved · Time unavailable" in markup
    assert 'data-save-state="saved"' in markup
    assert 'title="' + escape(timestamp, quote=True) + '"' in markup
    assert "<synthetic " not in markup
    assert not app.button
    assert _json_records(tmp_path) == records
    assert active.load(TOKEN, *stored.identity) == browser
    assert stored.original.read_bytes() == stored.raw
