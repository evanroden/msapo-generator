"""A stale browser page compares both complete copies before a guarded choice."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from test_monthly_report_active_recovery_ui import _visit, _value, TOKEN, ROOT, PERIOD
from test_monthly_report_ui import monthly, choose_report
from app.monthly_report_model import synthetic_profiles


def _button(app, label):
    return next(item for item in app.button if item.label == label)


def _two_copies(monkeypatch, tmp_path):
    _visit(monkeypatch)
    first = monthly(monkeypatch, tmp_path)
    _value(first, 'Prepared by', 'text_input').set_value('Synthetic first editor').run()
    _value(first, 'Activity summary').set_value('Synthetic starting wording.').run()
    second = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
    second.segmented_control[0].set_value('Monthly report').run()
    choose_report(second, synthetic_profiles()[0].facilities[0].title)
    _value(second, 'Activity summary').set_value('Synthetic newer recovery wording.').run()
    newer = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    _value(first, 'Activity summary').set_value('Synthetic wording still on the first page.').run()
    assert not first.exception and not second.exception
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == newer
    return first, second, newer


def test_conflicting_browser_copies_can_be_compared_without_reload(monkeypatch, tmp_path):
    first, _, newer = _two_copies(monkeypatch, tmp_path)
    _button(first, 'Compare browser copies').click().run()
    assert not first.exception
    shown = '\n'.join(item.value for item in first.text)
    assert 'Synthetic newer recovery wording.' in shown
    assert 'Synthetic wording still on the first page.' in shown
    assert not _button(first, 'Keep this page for recovery').disabled
    assert not _button(first, 'Use the newer browser copy').disabled
    assert not any(item.label == 'I reviewed the recovery conflict' for item in first.checkbox)
    captions = '\n'.join(item.value for item in first.caption)
    assert newer.updated_at[:10] in captions and 'UTC' in captions
    assert 'September 2026' in captions and newer.draft.profile.facilities[0].title in captions
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == newer
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) is None


def _review(first):
    _button(first, 'Compare browser copies').click().run()


@pytest.mark.parametrize('choice,expected', [
    ('Keep this page for recovery', 'Synthetic wording still on the first page.'),
    ('Use the newer browser copy', 'Synthetic newer recovery wording.'),
])
def test_explicit_copy_choice_recovers_without_creating_shared_history(monkeypatch, tmp_path, choice, expected):
    first, _, newer = _two_copies(monkeypatch, tmp_path)
    _review(first)
    _button(first, choice).click().run()
    assert not first.exception
    assert _value(first, 'Activity summary').value == expected
    kept = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    assert next(block.text for block in kept.draft.blocks if block.key == 'activity_summary') == expected
    assert kept.generation == newer.generation
    if choice == 'Use the newer browser copy':
        assert kept == newer
    else:
        assert kept.revision > newer.revision
    assert not any('not kept for recovery' in item.value for item in first.error)
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) is None
    # A fresh native application session must recover the selected copy.
    reopened = AppTest.from_file(ROOT / 'run_web.py', default_timeout=30).run()
    reopened.segmented_control[0].set_value('Monthly report').run()
    choose_report(reopened, synthetic_profiles()[0].facilities[0].title)
    assert _value(reopened, 'Activity summary').value == expected


@pytest.mark.parametrize('side', ['newer', 'this page'])
def test_old_choice_does_not_survive_a_change_to_either_compared_copy(monkeypatch, tmp_path, side):
    first, second, newer = _two_copies(monkeypatch, tmp_path)
    _review(first)
    prior_button = _button(first, 'Keep this page for recovery')
    if side == 'newer':
        _value(second, 'Activity summary').set_value('Synthetic newer copy changed after comparison.').run()
        newer = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    else:
        # This pending edit is delivered with the old choice. It must be
        # captured without treating an earlier comparison as its approval.
        _value(first, 'Activity summary').set_value('Synthetic later human edit on this page.')
    prior_button.click().run()
    assert not first.exception
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == newer
    assert _button(first, 'Keep this page for recovery').key != prior_button.key
    assert any('A browser copy changed' in item.value for item in first.info)
    if side == 'this page':
        assert _value(first, 'Activity summary').value == 'Synthetic later human edit on this page.'


def test_recovery_choice_write_failure_keeps_both_copies_and_an_actionable_error(monkeypatch, tmp_path):
    first, _, newer = _two_copies(monkeypatch, tmp_path)
    _review(first)
    original = active.save
    def fail_choice(token, draft, **kwargs):
        if kwargs['expected_revision'] == newer.revision:
            raise library.LibraryError('Synthetic write failure')
        return original(token, draft, **kwargs)
    monkeypatch.setattr(active, 'save', fail_choice)
    _button(first, 'Keep this page for recovery').click().run()
    assert not first.exception
    assert any('This page could not be kept for recovery' in item.value for item in first.error)
    assert _value(first, 'Activity summary').value == 'Synthetic wording still on the first page.'
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == newer
    assert not any('data-save-state="saved"' in item.value for item in first.markdown)
    monkeypatch.setattr(active, 'save', original)
    _button(first, 'Keep this page for recovery').click().run()
    assert not first.exception
    assert any('data-save-state="saved"' in item.value and 'Last saved' in item.value for item in first.markdown)
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD).draft == next(
        value for key, value in first.session_state.filtered_state.items()
        if key.endswith('_draft') and hasattr(value, 'blocks'))


def test_another_write_during_the_choice_is_rejected_atomically(monkeypatch, tmp_path):
    first, _, newer = _two_copies(monkeypatch, tmp_path)
    _review(first)
    original = active.save
    intervening = []
    def race_choice(token, draft, **kwargs):
        if kwargs['expected_revision'] == newer.revision and not intervening:
            revised = replace(newer.draft, prepared_by='Synthetic intervening editor')
            intervening.append(original(token, revised,
                expected_revision=newer.revision, expected_generation=newer.generation,
                base_snapshot_revision=newer.base_snapshot_revision, assets=dict(newer.assets)))
        return original(token, draft, **kwargs)
    monkeypatch.setattr(active, 'save', race_choice)
    _button(first, 'Keep this page for recovery').click().run()
    assert not first.exception and len(intervening) == 1
    assert any('The recovery copy changed again' in item.value for item in first.error)
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == intervening[0]
    assert _value(first, 'Activity summary').value == 'Synthetic wording still on the first page.'
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) is None


def test_cleared_recovery_is_not_recreated_until_an_explicit_choice(monkeypatch, tmp_path):
    first, _, newer = _two_copies(monkeypatch, tmp_path)
    generation = active.discard(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD,
        expected_revision=newer.revision, expected_generation=newer.generation)
    _review(first)
    assert active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) is None
    assert not any(item.label == 'Use the newer browser copy' for item in first.button)
    assert any('The browser recovery copy was cleared' in item.value for item in first.warning)
    _button(first, 'Keep this page for recovery').click().run()
    assert not first.exception
    kept = active.load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD)
    assert kept.generation == generation != newer.generation
    assert next(block.text for block in kept.draft.blocks if block.key == 'activity_summary') == 'Synthetic wording still on the first page.'
    assert library.load_snapshot(RRH_CONTRACT, 'synthetic-guided', PERIOD) is None


def test_use_newer_copy_checks_it_again_before_replacing_page(monkeypatch, tmp_path):
    first, _, newer = _two_copies(monkeypatch, tmp_path)
    _review(first)
    original_load = active.load
    calls = []
    raced = []

    def race_load(*args, **kwargs):
        calls.append(None)
        if len(calls) == 2:
            raced.append(active.save(TOKEN, replace(newer.draft, prepared_by='Intervening author'),
                expected_revision=newer.revision, expected_generation=newer.generation,
                base_snapshot_revision=newer.base_snapshot_revision))
        return original_load(*args, **kwargs)

    monkeypatch.setattr(active, 'load', race_load)
    _button(first, 'Use the newer browser copy').click().run()
    assert not first.exception and len(raced) == 1
    assert any('The recovery copy changed again' in item.value for item in first.error)
    assert _value(first, 'Activity summary').value == 'Synthetic wording still on the first page.'
    assert original_load(TOKEN, RRH_CONTRACT, 'synthetic-guided', PERIOD) == raced[0]
