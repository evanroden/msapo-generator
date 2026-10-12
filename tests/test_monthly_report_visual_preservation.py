"""No silent diagram loss when simplifying monthly first-section import.

Only invented Word drawings and organization names are used. Image presence,
source section, renderer failures, page pricing and prior-client scope all
remain explicit constraints on what can enter the report.
"""
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.monthly_report_docx import ReportImage
from app.monthly_report_import import DocxInspection, ImportItem
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_sections import ImportSection, build_section_import
from app.monthly_report_start_import import (
    StartingReportAnalysis, automatic_section_plans, build_starting_import,
)
from app.monthly_report_visual_preservation import (
    DiagramPreservationError, VISUAL_SLOTS, diagram_source_sections,
    preserve_section_diagrams,
)
from app.monthly_report_word_pages import WordPage


SOURCE = "a" * 64


def scene(section="organization", other=False):
    item = ImportItem("native-drawing", "unsupported", "word/document.xml",
                      8, 2, section, note="Unmapped native SmartArt")
    items = [item]
    if other:
        items.append(ImportItem("other-section", "text", "word/document.xml",
                                9, 2, "activity", text="Another section's work"))
    info = DocxInspection(SOURCE, tuple(items), (), (), 2)
    section_obj = ImportSection(section, section.title(), (item,))
    return info, section_obj


def raster():
    output = BytesIO()
    Image.new("RGB", (640, 480), "navy").save(output, "PNG")
    return output.getvalue()


def plan_for(inspection):
    return automatic_section_plans(
        inspection, StartingReportAnalysis((), "same", (), (), ())
    )


def test_unsupported_drawings_cannot_auto_approve_as_missing():
    inspection, _ = scene()
    plan = plan_for(inspection)["organization"]
    assert not plan["approved"]
    assert plan["questions"]
    assert not plan.get("unsupported_reviewed", False)
    assert not plan["selected"]


def test_diagrams_map_into_the_original_logical_section(monkeypatch):
    import app.monthly_report_visual_preservation as visuals
    inspection, section = scene("organization")
    png = raster()
    monkeypatch.setattr(visuals, "preserve_word_pages",
                        lambda _path, numbers: (WordPage(1, png, 640, 480,
                            "Synthetic organizational staff roles and reporting lines", False),))
    assert diagram_source_sections(inspection, section) == (2,)
    preserved = preserve_section_diagrams(Path("not-opened.docx"), inspection, section)
    assert preserved["auto_native_diagrams"]
    assert preserved["preserved_assets"][0][0] == "org_chart"
    assert preserved["word_page_records"][0]["sections"] == (2,)
    assert preserved["word_page_records"][0]["source_sha256"] == SOURCE
    assert not preserved["word_page_records"][0]["reviewed"]
    assert preserved["word_page_records"][0]["source_verified"]
    plan = plan_for(inspection)["organization"]
    plan.update(preserved)
    plan["unsupported_reviewed"] = True
    plan["approved"] = True
    plan["questions"] = ()
    mapped, mappings = build_starting_import(
        Path("not-opened.docx"), inspection, (plan,))
    chart = next(block for block in mapped.blocks if block.key == "org_chart")
    assert chart.asset_hashes
    assert len(chart.asset_hashes) == 1
    assert chart.references[0] == f"docx:{SOURCE}:word-sections:2:page:1"
    assert not chart.client_reviewed_fingerprint
    assert chart.client_asset_reviews == ()
    assert len(mapped.assets) == 1
    assert mapped.assets[0][1] == png


@pytest.mark.parametrize("section,slot", [
    ("organization", "org_chart"),
    ("activity", "improvements"),
    ("mbcx", "mbcx_report"),
    ("subcontractors", "subcontractor_matrix"),
    ("water", "water_reports"),
    ("issues", "equipment_issues_evidence"),
    ("capital", "capital_renewal"),
    ("training", "training_summary"),
    ("rfi", "rfi_matrix"),
])
def test_logical_diagram_section_never_routes_to_unrelated_content(section, slot, monkeypatch):
    import app.monthly_report_visual_preservation as visuals
    inspection, portion = scene(section)
    monkeypatch.setattr(visuals, "preserve_word_pages",
                        lambda _path, numbers: (WordPage(1, raster(), 640, 480,
                            "Synthetic maintenance work completed on site", False),))
    result = preserve_section_diagrams(Path("not-opened.docx"), inspection, portion)
    assert result["preserved_assets"][0][0] == slot == VISUAL_SLOTS[section]


def test_word_section_shared_with_another_report_section_does_not_cross_route():
    inspection, section = scene("organization", other=True)
    with pytest.raises(DiagramPreservationError, match="shares a Word page"):
        diagram_source_sections(inspection, section)


@pytest.mark.parametrize("text,blank", [
    ("Vendor quote: Price $12,345.67", False),
    ("Terms and Conditions Indemnification and Limitation of Liability", False),
    ("Current technical work", True),
])
def test_unsafe_or_unreadable_diagram_is_recoverable_not_omitted(monkeypatch, text, blank):
    import app.monthly_report_visual_preservation as visuals
    inspection, section = scene()
    monkeypatch.setattr(visuals, "preserve_word_pages",
                        lambda _path, numbers: (WordPage(1, raster(), 640, 480,
                            text, blank),))
    with pytest.raises(DiagramPreservationError, match="not dropped or"):
        preserve_section_diagrams(Path("not-opened.docx"), inspection, section)


def test_image_only_native_diagram_is_carried_without_inventing_visual_approval(monkeypatch):
    import app.monthly_report_visual_preservation as visuals
    inspection, section = scene()
    raw = raster()
    monkeypatch.setattr(visuals, "preserve_word_pages",
                        lambda _path, numbers: (WordPage(1, raw, 640, 480, "", False),))
    record = preserve_section_diagrams(Path("not-opened.docx"), inspection, section)
    assert record["word_page_records"][0]["visual_review_required"] is True
    assert record["word_page_records"][0]["source_verified"]
    assert record["word_page_records"][0]["reviewed"] is False
    plan = plan_for(inspection)["organization"]
    plan.update(record)
    plan.update(approved=True, unsupported_reviewed=True, questions=())
    mapped, _ = build_starting_import(Path("not-opened.docx"), inspection, (plan,))
    chart = next(block for block in mapped.blocks if block.key == "org_chart")
    assert chart.asset_hashes
    assert chart.client_asset_reviews == ()
    assert chart.client_reviewed_fingerprint == ""
    assert mapped.assets[0][1] == raw


def test_renderer_failure_is_explicit_and_original_is_not_changed(monkeypatch, tmp_path):
    import app.monthly_report_visual_preservation as visuals
    source = tmp_path / "original.docx"
    source.write_bytes(b"INVENTED ORIGINAL THAT MAY NOT BE READ")
    inspection, section = scene()
    def refused(*_):
        raise ValueError("A source drawing's dependencies cannot be validated")
    monkeypatch.setattr(visuals, "preserve_word_pages", refused)
    with pytest.raises(DiagramPreservationError, match="could not be safely rendered"):
        preserve_section_diagrams(source, inspection, section)
    assert source.read_bytes() == b"INVENTED ORIGINAL THAT MAY NOT BE READ"


def test_cannot_forge_source_proof_to_release_unreviewed_rendered_page():
    inspection, _ = scene()
    png = raster()
    result = plan_for(inspection)["organization"]
    result.update({
        "questions": (), "approved": True, "auto_native_diagrams": True,
        "captured_word_sections": (2,),
        "preserved_assets": [("org_chart", ReportImage(png, "png", 640, 480))],
        "word_page_records": [{
            "page": 1, "slot": "org_chart", "sections": (2,),
            "sha256": "b" * 64, "text": "Synthetic technical diagram staff",
            "blank": False, "reviewed": False, "source_verified": True,
            "source_sha256": SOURCE,
        }],
    })
    with pytest.raises(ValueError, match="not safely preserved"):
        build_section_import(Path("not-opened.docx"), inspection, (result,))


@pytest.mark.parametrize("section,slot", [
    ("scorecards", "utility_analysis"),
    ("subcontractors", "subcontractor_matrix"),
    ("capital", "capital_renewal"),
    ("training", "training_summary"),
])
def test_uncaptioned_original_photograph_keeps_its_document_section(section, slot):
    item = ImportItem("uncaptioned-visible-image", "image",
                      "word/document.xml", 16, 4, section,
                      image_part="word/media/unnamed-photo.png",
                      image_width=880, image_height=640)
    inspection = DocxInspection(SOURCE, (item,), (), (), 4)
    same = plan_for(inspection)[section]
    assert same["approved"]
    assert same["selected"] == [item.id]
    assert same["destinations"][item.id] == slot
    # Another client's section pictures are NOT safe to borrow merely to
    # reuse an otherwise compatible report design.
    foreign = automatic_section_plans(
        inspection, StartingReportAnalysis((), "other", (), (), ())
    )[section]
    assert item.id not in foreign["selected"]


def test_uncaptioned_vendor_quote_picture_is_not_claimed_price_free():
    item = ImportItem("unread-proposal-image", "image",
                      "word/document.xml", 21, 6, "proposals",
                      image_part="word/media/quote.png",
                      image_width=880, image_height=640)
    inspection = DocxInspection(SOURCE, (item,), (), (), 6)
    plan = plan_for(inspection)["proposals"]
    assert not plan["approved"]
    assert plan["questions"]
    assert not plan["selected"]


def test_unnamed_ummc_style_contact_matrix_routes_to_contacts_not_org_chart():
    """Structural analogue of a real ENFRA source; no client bytes included."""
    import app.monthly_report_start_import as source
    contact = ImportItem(
        "invented-contact-matrix", "image", "word/document.xml",
        24, 4, "organization", suggested_slot="org_chart",
        image_part="word/media/contact_matrix_revision6.png",
        image_width=3325, image_height=1875)
    workflow = ImportItem(
        "invented-workflow", "image", "word/document.xml",
        23, 4, "organization", suggested_slot="org_chart",
        image_part="word/media/image9.jpeg",
        image_width=1280, image_height=720)
    inspection = DocxInspection(SOURCE, (workflow, contact), (), (), 4)
    matching = source.automatic_section_plans(
        inspection, StartingReportAnalysis((), "same", (), (), ())
    )["organization"]
    assert matching["destinations"][contact.id] == "contact_matrix"
    assert matching["destinations"][workflow.id] == "org_chart"
    assert matching["selected"] == [workflow.id, contact.id]
    assert matching["approved"]
    foreign = source.automatic_section_plans(
        inspection, StartingReportAnalysis((), "other", (), (), ())
    )["organization"]
    assert not foreign["selected"], "Do not import another site's image assets."
