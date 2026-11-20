"""A70 synthetic Water upload: native safety, ordering, geometry and removal."""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources
from app import monthly_report_upload_ui as ui
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_page_controls import revise_included_page
from app.monthly_report_section_uploads import (
    automatic_water_upload, prepare_section_pages,
)
from test_monthly_report_section_uploads import APP


def water_pdf():
    """Four pages: safe portrait, priced, safe landscape, scanned image."""
    with fitz.open() as pdf:
        p = pdf.new_page(width=612, height=792)
        p.insert_text((42, 55), "Water Treatment Results\nFacility: Demonstration North Facility\nDate: 2026-09-14\nConductivity stable; performed water sample checks.")
        p = pdf.new_page(width=612, height=792)
        p.insert_text((42, 55), "Water Treatment Invoice\nFacility: Demonstration North Facility\nDate: 2026-09-14\nInvoice amount $500.00.")
        p = pdf.new_page(width=612, height=792)
        p.insert_text((42, 55), "Water Treatment Log\nFacility: Demonstration North Facility\nDate: 2026-09-14\nSamples checked; chemical balance stable.")
        p.set_rotation(90)
        p = pdf.new_page(width=612, height=792)
        buffer = BytesIO()
        Image.new("RGB", (240, 180), "white").save(buffer, format="PNG")
        p.insert_image(p.rect, stream=buffer.getvalue())
        return pdf.tobytes()


def _ingested(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = water_pdf()
    content, _ = sources.ingest(profile, "water-september.pdf", raw)
    return profile, raw, content


def test_native_water_plan_admits_only_text_only_unpriced_pages_in_source_order(monkeypatch, tmp_path):
    profile, raw, content = _ingested(monkeypatch, tmp_path)
    assert content.source.selected_pages == (1, 3)
    assert not content.source.client_page_reviews
    plan = automatic_water_upload(profile, ReportPeriod(2026, 9), content, {})
    assert plan.pages == (1, 3)
    assert "Page 2" in " ".join(plan.exceptions) and "pricing" in " ".join(plan.exceptions).lower()
    assert "Page 4" in " ".join(plan.exceptions)
    assert sources.source_bytes(profile, plan.content.source) == raw
    assert sha256(sources.source_bytes(profile, plan.content.source)).hexdigest() == sha256(raw).hexdigest()
    assert not plan.content.source.client_page_exclusions
    addition = prepare_section_pages(profile, (plan.content,), "water_reports", {},
                                     only_pages=frozenset((content.source.id, n) for n in plan.pages))
    block = addition["water_reports"]
    assert len(block.asset_hashes) == 2
    assert block.asset_captions == (
        "water-september.pdf · page/item 1",
        "water-september.pdf · page/item 3",
    )
    assert block.references == tuple(sources.source_reference(plan.content.source, n) for n in (1, 3))
    dimensions = []
    from app import monthly_report_library as library
    for ref in block.asset_hashes:
        with Image.open(BytesIO(library.read_asset(profile.contract, profile.key, ref))) as image:
            dimensions.append(image.size)
    assert dimensions[0][1] > dimensions[0][0]
    assert dimensions[1][0] > dimensions[1][1]


def test_auto_plan_blocks_unrelated_site_month_and_non_water_file(monkeypatch, tmp_path):
    profile, raw, content = _ingested(monkeypatch, tmp_path)
    period = ReportPeriod(2026, 9)
    for source in (
        replace(content.source, facility="Demonstration South Facility"),
        replace(content.source, service_date="2026-08-14"),
        replace(content.source, service_date=""),
        replace(content.source, classification="Reference only"),
        replace(content.source, suffix=".txt"),
    ):
        plan = automatic_water_upload(profile, period, replace(content, source=source), {})
        assert not plan.pages
        assert plan.content.source == source
    assert sources.source_bytes(profile, content.source) == raw


def test_water_upload_includes_safe_pages_once_without_reopening_removed_page(monkeypatch, tmp_path):
    profile, raw, _ = _ingested(monkeypatch, tmp_path)
    stream = BytesIO(raw)
    stream.name = "water-september.pdf"
    monkeypatch.setattr(ui.st, "file_uploader",
                        lambda label, **kwargs: [stream] if label == "Water-treatment files" else [])
    app = AppTest.from_string(APP, default_timeout=30).run()
    assert not app.exception
    update = ResolvedBlock("water_monthly_update", "This month",
                           text="September sample readings were stable.")
    diagram = ResolvedBlock("business_hours_workflow", "Library", text="Keep recurring procedure.")
    app.session_state["test_blocks"] = {
        "water_monthly_update": update, "business_hours_workflow": diagram,
    }
    app.radio[0].set_value("water_reports").run()
    assert not app.exception
    assert app.session_state["test_apply_count"] == 1
    block = app.session_state["test_blocks"]["water_reports"]
    assert len(block.asset_hashes) == 2
    assert app.session_state["test_blocks"]["water_monthly_update"] == update
    assert app.session_state["test_blocks"]["business_hours_workflow"] == diagram
    source = app.session_state["test_sources"][0]
    assert sources.source_bytes(profile, source) == raw
    assert any("Page 2" in warning.value for warning in app.warning)
    app.run()  # Duplicate native uploader bytes and routine rerun are no-ops.
    assert not app.exception
    assert app.session_state["test_apply_count"] == 1
    assert app.session_state["test_blocks"]["water_reports"].asset_hashes == block.asset_hashes
    omitted, edited_source = revise_included_page(
        block, source, 1, "omit", all_sources=(source,))
    app.session_state["test_blocks"]["water_reports"] = omitted
    app.session_state["synthetic_evidence"] = tuple(
        replace(item, source=edited_source) if item.source.id == source.id else item
        for item in app.session_state["synthetic_evidence"])
    app.run()  # An earlier upload remains selected in the browser.
    assert not app.exception
    result = app.session_state["test_blocks"]["water_reports"]
    assert len(result.asset_hashes) == 1
    assert result.references == (sources.source_reference(source, 3),)
    assert app.session_state["test_blocks"]["business_hours_workflow"] == diagram
    assert app.session_state["test_blocks"]["water_monthly_update"] == update
    assert sources.source_bytes(profile, edited_source) == raw


def test_water_bad_pdf_never_changes_saved_good_pages(monkeypatch, tmp_path):
    profile, raw, content = _ingested(monkeypatch, tmp_path)
    plan = automatic_water_upload(profile, ReportPeriod(2026, 9), content, {})
    block = prepare_section_pages(profile, (plan.content,), "water_reports", {},
                                  only_pages=frozenset((content.source.id, n) for n in plan.pages))["water_reports"]
    with pytest.raises((ValueError, RuntimeError, OSError)):
        sources.ingest(profile, "bad.pdf", b"%PDF-1.0\nnot a valid PDF")
    assert len(block.asset_hashes) == 2
    assert sources.source_bytes(profile, content.source) == raw

def test_water_auto_pages_and_monthly_update_survive_snapshot_roundtrip(monkeypatch, tmp_path):
    """Report-only attachments and one optional update round-trip independently."""
    from dataclasses import asdict
    from app import monthly_report_library as library
    from app.monthly_report_model import BlockSpec, synthetic_draft

    profile, raw, content = _ingested(monkeypatch, tmp_path)
    period = ReportPeriod(2026, 9)
    plan = automatic_water_upload(profile, period, content, {})
    pages = prepare_section_pages(profile, (plan.content,), "water_reports", {},
                                  only_pages=frozenset((content.source.id, n) for n in plan.pages))["water_reports"]
    update = ResolvedBlock("water_monthly_update", "This month",
                           text="Inspected September water readings.")
    procedure = ResolvedBlock("business_hours_workflow", "Library",
                              text="Saved, recurring demonstration workflow.")
    fresh = synthetic_draft(profile, period)
    section = next(s for s in fresh.sections if s.key == "water")
    rebuilt = replace(fresh, blocks=(update, pages, procedure),
                      sources=(plan.content.source,),
                      sections=tuple(replace(s, included=True, blocks=(
                          BlockSpec("water_monthly_update", "rich_text", False),
                          BlockSpec("water_reports", "pdf_pages", False),
                      )) if s.key == "water" else s for s in fresh.sections))
    restored = library.draft_from_dict(asdict(rebuilt))
    assert restored == rebuilt
    values = {block.key: block for block in restored.blocks}
    assert values["water_monthly_update"].text == update.text
    assert values["water_reports"].references == pages.references
    assert values["water_reports"].asset_captions == pages.asset_captions
    assert values["business_hours_workflow"] == procedure
    assert sources.source_bytes(profile, restored.sources[0]) == raw
