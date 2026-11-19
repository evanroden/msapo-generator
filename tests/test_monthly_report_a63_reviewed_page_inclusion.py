"""A63 synthetic per-page technical inclusion: one decision, no second Add.

Uses the existing MBCx/Scorecard native Streamlit harness and immutable local
PDFs. No genuine client reports, remote AI calls, or served-browser claims.
"""

from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_upload_ui as upload_ui
from app.monthly_report_content_policy import page_allowed, page_fingerprint
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec,
    synthetic_profiles,
)
from app.monthly_report_page_controls import retained_page_section_omission
from app.monthly_report_saved_pictures_ui import remove_saved_picture
from test_monthly_report_mbcx_pdf import APP, pdf_bytes


TECHNICAL = ("mbcx_report", "utility_analysis")


def launch(monkeypatch, tmp_path, destination, raw=None):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = pdf_bytes(2) if raw is None else raw
    stream = BytesIO(raw)
    stream.name = "synthetic-technical.pdf"
    monkeypatch.setattr(upload_ui.st, "file_uploader", lambda *args, **kwargs: [stream])
    script = APP.replace('"mbcx_report"', repr(destination))
    app = AppTest.from_string(script, default_timeout=20).run()
    assert not app.exception
    next(widget for widget in app.toggle
         if widget.label == "Review individual pages").set_value(True).run()
    assert not app.exception
    return app, raw


def button(app, label):
    return next(widget for widget in app.button if widget.label == label)


@pytest.mark.parametrize("destination", TECHNICAL)
def test_last_page_decision_appends_without_an_extra_button_and_saves(monkeypatch, tmp_path, destination):
    app, raw = launch(monkeypatch, tmp_path, destination)
    assert not any(widget.label == "Add reviewed pages" for widget in app.button)
    assert not app.session_state["blocks"]
    assert not button(app, "Include page").disabled

    button(app, "Include page").click().run()
    assert not app.exception
    assert not app.session_state["blocks"], "A partly reviewed file is not silently included"
    assert next(widget for widget in app.selectbox
                if widget.label == "Page to review").value == 2
    button(app, "Exclude page").click().run()
    assert not app.exception
    block = app.session_state["blocks"][destination]
    assert len(block.asset_hashes) == 1
    assert len(block.references) == 1
    source = app.session_state["sources"][0]
    assert source.selected_pages == (1,)
    assert page_allowed(source, 1) and not page_allowed(source, 2)
    assert dict(source.client_page_exclusions)[2] == page_fingerprint(source, 2)
    assert block.references[0] == sources.source_reference(source, 1)
    assert sources.source_bytes(synthetic_profiles()[0], source) == raw
    assert not any(widget.label == "Add reviewed pages" for widget in app.button)

    from app.monthly_report_section_uploads import included_pages
    assert included_pages({destination: block}) == {(source.id, 1): {destination}}
    app.run()
    assert not app.exception and app.session_state["blocks"][destination] == block
    assert not any(widget.label == "Add reviewed pages" for widget in app.button)

    # Real local snapshot round-trip exercises the same content identity as
    # the guided persistence path; original PDF content is unchanged.
    profile = synthetic_profiles()[0]
    period = ReportPeriod(2026, 9)
    section = SectionSpec(destination, "1", "Synthetic technical pages",
                          (BlockSpec(destination, "pdf_pages"),))
    draft = ReportDraft(profile, period, "Synthetic Editor", (section,), (block,), sources=(source,))
    assert library.draft_from_dict(asdict(draft)) == draft
    saved = library.save_snapshot(draft, expected_revision=0)
    resumed = library.load_snapshot(profile.contract, profile.key, period)
    assert resumed.draft == draft
    assert sources.source_bytes(profile, resumed.draft.sources[0]) == raw

    # Exercise the actual Word renderer from the individually reviewed,
    # persisted source/page selection, not just a mock or whole-PDF shortcut.
    from docx import Document
    from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
    from app.monthly_report_docx import assemble_docx
    reviewed_source = replace(source, service_date="2026-09-12",
                              facility=profile.facilities[0].key)
    reviewed_block = approve_all_assets(refresh_asset_source_context(block, (reviewed_source,)))
    section_key = "mbcx" if destination == "mbcx_report" else "scorecards"
    printable = replace(draft, sources=(reviewed_source,), blocks=(reviewed_block,),
                        sections=(replace(section, key=section_key),))
    docx_bytes = assemble_docx(
        printable, acknowledged_fingerprint=printable.fingerprint,
        asset_loader=lambda name: library.read_asset(profile.contract, profile.key, name),
    )
    assert len(Document(BytesIO(docx_bytes)).inline_shapes) == 1
    assert sha256(docx_bytes).hexdigest() != sha256(raw).hexdigest()


@pytest.mark.parametrize("destination", TECHNICAL)
def test_duplicate_and_deliberate_removal_never_reappears(monkeypatch, tmp_path, destination):
    app, _ = launch(monkeypatch, tmp_path, destination, raw=pdf_bytes(1))
    button(app, "Include page").click().run()
    assert not app.exception
    block = app.session_state["blocks"][destination]
    assert len(block.asset_hashes) == 1
    app.run()
    assert app.session_state["blocks"][destination] == block
    app.session_state["blocks"][destination] = remove_saved_picture(block, 0)
    app.run()
    app.run()
    assert not app.exception
    assert not app.session_state["blocks"][destination].asset_hashes
    assert "synthetic_evidence_section_" + destination + "_auto_include" not in app.session_state.filtered_state
    # A deliberate fresh Include action remains possible; rerender alone is not.
    button(app, "Include page").click().run()
    assert not app.exception
    assert len(app.session_state["blocks"][destination].asset_hashes) == 1


@pytest.mark.parametrize("destination", TECHNICAL)
def test_omitted_content_and_stale_receipts_fail_closed(monkeypatch, tmp_path, destination):
    app, raw = launch(monkeypatch, tmp_path, destination, raw=pdf_bytes(1))
    source = app.session_state["sources"][0]
    retained = ResolvedBlock(destination, "Omit", text="Retained synthetic operator note.")
    assert retained_page_section_omission(retained)
    app.session_state["blocks"][destination] = retained
    request_key = "synthetic_evidence_section_" + destination + "_auto_include"
    app.session_state[request_key] = {
        "source_id": source.id, "fingerprint": source.fingerprint, "pages": (1,),
    }
    app.run()
    assert not app.exception
    assert app.session_state["blocks"][destination] == retained
    assert request_key not in app.session_state.filtered_state
    assert button(app, "Include page").disabled
    assert sources.source_bytes(synthetic_profiles()[0], app.session_state["sources"][0]) == raw


@pytest.mark.parametrize("destination", TECHNICAL)
def test_changed_review_request_does_not_append(monkeypatch, tmp_path, destination):
    app, _ = launch(monkeypatch, tmp_path, destination, raw=pdf_bytes(1))
    source = app.session_state["sources"][0]
    request_key = "synthetic_evidence_section_" + destination + "_auto_include"
    app.session_state[request_key] = {
        "source_id": source.id, "fingerprint": "obsolete",
        "pages": (1,),
    }
    app.run()
    assert not app.exception
    assert not app.session_state["blocks"]
    assert request_key not in app.session_state.filtered_state
    assert not source.client_page_reviews


@pytest.mark.parametrize("destination", TECHNICAL)
@pytest.mark.parametrize("bad_text", [
    "Equipment quote invoice amount $325.00",
    "Terms and conditions. Limitation of liability and governing law.",
    "",
    "Approved by manager. Signature.",
])
def test_unsafe_or_empty_pages_cannot_be_included(monkeypatch, tmp_path, destination, bad_text):
    with fitz.open() as pdf:
        page = pdf.new_page()
        if bad_text:
            page.insert_text((40, 60), bad_text)
        raw = pdf.tobytes()
    app, _ = launch(monkeypatch, tmp_path, destination, raw=raw)
    assert not app.exception
    assert button(app, "Include page").disabled
    assert not app.session_state["blocks"]
    button(app, "Exclude page").click().run()
    assert not app.exception
    assert not app.session_state["blocks"]
    assert not app.session_state["sources"][0].client_page_reviews


@pytest.mark.parametrize("destination", TECHNICAL)
def test_oversized_page_batch_still_fails_atomically(monkeypatch, tmp_path, destination):
    app, _ = launch(monkeypatch, tmp_path, destination, raw=pdf_bytes(1))
    # A preexisting large attachment makes the reviewed page exceed 150 total
    # source pages: the normal preparation gate, not the UI, must reject it.
    app.session_state["blocks"]["vendor_reports"] = ResolvedBlock(
        "vendor_reports", "This month", asset_hashes=("synthetic-previous.png",) * 150)
    button(app, "Include page").click().run()
    assert not app.exception
    assert destination not in app.session_state["blocks"]
    assert any("150" in widget.value for widget in app.error)
    assert app.session_state["sources"][0].client_page_reviews
    app.run()
    assert any(widget.label == "Retry including reviewed pages" for widget in app.button)
