"""A thumbnail failure must not silently omit a previously selected source photo."""
import pytest

from app import monthly_report_picture_cards as cards
from test_monthly_report_cover_gallery_recovery import photo_report, cover_plan
from tests.test_monthly_report_start_import import start_app


def test_preview_failure_retains_selected_cover_mapping(monkeypatch, tmp_path):
    source = photo_report(tmp_path)
    original = source.read_bytes()
    app = start_app(monkeypatch, tmp_path, source)
    initial = cover_plan(app)
    selected = initial['cover_picture_id']
    assert selected
    reader = cards.read_import_image
    def fail_thumbnail(path, item, **kwargs):
        if item.id == selected and kwargs.get('preview'):
            raise ValueError('Synthetic transient thumbnail failure')
        return reader(path, item, **kwargs)
    monkeypatch.setattr(cards, 'read_import_image', fail_thumbnail)
    app.run()
    assert not app.exception
    current = cover_plan(app)
    assert current['cover_picture_id'] == selected
    assert current['destinations'][selected] == 'cover_photo'
    assert not current.get('cover_photo_omitted')
    assert source.read_bytes() == original
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_start_import import build_starting_import
    from app.monthly_report_asset_review import pending_asset_indexes
    plans = next(value for key, value in app.session_state.filtered_state.items()
                 if key.endswith('_section_plans') and isinstance(value, dict))
    mapped, _ = build_starting_import(source, inspect_docx(source), plans.values())
    photo = next(block for block in mapped.blocks if block.key == 'cover_photo')
    assert len(photo.asset_hashes) == 1
    assert pending_asset_indexes(photo) == (0,)  # Preview recovery is not approval.
    # Recovery/repeated rerender cannot erase or replace the chosen identity.
    monkeypatch.setattr(cards, 'read_import_image', reader)
    app.run()
    assert cover_plan(app)['cover_picture_id'] == selected
    assert source.read_bytes() == original


def test_explicit_omit_survives_thumbnail_failure(monkeypatch, tmp_path):
    source = photo_report(tmp_path)
    app = start_app(monkeypatch, tmp_path, source)
    next(button for button in app.button if button.label == 'No cover photograph').click().run()
    def fail_thumbnail(*args, **kwargs):
        raise ValueError('Synthetic thumbnail failure')
    monkeypatch.setattr(cards, 'read_import_image', fail_thumbnail)
    app.run()
    assert not app.exception
    plan = cover_plan(app)
    assert plan['cover_picture_id'] == ''
    assert plan['cover_photo_omitted']
    assert 'cover_photo' not in plan['destinations'].values()
    assert not any(button.label.startswith('Choose picture') for button in app.button)


def test_original_decode_failure_is_still_refused(monkeypatch, tmp_path):
    from app import monthly_report_sections as sections
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_start_import import build_starting_import
    source = photo_report(tmp_path)
    app = start_app(monkeypatch, tmp_path, source)
    plans = next(value for key, value in app.session_state.filtered_state.items()
                 if key.endswith('_section_plans') and isinstance(value, dict))
    def fail_original(*args, **kwargs):
        raise ValueError('Synthetic original decode refusal')
    monkeypatch.setattr(sections, 'read_import_image', fail_original)
    with pytest.raises(ValueError, match='Synthetic original decode refusal'):
        build_starting_import(source, inspect_docx(source), plans.values())


@pytest.mark.parametrize('omit', [False, True], ids=['selected', 'explicitly-omitted'])
def test_preview_failure_import_survives_saved_reopen_and_month_rollover(monkeypatch, tmp_path, omit):
    from app import monthly_report_library as library
    from app.monthly_report_asset_review import pending_asset_indexes
    from app.monthly_report_model import ReportPeriod
    from app.monthly_report_setup import new_month_draft
    from tests.test_monthly_report_start_import import save_start

    source = photo_report(tmp_path)
    original = source.read_bytes()
    app = start_app(monkeypatch, tmp_path, source)
    selected = cover_plan(app)['cover_picture_id']
    assert selected
    if omit:
        next(button for button in app.button if button.label == 'No cover photograph').click().run()
    reader = cards.read_import_image
    def fail_selected_thumbnail(path, item, **kwargs):
        if item.id == selected and kwargs.get('preview'):
            raise ValueError('Synthetic transient thumbnail failure')
        return reader(path, item, **kwargs)
    monkeypatch.setattr(cards, 'read_import_image', fail_selected_thumbnail)
    app.run()
    assert not app.exception
    assert cover_plan(app)['cover_picture_id'] == ('' if omit else selected)
    # Ordinary Continue performs the real builder/source checks and saves the
    # unchanged original. No client-art approval or output gate is waived.
    draft = save_start(app)
    assert draft is not None
    photo = next(block for block in draft.blocks if block.key == 'cover_photo')
    assert pending_asset_indexes(photo) == (() if omit else (0,))
    assert (photo.source == 'Omit') == omit
    assert bool(photo.asset_hashes) != omit
    initial_assets = {ref: library.read_asset(draft.profile.contract, draft.profile.key, ref)
                      for ref in photo.asset_hashes}
    library.save_snapshot(draft, expected_revision=0)
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft
    assert next(block for block in reopened.blocks if block.key == 'cover_photo') == photo
    carried = new_month_draft(reopened, ReportPeriod(2026, 10))
    library.save_snapshot(carried, expected_revision=0)
    carried = library.load_snapshot(carried.profile.contract, carried.profile.key, carried.period).draft
    carried_photo = next(block for block in carried.blocks if block.key == 'cover_photo')
    assert carried_photo.asset_hashes == photo.asset_hashes
    assert carried_photo.asset_provenance == photo.asset_provenance
    assert pending_asset_indexes(carried_photo) == (() if omit else (0,))
    assert (carried_photo.source == 'Omit') == omit
    assert all(library.read_asset(carried.profile.contract, carried.profile.key, ref) == raw
               for ref, raw in initial_assets.items())
    assert source.read_bytes() == original
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == original
    # Reopening the old version after rollover must not rewrite it either.
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft == reopened
