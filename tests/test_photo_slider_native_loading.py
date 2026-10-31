"""The visible photo-count slider reserves its pinned native loading height."""
from app import monthly_report_native_loading as loading
from app.monthly_report_model import ResolvedBlock
from test_monthly_photo_disclosures import photo_app


def example():
    return ResolvedBlock('improvements', 'This month', asset_hashes=('one.png',),
                         asset_captions=('Original synthetic caption',))


def test_photo_slider_placeholder_matches_native_label_plus_track():
    app = photo_app(example())
    slider, = app.select_slider
    selector = '.st-key-' + slider.key + ' > [data-testid="stSkeleton"]'
    rules = [x.proto.body for x in app.get('html') if selector in x.proto.body]
    assert len(rules) == 1, 'native 40px skeleton must reserve the 68px labeled slider'
    css = rules[0]
    assert 'height:auto' in css and 'Photos per page' in css
    assert 'min-height:1.5rem;margin-bottom:.25rem' in css
    assert '::after{content:"";display:block;height:2.5rem;}' in css
    # Exact captured desktop geometry: label24+gap4+track40, not generic40.
    assert (1.5 + .25 + 2.5) * 16 == 68
    assert 'visibility:hidden' in css and 'white-space:normal' in css
    assert '<input' not in css and 'focus' not in css and 'scroll' not in css


def test_same_slider_identity_and_delivered_values_without_content_mutation(monkeypatch):
    reserve = getattr(loading, 'reserve_photo_count_slider', None)
    assert reserve is not None
    monkeypatch.setattr(loading, 'reserve_photo_count_slider', lambda *args: None)
    app = photo_app(example())
    identity, key = app.select_slider[0].proto.id, app.select_slider[0].key
    before = app.session_state.photos_draft.blocks[0]
    monkeypatch.setattr(loading, 'reserve_photo_count_slider', reserve)
    app.run()
    assert not app.exception
    assert app.select_slider[0].proto.id == identity and app.select_slider[0].key == key
    assert app.session_state.photos_draft.blocks[0] == before
    app.select_slider[0].set_value(5).run()
    assert not app.exception and app.select_slider[0].value == 5
    assert app.session_state.photos_draft.blocks[0].photos_per_page == 5
    assert app.session_state.photos_draft.blocks[0].asset_captions == before.asset_captions
    assert len(app.select_slider) == 1


def test_unreviewed_runtime_does_not_guess_placeholder_geometry(monkeypatch):
    monkeypatch.setattr(loading.st, '__version__', 'future-unreviewed')
    app = photo_app(example())
    slider, = app.select_slider
    selector = '.st-key-' + slider.key + ' > [data-testid="stSkeleton"]'
    assert not any(selector in x.proto.body for x in app.get('html'))
