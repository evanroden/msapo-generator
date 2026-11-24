"""Two pictures must not be stacked on one single-picture page.

Synthetic only: two uncaptioned charts in the Organizational Chart section
used to both land on the org chart page (one picture per page).
"""

from io import BytesIO

from PIL import Image, ImageDraw
from docx import Document
from docx.shared import Inches

from app.monthly_report_import import inspect_docx
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_start_import import analyze_starting_report, automatic_section_plans


def chart(shade):
    image = Image.new("RGB", (1280, 720), (250, 250, 250))
    ImageDraw.Draw(image).rectangle((200, 150, 1000, 550), outline=(shade, 60, 60), width=12)
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def organization_plan(tmp_path, count):
    profile = synthetic_profiles()[0]
    doc = Document()
    doc.add_paragraph(profile.facilities[0].title)
    doc.add_paragraph("November 2026")
    doc.add_heading("Organizational Chart", 1)
    for number in range(count):
        doc.add_picture(BytesIO(chart(40 + 60 * number)), width=Inches(6))
    path = tmp_path / "source.docx"
    doc.save(path)
    inspection = inspect_docx(path)
    analysis = analyze_starting_report(inspection, profile, ReportPeriod(2026, 11))
    pictures = [i.id for i in inspection.items if i.kind == "image" and i.section == "organization"]
    return pictures, automatic_section_plans(inspection, analysis)["organization"]


def test_two_charts_are_asked_about_not_stacked_on_the_org_chart_page(tmp_path):
    pictures, plan = organization_plan(tmp_path, 2)
    assert len(pictures) == 2
    assert not set(pictures) & set(plan["selected"])
    assert "A picture's purpose is not clear." in plan["questions"]
    assert not plan["approved"]


def test_one_chart_still_goes_to_the_org_chart_page(tmp_path):
    pictures, plan = organization_plan(tmp_path, 1)
    assert len(pictures) == 1
    assert plan["destinations"][pictures[0]] == "org_chart"
    assert plan["approved"]
