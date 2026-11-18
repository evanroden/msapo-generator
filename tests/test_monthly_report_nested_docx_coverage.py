"""Synthetic DOCX source-item conservation tests for #271/#471.

All source bytes and names are synthetic. No customer report is read here.
"""
from hashlib import sha256
from docx import Document
from app import monthly_report_import as importer
from app.monthly_report_sections import section_reviews, table_without_prices


def _nested_source(tmp_path):
    doc = Document()
    doc.add_paragraph("Synthetic Facility North")
    doc.add_heading("Monthly Activity Summary", 1)
    doc.add_paragraph("Synthetic completed September 2026 service.")
    outer = doc.add_table(rows=2, cols=2)
    outer.cell(0, 0).text = "Area"
    outer.cell(0, 1).text = "Details"
    outer.cell(1, 0).text = "Mechanical"
    outer.cell(1, 1).text = "Parent note"
    nested = outer.cell(1, 1).add_table(rows=2, cols=2)
    for cell, value in zip(nested.rows[0].cells, ("Equipment", "Status")):
        cell.text = value
    for cell, value in zip(nested.rows[1].cells, ("Pump A", "Completed")):
        cell.text = value
    path = tmp_path / "nested-synthetic.docx"
    doc.save(path)
    return path


def test_nested_table_occurrences_are_conserved_and_reviewed(tmp_path):
    path = _nested_source(tmp_path)
    before = sha256(path.read_bytes()).hexdigest()
    inspected = importer.inspect_docx(path)
    assert inspected.sha256 == before
    assert sha256(path.read_bytes()).hexdigest() == before
    tables = [item for item in inspected.items if item.kind == "table"]
    assert len(tables) == 1, "Nested table must be an independent editable item."
    child = tables[0]
    assert child.rows == (("Equipment", "Status"), ("Pump A", "Completed"))
    assert child.section == "activity"
    assert child.suggested_slot
    parents = [item for item in inspected.items if item.kind == "unsupported"
               and "nested" in item.note.lower() and item.position == child.position]
    assert len(parents) == 1, "Outer layout must remain in a single actionable review item."
    assert "Pump A" not in parents[0].text, "Nested cells cannot be duplicated as outer prose."
    assert child.id.startswith(parents[0].id + "-nested-")
    assert any(parent.id in {i.id for s in section_reviews(inspected) for i in s.items}
               for parent in parents)
    table, removed = table_without_prices(child)
    assert table.columns == ("Equipment", "Status")
    assert table.rows == (("Pump A", "Completed"),)
    assert not removed


def test_plain_table_schema_remains_unchanged(tmp_path):
    doc = Document()
    doc.add_heading("Training Summary", 1)
    table = doc.add_table(rows=2, cols=2)
    for cell, value in zip(table.rows[0].cells, ("Session", "Hours")):
        cell.text = value
    for cell, value in zip(table.rows[1].cells, ("Synthetic safety", "0")):
        cell.text = value
    path = tmp_path / "plain-synthetic.docx"
    doc.save(path)
    inspection = importer.inspect_docx(path)
    candidates = [i for i in inspection.items if i.kind == "table"]
    assert len(candidates) == 1
    assert candidates[0].rows == (("Session", "Hours"), ("Synthetic safety", "0"))


def test_nested_depth_and_item_ledger_are_deterministic(tmp_path):
    from app.monthly_report_docx_coverage import coverage_inventory, coverage_totals

    doc = Document()
    doc.add_heading("Sub-Contractor Status", 1)
    outer = doc.add_table(rows=2, cols=2)
    outer.cell(0, 0).text = "Parent Header"
    outer.cell(1, 0).text = "Decorative parent"
    middle = outer.cell(1, 1).add_table(rows=2, cols=1)
    middle.cell(0, 0).text = "Inner caption"
    leaf = middle.cell(1, 0).add_table(rows=2, cols=2)
    for cell, value in zip(leaf.rows[0].cells, ("Vendor", "State")):
        cell.text = value
    for cell, value in zip(leaf.rows[1].cells, ("Synthetic vendor", "Pending")):
        cell.text = value
    path = tmp_path / "deep.docx"
    doc.save(path)
    original = path.read_bytes()
    first = importer.inspect_docx(path)
    second = importer.inspect_docx(path)
    assert first == second
    assert path.read_bytes() == original
    entries = coverage_inventory(first)
    assert len([e for e in entries if not e.item_id.startswith("excluded:")]) == len(first.items)
    tables = [e for e in entries if e.kind == "table"]
    parents = [e for e in entries if e.kind == "unsupported" and "nested" in e.reason.lower()]
    assert len(tables) == 1 and len(parents) == 2
    assert tables[0].cells == (("Vendor", "State"), ("Synthetic vendor", "Pending"))
    assert tables[0].item_id.startswith(parents[1].item_id + "-nested-")
    assert parents[1].item_id.startswith(parents[0].item_id + "-nested-")
    assert all("Synthetic vendor" not in parent.text for parent in parents)
    assert all(parent.review_location == "subcontractors" for parent in parents)
    assert all("physical page unknown" in entry.word_region for entry in (tables[0], *parents))
    totals = coverage_totals(entries)
    assert sum(totals.values()) == len(entries)
    assert totals["review-needed"] >= 2
    assert totals["imported"] >= 1


def test_nested_table_can_be_saved_reloaded_without_mutating_original(tmp_path, monkeypatch):
    from app.monthly_report_model import ReportPeriod, synthetic_profiles
    from app import monthly_report_library as library

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    path = _nested_source(tmp_path)
    original = path.read_bytes()
    inspected = importer.inspect_docx(path)
    item = next(item for item in inspected.items if item.kind == "table")
    mapped = importer.map_items(path, inspected, (importer.ImportMapping(item.id, "service_calls"),))
    profile = synthetic_profiles()[0]
    draft = importer.imported_draft(profile, ReportPeriod(2026, 10), "Synthetic Reviewer", mapped)
    saved = library.save_snapshot(draft, expected_revision=0, assets=mapped.assets, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert reopened.draft == draft and saved.draft == draft
    assert draft.blocks[0].rows == (("Pump A", "Completed"),)
    assert draft.blocks[0].references == (f"docx:{inspected.sha256}:{item.id}",)
    assert path.read_bytes() == original


def test_markup_exclusions_are_not_report_content(tmp_path):
    from docx.oxml import parse_xml
    from app.monthly_report_docx_coverage import coverage_inventory

    doc = Document()
    doc.add_heading("Training Summary", 1)
    paragraph = doc.add_paragraph("Approved synthetic completion")
    paragraph._p.append(parse_xml(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:del w:id="1"><w:r><w:delText>Deleted offer</w:delText></w:r></w:del>'
        '</w:r>'))
    paragraph._p.append(parse_xml(
        '<w:commentRangeStart xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:id="5"/>'))
    path = tmp_path / "revisions.docx"
    doc.save(path)
    raw = path.read_bytes()
    result = importer.inspect_docx(path)
    assert path.read_bytes() == raw
    assert not any("Deleted offer" in item.text for item in result.items)
    assert any(item.text == "Approved synthetic completion" for item in result.items)
    entries = coverage_inventory(result)
    assert any(e.item_id == "excluded:tracked-deletions" and e.status == "excluded-with-reason" for e in entries)
    assert any(e.item_id == "excluded:word-comments" and e.status == "excluded-with-reason" for e in entries)


def test_unsupported_chart_is_review_not_extracted(tmp_path):
    from docx.oxml import parse_xml
    from app.monthly_report_docx_coverage import coverage_inventory

    doc = Document()
    doc.add_heading("Monthly Scorecards", 1)
    paragraph = doc.add_paragraph("Synthetic scorecard description")
    paragraph._p.append(parse_xml(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:drawing><a:graphic><a:graphicData '
        'uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        '<c:chart r:id="rIdMissingChart"/></a:graphicData></a:graphic></w:drawing>'
        '</w:r>'))
    path = tmp_path / "chart.docx"
    doc.save(path)
    inspected = importer.inspect_docx(path)
    review = [e for e in coverage_inventory(inspected) if e.kind == "unsupported"]
    assert review and any(e.review_location == "scorecards" for e in review)
    assert all(e.status == "review-needed" for e in review)
    assert any(e.relationship_id == "rIdMissingChart" for e in review)


def test_named_chart_part_labels_are_review_only_and_numeric_values_not_extracted(tmp_path):
    from zipfile import ZipFile, ZIP_DEFLATED
    from docx.oxml import parse_xml
    from app.monthly_report_docx_coverage import coverage_inventory

    doc = Document()
    doc.add_heading("Monthly Scorecards", 1)
    doc.add_paragraph()._p.append(parse_xml(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:drawing><a:graphic><a:graphicData '
        'uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        '<c:chart r:id="rIdChartUnit"/></a:graphicData></a:graphic></w:drawing>'
        '</w:r>'))
    path = tmp_path / "chart-with-local-labels.docx"
    doc.save(path)
    with ZipFile(path) as archive:
        parts = {part.filename: archive.read(part.filename) for part in archive.infolist()}
    rels = parts["word/_rels/document.xml.rels"].decode()
    rels = rels.replace("</Relationships>",
        '<Relationship Id="rIdChartUnit" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" '
        'Target="charts/chart1.xml"/></Relationships>')
    parts["word/_rels/document.xml.rels"] = rels.encode()
    parts["word/charts/chart1.xml"] = (
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        '<c:chart><c:plotArea><c:barChart><c:ser>'
        '<c:tx><c:v>Boiler performance</c:v></c:tx>'
        '<c:cat><c:strRef><c:strCache><c:pt idx="0"><c:v>North site</c:v>'
        '</c:pt></c:strCache></c:strRef></c:cat>'
        '<c:val><c:numRef><c:numCache><c:pt idx="0"><c:v>987654321</c:v>'
        '</c:pt></c:numCache></c:numRef></c:val>'
        '</c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>'
    ).encode()
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, contents in parts.items():
            archive.writestr(name, contents)
    original = path.read_bytes()
    entries = coverage_inventory(importer.inspect_docx(path))
    charts = [e for e in entries if e.relationship_id == "rIdChartUnit"]
    assert len(charts) == 1 and charts[0].status == "review-needed"
    assert "Boiler performance" in charts[0].text and "North site" in charts[0].text
    assert "987654321" not in charts[0].text
    assert "numeric data and layout are not imported" in charts[0].reason
    assert path.read_bytes() == original

    # A corrupt chart part must remain an actionable single-object notice,
    # never abort the entire supported sibling table/paragraph inspection.
    parts["word/charts/chart1.xml"] = b"<invalid"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, contents in parts.items():
            archive.writestr(name, contents)
    damaged = path.read_bytes()
    revised = coverage_inventory(importer.inspect_docx(path))
    chart = next(e for e in revised if e.relationship_id == "rIdChartUnit")
    assert chart.status == "review-needed"
    assert "could not be read safely" in chart.reason
    assert path.read_bytes() == damaged


def test_cover_identity_does_not_include_unrelated_body_site_or_scheduled_work(tmp_path):
    from app.monthly_report_start_import import analyze_starting_report
    from app.monthly_report_model import ReportPeriod, synthetic_profiles

    doc = Document()
    doc.add_paragraph("Demonstration North Facility")
    doc.add_paragraph("Monthly Report September 2026")
    doc.add_heading("Monthly Activity Summary", 1)
    doc.add_paragraph("Demonstration South Facility was mentioned in a body reference.")
    doc.add_paragraph("Pump A service scheduled for October 2026, not completed.")
    path = tmp_path / "cover-identity.docx"
    doc.save(path)
    inspected = importer.inspect_docx(path)
    north, group = synthetic_profiles()[:2]
    analysis = analyze_starting_report(inspected, north, ReportPeriod(2026, 10),
                                      known_sites=group.facilities)
    assert analysis.site_relation == "same"
    assert tuple(site.key for site in analysis.source_sites) == ("north",)
    assert analysis.source_period == (2026, 9)
    assert not analysis.current_items

    other = Document()
    other.add_paragraph("Demonstration South Facility")
    other.add_paragraph("Monthly Report September 2026")
    other.add_heading("Monthly Activity Summary", 1)
    other.add_paragraph("No current work is confirmed.")
    other_path = tmp_path / "foreign.docx"
    other.save(other_path)
    foreign = analyze_starting_report(importer.inspect_docx(other_path), north,
                                      ReportPeriod(2026, 10), known_sites=group.facilities)
    assert foreign.site_relation == "other"


def test_real_parser_budgets_have_stage_specific_exact_unit_errors(tmp_path, monkeypatch):
    import pytest

    path = _nested_source(tmp_path)
    for knob, message in (
        ("MAX_DOCX_BYTES", "1 byte import limit"),
        ("MAX_EXPANDED_BYTES", "Expanded DOCX exceeds the 1 byte limit"),
        ("MAX_MEMBER_BYTES", "per-member limit 1 byte"),
        ("MAX_XML_BYTES", "1 byte per-part safe parsing budget"),
        ("MAX_XML_TOTAL", "1 byte total safe parsing budget"),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(importer, knob, 1)
            with pytest.raises(importer.ImportError, match=message) as caught:
                importer.inspect_docx(path)
            from app.monthly_report_starting_errors import starting_docx_failure_notice
            visible = starting_docx_failure_notice(caught.value)
            assert "This report could not be analyzed" not in visible
            assert "original file and existing report were not changed" in visible


def test_empty_proposal_frame_does_not_consume_following_native_table(tmp_path):
    from docx.oxml import parse_xml

    doc = Document()
    doc.add_heading("Pending & Declined Proposals", 1)
    doc.add_paragraph()._p.append(parse_xml(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml">'
        '<w:pict><v:shape id="empty-proposal-frame"><v:textbox>'
        '<w:txbxContent><w:p/></w:txbxContent></v:textbox></v:shape></w:pict></w:r>'))
    table = doc.add_table(rows=2, cols=2)
    for cell, value in zip(table.rows[0].cells, ("Scope", "Status")):
        cell.text = value
    for cell, value in zip(table.rows[1].cells, ("Synthetic no-price quote", "Pending")):
        cell.text = value
    path = tmp_path / "proposal-frame.docx"
    doc.save(path)
    inspected = importer.inspect_docx(path)
    assert any(i.kind == "unsupported" and i.section == "proposals" for i in inspected.items)
    proposals = [i for i in inspected.items if i.kind == "table" and i.section == "proposals"]
    assert len(proposals) == 1
    assert proposals[0].rows[1] == ("Synthetic no-price quote", "Pending")
