"""Pending photo work is visible without changing captions or review status."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_photo_controls import photo_disclosure_identity
from test_monthly_report_photo_review_ui import SCRIPT, button


def photo_app(block):
    script = SCRIPT.replace('assets, _field)', 'assets, _field, show_preview=False)')
    app = AppTest.from_string(script).run()
    app.session_state.photos_draft = replace(app.session_state.photos_draft, blocks=(block,))
    app.run()
    assert not app.exception
    return app


def test_empty_intake_is_open_and_display_does_not_create_report_content():
    block = ResolvedBlock('improvements', 'This month')
    app = photo_app(block)
    intake = next(panel for panel in app.expander if panel.label == 'Add photos')
    assert intake.proto.expanded
    assert len(app.get('file_uploader')) == 1
    assert not app.text_area
    assert app.session_state.photos_draft.blocks[0] == block
    app.run()
    assert app.session_state.photos_draft.blocks[0] == block


@pytest.mark.parametrize('count', [1, 2, 3, 6])
def test_every_pending_caption_starts_open_without_approving_it(count):
    block = ResolvedBlock('improvements', 'This month',
        asset_hashes=tuple(f'photo-{n}.png' for n in range(count)),
        asset_captions=tuple(f'Existing caption {n}' for n in range(count)))
    app = photo_app(block)
    panels = [panel for panel in app.expander if panel.label.startswith('Photo ')]
    assert len(panels) == count
    assert all(panel.proto.expanded for panel in panels)
    assert pending_asset_indexes(app.session_state.photos_draft.blocks[0]) == tuple(range(count))
    keys = [area.key for area in app.text_area]
    app.text_area[-1].set_value('Corrected caption').run()
    assert [area.key for area in app.text_area] == keys
    assert app.session_state.photos_draft.blocks[0].asset_captions[-1] == 'Corrected caption'
    assert pending_asset_indexes(app.session_state.photos_draft.blocks[0]) == tuple(range(count))


def test_mixed_photos_open_pending_and_keep_reviewed_siblings_compact():
    block = approve_all_assets(ResolvedBlock('improvements', 'Last month',
        asset_hashes=('one.png', 'two.png', 'three.png'), asset_captions=('One', 'Two', 'Three')))
    block = replace(block, asset_captions=('One', 'Pending correction', 'Three'))
    app = photo_app(block)
    panels = [panel for panel in app.expander if panel.label.startswith('Photo ')]
    assert [panel.label for panel in panels] == ['Photo 2']
    assert panels[0].proto.expanded
    button(app, 'Edit all photos or captions').click().run()
    panels = [panel for panel in app.expander if panel.label.startswith('Photo ')]
    assert [panel.proto.expanded for panel in panels] == [False, True, False]
    assert pending_asset_indexes(app.session_state.photos_draft.blocks[0]) == (1,)
    assert app.session_state.photos_draft.blocks[0].asset_captions == block.asset_captions


def test_reviewed_photos_keep_the_existing_compact_ready_state():
    block = approve_all_assets(ResolvedBlock('improvements', 'Last month',
        asset_hashes=('one.png', 'two.png', 'three.png'), asset_captions=('One', 'Two', 'Three')))
    app = photo_app(block)
    assert not app.text_area
    assert not next(panel for panel in app.expander if panel.label == 'Add photos').proto.expanded
    assert not pending_asset_indexes(app.session_state.photos_draft.blocks[0])


@pytest.mark.parametrize('instances', [False, True])
def test_panel_identity_follows_photo_through_caption_edit_reorder_and_removal(instances):
    from app.monthly_report_asset_instances import asset_instances, reindex_asset_instances, with_asset_instances
    block = ResolvedBlock('improvements', 'This month', asset_hashes=('one.png', 'two.png', 'three.png'),
                          asset_captions=('One', 'Two', 'Three'))
    if instances:
        block = with_asset_instances(block, asset_instances(block))
    identity = photo_disclosure_identity(block, 1, scope='current report')
    edited = replace(block, asset_captions=('One', 'Changed caption', 'Three'))
    assert photo_disclosure_identity(edited, 1, scope='current report') == identity
    moved = replace(edited, asset_hashes=('two.png', 'one.png', 'three.png'),
                    asset_captions=('Changed caption', 'One', 'Three'))
    removed = replace(edited, asset_hashes=('two.png', 'three.png'), asset_captions=('Changed caption', 'Three'))
    if instances:
        moved = with_asset_instances(moved, reindex_asset_instances(edited, (1, 0, 2)))
        removed = with_asset_instances(removed, reindex_asset_instances(edited, (1, 2)))
    assert photo_disclosure_identity(moved, 0, scope='current report') == identity
    assert photo_disclosure_identity(removed, 0, scope='current report') == identity
    assert photo_disclosure_identity(block, 1, scope='restarted report') != identity


def test_equal_bytes_keep_independent_occurrence_disclosures():
    from app.monthly_report_asset_instances import new_asset_instance, with_asset_instances
    block = ResolvedBlock('improvements', 'This month', asset_hashes=('same.png', 'same.png'))
    for current in (block, with_asset_instances(block, (new_asset_instance('same.png'), new_asset_instance('same.png')))):
        assert photo_disclosure_identity(current, 0, scope='report') != photo_disclosure_identity(current, 1, scope='report')


@pytest.mark.parametrize('instances', [False, True])
def test_removing_earlier_duplicate_keeps_remaining_disclosure_identity(instances):
    from app.monthly_report_asset_instances import asset_instances, with_asset_instances
    from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod
    from app.monthly_report_photo_controls import photo_order_identity, remove_photo
    block = ResolvedBlock('improvements', 'This month',
        asset_hashes=('same.png', 'same.png', 'third.png'),
        asset_captions=('First occurrence', 'Second occurrence', 'Third photo'))
    if instances:
        block = with_asset_instances(block, asset_instances(block))
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), blocks=(block,))
    identity = photo_disclosure_identity(block, 1, scope='report')
    request = dict(identity=photo_order_identity(draft, block, scope='report', cycle='cycle'),
                   index=0, asset='same.png')
    remaining = remove_photo(draft, block, request, block.asset_captions, 2,
                             scope='report', cycle='cycle')
    assert remaining.asset_captions == ('Second occurrence', 'Third photo')
    assert photo_disclosure_identity(remaining, 0, scope='report') == identity


def test_legacy_display_is_read_only_and_explicit_move_pins_existing_keys():
    from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod
    from app.monthly_report_photo_controls import photo_order_identity, photo_move_request, move_photo
    block = ResolvedBlock('improvements', 'This month',
        asset_hashes=('same.png', 'same.png', 'third.png'),
        asset_captions=('First', 'Second', 'Third'))
    app = photo_app(block)
    displayed = app.session_state.photos_draft.blocks[0]
    assert not displayed.asset_instances
    identities = tuple(photo_disclosure_identity(displayed, n, scope='report') for n in range(3))
    app.run()
    assert app.session_state.photos_draft.blocks[0] == displayed
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), blocks=(displayed,))
    request = photo_move_request(photo_order_identity(draft, displayed, scope='report', cycle='one'),
                                 displayed, 1, -1)
    moved = move_photo(draft, displayed, request, ('First corrected', 'Second', 'Third'), 2,
                       scope='report', cycle='one')
    assert moved.asset_captions == ('Second', 'First corrected', 'Third')
    assert tuple(photo_disclosure_identity(moved, n, scope='report') for n in range(3)) == (
        identities[1], identities[0], identities[2])
    assert not displayed.asset_instances


@pytest.mark.parametrize('caption', ['Manual correction', ''])
def test_explicit_legacy_move_does_not_duplicate_reimport_or_replace_manual_caption(caption):
    from app.monthly_report_asset_instances import asset_instances, merge_picture_occurrences
    from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod
    from app.monthly_report_photo_controls import photo_order_identity, photo_move_request, move_photo
    original = ResolvedBlock('improvements', 'Last month', asset_hashes=('one.png', 'two.png'),
                             asset_captions=('Original one', 'Original two'))
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), blocks=(original,))
    request = photo_move_request(photo_order_identity(draft, original, scope='report', cycle='one'),
                                 original, 0, 1)
    moved = move_photo(draft, original, request, (caption, 'Original two'), 2,
                       scope='report', cycle='one')
    images, captions, instances = merge_picture_occurrences(moved, original)
    assert images == moved.asset_hashes == ('two.png', 'one.png')
    assert captions == moved.asset_captions == ('Original two', caption)
    assert tuple(item.key for item in instances) == tuple(item.key for item in asset_instances(moved))


@pytest.mark.parametrize('caption', ['Manual correction', ''])
def test_pinned_duplicate_survivor_reimport_preserves_manual_caption(caption):
    from app.monthly_report_asset_instances import merge_picture_occurrences
    from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod
    from app.monthly_report_photo_controls import photo_order_identity, remove_photo
    original = ResolvedBlock('improvements', 'Last month',
        asset_hashes=('same.png', 'same.png', 'third.png'), asset_captions=('First', 'Second', 'Third'))
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), blocks=(original,))
    request = dict(identity=photo_order_identity(draft, original, scope='report', cycle='one'),
                   index=0, asset='same.png')
    remaining = remove_photo(draft, original, request, ('First', caption, 'Third'), 2,
                             scope='report', cycle='one')
    incoming = replace(original, asset_hashes=('same.png', 'third.png'), asset_captions=('Second', 'Third'))
    images, captions, instances = merge_picture_occurrences(remaining, incoming)
    assert images == remaining.asset_hashes == ('same.png', 'third.png')
    assert captions == remaining.asset_captions == (caption, 'Third')
    assert tuple(item.key for item in instances) == tuple(item.key for item in remaining.asset_instances)
