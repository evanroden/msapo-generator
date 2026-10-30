"""Real Streamlit editor renders exact warning/caption pairs without extra forms."""
import re
from dataclasses import replace
from streamlit.testing.v1 import AppTest
from test_monthly_report_photo_review_ui import SCRIPT, button

SCRIPT = SCRIPT.replace('draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))',
    'draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))\n    from app.monthly_report_model import default_sections\n    draft = replace(draft, sections=default_sections())')

REVIEW = '''
from app.monthly_report_checks import preflight
from app.monthly_report_correction_ui import render_picture_links
for check in preflight(st.session_state.photos_draft):
    render_picture_links(check, st.session_state.photos_draft, 'photos')
'''


def ids(app, kind):
    markup = '\n'.join(item.value for item in app.markdown)
    expression = r'id="(report-correction-[a-f0-9]+)"' if kind == 'markers' else r'href="#(report-correction-[a-f0-9]+)"'
    return re.findall(expression, markup)


def test_pending_caption_warning_pairs_survive_delivered_edit_and_repeated_render():
    app = AppTest.from_string(SCRIPT + REVIEW).run()
    button(app, 'Edit photos or captions').click().run()
    app.text_area[0].set_value('The exact changed caption').run()
    assert not app.exception
    assert len(ids(app, 'links')) == 1
    assert ids(app, 'links')[0] in ids(app, 'markers')
    before = app.session_state.photos_draft
    original_keys = [item.key for item in app.text_area]
    for _ in range(2):
        app.run()
        assert not app.exception
        assert app.session_state.photos_draft == before
        assert ids(app, 'links')[0] in ids(app, 'markers')
        assert [item.key for item in app.text_area] == original_keys
    assert app.text_area[0].value == 'The exact changed caption'


def test_removed_target_is_not_reused_for_remaining_picture():
    app = AppTest.from_string(SCRIPT + REVIEW).run()
    button(app, 'Edit photos or captions').click().run()
    app.text_area[0].set_value('Changed first caption').run()
    old = ids(app, 'links')[0]
    button(app, 'Remove photo').click().run()
    assert not app.exception
    assert old not in ids(app, 'markers')
    assert old not in ids(app, 'links')
    assert app.session_state.photos_draft.blocks[0].asset_captions == ('Second photo',)


def test_identical_photo_bytes_have_distinct_live_caption_targets():
    from app.monthly_report_asset_instances import new_asset_instance, with_asset_instances
    app = AppTest.from_string(SCRIPT + REVIEW).run()
    draft = app.session_state.photos_draft
    block = replace(draft.blocks[0], asset_hashes=('one.png', 'one.png'),
                    asset_captions=('Equal caption', 'Equal caption'),
                    client_reviewed_fingerprint='', client_asset_reviews=())
    block = with_asset_instances(block, (new_asset_instance('one.png'), new_asset_instance('one.png')))
    app.session_state.photos_draft = replace(draft, blocks=(block,))
    app.run()
    assert not app.exception
    links = ids(app, 'links')
    assert len(links) == len(set(links)) == 2
    assert set(links) == set(ids(app, 'markers'))
    app.text_area[0].set_value('Only the first occurrence changes').run()
    assert app.session_state.photos_draft.blocks[0].asset_captions == (
        'Only the first occurrence changes', 'Equal caption')
    assert ids(app, 'links') == links  # Display identity survives a caption edit.
    button(app, 'Remove photo').click().run()
    assert not app.exception
    assert ids(app, 'links') == [links[1]]
    assert links[0] not in ids(app, 'markers')
