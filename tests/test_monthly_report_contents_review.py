"""Contents warnings describe retained source text, never certify pagination."""
from dataclasses import replace
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import pytest

from app import monthly_report_designs as designs, monthly_report_docx as renderer
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec, synthetic_profiles,
)


def source(tmp_path, kind):
    document = Document()
    document.add_paragraph("Synthetic Site")
    document.add_paragraph("September 2026")
    if kind == "static":
        document.add_paragraph("Table of contents")
        document.add_paragraph("Monthly Activity Summary\t3")
        document.add_paragraph("Training Summary\t4")
    elif kind == "simple":
        paragraph = document.add_paragraph()
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), ' TOC \\o "1-3" \\h ')
        run, text = OxmlElement("w:r"), OxmlElement("w:t")
        text.text = "Monthly Activity Summary 3"
        run.append(text)
        field.append(run)
        paragraph._p.append(field)
    elif kind == "complex":
        for tag, value in (("fldChar", "begin"), ("instrText", " TO"),
                           ("instrText", 'C \\o "1-3" '), ("fldChar", "separate"),
                           ("t", "Monthly Activity Summary 3"), ("fldChar", "end")):
            run = document.add_paragraph().add_run()._r
            node = OxmlElement("w:" + tag)
            if tag == "fldChar":
                node.set(qn("w:fldCharType"), value)
            else:
                node.text = value
            run.append(node)
    elif kind in {"sections", "sections_paged"}:
        # The owner's designs: "TABLE OF CONTENTS", then "Section N: Title"
        # lines, the number in its own coloured run, and no page numbers.
        document.add_paragraph("TABLE OF CONTENTS")
        for number, title in (("1", "Monthly Activity Summary"), ("2", "Training Summary")):
            paragraph = document.add_paragraph()
            paragraph.add_run("Section " + number).bold = True
            paragraph.add_run(": " + title + ("\t" + str(int(number) + 2) if kind == "sections_paged" else ""))
    elif kind == "prose":
        document.add_paragraph("The contents of this report are confidential.")
        document.add_paragraph("See the table of contents for report navigation.")
    document.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    document.add_paragraph("Prior activity")
    document.add_heading("TRAINING SUMMARY", 1)
    document.add_paragraph("Prior training")
    path = tmp_path / (kind + ".docx")
    document.save(path)
    return path


def draft(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    path = source(tmp_path, kind)
    profile = designs.install(path, synthetic_profiles()[0], actor="Synthetic Editor", expected_revision=0)
    value = ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic Editor", (
        SectionSpec("activity", "1", "Monthly Activity Summary", (BlockSpec("activity_summary", "rich_text"),)),
        SectionSpec("training", "2", "Training Summary", (BlockSpec("training_summary", "rich_text"),), included=False),
    ), (ResolvedBlock("activity_summary", "This month", text="Current synthetic work."),))
    return path, value


@pytest.mark.parametrize("kind,label", [("static", "static"), ("simple", "Word contents field"), ("complex", "Word contents field")])
def test_finished_package_exposes_unavailable_contents_update(tmp_path, monkeypatch, kind, label):
    path, value = draft(tmp_path, monkeypatch, kind)
    original = path.read_bytes()
    monkeypatch.setattr(renderer, "_convert_report_pdf", lambda *args: (b"%PDF-synthetic", ""))
    result = renderer.generate_report(value, acknowledged_fingerprint=value.fingerprint)
    assert label in result.contents_notice
    assert "not recalculated" in result.contents_notice
    assert "titles, order and page numbers" in result.contents_notice
    assert result.docx and result.pdf and not result.pdf_error
    assert path.read_bytes() == original
    assert designs.source_for(value.profile).read_bytes() == original
    # Retained fields must remain passive; a warning never re-enables fields.
    generated = Document(BytesIO(result.docx))
    assert not any("TOC" in (node.text or "") for node in generated.element.iter(qn("w:instrText")))


@pytest.mark.parametrize("kind", ["none", "prose"])
def test_normal_prose_and_no_contents_do_not_acquire_warning(tmp_path, monkeypatch, kind):
    _, value = draft(tmp_path, monkeypatch, kind)
    monkeypatch.setattr(renderer, "_convert_report_pdf", lambda *args: (None, "Synthetic conversion unavailable"))
    result = renderer.generate_report(value, acknowledged_fingerprint=value.fingerprint)
    assert result.contents_notice == ""


def test_section_list_without_page_numbers_has_no_warning(tmp_path, monkeypatch):
    """Owner, 27 Nov: nothing on such a list can be stale, so do not warn.

    Its titles and order are the design's, and the section numbering (#902)
    keeps the numbers current: the left-out section's line is removed here.
    """
    path, value = draft(tmp_path, monkeypatch, "sections")
    original = path.read_bytes()
    # The first section unchecked, as the guided editor records it.
    value = replace(value, sections=tuple(replace(section, included=section.key != "activity")
                                          for section in value.sections),
                    omitted_sections=("activity",))
    monkeypatch.setattr(renderer, "_convert_report_pdf", lambda *args: (b"%PDF-synthetic", ""))
    result = renderer.generate_report(value, acknowledged_fingerprint=value.fingerprint)
    assert result.contents_notice == ""
    lines = [paragraph.text for paragraph in Document(BytesIO(result.docx)).paragraphs]
    assert "Section 1: Training Summary" in lines  # Renumbered from 2.
    assert not any("Monthly Activity Summary" in line for line in lines)
    assert path.read_bytes() == original


def test_section_list_with_page_numbers_keeps_the_warning(tmp_path, monkeypatch):
    _, value = draft(tmp_path, monkeypatch, "sections_paged")
    monkeypatch.setattr(renderer, "_convert_report_pdf", lambda *args: (b"%PDF-synthetic", ""))
    result = renderer.generate_report(value, acknowledged_fingerprint=value.fingerprint)
    assert "titles, order and page numbers are not recalculated" in result.contents_notice


def _contents(lines, *, after="ORGANIZATIONAL CHART"):
    document = Document()
    document.add_paragraph("Synthetic Site")
    document.add_paragraph("TABLE OF CONTENTS")
    for line in lines:
        paragraph = document.add_paragraph()
        if line.startswith("Section "):
            number, rest = line.split(":", 1)
            paragraph.add_run(number).bold = True  # The owner's coloured number run.
            paragraph.add_run(":" + rest)
        else:
            paragraph.add_run(line)
        # A right-aligned dot-leader tab stop is layout, not a page number.
        stops, stop = OxmlElement("w:tabs"), OxmlElement("w:tab")
        for name, value in (("w:val", "right"), ("w:leader", "dot"), ("w:pos", "9350")):
            stop.set(qn(name), value)
        stops.append(stop)
        paragraph._p.get_or_add_pPr().append(stops)
    document.add_paragraph(after)
    return document


@pytest.mark.parametrize("lines,expected", [
    (["Section 1: Organizational Chart", "", "Section 2: Monthly Activity Summary",
      "Section 11: Training Summary"], True),
    (["Section 1: Organizational Chart\t3"], False),              # Tab, then a page number.
    (["Section 1: Organizational Chart ........ 3"], False),       # Dot leaders.
    (["Section 1: Organizational Chart \u2026 3"], False),        # Ellipsis.
    (["Section 1: Organizational Chart 3"], False),                # Codex: after a space.
    (["Section 1: Organizational Chart\tiii"], False),            # Codex: Roman numeral.
    (["Section 1: Organizational Chart", "3"], False),            # A number listed apart.
    (["Section 1: Not A Report Section"], False),                 # Title the importer cannot prove.
    (["Monthly Activity Summary"], False),                        # No section lines at all.
])
def test_only_a_positively_identified_title_list_counts(lines, expected):
    from app.monthly_report_contents_review import section_titles_only
    assert section_titles_only(_contents(lines).element) is expected


def test_section_titles_in_a_table_keep_the_warning():
    """Codex on #1144: a page number can sit in another cell of the row."""
    from app.monthly_report_contents_review import section_titles_only
    document = Document()
    document.add_paragraph("TABLE OF CONTENTS")
    row = document.add_table(rows=1, cols=2).rows[0]
    row.cells[0].text = "Section 1: Organizational Chart"
    row.cells[1].text = "3"
    document.add_paragraph("ORGANIZATIONAL CHART")
    assert section_titles_only(document.element) is False


def test_page_field_among_section_titles_keeps_the_warning():
    from app.monthly_report_contents_review import section_titles_only
    document = _contents(["Section 1: Organizational Chart"])
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), " PAGEREF _Toc1 \\h ")
    document.paragraphs[2]._p.append(field)
    assert section_titles_only(document.element) is False


def test_text_box_heading_with_its_legacy_copy_is_read_once():
    """A heading in a text box repeats in its VML fallback; that is one heading."""
    from lxml import etree
    from app.monthly_report_contents_review import section_titles_only
    document = _contents(["Section 1: Organizational Chart"])
    heading = document.paragraphs[1]._p
    for run in heading.findall(qn("w:r")):
        heading.remove(run)
    box = (
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'xmlns:v="urn:schemas-microsoft-com:vml"><mc:AlternateContent>'
        '<mc:Choice Requires="wps"><w:drawing><wps:txbx><w:txbxContent><w:p><w:r><w:t>TABLE OF CONTENTS'
        '</w:t></w:r></w:p></w:txbxContent></wps:txbx></w:drawing></mc:Choice>'
        '<mc:Fallback><w:pict><v:textbox><w:txbxContent><w:p><w:r><w:t>TABLE OF CONTENTS'
        '</w:t></w:r></w:p></w:txbxContent></v:textbox></w:pict></mc:Fallback>'
        '</mc:AlternateContent></w:r>')
    heading.append(etree.fromstring(box))
    assert section_titles_only(document.element) is True


def test_contents_notice_survives_pdf_retry(tmp_path, monkeypatch):
    _, value = draft(tmp_path, monkeypatch, "static")
    monkeypatch.setattr(renderer, "_convert_report_pdf", lambda *args: (None, "Synthetic first failure"))
    package = renderer.generate_report(value, acknowledged_fingerprint=value.fingerprint)
    monkeypatch.setattr(renderer, "_convert_report_pdf", lambda *args: (b"%PDF-synthetic", ""))
    retried = renderer.retry_report_pdf(value, package)
    assert retried.contents_notice == package.contents_notice
    assert "not recalculated" in retried.contents_notice
    assert retried.docx == package.docx and retried.pdf and not retried.pdf_error


def test_selected_design_version_controls_notice_not_latest_master(tmp_path, monkeypatch):
    from app.monthly_report_contents_review import contents_notice_for
    _, value = draft(tmp_path, monkeypatch, "static")
    newer = designs.install(source(tmp_path, "none"), value.profile,
                            actor="Synthetic Editor", expected_revision=1)
    assert "static contents" in contents_notice_for(value.profile)
    assert contents_notice_for(newer) == ""


def test_lost_source_after_assembly_keeps_files_with_unavailable_notice(tmp_path, monkeypatch):
    path, value = draft(tmp_path, monkeypatch, "static")
    original = path.read_bytes()
    pinned = designs.source_for(value.profile)
    def convert(*args):
        pinned.unlink()  # Isolated race after Word was successfully assembled.
        return b"%PDF-synthetic", ""
    monkeypatch.setattr(renderer, "_convert_report_pdf", convert)
    result = renderer.generate_report(value, acknowledged_fingerprint=value.fingerprint)
    assert result.docx and result.pdf and not result.pdf_error
    assert "Contents verification is unavailable" in result.contents_notice
    assert path.read_bytes() == original


def test_bare_toc_result_and_unrelated_fields_are_not_contents():
    from app.monthly_report_contents_review import contents_kind
    document = Document()
    paragraph = document.add_paragraph()
    for tag, value in (("fldChar", "begin"), ("instrText", " PAGE "),
                       ("fldChar", "separate"), ("t", "TOC"), ("fldChar", "end")):
        node = OxmlElement("w:" + tag)
        if tag == "fldChar":
            node.set(qn("w:fldCharType"), value)
        else:
            node.text = value
        paragraph.add_run()._r.append(node)
    assert contents_kind(document.element) == ""


@pytest.mark.parametrize("pdf", [True, False])
def test_finished_files_show_contents_notice_after_shared_save_and_rerun(tmp_path, monkeypatch, pdf):
    from app import monthly_report_guided as guided
    from test_monthly_report_output_status_ui import ready, create
    from app.monthly_report_contents_review import contents_notice_for

    _, value = draft(tmp_path, monkeypatch, "static")
    notice = contents_notice_for(value.profile)
    app, calls = ready(monkeypatch, tmp_path / "ui", pdf=pdf)
    generate = guided.generate_report
    monkeypatch.setattr(guided, "generate_report", lambda *args, **kwargs:
                        replace(generate(*args, **kwargs), contents_notice=notice))
    create(app)
    assert any(item.value == notice for item in app.warning)
    assert any("[Shared version 1]" in item.value for item in app.caption)
    app.run()
    assert not app.exception
    assert sum(item.value == notice for item in app.warning) == 1
    assert [item.label for item in app.get("download_button")] == (
        ["Download DOCX", "Download PDF"] if pdf else ["Download DOCX"])
    assert len(calls) == 1
