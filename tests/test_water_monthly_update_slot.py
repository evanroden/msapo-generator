"""Contract checks for the optional monthly Water narrative.

The Water update must remain independent of the underlying vendor pages:
no auto-populated status claim and no required narrative when only PDFs exist.
"""

from app.monthly_report_model import default_sections


def test_water_update_is_optional_and_precedes_source_pages():
    water = next(section for section in default_sections() if section.key == "water")
    assert tuple(block.key for block in water.blocks) == (
        "water_monthly_update",
        "water_reports",
    )
    update, pages = water.blocks
    assert update.type == "rich_text"
    assert update.required is False
    assert not update.stock_text_keys
    assert pages.type == "pdf_pages"
    assert pages.required is False


def test_water_section_has_one_update_slot_not_one_per_vendor_page():
    water = next(section for section in default_sections() if section.key == "water")
    assert sum(block.type == "rich_text" for block in water.blocks) == 1
    assert sum(block.type == "pdf_pages" for block in water.blocks) == 1
