"""QA exports use the accepted report's images in its original test namespace.

DOCX assembly and source-page ingestion are real. The PDF converter seam below
only forwards a small invented PDF; actual office rendering stays a CI/browser
gate, independently of these deterministic resolver regressions.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import fitz
import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_testing as qa, monthly_report_testing_ui as ui
from app import monthly_report_qa_fixture as fixture
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_editor import _signature
from app.monthly_report_section_uploads import prepare_section_pages
from test_monthly_report_qa_ui import ACTOR_COOKIE, visit
from test_monthly_report_sources import pdf_bytes


def editor_prefix(draft):
    return "report_guided_" + _signature((draft.profile.contract, draft.profile.key, draft.period.key))


def source_page(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = fixture.profile()
    content, _ = sources.ingest(profile, "invented-water.pdf", pdf_bytes(1))
    content = replace(content, source=replace(content.source,
        client_page_reviews=((1, page_fingerprint(content.source, 1)),)))
    block = prepare_section_pages(profile, (content,), "water_reports", {})["water_reports"]
    reference = block.asset_hashes[0]
    return content, block, reference, library.read_asset(profile.contract, profile.key, reference)


@pytest.mark.parametrize("storage", ["library", "memory"])
def test_qa_toolbar_generates_real_docx_with_ingested_source_page(monkeypatch, tmp_path, storage):
    from app import monthly_report_render_jobs as jobs
    app = visit(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Load known-value report").click().run()
    profile = fixture.profile()
    prefix = "report_guided_" + _signature((fixture.CONTRACT, profile.key, fixture.PERIOD.key))
    with qa.isolated(ACTOR_COOKIE):
        content, block, reference, raw = source_page(monkeypatch, tmp_path)
        path = library._profile_path(profile.contract, profile.key) / "assets" / reference
        original = sources.source_bytes(profile, content.source)
    working = app.session_state[prefix + "_draft"]
    app.session_state[prefix + "_draft"] = replace(working,
        blocks=tuple(block if b.key == block.key else b for b in working.blocks), sources=(content.source,))
    app.session_state[prefix + "_evidence"] = (content,)
    app.session_state[prefix + "_evidence_section_routes"] = {content.source.id: "water_reports"}
    if storage == "memory":
        app.session_state[prefix + "_assets"] = {reference: raw}
        path.unlink()
    app.run()
    assert not app.exception
    converted = []

    def converter_stub(input_path, **_kwargs):
        # This is the actual generated, still editable DOCX handed to the
        # converter. The image must be embedded before any PDF seam executes.
        with ZipFile(input_path) as package:
            assert raw in [package.read(name) for name in package.namelist() if name.startswith("word/media/")]
        converted.append(1)
        output = tmp_path / "invented-converter-output.pdf"
        with fitz.open() as document:
            document.new_page().insert_text((40, 50), "Invented converter boundary only")
            document.save(output)
        return output

    monkeypatch.setattr(jobs, "convert_to_pdf", converter_stub)
    next(b for b in app.button if b.label == "Generate QA Word and PDF").click().run()
    assert not app.exception
    assert app.session_state["monthly_qa_generation_receipt"]["status"] == "completed"
    assert converted == [1]
    fingerprint, package = app.session_state["monthly_qa_package"]
    assert fingerprint == package.fingerprint
    assert package.pdf.startswith(b"%PDF-")
    with ZipFile(BytesIO(package.docx)) as document:
        assert raw in [document.read(name) for name in document.namelist() if name.startswith("word/media/")]
    with qa.isolated(ACTOR_COOKIE):
        assert sources.source_bytes(profile, content.source) == original
        assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD).draft.sources == ()
    assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None


def test_qa_toolbar_rejects_missing_asset_without_replaying_generation(monkeypatch, tmp_path):
    from app import monthly_report_guided as guided, monthly_report_render_jobs as jobs
    app = visit(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Load known-value report").click().run()
    with qa.isolated(ACTOR_COOKIE):
        content, block, reference, raw = source_page(monkeypatch, tmp_path)
        path = library._profile_path(fixture.CONTRACT, fixture.profile().key) / "assets" / reference
        path.unlink()
    prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
    working = app.session_state[prefix + "_draft"]
    app.session_state[prefix + "_draft"] = replace(working,
        blocks=tuple(block if b.key == block.key else b for b in working.blocks), sources=(content.source,))
    # Isolate the QA toolbar's handling of this accepted, finalized draft.
    # The ordinary editor's independent missing-image preflight is not the
    # layer under test, so it cannot consume the failure before QA Generate.
    monkeypatch.setattr(guided, "render_guided_workflow", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs, "convert_to_pdf", lambda *args, **kwargs: pytest.fail("Missing image reached PDF conversion"))
    app.run()
    next(b for b in app.button if b.label == "Generate QA Word and PDF").click().run()
    assert not app.exception
    receipt = dict(app.session_state["monthly_qa_generation_receipt"])
    assert receipt["status"] == "rejected" and "unavailable" in receipt["message"]
    assert "monthly_qa_package" not in app.session_state.filtered_state
    assert "monthly_qa_generate_queued" not in app.session_state.filtered_state
    app.run()
    assert app.session_state["monthly_qa_generation_receipt"] == receipt


def test_qa_loader_restores_its_captured_namespace_in_an_uncopied_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ui.st, "session_state", {})
    with qa.isolated(ACTOR_COOKIE):
        content, block, reference, raw = source_page(monkeypatch, tmp_path)
        draft = replace(fixture.prepare("prefill"), blocks=(block,), sources=(content.source,))
        loader = ui._qa_asset_loader(draft, tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(loader, reference).result() == raw
    assert qa.scope() is None


def test_missing_qa_asset_never_falls_back_to_same_asset_in_live_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ui.st, "session_state", {})
    with qa.isolated(ACTOR_COOKIE):
        content, block, reference, raw = source_page(monkeypatch, tmp_path)
        draft = replace(fixture.prepare("prefill"), blocks=(block,), sources=(content.source,))
        path = library._profile_path(draft.profile.contract, draft.profile.key) / "assets" / reference
        path.unlink()
        loader = ui._qa_asset_loader(draft, tmp_path)
    live_path = library._profile_path(draft.profile.contract, draft.profile.key) / "assets" / reference
    library._atomic_write(live_path, raw)
    with ThreadPoolExecutor(max_workers=1) as executor, pytest.raises(library.LibraryError, match="unavailable"):
        executor.submit(loader, reference).result()
    assert live_path.read_bytes() == raw


@pytest.mark.parametrize("storage", ["library", "memory"])
def test_old_qa_loader_cannot_read_after_reset_or_adopt_new_generation(monkeypatch, tmp_path, storage):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    state = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    with qa.isolated(ACTOR_COOKIE):
        content, block, reference, raw = source_page(monkeypatch, tmp_path)
        draft = replace(fixture.prepare("prefill"), blocks=(block,), sources=(content.source,))
        if storage == "memory":
            state[editor_prefix(draft) + "_assets"] = {reference: raw}
        loader = ui._qa_asset_loader(draft, tmp_path)
        old_generation = qa.generation()
        qa.reset(tmp_path)
        with pytest.raises(OSError, match="reset"):
            loader(reference)
    with qa.isolated(ACTOR_COOKIE):
        fixture.prepare("prefill")
        assert qa.generation() != old_generation
        with pytest.raises(OSError, match="changed"):
            loader(reference)
