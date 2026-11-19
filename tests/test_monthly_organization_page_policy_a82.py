"""A82: approved native chart and source-bound contacts must paginate accessibly.

Fixtures contain synthetic names, invented phone numbers and deliberately generated
images only. A source-bound contact table must not depend on header formatting
that happened to be present in an earlier month's original Word file.
"""
from hashlib import sha256
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches
from PIL import Image
import pytest

from app.monthly_report_import import inspect_docx, read_import_image
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable,
    ResolvedBlock, default_sections,
)
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_sections import table_without_prices
from tests.conftest import requires_libreoffice


def _bound_original(tmp_path, *, count=1, size=(1200, 600)):
    original = Document()
    original.add_heading("ORGANIZATIONAL CHART", 1)
    picture = BytesIO()
    Image.new("RGB", size, "#346a9a").save(picture, "PNG")
    original.add_picture(
        BytesIO(picture.getvalue()), width=Inches(6 if size[0] >= size[1] else 2)
    )
    table = original.add_table(rows=1 + count, cols=5)
    headings = ("Site", "Role", "Name", "Telephone", "Email")
    for cell, text in zip(table.rows[0].cells, headings):
        cell.text = text
    for index, row in enumerate(table.rows[1:]):
        for cell, text in zip(row.cells, (
            "Synthetic North", "Operations Lead", f"QA{index:04d} Synthetic Person",
            f"555-{index:04d}", f"qa{index:04d}@example.invalid",
        )):
            cell.text = text
    path = tmp_path / f"original-{count}-{size[0]}x{size[1]}.docx"
    original.save(path)
    before = path.read_bytes()
    source = inspect_docx(path)
    chart_item = next(item for item in source.items if item.kind == "image")
    contact_item = next(item for item in source.items if item.kind == "table")
    image = read_import_image(path, chart_item)
    reference = sha256(image.data).hexdigest() + "." + image.extension
    filtered, _ = table_without_prices(contact_item)
    chart = ResolvedBlock(
        "org_chart", "This month", asset_hashes=(reference,),
        references=(f"docx:{source.sha256}:{chart_item.id}",),
    )
    contact = ResolvedBlock(
        "contact_matrix", "This month",
        extra_tables=(ReportTable(
            filtered.columns, filtered.rows,
            f"docx:{source.sha256}:{contact_item.id}"
        ),),
    )
    profile = ReportProfile(
        "Synthetic contract A", "north", "North",
        (Facility("north", "North"),),
    )
    draft = ReportDraft(
        profile, ReportPeriod(2026, 9), "Synthetic Tester",
        default_sections(), (chart, contact), synthetic=True,
    )
    output = build_native_docx(
        draft, path, section_key="organization", master=True,
        asset_loader={reference: image.data}.__getitem__,
    )
    assert path.read_bytes() == before, "The original DOCX may never be changed."
    return output


@pytest.mark.parametrize("size", [(1800, 450), (450, 1800)])
@pytest.mark.parametrize("count", [1, 46])
def test_source_bound_chart_contain_and_repeating_contacts(tmp_path, size, count):
    document = Document(BytesIO(_bound_original(tmp_path, count=count, size=size)))
    assert len(document.inline_shapes) == 1
    shape = document.inline_shapes[0]
    assert abs(shape.width / shape.height - size[0] / size[1]) < .02
    chart = next(node for node in document.element.body
                 if node.xpath('.//*[local-name()="blip"]'))
    descriptions = [node.get("descr") for node in chart.iter(qn("wp:docPr"))]
    assert descriptions and all(text and "organization" in text.lower()
                                for text in descriptions), (
        "Current approved chart must have safe, useful screen-reader text."
    )
    contacts = [table for table in document.tables
                if "QA0000 Synthetic Person" in table._tbl.xml]
    assert len(contacts) == 1
    rows = contacts[0].rows
    assert len(rows) == count + 1
    assert rows[0]._tr.xpath("./w:trPr/w:tblHeader"), (
        "Source-bound first contact row must repeat on every rendered page."
    )
    assert all(row._tr.xpath("./w:trPr/w:cantSplit") for row in rows)
    assert not any(row._tr.xpath("./w:trPr/w:tblHeader") for row in rows[1:])


@requires_libreoffice
@pytest.mark.parametrize("size", [(1800, 450), (450, 1800)])
def test_actual_pdf_source_bound_contacts_repeat_and_chart_has_own_page(tmp_path, monkeypatch, size):
    import pymupdf
    from app import pdf_converter

    raw = _bound_original(tmp_path, count=46, size=size)
    saved = tmp_path / f"a82-generated-{size[0]}x{size[1]}.docx"
    saved.write_bytes(raw)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    pdf_path = pdf_converter.convert_to_pdf(saved)
    with pymupdf.open(pdf_path) as pdf:
        pages = [page.get_text() for page in pdf]
        contact_pages = [
            i for i, text in enumerate(pages)
            if "QA000" in text or "QA001" in text or "QA002" in text or "QA003" in text
        ]
        assert len(contact_pages) >= 2, "The synthetic overflow must really span pages."
        for index in contact_pages:
            assert "Telephone" in pages[index] and "Name" in pages[index], (
                f"Missing repeating column names on PDF page {index + 1}."
            )
        assert sum(text.count("QA0000") for text in pages) == 1
        assert sum(text.count("QA0045") for text in pages) == 1
        chart_pages = [i for i, page in enumerate(pdf) if page.get_image_info()]
        assert chart_pages and max(chart_pages) < min(contact_pages)
        assert not any(pdf[i].get_image_info() for i in contact_pages)
        for i in chart_pages:
            page = pdf[i]
            for image in page.get_images(full=True):
                for rect in page.get_image_rects(image[0]):
                    assert rect.x0 >= -1 and rect.y0 >= -1
                    assert rect.x1 <= page.rect.width + 1
                    assert rect.y1 <= page.rect.height + 1
        # The test workflow retains these ACTUAL generated bytes; neither a
        # fixture mock nor an XML-only assertion can supply these hashes.
        import json
        import os
        from pathlib import Path
        directory = (Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path)))
                     / "a82" / ("wide" if size[0] >= size[1] else "tall"))
        directory.mkdir(parents=True, exist_ok=True)
        pdf_bytes = pdf_path.read_bytes()
        (directory / "source-bound-organization.docx").write_bytes(raw)
        (directory / "source-bound-organization.pdf").write_bytes(pdf_bytes)
        (directory / "manifest.json").write_text(json.dumps({
            "scope": "Synthetic bound original, 46 contacts, not a served or authentic report",
            "docx_sha256": sha256(raw).hexdigest(),
            "pdf_sha256": sha256(pdf_bytes).hexdigest(),
            "diagram_pixels": list(size),
            "pdf_pages": len(pdf),
            "chart_pages_0based": chart_pages,
            "contact_pages_0based": contact_pages,
        }, indent=2))


def test_scoped_chart_is_reused_next_month_without_mutating_defaults(tmp_path, monkeypatch):
    """An explicitly approved picture is copied, never looked up across contracts.

    Editing this month's report and rolling forward must not republish the
    shared default, change another site's choice, or drop source bytes.
    """
    from dataclasses import replace
    from app import monthly_report_library as library
    from app import monthly_report_org_chart_defaults as defaults
    from app.monthly_report_asset_review import approve_all_assets
    from app.monthly_report_guided import _initial_draft
    from app.monthly_report_model import synthetic_profiles
    from app.monthly_report_setup import new_month_draft

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original_profile = synthetic_profiles()[0]
    profile_a = replace(
        original_profile, contract="A82 Synthetic A", key="north",
        facilities=(Facility("north", "North"),),
    )
    profile_b = replace(
        profile_a, contract="A82 Synthetic B", key="south",
        facilities=(Facility("south", "South"),),
    )
    for profile in (profile_a, profile_b):
        library.save_profile(
            profile, expected_revision=0, actor="Synthetic Tester", confirmed=True,
        )

    image = BytesIO()
    Image.new("RGB", (900, 360), "blue").save(image, "PNG")
    raw = image.getvalue()
    picture_id = library.asset_reference(raw, "png")
    block = approve_all_assets(
        ResolvedBlock("org_chart", "This month", asset_hashes=(picture_id,))
    )
    initial = replace(_initial_draft(
        library.load_profile(profile_a.contract, profile_a.key),
        ReportPeriod(2026, 9), "Synthetic Tester",
    ), synthetic=False)
    initial = replace(initial, blocks=tuple(
        block if current.key == "org_chart" else current
        for current in initial.blocks
    ))
    defaults.save_default(
        initial, block, {picture_id: raw}, scope="contract", expected_revision=0,
        expected_fingerprint=block.fingerprint, confirmed=True,
    )
    manifest_path = defaults._path(profile_a.contract) / "manifest.json"
    standing_before = manifest_path.read_bytes()
    assets = {}
    month = _initial_draft(
        library.load_profile(profile_a.contract, profile_a.key),
        ReportPeriod(2026, 10), "Synthetic Tester", assets=assets,
    )
    current = next(item for item in month.blocks if item.key == "org_chart")
    assert current.asset_hashes == (picture_id,)
    assert assets[picture_id] == raw
    # Report-local notes must never rewrite the approved chart manifest.
    edited = replace(month, blocks=tuple(
        replace(item, text="Synthetic report-only note")
        if item.key == "org_chart" else item for item in month.blocks
    ))
    following = new_month_draft(edited, ReportPeriod(2026, 11))
    next_chart = next(item for item in following.blocks if item.key == "org_chart")
    assert next_chart.asset_hashes == (picture_id,)
    assert next_chart.text == "Synthetic report-only note"
    assert manifest_path.read_bytes() == standing_before
    assert defaults.read_asset(profile_a.contract, picture_id) == raw
    unrelated = _initial_draft(
        library.load_profile(profile_b.contract, profile_b.key),
        ReportPeriod(2026, 11), "Synthetic Tester", assets={},
    )
    assert picture_id not in next(
        item for item in unrelated.blocks if item.key == "org_chart"
    ).asset_hashes
    assert defaults.load_defaults(profile_b.contract).revision == 0
