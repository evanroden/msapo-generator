"""Imported content capabilities are truthful without retyping source data."""
from dataclasses import asdict

from streamlit.testing.v1 import AppTest

from app.monthly_report_import import ImportItem, inspect_docx
from app.monthly_report_import_content_types import (
    content_type_summary, picture_review_caption, unsupported_content_guidance,
)
from tests.test_monthly_report_import import synthetic_docx


def item(kind, number, **fields):
    return ImportItem(f"synthetic-{number}", kind, "word/document.xml",
                      number, 1, "activity", **fields)


def test_mixed_source_counts_distinguish_editable_content_and_picture_pages():
    items = (
        item("text", 1, text="Synthetic authored note."),
        item("table", 2, rows=(("Pump", "Checked"),)),
        item("image", 3, image_part="word/media/synthetic.png"),
        item("native_layout", 4, note="Validated native SmartArt text", text="Synthetic drawing"),
        item("unsupported", 5, note="Alternate drawing requires review"),
    )
    before = tuple(asdict(x) for x in items)
    label = content_type_summary(items)
    assert "1 editable text item" in label
    assert "1 editable Word table" in label
    assert "1 image-only picture" in label
    assert "2 drawing/embedded items to review" in label
    assert "OCR" not in label and "searchable" not in label
    assert tuple(asdict(x) for x in items) == before


def test_no_filler_when_only_text_or_passive_artwork():
    assert content_type_summary((item("text", 1, text="A source paragraph"),)) == ""
    # A passive native layout marker without readable foreground content is
    # not evidence of an extra editing task.
    assert content_type_summary((item("native_layout", 1, note="Native divider artwork"),)) == ""


def test_pictures_have_precise_but_noninvented_accessible_descriptions():
    photograph = item("image", 1, text="Undetermined site photo", image_role="")
    unknown_logo = item("image", 2, image_role="logo")
    client_logo = item("image", 3, image_role="client_logo")
    header = item("image", 4, image_role="header_artwork")
    for picture in (photograph, unknown_logo, client_logo, header):
        caption = picture_review_caption(picture)
        assert "Image only" in caption and "not editable" in caption
        assert picture.text not in caption
    assert picture_review_caption(photograph).startswith("Imported picture")
    assert "owner unconfirmed" in picture_review_caption(unknown_logo)
    assert picture_review_caption(client_logo).startswith("Client logo image")
    assert picture_review_caption(header).startswith("Header artwork")
    assert "ENFRA" not in picture_review_caption(unknown_logo)


def test_unsupported_review_is_explicit_and_does_not_unlock_layout():
    unsupported = item("unsupported", 1, note="Embedded object was not executed.")
    editable = item("table", 2, rows=(("Field", "Value"),))
    message = unsupported_content_guidance((unsupported, editable))
    assert "not an editable table" in message
    assert "original-page preview" in message
    assert "clear replacement" in message
    assert unsupported_content_guidance((editable,)) == ""


def test_real_synthetic_word_import_has_correct_editability_inventory(tmp_path):
    path = synthetic_docx(tmp_path)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    assert any(x.kind == "table" and x.section == "activity" for x in inspection.items)
    assert any(x.kind == "image" for x in inspection.items)
    message = content_type_summary(inspection.items)
    assert "editable Word table" in message
    assert "image-only picture" in message
    assert original == path.read_bytes()  # no source rewrite or read-side mutation


def test_streamlit_exposes_usable_screen_reader_text_with_no_new_review_controls():
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_import import ImportItem
from app.monthly_report_import_content_types import (
    content_type_summary, picture_review_caption, unsupported_content_guidance
)
items = (
    ImportItem("text", "text", "word/document.xml", 1, 1, text="Synthetic note"),
    ImportItem("picture", "image", "word/document.xml", 2, 1),
    ImportItem("floating", "unsupported", "word/document.xml", 3, 1),
)
st.caption(content_type_summary(items))
st.caption(picture_review_caption(items[1]))
st.caption(unsupported_content_guidance(items))
""").run()
    assert not app.exception
    captions = " ".join(entry.value for entry in app.get("caption"))
    assert "image-only picture" in captions
    assert "text inside is not editable" in captions
    assert "original-page preview" in captions
    assert not app.button and not app.radio and not app.checkbox
