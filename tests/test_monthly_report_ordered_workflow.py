"""The report's sequence is the editing interface, without a second navigator."""

from app import monthly_report_guided as guided, monthly_report_library as library
from app.monthly_report_docx import ReportPackage
from app.monthly_report_model import ReportPeriod, default_sections
from test_monthly_report_ui import monthly, choose_report, ROOT
from streamlit.testing.v1 import AppTest


def test_report_order_all_editors_and_direct_previews(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    next(item for item in app.text_input if item.label == "Prepared by").set_value("Report Author").run()
    from app import monthly_report_section_preview_ui
    calls = []
    monkeypatch.setattr(monthly_report_section_preview_ui, "render_section_preview",
                        lambda draft, section, assets, prefix, **kwargs: calls.append((section, kwargs)))
    app.run()
    assert not app.exception
    titles = [item.value for item in app.subheader]
    expected = [section.title for section in default_sections()]
    assert [title for title in titles if title in expected] == expected
    assert [key for key, _ in calls] == ["cover", *(section.key for section in default_sections())]
    assert all(options.get("deferred") for _, options in calls)
    assert not any(item.label == "Report steps" for item in app.radio)
    assert not any(item.label in ("Section to update", "Site information to update") for item in app.selectbox)
    assert not any(item.label == "Show writing help" for item in app.toggle)
    assert next(item for item in app.checkbox if item.label == "Add work-order spreadsheets")
    assert next(item for item in app.text_area if item.label == "Activity summary")
    assert next(item for item in app.button if item.label == "Generate DOCX and PDF")


def test_inline_edits_save_resume_and_generate_without_navigation(monkeypatch, tmp_path):
    captured = []
    def generate(draft, **kwargs):
        captured.append(draft)
        return ReportPackage(b"docx", b"%PDF", "report.docx", "report.pdf", draft.fingerprint)
    monkeypatch.setattr(guided, "generate_report", generate)
    app = monthly(monkeypatch, tmp_path)
    next(item for item in app.text_input if item.label == "Prepared by").set_value("Report Author").run()
    next(item for item in app.text_area if item.label == "Activity summary").set_value("Completed the September inspections.").run()
    next(item for item in app.button if item.label == "Save progress").click().run()
    assert not app.exception
    from app.contracts import RRH_CONTRACT
    saved = library.load_snapshot(RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9))
    assert next(block for block in saved.draft.blocks if block.key == "activity_summary").text == "Completed the September inspections."
    assert all(section.included for section in saved.draft.sections)
    resumed = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    resumed.segmented_control[0].set_value("Monthly report").run()
    choose_report(resumed, saved.draft.profile.facilities[0].title)
    next(item for item in resumed.text_input if item.label == "Prepared by").set_value("Report Author").run()
    assert next(item for item in resumed.text_area if item.label == "Activity summary").value == "Completed the September inspections."
    warning = next((item for item in resumed.checkbox if item.label == "I checked these specific warnings"), None)
    if warning:
        warning.check().run()
    next(item for item in resumed.button if item.label == "Generate DOCX and PDF").click().run()
    assert not resumed.exception
    assert captured and next(block for block in captured[-1].blocks if block.key == "activity_summary").text == "Completed the September inspections."
    assert {item.label for item in resumed.get("download_button")} >= {"Download DOCX", "Download PDF"}


def test_native_ar_design_keeps_source_order_without_inserting_rfi():
    from dataclasses import replace
    from app.monthly_report_model import ReportDraft, synthetic_profiles, optional_sections
    core = [section.key for section in default_sections() if section.key != "rfi"]
    order = tuple((*core[:9], "accounts_receivable", *core[9:]))
    profile = replace(synthetic_profiles()[0], template="enfra_master:" + "a" * 64, section_order=order)
    # A legacy draft can still contain its old RFI default; the pinned native
    # master is authoritative about this variant's optional sections.
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Editor", default_sections(), ())
    result = guided.complete_guided_sections(draft)
    assert tuple(section.key for section in result.sections) == order
    assert all(section.included for section in result.sections)
    ar = next(section for section in result.sections if section.key == "accounts_receivable")
    assert ar.blocks == tuple(replace(block, required=False) for block in optional_sections()[0].blocks)


def test_native_core_only_design_does_not_gain_optional_sections():
    from dataclasses import replace
    from app.monthly_report_model import ReportDraft, synthetic_profiles
    order = tuple(section.key for section in default_sections() if section.key != "rfi")
    profile = replace(synthetic_profiles()[0], template="enfra_native:" + "b" * 64, section_order=order)
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Editor", default_sections(), ())
    assert tuple(section.key for section in guided.complete_guided_sections(draft).sections) == order


def test_unnamed_visitor_does_not_render_saved_contact_pages(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    from app import monthly_report_section_preview_ui, monthly_report_editor
    calls = []
    image_reviews = []
    linked_sections = []
    from app import monthly_report_ai_ui
    monkeypatch.setattr(monthly_report_ai_ui, "edit_linked_paragraphs",
                        lambda draft, blocks, prefix, field, allowed: linked_sections.append(allowed) or blocks)
    monkeypatch.setattr(monthly_report_section_preview_ui, "render_section_preview",
                        lambda draft, section, *args, **kwargs: calls.append(section))
    monkeypatch.setattr(monthly_report_editor, "review_client_images",
                        lambda draft, *args, **kwargs: image_reviews.append(True) or draft)
    app.run()
    assert not app.exception
    assert not {"organization", "subcontractors", "training"}.intersection(calls)
    assert not image_reviews
    assert not any({"org_chart", "contact_matrix", "subcontractor_matrix", "training_summary"}.intersection(keys)
                   for keys in linked_sections)
    next(item for item in app.text_input if item.label == "Prepared by").set_value("Report Author").run()
    assert {"organization", "subcontractors", "training"}.issubset(calls)
    assert image_reviews
