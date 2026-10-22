"""A failed review display must not interrupt unrelated ordered recovery."""
import pytest
from streamlit.runtime.media_file_manager import MediaFileManager
from app import monthly_report_picture_batch_ui as batch
from app import monthly_report_picture_group as group
from app import monthly_report_active_work as active
from app.monthly_report_asset_review import pending_asset_indexes
from test_monthly_report_photo_order import loaded_photos, button, current, photos, TOKEN


@pytest.mark.parametrize('failure', ['storage', 'unsafe_url'])
def test_second_media_registration_failure_preserves_same_packet_journal(monkeypatch, tmp_path, failure):
    app, _ = loaded_photos(monkeypatch, tmp_path)
    button(app, 'Edit photos or captions').click().run()
    original = MediaFileManager.add
    calls = []
    def add(self, raw, mime, coordinates, *args, **kwargs):
        if coordinates.startswith('picture-review:'):
            calls.append(coordinates)
            if len(calls) >= 2:
                if failure == 'storage':
                    raise OSError('Synthetic registration failure')
                return '//external.invalid/media/' + 'a' * 32 + '.png'
        return original(self, raw, mime, coordinates, *args, **kwargs)
    monkeypatch.setattr(MediaFileManager, 'add', add)
    captions = [item for item in app.text_area if item.label == 'Caption']
    captions[0].set_value('First edited caption retained during display failure')
    captions[2].set_value('Third edited caption retained during display failure')
    next(item for item in app.text_area if item.label == 'Activity summary').set_value('Retain the same-event activity edit.')
    next(item for item in app.text_input if item.label == 'Prepared by').set_value('Synthetic Changed Editor')
    button(app, 'Move later').click().run()
    assert not app.exception
    assert all('Review the new or changed pictures' in e.value for e in app.error)
    after = current(app)
    assert len(calls) >= 2
    assert after.prepared_by == 'Synthetic Changed Editor'
    assert photos(after).asset_captions == ('Second photo',
        'First edited caption retained during display failure', 'Third edited caption retained during display failure')
    assert pending_asset_indexes(photos(after)) == (1, 2)
    assert button(app, 'Create Word and PDF').disabled
    assert next(b for b in after.blocks if b.key == 'activity_summary').text == 'Retain the same-event activity edit.'
    journal = active.load(TOKEN, after.profile.contract, after.profile.key, after.period)
    assert journal.draft == after
    assert any('could not be displayed' in w.value for w in app.warning)
    assert any(b.label.startswith('Remove picture') for b in app.button)
    assert not any(k.endswith('_picture_batch_active') for k in app.session_state.filtered_state)


def test_display_failure_revokes_old_component_consent_without_swallowing_programming_errors(monkeypatch):
    envelope = {'identity': 'exact', 'nonce': 'old', 'entries': ('one', 'two')}
    key = 'test_picture_component_old'
    state = {'test_picture_batch_active': envelope,
             key: {'submission': {'identity': 'exact', 'nonce': 'old', 'loaded': [True, True], 'left': [False, False]}}}
    monkeypatch.setattr(batch.st, 'session_state', state)
    warnings = []
    monkeypatch.setattr(batch.st, 'warning', warnings.append)
    def fail(**kwargs):
        raise group.PictureMediaError('Synthetic media failure')
    monkeypatch.setattr(group, 'render_group', fail)
    batch._render_group('test', envelope, [])
    batch._queue_component('test', envelope, key)
    assert warnings and 'test_picture_batch_active' not in state
    assert 'test_picture_batch_request' not in state
    def bug(**kwargs):
        raise RuntimeError('Synthetic programming error')
    monkeypatch.setattr(group, 'render_group', bug)
    with pytest.raises(RuntimeError, match='programming error'):
        batch._render_group('test', envelope, [])
