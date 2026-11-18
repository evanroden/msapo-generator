"""Independent synthetic regression for A72's optional direct-PDF Scorecard preview.

No genuine source PDF, paid model, production state, or external renderer is
required for the UI cases. Actual Word/PDF pagination is also exercised by
test_monthly_scorecard_pdf and test_monthly_section_assembly_joined.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
from app.monthly_report_docx import assemble_docx
from app.monthly_report_mbcx_pdf import prepare_whole_pdf
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, default_sections, synthetic_profiles,
)
from app.monthly_report_source_details import detail_problems
from app.monthly_report_source_scope import correct_scope
from test_monthly_report_mbcx_pdf import APP, pdf_bytes


def _scorecard_app(monkeypatch, tmp_path, *, count=3, bad_page=None):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    from app import monthly_report_upload_ui as ui
    uploaded = BytesIO(pdf_bytes(count, bad_page=bad_page))
    uploaded.name = "synthetic-scorecard.pdf"
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: [uploaded])
    return AppTest.from_string(
        APP.replace('"mbcx_report"', '"utility_analysis"'),
        default_timeout=30,
    ).run()


@pytest.mark.parametrize("count", (1, 3))
def test_preview_is_optional_and_one_click_still_includes_all_pages(
    monkeypatch, tmp_path, count,
):
    calls = []
    original = sources.page_image

    def measured(profile, content, number, **kwargs):
        calls.append((number, kwargs.get("preview", False)))
        return original(profile, content, number, **kwargs)

    monkeypatch.setattr(sources, "page_image", measured)
    app = _scorecard_app(monkeypatch, tmp_path, count=count)
    assert not app.exception
    assert not calls, "Closed preview must not rasterize on first paint"
    assert any("Target report: September 2026" in element.value
               and "Source date: not established" in element.value
               and "synthetic-scorecard.pdf" in element.value
               for element in (*app.markdown, *app.caption))
    assert len([b for b in app.button if b.label == "Preview a Scorecard PDF page"]) == 1
    assert not any(box.label == "Scorecard PDF page" for box in app.selectbox)
    next(b for b in app.button if b.label == "Preview a Scorecard PDF page").click().run()
    assert not app.exception
    assert calls == [(1, True)]
    assert not app.session_state["blocks"]
    preview = next(box for box in app.selectbox if box.label == "Scorecard PDF page")
    assert len(preview.options) == count and preview.value == 1
    if count > 1:
        # AppTest's select_index re-formats an already formatted option
        # ("Page Page 3 of 3 of 3"); choose the page by its own value.
        preview.set_value(count).run()
        assert not app.exception and calls[-1] == (count, True)
        assert not app.session_state["blocks"]
    next(b for b in app.button if b.label == f"Include all {count} PDF pages").click().run()
    assert not app.exception
    assert len(app.session_state["blocks"]["utility_analysis"].asset_hashes) == count
    app.run()
    assert len(app.session_state["blocks"]["utility_analysis"].asset_hashes) == count


def test_preview_is_scoped_to_report_month_and_is_not_a_page_review(monkeypatch, tmp_path):
    app = _scorecard_app(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Preview a Scorecard PDF page").click().run()
    assert any(box.label == "Scorecard PDF page" for box in app.selectbox)
    assert not app.session_state["sources"][0].client_page_reviews
    app.session_state["period"] = ReportPeriod(2026, 10)
    app.run()
    assert not app.exception
    assert not any(box.label == "Scorecard PDF page" for box in app.selectbox)
    assert not app.session_state["blocks"]
    assert not app.session_state["sources"][0].client_page_reviews
    assert any("Target report: October 2026" in item.value for item in (*app.markdown, *app.caption))


def test_priced_scorecard_can_be_previewed_but_never_batch_included(monkeypatch, tmp_path):
    app = _scorecard_app(monkeypatch, tmp_path, bad_page="Invoice amount $500.")
    assert not app.exception
    include = next(b for b in app.button if b.label == "Include all 3 PDF pages")
    assert include.disabled
    next(b for b in app.button if b.label == "Preview a Scorecard PDF page").click().run()
    page = next(box for box in app.selectbox if box.label == "Scorecard PDF page")
    page.set_value(2).run()
    assert not app.exception
    assert not app.session_state["blocks"]
    assert not app.session_state["sources"][0].client_page_reviews
    # A rejected batch has the existing individual-page correction path.
    assert any(toggle.label == "Review individual pages" for toggle in app.toggle)


def test_multisite_scorecard_scope_survives_save_reopen_and_native_section(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    base = synthetic_profiles()[0]
    profile = replace(
        base, key="a72-two-site", title="Synthetic North and South",
        facilities=(Facility("a72-north", "Synthetic North"),
                    Facility("a72-south", "Synthetic South")),
        scope_type="multi_site",
    )
    original = pdf_bytes(3)
    content, _ = sources.ingest(profile, "two-site-scorecard.pdf", original)
    scoped = correct_scope(
        replace(content.source, service_date="2026-09-15"),
        profile, ("a72-north", "a72-south"),
    )
    revised, additions = prepare_whole_pdf(
        profile, replace(content, source=scoped), {},
        destination="utility_analysis",
    )
    block = approve_all_assets(refresh_asset_source_context(
        additions["utility_analysis"], (revised.source,),
    ))
    assert len(block.asset_hashes) == 3
    assert block.references == tuple(
        sources.source_reference(revised.source, number) for number in (1, 2, 3)
    )
    period = ReportPeriod(2026, 9)
    assert not detail_problems(revised.source, profile, period)
    foreign = replace(revised.source, facility="unrelated-site", scope_review="")
    assert "site does not match this report" in detail_problems(foreign, profile, period)
    other_month = replace(revised.source, service_date="2026-10-15", scope_review="")
    assert "date outside this report month" in detail_problems(other_month, profile, period)

    section = next(item for item in default_sections() if item.key == "scorecards")
    draft = ReportDraft(
        profile, period, "Synthetic Editor", (section,), (block,),
        sources=(revised.source,), synthetic=True,
    )
    library.save_snapshot(draft, expected_revision=0)
    reopened = library.load_snapshot(profile.contract, profile.key, period).draft
    assert reopened == draft
    assert sources.source_bytes(profile, reopened.sources[0]) == original
    output = assemble_docx(
        reopened, acknowledged_fingerprint=reopened.fingerprint,
        asset_loader=lambda ref: library.read_asset(profile.contract, profile.key, ref),
    )
    word = Document(BytesIO(output))
    assert len(word.inline_shapes) == 3
    contents = [paragraph.text for paragraph in word.paragraphs]
    # Numbering follows the report's own sections; Scorecards is this draft's only one.
    assert any("1. Monthly Scorecards" in line for line in contents)
    assert "two-site-scorecard.pdf · page/item 1" in contents
    assert "two-site-scorecard.pdf · page/item 3" in contents
    assert any("September 2026" in line for line in contents)


def test_unsupported_or_malformed_scorecard_is_not_batch_included(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    text, _ = sources.ingest(profile, "not-a-scorecard.txt", b"Technical results only")
    with pytest.raises(ValueError, match="Choose a PDF"):
        prepare_whole_pdf(profile, text, {}, destination="utility_analysis")
    with pytest.raises(Exception):
        sources.ingest(profile, "malformed-scorecard.pdf", b"not a PDF")
