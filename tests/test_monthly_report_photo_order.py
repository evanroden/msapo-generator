"""Native photo order, delivered captions and guided recovery stay one revision."""

from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active, monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes
from app.monthly_report_model import ReportPeriod, ReportSource, ResolvedBlock, ReportTable, synthetic_draft, synthetic_profiles
from app.monthly_report_photo_controls import move_photo, photo_move_request, photo_order_identity
from test_monthly_report_cover_photo_path import current, standing
from test_monthly_report_ui import ROOT, choose_report, monthly

TOKEN = 'f' * 32


def photos(draft):
    return next(block for block in draft.blocks if block.key == 'improvements')


def button(app, label, index=0):
    matches = [value for value in app.button if value.label == label]
    assert len(matches) > index, f'{label} is missing from the existing photo editor'
    return matches[index]


def loaded_photos(monkeypatch, tmp_path, *, omitted=False):
    from app import web_ui
    # The ordinary workflow writes only this temporary root and synthetic actor.
    monkeypatch.setattr(web_ui, 'device_token', lambda cookies: TOKEN)
    app = monthly(monkeypatch, tmp_path)
    draft = current(app)
    assets = {}
    for color in ('blue', 'green', 'orange'):
        stream = BytesIO()
        Image.new('RGB', (24, 18), color).save(stream, 'PNG')
        raw = stream.getvalue()
        assets[library.asset_reference(raw, 'png')] = raw
    references = tuple(assets)
    block = approve_all_assets(ResolvedBlock(
        'improvements', 'Last month', asset_hashes=references,
        asset_captions=('First photo', 'Second photo', 'Third photo'), photos_per_page=2,
        text='Retained photo context: 0, NR, qualified.', rows=(('0', 'NR'),),
        extra_tables=(ReportTable(('Known', 'Qualified'), (('0', 'NR — not recorded'),)),),
        references=('native-progress-original',),
        asset_provenance=tuple((ref, ('native-progress-original',)) for ref in references)))
    if omitted:
        block = replace(block, source='Omit')
    blocks = {item.key: item for item in draft.blocks}
    blocks[block.key] = block
    draft = replace(draft, blocks=tuple(blocks.values()), prepared_by='Synthetic Editor')
    # A synthetic completed version is fixture setup, not an application action.
    library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()), entered_editor='Synthetic Editor')
    active.discard(TOKEN, draft.profile.contract, draft.profile.key, draft.period,
                   expected_revision=app.session_state[next(key for key in app.session_state.filtered_state
                       if key.startswith('report_guided_') and key.endswith('_active_sequence'))],
                   expected_generation=app.session_state[next(key for key in app.session_state.filtered_state
                       if key.startswith('report_guided_') and key.endswith('_active_generation'))])
    app = AppTest.from_file(ROOT / 'run_web.py', default_timeout=20).run()
    app.segmented_control[0].set_value('Monthly report').run()
    choose_report(app, draft.profile.facilities[0].title)
    next(item for item in app.text_input if item.label == 'Prepared by').set_value('Synthetic Editor').run()
    assert not app.exception
    return app, assets


def test_guided_move_commits_all_captions_and_activity_before_refresh_and_recovers(monkeypatch, tmp_path):
    app, assets = loaded_photos(monkeypatch, tmp_path)
    before, persisted = current(app), standing(current(app))
    assert not any(item.label.startswith('Move ') for item in app.button)
    button(app, 'Edit photos or captions').click().run()
    assert current(app) == before and standing(before) == persisted
    captions = [item for item in app.text_area if item.label == 'Caption']
    assert len(captions) == 3
    assert button(app, 'Move earlier').disabled and button(app, 'Move later', 2).disabled
    summary = next(item for item in app.text_area if item.label == 'Activity summary')
    summary.set_value('September inspections recorded alongside a photo move.')
    captions[0].set_value('First caption delivered with the move')
    captions[2].set_value('Later caption delivered before the same move commits')
    button(app, 'Move later').click().run()
    assert not app.exception
    after = current(app)
    old, new = photos(before), photos(after)
    assert new.asset_hashes == (old.asset_hashes[1], old.asset_hashes[0], old.asset_hashes[2])
    assert new.asset_captions == ('Second photo', 'First caption delivered with the move',
                                  'Later caption delivered before the same move commits')
    assert dict(new.asset_provenance) == dict(old.asset_provenance) and new.references == old.references
    assert (new.text, new.rows, new.extra_tables, new.photos_per_page) == (old.text, old.rows, old.extra_tables, 2)
    assert pending_asset_indexes(new) == (1, 2), 'Only changed captions need another review'
    assert next(item for item in after.blocks if item.key == 'activity_summary').text == summary.value
    assert all(item == next(value for value in after.blocks if value.key == item.key)
               for item in before.blocks if item.key not in ('improvements', 'activity_summary'))
    journal = active.load(TOKEN, after.profile.contract, after.profile.key, after.period)
    assert journal.draft == after, 'The guided refresh must follow the complete recovery commit'
    assert not any(key.endswith('_period_editor_refresh') for key in app.session_state.filtered_state)
    assert standing(before) == persisted
    assert all(library.read_asset(after.profile.contract, after.profile.key, ref) == raw for ref, raw in assets.items())

    # Reverse the order: the earlier native caption slots must not resurrect.
    button(app, 'Move earlier', 1).click().run()
    assert not app.exception
    reverse = photos(current(app))
    assert reverse.asset_hashes == old.asset_hashes
    assert reverse.asset_captions == (new.asset_captions[1], new.asset_captions[0], new.asset_captions[2])
    assert pending_asset_indexes(reverse) == (0, 2)
    button(app, 'Done editing photos').click().run()
    assert not any(item.label.startswith('Move ') for item in app.button)
    reopened = AppTest.from_file(ROOT / 'run_web.py', default_timeout=20).run()
    reopened.segmented_control[0].set_value('Monthly report').run()
    choose_report(reopened, after.profile.facilities[0].title)
    assert not reopened.exception
    assert photos(current(reopened)) == reverse
    assert standing(before) == persisted


def test_order_only_keeps_reviews_density_omission_and_stales_old_native_actions(monkeypatch, tmp_path):
    app, _ = loaded_photos(monkeypatch, tmp_path, omitted=True)
    before, persisted = current(app), standing(current(app))
    button(app, 'Edit photos or captions').click().run()
    old_action = button(app, 'Move later')
    old_action.click().run()
    assert not app.exception
    moved = photos(current(app))
    assert moved.source == 'Omit' and not pending_asset_indexes(moved)
    assert moved.asset_captions == ('Second photo', 'First photo', 'Third photo')
    app.select_slider[0].set_value(3)
    button(app, 'Move earlier', 1).click().run()
    returned = current(app)
    assert photos(returned).asset_hashes == photos(before).asset_hashes
    assert photos(returned).photos_per_page == 3 and photos(returned).source == 'Omit'
    assert not pending_asset_indexes(photos(returned))
    assert button(app, 'Move later').key != old_action.key
    old_action.click().run()
    assert not app.exception and current(app) == returned
    button(app, 'Remove photo').click().run()
    removed = photos(current(app))
    assert removed.source == 'Omit' and removed.photos_per_page == 3
    assert removed.asset_hashes == photos(returned).asset_hashes[1:]
    assert removed.asset_captions == photos(returned).asset_captions[1:]
    assert not pending_asset_indexes(removed)
    assert standing(before) == persisted


def test_move_invalidates_current_generated_package_and_docx_keeps_photo_page_order(monkeypatch, tmp_path):
    from app.monthly_report_docx import ReportPackage, assemble_docx
    app, assets = loaded_photos(monkeypatch, tmp_path)
    before = current(app)
    prefix = next(key[:-6] for key, value in app.session_state.filtered_state.items()
                  if key.startswith('report_guided_') and key.endswith('_draft') and value == before)
    app.session_state[prefix + '_package'] = ReportPackage(b'old-docx', b'old-pdf', 'old.docx', 'old.pdf', before.fingerprint)
    button(app, 'Edit photos or captions').click().run()
    assert {item.label for item in app.get('download_button')} >= {'Download DOCX', 'Download PDF'}
    button(app, 'Move later').click().run()
    assert not app.exception
    after = current(app)
    assert before.fingerprint != after.fingerprint
    assert prefix + '_package' not in app.session_state.filtered_state
    assert not any(item.label in ('Download DOCX', 'Download PDF') for item in app.get('download_button'))
    raw = assemble_docx(after, acknowledged_fingerprint=after.fingerprint, asset_loader=assets.__getitem__)
    with ZipFile(BytesIO(raw)) as package:
        # The existing native image-grid renderer includes captions in each
        # photo-page raster; they are not separate document.xml paragraphs.
        # Follow actual document relationships, then independently locate the
        # unchanged solid-color source pixels on the two embedded photo pages.
        from lxml import etree
        import numpy as np
        rels = etree.fromstring(package.read('word/_rels/document.xml.rels'))
        targets = {value.get('Id'): value.get('Target') for value in rels}
        xml = etree.fromstring(package.read('word/document.xml'))
        ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
              'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
        color_pages = []
        colors = {(0, 0, 255), (0, 128, 0), (255, 165, 0)}
        for reference in xml.xpath('//a:blip/@r:embed', namespaces=ns):
            with Image.open(BytesIO(package.read('word/' + targets[reference]))) as page:
                pixels = np.asarray(page.convert('RGB'))
                first_y = {}
                for color in colors:
                    rows = np.nonzero(np.all(pixels == color, axis=2))[0]
                    if len(rows):
                        first_y[color] = int(rows[0])
                if first_y:
                    color_pages.append(first_y)
    assert len(color_pages) == 2
    assert color_pages[0][(0, 128, 0)] < color_pages[0][(0, 0, 255)]
    assert set(color_pages[1]) == {(255, 165, 0)}


@pytest.mark.parametrize('action_label', ['Move later', 'Remove photo', 'Done editing photos'])
@pytest.mark.parametrize('boundary', ['incarnation', 'qa-reset', 'source'])
def test_old_native_action_packet_cannot_overwrite_replacement_photo_fields(monkeypatch, tmp_path, boundary, action_label):
    app, _ = loaded_photos(monkeypatch, tmp_path)
    button(app, 'Edit photos or captions').click().run()
    before = current(app)
    prefix = next(key[:-6] for key, value in app.session_state.filtered_state.items()
                  if key.startswith('report_guided_') and key.endswith('_draft') and value == before)
    action = button(app, action_label)
    next(item for item in app.text_area if item.label == 'Caption').set_value('Late old caption packet')
    app.select_slider[0].set_value(6)
    original = photos(before)
    replacement = replace(original, asset_captions=('Replacement caption', *original.asset_captions[1:]), photos_per_page=3)
    if boundary == 'incarnation':
        app.session_state[prefix + '_rich_text_epoch'] = 'replacement-editor-incarnation'
    elif boundary == 'qa-reset':
        app.session_state['_monthly_qa_generation'] = 'replacement-isolated-generation'
    else:
        replacement = replace(replacement, references=('replacement-native-original',),
            asset_provenance=tuple((ref, ('replacement-native-original',)) for ref in original.asset_hashes))
    replaced = replace(before, blocks=tuple(replacement if item.key == replacement.key else item for item in before.blocks))
    # This is a stale-packet component experiment: replace the authoritative
    # report at its actual import/reset/source boundary, then deliver the old
    # native widget state. It is not browser-reset or authentic-import proof.
    app.session_state[prefix + '_draft'] = replaced
    action.click().run()
    assert not app.exception
    assert photos(current(app)).asset_hashes == original.asset_hashes
    assert photos(current(app)).asset_captions[0] == 'Replacement caption'
    assert photos(current(app)).photos_per_page == 3
    assert len([item for item in app.text_area if item.label == 'Caption']) == 3


@pytest.mark.parametrize('action_label', ['Remove photo', 'Done editing photos'])
def test_photo_action_preserves_later_caption_and_activity_before_commit(monkeypatch, tmp_path, action_label):
    app, assets = loaded_photos(monkeypatch, tmp_path)
    before, persisted = current(app), standing(current(app))
    button(app, 'Edit photos or captions').click().run()
    [item for item in app.text_area if item.label == 'Caption'][2].set_value('Later caption delivered with photo action')
    next(item for item in app.text_area if item.label == 'Activity summary').set_value('September activity delivered with photo action.')
    button(app, action_label).click().run()
    assert not app.exception
    after = current(app)
    block = photos(after)
    expected_refs = photos(before).asset_hashes[1:] if action_label == 'Remove photo' else photos(before).asset_hashes
    expected_captions = ('Second photo', 'Later caption delivered with photo action') if action_label == 'Remove photo' else ('First photo', 'Second photo', 'Later caption delivered with photo action')
    assert block.asset_hashes == expected_refs and block.asset_captions == expected_captions
    assert next(item for item in after.blocks if item.key == 'activity_summary').text == 'September activity delivered with photo action.'
    assert pending_asset_indexes(block) == (len(block.asset_hashes) - 1,)
    assert active.load(TOKEN, after.profile.contract, after.profile.key, after.period).draft == after
    assert standing(before) == persisted
    assert all(library.read_asset(after.profile.contract, after.profile.key, ref) == raw for ref, raw in assets.items())
    if action_label == 'Done editing photos':
        assert not any(item.label.startswith('Move ') for item in app.button)


@pytest.mark.parametrize('pending', [False, True])
def test_open_photo_editor_preserves_same_packet_activity_and_pending_caption(monkeypatch, tmp_path, pending):
    app, _ = loaded_photos(monkeypatch, tmp_path)
    if pending:
        button(app, 'Edit photos or captions').click().run()
        next(item for item in app.text_area if item.label == 'Caption').set_value('Changed first caption').run()
        button(app, 'Done editing photos').click().run()
        assert len([item for item in app.text_area if item.label == 'Caption']) == 1
        next(item for item in app.text_area if item.label == 'Caption').set_value('Pending caption delivered while opening all photos')
    next(item for item in app.text_area if item.label == 'Activity summary').set_value('Activity delivered while opening photos.')
    button(app, 'Edit all photos or captions' if pending else 'Edit photos or captions').click().run()
    assert not app.exception
    after = current(app)
    assert next(item for item in after.blocks if item.key == 'activity_summary').text == 'Activity delivered while opening photos.'
    assert len([item for item in app.text_area if item.label == 'Caption']) == 3
    if pending:
        assert photos(after).asset_captions[0] == 'Pending caption delivered while opening all photos'
    assert active.load(TOKEN, after.profile.contract, after.profile.key, after.period).draft == after


def test_add_photo_keeps_same_packet_existing_captions_activity_and_new_asset(monkeypatch, tmp_path):
    from app import monthly_report_visual_ui as ui
    from app.monthly_report_docx import normalize_report_image
    class Upload(BytesIO):
        name = 'new-synthetic-photo.png'
        @property
        def size(self):
            return len(self.getvalue())
    source = BytesIO()
    Image.new('RGB', (30, 22), 'purple').save(source, 'PNG')
    upload = Upload(source.getvalue())
    incoming = []
    original_uploader = ui.st.file_uploader
    def uploader(label, *args, **kwargs):
        mounted = original_uploader(label, *args, **kwargs)
        return incoming if kwargs.get('key', '').endswith('_photos_improvements_files') else mounted
    # AppTest has no uploader setter. Only the new synthetic uploader bytes are
    # supplied; the ordinary uploader and all native edit/action controls remain.
    monkeypatch.setattr(ui.st, 'file_uploader', uploader)
    app, assets = loaded_photos(monkeypatch, tmp_path)
    before, persisted = current(app), standing(current(app))
    button(app, 'Edit photos or captions').click().run()
    incoming.append(upload)
    app.run()
    next(item for item in app.text_area if item.label == 'Caption').set_value('Caption delivered with the new photo')
    [item for item in app.text_area if item.label == 'Caption'][2].set_value('Later caption delivered with the new photo')
    next(item for item in app.text_area if item.label == 'Activity summary').set_value('September activity delivered with the new photo.')
    button(app, 'Add these photos').click().run()
    assert not app.exception
    after = current(app)
    block = photos(after)
    normalized = normalize_report_image(source.getvalue(), '.png')
    added = library.asset_reference(normalized.data, normalized.extension)
    assert block.asset_hashes == (*photos(before).asset_hashes, added)
    assert block.asset_captions == ('Caption delivered with the new photo', 'Second photo', 'Later caption delivered with the new photo', '')
    assert next(item for item in after.blocks if item.key == 'activity_summary').text == 'September activity delivered with the new photo.'
    assert pending_asset_indexes(block) == (0, 2, 3), 'Only changed captions and the new photo need review'
    assert block.photos_per_page == photos(before).photos_per_page
    journal = active.load(TOKEN, after.profile.contract, after.profile.key, after.period)
    assert journal.draft == after and dict(journal.assets)[added] == normalized.data
    assert upload.getvalue() == source.getvalue()
    assert standing(before) == persisted
    assert all(library.read_asset(after.profile.contract, after.profile.key, ref) == raw for ref, raw in assets.items())
    button(app, 'Add these photos').click().run()
    assert not app.exception and current(app) == after
    repeated = active.load(TOKEN, after.profile.contract, after.profile.key, after.period)
    assert repeated == journal, 'Repeating the same upload is an idempotent no-op'
    assert standing(before) == persisted


def test_one_native_move_after_ordinary_caption_commit_uses_current_revision(monkeypatch, tmp_path):
    app, _ = loaded_photos(monkeypatch, tmp_path)
    button(app, 'Edit photos or captions').click().run()
    next(item for item in app.text_area if item.label == 'Caption').set_value('Caption committed before the next move').run()
    before = photos(current(app))
    button(app, 'Move later').click().run()
    assert not app.exception
    after = photos(current(app))
    assert after.asset_hashes == (before.asset_hashes[1], before.asset_hashes[0], before.asset_hashes[2])
    assert after.asset_captions == ('Second photo', 'Caption committed before the next move', 'Third photo')
    assert pending_asset_indexes(after) == (1,)


def model_case():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    source = ReportSource('source-one', 'synthetic.pdf', 'a' * 64, '.pdf')
    block = approve_all_assets(ResolvedBlock('improvements', 'Last month',
        asset_hashes=('one.png', 'two.png'), asset_captions=('0', 'NR — qualified'),
        references=('source-one:1:' + source.fingerprint,),
        asset_provenance=(('one.png', ('source-one:1:' + source.fingerprint,)), ('two.png', ()))))
    draft = replace(draft, sources=(source,), blocks=(block,))
    return draft, block


@pytest.mark.parametrize('change', ['caption', 'list', 'provenance', 'source', 'missing-source',
    'profile', 'month', 'incarnation', 'qa-reset', 'cycle', 'asset', 'index', 'offset', 'boundary'])
def test_revision_bound_move_rejects_stale_source_scope_list_and_actions(change):
    draft, block = model_case()
    scope, cycle = 'editor-and-qa-generation-one', 'action-one'
    identity = photo_order_identity(draft, block, scope=scope, cycle=cycle)
    request = photo_move_request(identity, block, 0, 1)
    original = block
    if change == 'caption': block = replace(block, asset_captions=('Newer manual correction', 'NR'))
    elif change == 'list': block = replace(block, asset_hashes=('one.png', 'new.png'))
    elif change == 'provenance': block = replace(block, asset_provenance=(('one.png', ()), ('two.png', ())))
    elif change == 'source': draft = replace(draft, sources=(replace(draft.sources[0], sha256='b' * 64),))
    elif change == 'missing-source': draft = replace(draft, sources=())
    elif change == 'profile': draft = replace(draft, profile=replace(draft.profile, key='other-profile'))
    elif change == 'month': draft = replace(draft, period=ReportPeriod(2026, 10))
    elif change in ('incarnation', 'qa-reset'): scope = 'other-editor-or-reset-generation'
    elif change == 'cycle': cycle = 'already-consumed-action'
    elif change == 'asset': request['asset'] = 'other.png'
    elif change == 'index': request['index'] = True
    elif change == 'offset': request['offset'] = 2
    elif change == 'boundary': request['offset'] = -1
    with pytest.raises(ValueError, match='photos changed'):
        move_photo(draft, block, request, original.asset_captions, 2, scope=scope, cycle=cycle)
    assert original.asset_hashes == ('one.png', 'two.png')


def test_same_action_caption_delivery_preserves_other_image_review_and_native_source_context():
    draft, block = model_case()
    identity = photo_order_identity(draft, block, scope='scope', cycle='cycle')
    updated = move_photo(draft, block, photo_move_request(identity, block, 0, 1),
                         ('0 — corrected', 'NR — qualified'), 4, scope='scope', cycle='cycle')
    assert updated.asset_hashes == ('two.png', 'one.png')
    assert updated.asset_captions == ('NR — qualified', '0 — corrected')
    assert dict(updated.asset_provenance) == dict(block.asset_provenance) and updated.references == block.references
    assert pending_asset_indexes(updated) == (1,) and updated.photos_per_page == 4
