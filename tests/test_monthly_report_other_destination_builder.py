"""Unresolved additional content must stop at the public import boundaries."""

from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO

from docx import Document
from docx.shared import Inches
from PIL import Image
import pytest

from app.monthly_report_import import inspect_docx
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_sections import build_section_import, section_reviews
from app.monthly_report_start_import import (
    analyze_starting_report, automatic_section_plans, build_starting_import,
)
from test_monthly_report_start_import import PERIOD, report_file


BUILDERS = (build_section_import, build_starting_import)
KNOWN_TEXT = "September 2026 inspected the synthetic main pump."
OTHER_TEXT = "September 2026 checked the synthetic auxiliary pump."


def source_file(tmp_path, *, foreign=False):
    north, south = synthetic_profiles()[1].facilities
    path = report_file(tmp_path, title=south.title if foreign else north.title,
                       activity=(KNOWN_TEXT,), contact=False, table=foreign)
    document = Document(path)
    document.add_heading("14 EXTRA SOURCE MATERIAL", 1)
    document.add_paragraph(OTHER_TEXT)
    data = BytesIO()
    Image.new("RGB", (400, 300), "navy").save(data, "PNG")
    document.add_picture(BytesIO(data.getvalue()), width=Inches(4))
    document.save(path)
    inspection = inspect_docx(path)
    sections = {section.key: section for section in section_reviews(inspection)}
    known = next(item for item in sections["activity"].items if item.text == KNOWN_TEXT)
    text = next(item for item in sections["other"].items if item.text == OTHER_TEXT)
    picture = next(item for item in sections["other"].items if item.kind == "image")
    return path, inspection, known, text, picture


@contextmanager
def unchanged_source_and_plans(path, plans):
    original, before = path.read_bytes(), deepcopy(plans)
    try:
        yield
    finally:
        assert path.read_bytes() == original
        assert plans == before


@pytest.mark.parametrize("builder", BUILDERS, ids=("section", "starting"))
@pytest.mark.parametrize("target", ("", "other", "unknown-section"),
                         ids=("blank", "legacy-other", "unknown"))
@pytest.mark.parametrize("kind", ("text", "image"))
def test_contributing_other_requires_a_real_report_section(tmp_path, builder, target, kind):
    path, inspection, _, text, picture = source_file(tmp_path)
    item = text if kind == "text" else picture
    plans = [{"key": "other", "target": target, "approved": True, "selected": [item.id]}]
    with unchanged_source_and_plans(path, plans):
        with pytest.raises(ValueError, match="Choose a report section"):
            builder(path, inspection, plans)


@pytest.mark.parametrize("builder", BUILDERS, ids=("section", "starting"))
def test_item_mapping_cannot_bypass_missing_other_section_destination(tmp_path, builder):
    path, inspection, _, text, _ = source_file(tmp_path)
    plans = [{"key": "other", "target": "", "approved": True,
              "selected": [text.id], "destinations": {text.id: "activity_summary"}}]
    with unchanged_source_and_plans(path, plans):
        with pytest.raises(ValueError, match="Choose a report section"):
            builder(path, inspection, plans)


@pytest.mark.parametrize("builder", BUILDERS, ids=("section", "starting"))
@pytest.mark.parametrize(("target", "slot"),
                         (("activity", "activity_summary"), ("scorecards", "utility_analysis")))
def test_chosen_other_destination_keeps_text_picture_and_source_references(tmp_path, builder, target, slot):
    path, inspection, _, text, picture = source_file(tmp_path)
    plans = [{"key": "other", "target": target, "approved": True,
              "selected": [text.id, picture.id]}]
    with unchanged_source_and_plans(path, plans):
        mapped, mappings = builder(path, inspection, plans)
    assert len(mapped.blocks) == 1
    block = mapped.blocks[0]
    assert block.key == slot and block.text == OTHER_TEXT
    assert len(block.asset_hashes) == 1 and dict(mapped.assets)[block.asset_hashes[0]]
    assert {mapping.item_id for mapping in mappings} == {text.id, picture.id}
    assert {mapping.slot for mapping in mappings} == {slot}
    assert set(block.references) == {
        f"docx:{inspection.sha256}:{text.id}", f"docx:{inspection.sha256}:{picture.id}",
    }


@pytest.mark.parametrize("builder", BUILDERS, ids=("section", "starting"))
def test_omitted_other_does_not_require_destination_or_leak_retained_selections(tmp_path, builder):
    path, inspection, known, text, picture = source_file(tmp_path)
    plans = [{"key": "activity", "target": "activity", "approved": True, "selected": [known.id]},
             {"key": "other", "target": "other", "approved": True, "omit": True,
              "selected": [text.id, picture.id]}]
    with unchanged_source_and_plans(path, plans):
        mapped, mappings = builder(path, inspection, plans)
    assert [(block.key, block.text) for block in mapped.blocks] == [("activity_summary", KNOWN_TEXT)]
    assert not mapped.assets
    assert {mapping.item_id for mapping in mappings} == {known.id}


@pytest.mark.parametrize("builder", BUILDERS, ids=("section", "starting"))
def test_empty_other_plan_does_not_block_an_unrelated_valid_contribution(tmp_path, builder):
    path, inspection, known, _, _ = source_file(tmp_path)
    plans = [{"key": "activity", "target": "activity", "approved": True, "selected": [known.id]},
             {"key": "other", "target": "other", "approved": True, "selected": []}]
    with unchanged_source_and_plans(path, plans):
        mapped, mappings = builder(path, inspection, plans)
    assert [(block.key, block.text) for block in mapped.blocks] == [("activity_summary", KNOWN_TEXT)]
    assert {mapping.item_id for mapping in mappings} == {known.id}
    assert not mapped.assets


def test_automatic_foreign_site_empty_other_remains_excluded(tmp_path):
    path, inspection, _, _, _ = source_file(tmp_path, foreign=True)
    profile = synthetic_profiles()[0]
    sites = synthetic_profiles()[1].facilities
    analysis = analyze_starting_report(inspection, profile, PERIOD, sites)
    assert analysis.site_relation == "other"
    plans = automatic_section_plans(inspection, analysis)
    other = plans["other"]
    assert other["approved"] and other["target"] == "other"
    assert not other["omit"] and not other["selected"]
    with unchanged_source_and_plans(path, plans):
        mapped, mappings = build_starting_import(path, inspection, plans.values())
    assert any(table.columns for block in mapped.blocks for table in block.extra_tables)
    assert not any(block.text or block.rows or block.asset_hashes
                   or any(table.rows for table in block.extra_tables) for block in mapped.blocks)
    assert not mapped.assets
    other_ids = {item.id for section in section_reviews(inspection) if section.key == "other"
                 for item in section.items}
    assert not other_ids.intersection(mapping.item_id for mapping in mappings)
