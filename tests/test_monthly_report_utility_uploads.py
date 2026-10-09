"""Utility pages can reach scorecards without becoming maintenance or capacity data."""

from dataclasses import asdict, replace
from io import BytesIO

from docx import Document
import fitz
import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import ReportDraft, ReportPeriod, ReportSource, default_sections, synthetic_profiles
from test_monthly_report_editor import app_with_library
from test_monthly_report_upload_ui import button, select, upload


def utility_pdf():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "Utility results. Facility: Demonstration North Facility.")
        page.insert_text((50, 80), "Report date: 2026-09-30")
        page.insert_text((50, 110), "Electricity consumption: 1250 kWh. Synthetic test data.")
        return pdf.tobytes()


def test_utility_page_requires_review_then_keeps_source_and_prints_in_scorecards(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-utility.pdf", utility_pdf())
    assert content.source.classification == "Utility results"
    assert content.source.service_date == "2026-09-30"
    assert not content.source.actions
    destination = ((content.source.id, "utility_analysis"),)
    with pytest.raises(ValueError, match="Check page 1"):
        sources.prepare_pages(profile, (content,), destination)
    source = replace(content.source, client_page_reviews=((1, page_fingerprint(content.source, 1)),))
    blocks = sources.prepare_pages(profile, (replace(content, source=source),), destination)
    block, = blocks
    assert block.key == "utility_analysis" and not block.rows
    assert block.references == (sources.source_reference(source, 1),)
    assert block.client_reviewed_fingerprint == block.fingerprint
    section = next(s for s in default_sections() if s.key == "scorecards")
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", (section,), blocks, sources=(source,))
    restored = library.draft_from_dict(asdict(draft))
    assert restored == draft
    document = Document(BytesIO(assemble_docx(restored, asset_loader=lambda ref: library.read_asset(profile.contract, profile.key, ref))))
    assert len(document.inline_shapes) == 1
    assert not document.tables


def test_utility_detection_keeps_unknown_and_conflicting_sources_uncertain():
    profile = synthetic_profiles()[0]
    unknown = ReportSource("synthetic", "results.pdf", "a" * 64, ".pdf", page_texts=("Synthetic monthly update.",))
    assert sources.suggest_facts(unknown, profile).classification == "Reference only"
    mixed = replace(unknown, page_texts=("Utility analysis and maintenance report.",))
    assert sources.suggest_facts(mixed, profile).classification == "Reference only"


def test_new_utility_section_does_not_invent_availability_or_capacity(monkeypatch, tmp_path):
    from app.monthly_report_guided import _initial_draft
    from app.monthly_report_start import design_seed
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    period = ReportPeriod(2026, 9)
    state = library.load_profile(profile.contract, profile.key)
    seeded, _ = design_seed(profile, period, "Synthetic Editor")
    for draft in (seeded, _initial_draft(state, period, "Synthetic Editor")):
        blocks = {b.key: b for b in draft.blocks}
        assert not blocks["utility_analysis"].text
        assert not blocks["thermal_capacity"].rows
        section = next(s for s in draft.sections if s.key == "scorecards")
        assert not section.blocks[0].stock_text_keys


def test_utility_upload_has_readable_destination_and_prepared_pages(monkeypatch, tmp_path):
    app, _ = app_with_library(monkeypatch, tmp_path)
    upload(monkeypatch, "synthetic-utility.pdf", utility_pdf())
    app.run()
    button(app, "Read monthly files").click().run()
    assert not app.exception
    assert select(app, "Classification").value == "Utility results"
    destination = select(app, "Add synthetic-utility.pdf to")
    assert destination.value == "utility_analysis"
    assert "Monthly scorecards — utility results and charts" in destination.options
    button(app, "Include page and continue").click().run()
    button(app, "Prepare selected pages").click().run()
    assert not app.exception
    assert any("Reviewed pages are ready" in w.value for w in app.success)
