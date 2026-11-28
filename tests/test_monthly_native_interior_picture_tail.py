"""Interior picture cleanup must prove original ownership and next-page flow."""

from copy import deepcopy
from types import SimpleNamespace
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import pytest


def fixture(tmp_path, transition="nextPage", field=False):
    doc = Document()
    doc.add_paragraph("Current roster")
    p = doc.add_paragraph("Old vendor picture")
    p.paragraph_format.page_break_before = True
    drawing = OxmlElement("w:drawing")
    p.add_run()._r.append(drawing)
    if field:
        p._p.append(OxmlElement("w:fldSimple"))
    end = doc.add_paragraph()
    end._p.get_or_add_pPr().append(OxmlElement("w:sectPr"))
    doc.add_paragraph("WATER TREATMENT REPORTS")
    typ = OxmlElement("w:type")
    typ.set(qn("w:val"), transition)
    doc._element.body.sectPr.append(typ)
    path = tmp_path / "source.docx"
    doc.save(path)
    return path, doc, p._p, end._p


def prove(path, doc):
    from app.monthly_report_native_interior_tail import interior_picture_tails

    b = doc._element.body
    nodes = list(b)
    return interior_picture_tails(
        path, nodes, {i + 1: "subcontractors" for i in range(3)}
    )


def clear(p):
    for n in list(p):
        if n.tag != qn("w:pPr"):
            p.remove(n)


def pages():
    return SimpleNamespace(live=set(), support=set(), headings=set())


def test_original_interior_tail_removes_only_obsolete_break(tmp_path):
    path, doc, p, end = fixture(tmp_path)
    before = end.xml
    plans = prove(path, doc)
    clear(p)
    assert len(plans) == 1
    plans[0].apply(doc._element.body, pages())
    assert p.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")) is None
    assert end.xml == before


@pytest.mark.parametrize(
    "transition", ["continuous", "oddPage", "evenPage", "nextColumn", "unknown"]
)
def test_other_flow_is_not_a_next_page_proof(tmp_path, transition):
    path, doc, p, end = fixture(tmp_path, transition)
    assert not prove(path, doc)


def test_raw_field_cannot_be_normalized_into_permission(tmp_path):
    path, doc, p, end = fixture(tmp_path, field=True)
    p.remove(p.find(qn("w:fldSimple")))
    assert not prove(path, doc)


@pytest.mark.parametrize("owner", ["live", "support", "headings"])
def test_final_ownership_blocks_cleanup(tmp_path, owner):
    path, doc, p, end = fixture(tmp_path)
    plans = prove(path, doc)
    clear(p)
    state = pages()
    getattr(state, owner).add(end)
    plans[0].apply(doc._element.body, state)
    assert p.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")) is not None


def test_inserted_content_blocks_cleanup(tmp_path):
    path, doc, p, end = fixture(tmp_path)
    plans = prove(path, doc)
    clear(p)
    p.addnext(OxmlElement("w:p"))
    plans[0].apply(doc._element.body, pages())
    assert p.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")) is not None


def test_public_builder_cleans_interior_old_picture_not_section(tmp_path):
    from dataclasses import replace
    from io import BytesIO
    from PIL import Image
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_native_layout import build_native_docx
    from app.monthly_report_model import default_sections
    from app.monthly_report_sections import table_without_prices
    from test_monthly_native_roster_contact_pagination import fixture as roster_fixture

    path, draft = roster_fixture(tmp_path)
    doc = Document(path)
    p = doc.add_paragraph("Synthetic old vendor page")
    p.paragraph_format.page_break_before = True
    image = BytesIO()
    Image.new("RGB", (40, 40), "navy").save(image, format="PNG")
    p.add_run().add_picture(BytesIO(image.getvalue()))
    end = doc.add_paragraph()
    end._p.get_or_add_pPr().append(OxmlElement("w:sectPr"))
    doc.add_heading("WATER TREATMENT REPORTS", 1)
    doc.add_paragraph("Old water summary")
    doc.save(path)
    inspection = inspect_docx(path)
    item = next(i for i in inspection.items if i.kind == "table")
    supplied, _ = table_without_prices(item)
    supplied = replace(supplied, reference=f"docx:{inspection.sha256}:{item.id}")
    water = next(s for s in default_sections() if s.key == "water")
    draft = replace(
        draft,
        sections=(*draft.sections, water),
        blocks=(replace(draft.blocks[0], extra_tables=(supplied,)),),
    )
    before = path.read_bytes()
    output = Document(BytesIO(build_native_docx(draft, path)))
    assert not output.element.xpath("//w:pPr/w:pageBreakBefore")
    assert len(output.sections) == len(doc.sections)
    assert path.read_bytes() == before


@pytest.mark.parametrize("value", ["0", "false", "off"])
def test_original_false_break_is_never_eligible(tmp_path, value):
    path, doc, p, end = fixture(tmp_path)
    p.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")).set(qn("w:val"), value)
    doc.save(path)
    assert not prove(path, doc)


def test_following_section_changed_after_proof_blocks_cleanup(tmp_path):
    path, doc, p, end = fixture(tmp_path)
    plans = prove(path, doc)
    clear(p)
    doc.element.body.sectPr.find(qn("w:type")).set(qn("w:val"), "continuous")
    plans[0].apply(doc.element.body, pages())
    assert p.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")) is not None


def test_current_content_after_proof_blocks_cleanup(tmp_path):
    path, doc, p, end = fixture(tmp_path)
    plans = prove(path, doc)
    clear(p)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "Current vendor status"
    r.append(t)
    p.append(r)
    plans[0].apply(doc.element.body, pages())
    assert p.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")) is not None


def test_nested_section_in_table_does_not_grant_physical_flow(tmp_path):
    path, doc, p, end = fixture(tmp_path, transition="continuous")
    table = doc.add_table(rows=1, cols=1)
    nested = OxmlElement("w:sectPr")
    table.cell(0, 0).paragraphs[0]._p.get_or_add_pPr().append(nested)
    doc.save(path)
    assert not prove(path, doc)


def test_new_physical_boundary_after_proof_blocks_cleanup(tmp_path):
    path, doc, p, end = fixture(tmp_path)
    plans = prove(path, doc)
    clear(p)
    inserted = OxmlElement("w:p")
    props = OxmlElement("w:pPr")
    props.append(OxmlElement("w:sectPr"))
    inserted.append(props)
    doc.element.body[-1].addprevious(inserted)
    plans[0].apply(doc.element.body, pages())
    assert p.find("./" + qn("w:pPr") + "/" + qn("w:pageBreakBefore")) is not None


def test_missing_final_properties_returns_without_mutation(tmp_path):
    path, doc, p, end = fixture(tmp_path)
    plans = prove(path, doc)
    clear(p)
    p.remove(p.find(qn("w:pPr")))
    before = doc.element.xml
    plans[0].apply(doc.element.body, pages())
    assert doc.element.xml == before
