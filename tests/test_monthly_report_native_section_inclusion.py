"""Whole-section omissions keep independently proved source chrome closure."""
from dataclasses import replace
from io import BytesIO
import pytest
from docx import Document
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_section_inclusion import set_section_included
from test_monthly_report_native_art_review import sample
from test_monthly_report_native_art_lifecycle import save_sample


def _split_region_fixture(*, contacts=False):
    """Synthetic native region map with two reflow regions in one Word section."""
    from copy import deepcopy
    from types import SimpleNamespace
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document()
    labels = ["Cover", "Organization"]
    if contacts:
        labels.append("Contacts")
    labels += ["Activity", "Training"]
    paragraphs = [document.add_paragraph(label) for label in labels]
    body = document.element.body
    terminal = body[-1]
    regions = [0, 1, *([1] if contacts else []), 2, 3]
    for index in (0, (2 if contacts else 1), (3 if contacts else 2)):
        paragraphs[index]._p.get_or_add_pPr().append(deepcopy(terminal))

    def reference(kind, rid):
        node = OxmlElement("w:" + kind + "Reference")
        node.set(qn("w:type"), "default")
        node.set(qn("r:id"), rid)
        return node

    # Cover uses A, Organization switches to B; the retained Activity and
    # Training sections inherit B without carrying raw reference elements.
    sources = [deepcopy(terminal) for _ in range(4)]
    sources[0].insert(0, reference("header", "rIdCover"))
    for source in sources[1:]:
        source.insert(0, reference("header", "rIdOrganization"))
    first_boundary = paragraphs[0]._p.find(".//" + qn("w:sectPr"))
    first_boundary.insert(0, reference("header", "rIdCover"))
    org_boundary = paragraphs[2 if contacts else 1]._p.find(".//" + qn("w:sectPr"))
    org_boundary.insert(0, reference("header", "rIdOrganization"))
    names = ["cover", "organization", *([ "organization" ] if contacts else []),
             "activity", "training"]
    plan = SimpleNamespace(
        owner={**{p._p: regions[i] for i, p in enumerate(paragraphs)}, terminal: 3},
        logical_owner={**{p._p: names[i] for i, p in enumerate(paragraphs)}, terminal: "training"},
        source_word_sections=[1, 2, 3, 3],
        regions=[SimpleNamespace(properties=source) for source in sources],
    )
    return document, paragraphs, names, plan


def test_omitting_middle_native_section_keeps_reflow_splits_and_inherited_headers():
    from docx.oxml.ns import qn
    from app.monthly_report_native_section_inclusion import apply_native_section_choices

    document, paragraphs, names, plan = _split_region_fixture()
    choice = set_section_included(
        __import__("tests.test_monthly_report_section_inclusion",
                   fromlist=["draft"]).draft(), "organization", False)
    apply_native_section_choices(
        document, choice, [p._p for p in paragraphs], set(),
        {i + 1: name for i, name in enumerate(names)}, plan)
    body = document.element.body
    assert [p.text for p in document.paragraphs] == ["Cover", "Activity", "Training"]

    # Activity and Training originated in the same source Word section but
    # are two different proven reflow regions and must not run together.
    assert len(list(body.iter(qn("w:sectPr")))) == 3
    activity_boundary = paragraphs[2]._p.find(".//" + qn("w:sectPr"))
    assert activity_boundary is not None
    refs = [ref.get(qn("r:id")) for ref in activity_boundary
            if ref.tag == qn("w:headerReference")]
    assert refs == ["rIdOrganization"]
    final_refs = [ref.get(qn("r:id")) for ref in body[-1]
                  if ref.tag == qn("w:headerReference")]
    assert final_refs == ["rIdOrganization"]


def test_proved_contacts_page_separator_gets_region_ownership_before_omission():
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from app.monthly_report_native_section_inclusion import apply_native_section_choices

    document, paragraphs, names, plan = _split_region_fixture(contacts=True)
    separator = OxmlElement("w:p")
    props = OxmlElement("w:pPr")
    props.append(OxmlElement("w:pageBreakBefore"))
    separator.append(props)
    paragraphs[2]._p.addprevious(separator)  # Native org/contact split.
    assert separator not in plan.owner
    choice = set_section_included(
        __import__("tests.test_monthly_report_section_inclusion",
                   fromlist=["draft"]).draft(), "training", False)
    apply_native_section_choices(
        document, choice, [p._p for p in paragraphs], set(),
        {i + 1: name for i, name in enumerate(names)}, plan)
    assert separator in document.element.body
    assert plan.owner[separator] == plan.owner[paragraphs[2]._p]
    assert plan.logical_owner[separator] == "organization"
    assert separator.find(".//" + qn("w:pageBreakBefore")) is not None
    assert "Training" not in [p.text for p in document.paragraphs]


@pytest.mark.parametrize('key',['activity','training'])
def test_reviewed_native_source_omission_has_derived_header_scope(sample,key):
    path,view,profile,period,inventory,receipt=sample
    value,loader=save_sample(sample)
    assert key in {s.key for s in value.sections}
    before=path.read_bytes()
    value=set_section_included(value,key,False)
    output=build_native_docx(value,path,asset_loader=loader,source_view=view)
    text='\n'.join(p.text for p in Document(BytesIO(output)).paragraphs)
    assert ('MONTHLY ACTIVITY SUMMARY' if key=='activity' else 'TRAINING SUMMARY') not in text
    assert path.read_bytes()==before
