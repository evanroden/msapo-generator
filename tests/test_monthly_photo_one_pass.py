"""Synthetic A68: one-pass progress-photo caption, thumbnail and ordering controls.

AppTest exercises native widget actions, not a served browser, drag gestures or PDF conversion.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_asset_review import pending_asset_indexes
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_photo_review_ui import SCRIPT


PALETTE = (
    ("one.png", "blue"), ("two.png", "green"), ("three.png", "orange"),
    ("four.png", "purple"), ("five.png", "red"), ("six.png", "yellow"),
)


def _app(count, *, missing=()):
    # Match every real synthetic source identity to a readable image, except
    # missing refs specifically supplied to exercise preview failure recovery.
    assets = tuple((name, color) for name, color in PALETTE[:count] if name not in missing)
    script = SCRIPT.replace(
        'for name, color in (("one.png", "blue"), ("two.png", "green")):',
        'for name, color in ' + repr(assets) + ':',
    ).replace('assets, _field)', 'assets, _field, show_preview=False)')
    app = AppTest.from_string(script).run()
    original = app.session_state.photos_draft
    block = ResolvedBlock(
        "improvements", "This month",
        asset_hashes=tuple(name for name, _ in PALETTE[:count]),
        asset_captions=tuple("Caption " + str(i + 1) for i in range(count)),
    )
    app.session_state.photos_draft = replace(original, blocks=(block,))
    app.run()
    assert not app.exception
    return app


@pytest.mark.parametrize("count", (1, 2, 3, 6))
def test_pending_caption_has_its_own_contained_thumbnail_without_extra_disclosure(count):
    app = _app(count)
    assert len([item for item in app.text_area if item.label == "Caption"]) == count
    assert len(app.get("image")) == count, "Every editable caption needs an adjacent source thumbnail"
    assert all(item.proto.expanded for item in app.expander if item.label.startswith("Photo "))
    assert pending_asset_indexes(app.session_state.photos_draft.blocks[0]) == tuple(range(count))
    app.run()
    assert len(app.get("image")) == count
    assert app.session_state.photos_draft.blocks[0].asset_captions == tuple(
        "Caption " + str(i + 1) for i in range(count)
    )


def test_pending_caption_and_order_commit_in_one_action_without_opening_all_photos():
    app = _app(3)
    assert not any(b.label == "Edit photos or captions" for b in app.button)
    move = next(b for b in app.button if b.label == "Move later" and not b.disabled)
    app.text_area[0].set_value("Corrected first caption")
    move.click().run()
    assert not app.exception
    block = app.session_state.photos_draft.blocks[0]
    assert block.asset_hashes == ("two.png", "one.png", "three.png")
    assert block.asset_captions == ("Caption 2", "Corrected first caption", "Caption 3")
    assert pending_asset_indexes(block) == (0, 1, 2)
    app.run()
    assert block == app.session_state.photos_draft.blocks[0]


def test_one_pass_remove_retains_survivor_caption_and_photo_identity():
    app = _app(3)
    app.text_area[2].set_value("Human-reviewed third photo")
    next(b for b in app.button if b.label == "Remove photo").click().run()
    assert not app.exception
    block = app.session_state.photos_draft.blocks[0]
    assert block.asset_hashes == ("two.png", "three.png")
    assert block.asset_captions == ("Caption 2", "Human-reviewed third photo")
    assert len(app.get("image")) == 2


def test_missing_thumbnail_is_explicit_and_never_erases_caption_or_changes_source():
    app = _app(3, missing=("three.png",))
    before = app.session_state.photos_draft.blocks[0]
    assert len(app.get("image")) == 2
    assert len(app.text_area) == 3
    assert any("preview" in item.value.lower() or "image" in item.value.lower()
               for item in app.warning)
    app.text_area[1].set_value("Corrected without changing missing sibling").run()
    updated = app.session_state.photos_draft.blocks[0]
    assert updated.asset_hashes == before.asset_hashes
    assert updated.asset_captions == ("Caption 1", "Corrected without changing missing sibling", "Caption 3")


def test_thumbnail_contains_uncropped_photo_on_white_and_keeps_original_bytes():
    from hashlib import sha256
    from io import BytesIO
    from PIL import Image

    from app.monthly_report_picture_cards import caption_thumbnail

    source = BytesIO()
    Image.new("RGB", (80, 40), "blue").save(source, "PNG")
    raw = source.getvalue()
    digest = sha256(raw).hexdigest()
    preview = caption_thumbnail(raw)
    with Image.open(BytesIO(preview)) as rendered:
        assert rendered.size == (288, 192)
        assert rendered.getpixel((144, 0)) == (255, 255, 255), "Contain, not center-crop"
        assert rendered.getpixel((144, 96)) == (0, 0, 255)
    assert sha256(raw).hexdigest() == digest, "Original bytes must stay immutable"


@pytest.mark.parametrize("bad", (b"", b"not-a-photo", b"GIF89a"))
def test_thumbnail_rejects_missing_malformed_or_unsupported_input(bad):
    from app.monthly_report_picture_cards import caption_thumbnail

    with pytest.raises((ValueError, OSError, SyntaxError)):
        caption_thumbnail(bad)
