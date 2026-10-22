"""Preflight names renderer layout limits before Generate (Refs #296, G5-output-1).

Every case is tied to the real renderer: a draft preflight accepts must render,
and the item preflight refuses must be the one the renderer would reject.
Synthetic data only.
"""
from dataclasses import replace
from io import BytesIO

from PIL import Image
import pytest

from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (OrgChartNode, ReportPeriod, ReportTable, ResolvedBlock,
                                      default_sections, synthetic_draft, synthetic_profiles)
from app.monthly_report_visuals import (_measure, _photo_grid, font, org_groups, org_page,
                                        photo_page, wrapped)

LAYOUT_KINDS = {"org_chart", "photo_caption", "table_columns"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def _draft(*blocks):
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    return replace(draft, sections=default_sections(), blocks=blocks)


def _layout(draft):
    return [(c.code, c.block_key, c.blocking) for c in preflight(draft) if c.code in LAYOUT_KINDS]


def _jpeg(_reference):
    buffer = BytesIO()
    Image.new("RGB", (40, 30), "white").save(buffer, "JPEG")
    return buffer.getvalue()


def _caption_at(lines, per_page):
    """The longest synthetic caption that wraps to exactly ``lines`` lines."""
    _, cell_w, _ = _photo_grid(per_page)
    words, draw, face = [], _measure(), font(24)
    while len(wrapped(" ".join(words + ["Synthetic"]), face, cell_w - 44, draw)) <= lines:
        words.append("Synthetic")
    return " ".join(words)


def _photos(caption, per_page=4):
    return ResolvedBlock("improvements", "This month", asset_hashes=("synthetic-photo",),
                         asset_captions=(caption,), photos_per_page=per_page)


@pytest.mark.parametrize("per_page", [1, 4, 6])
def test_caption_at_the_line_limit_passes_and_one_more_word_is_named_before_generate(per_page):
    fits = _caption_at(4, per_page)
    ok = _photos(fits, per_page)
    assert _layout(_draft(ok)) == []
    photo_page(ok, _jpeg)  # the renderer accepts what preflight accepts

    too_long = _photos(fits + " Synthetic", per_page)
    assert _layout(_draft(too_long)) == [("photo_caption", "improvements", True)]
    message = next(c.message for c in preflight(_draft(too_long)) if c.code == "photo_caption")
    assert "caption 1" in message and f"{per_page} per page" in message
    with pytest.raises(ValueError, match="caption"):
        photo_page(too_long, _jpeg)


def test_blank_or_omitted_photo_content_is_never_flagged():
    assert _layout(_draft(_photos(""))) == []
    omitted = replace(_photos(_caption_at(4, 4) + " Synthetic"), source="Omit")
    assert _layout(_draft(omitted)) == []


def _chain(text):
    nodes, manager = [], ""
    for level in range(4):
        key = f"synthetic-{level}"
        nodes.append(OrgChartNode(key, name=text, role=text, team=text, reports_to=manager))
        manager = key
    return tuple(nodes)


def test_chart_text_that_cannot_fit_its_pages_is_named_before_generate():
    long_text = " ".join(["Synthetic"] * 10)
    too_tall = ResolvedBlock("org_chart", "This month", org_nodes=_chain(long_text))
    assert _layout(_draft(too_tall)) == [("org_chart", "org_chart", True)]
    with pytest.raises(ValueError, match="too much text"):
        for index in range(len(org_groups(too_tall.org_nodes))):
            org_page(too_tall.org_nodes, index)

    readable = ResolvedBlock("org_chart", "This month", org_nodes=_chain("Synthetic Lead"))
    assert _layout(_draft(readable)) == []
    for index in range(len(org_groups(readable.org_nodes))):
        org_page(readable.org_nodes, index)


def test_chart_identity_errors_are_reported_once_by_the_existing_check():
    broken = ResolvedBlock("org_chart", "This month", org_nodes=(
        OrgChartNode("synthetic-a", name="Synthetic A", reports_to="missing"),))
    org_checks = [c for c in preflight(_draft(broken)) if c.code == "org_chart"]
    assert len(org_checks) == 1 and "existing manager" in org_checks[0].message


def test_rows_wider_than_their_columns_are_named_before_generate():
    wide = ResolvedBlock("end_of_life", "This month",
                         rows=(("Synthetic North", "Synthetic AHU-1", "2027", "extra"),))
    assert _layout(_draft(wide)) == [("table_columns", "end_of_life", True)]
    with pytest.raises(ValueError):
        assemble_docx(_draft(wide), asset_loader=_jpeg)

    fitting = replace(wide, rows=(("Synthetic North", "Synthetic AHU-1", "2027"),))
    assert _layout(_draft(fitting)) == []


def test_added_tables_are_checked_only_when_they_would_print():
    table = ReportTable(("Item", "Note"), (("Synthetic valve", "Checked", "extra"),))
    block = ResolvedBlock("end_of_life", "This month", extra_tables=(table,))
    assert _layout(_draft(block)) == [("table_columns", "end_of_life", True)]
    blank = replace(block, extra_tables=(ReportTable(("Item", "Note"), (("", "", ""),)),))
    assert _layout(_draft(blank)) == []
