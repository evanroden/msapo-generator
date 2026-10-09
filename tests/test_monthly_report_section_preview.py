from dataclasses import replace
from io import BytesIO

from docx import Document
import fitz
from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_preview as engine
from app import monthly_report_section_preview_ui as ui
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    ReportPeriod, ResolvedBlock, default_sections, synthetic_draft, synthetic_profiles,
)
from tests.conftest import requires_libreoffice


def draft():
    base = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    return replace(base, sections=default_sections(), prepared_by="", blocks=(
        ResolvedBlock("activity_summary", "This month", text="Inspected the synthetic pumps."),
        ResolvedBlock("training_summary", "This month", text="Completed synthetic safety training.", ai_written=True),
    ))


def fake_converter(monkeypatch, tmp_path):
    calls = []

    def convert(path):
        calls.append(Document(path))
        output = tmp_path / (path.stem + ".pdf")
        with fitz.open() as pdf:
            for number in range(2):
                page = pdf.new_page(width=612, height=792)
                page.insert_text((72, 72), "Live vector section page " + str(number + 1))
            pdf.save(output)
        return output

    monkeypatch.setattr(engine.pdf_converter, "convert_to_pdf", convert)
    return calls


def text(raw):
    return "\n".join(paragraph.text for paragraph in Document(BytesIO(raw)).paragraphs)


def test_section_docx_contains_only_selected_divider_and_content_with_original_number():
    raw = engine.section_preview_docx(draft(), "training")
    visible = text(raw)
    assert "Section 11" in visible
    assert "11. Training Summary" in visible
    assert "Completed synthetic safety training." in visible
    assert "Table of contents" not in visible
    assert "Prepared by:" not in visible
    assert "Inspected the synthetic pumps." not in visible
    assert "Monthly Activity Summary" not in visible
    document = Document(BytesIO(raw))
    assert len(document.sections) == 2
    assert document.sections[0].left_margin == 0
    assert document.sections[1].left_margin.inches == 0.75
    assert "ENFRA" in document.sections[1].header.paragraphs[0].text
    # Previewing incomplete work never supplies an approval to final generation.
    with pytest.raises(ValueError, match="prepared|Review|required"):
        assemble_docx(draft())


def test_cover_preview_is_only_cover_and_keeps_cover_geometry():
    raw = engine.section_preview_docx(draft(), "cover")
    visible = text(raw)
    assert draft().profile.title in visible
    assert "September 2026" in visible
    assert "Prepared by:" in visible
    assert "Table of contents" not in visible
    assert "Completed synthetic safety training." not in visible
    assert len(Document(BytesIO(raw)).sections) == 1
    assert Document(BytesIO(raw)).sections[0].left_margin == 0


def test_empty_and_unfinished_template_sections_can_be_previewed():
    report = draft()
    assert "Water Treatment Reports" in text(engine.section_preview_docx(report, "water"))
    unfinished = replace(report, blocks=(ResolvedBlock("training_summary", "This month", text="Insert image here"),))
    assert "Insert image here" in text(engine.section_preview_docx(unfinished, "training"))
    with pytest.raises(ValueError, match="template instructions"):
        assemble_docx(unfinished)


def test_preview_does_not_resolve_other_sections_or_cover_art():
    report = draft()
    image = BytesIO()
    Image.new("RGB", (1200, 1200), "#123456").save(image, "PNG")
    report = replace(report, blocks=(*report.blocks,
        ResolvedBlock("water_reports", "This month", asset_hashes=("water.png",)),
        ResolvedBlock("org_chart", "This month", asset_hashes=("unavailable-org.png",)),
        ResolvedBlock("cover_photo", "This month", asset_hashes=("unavailable-cover.png",)),
    ))
    loaded = []

    def loader(ref):
        loaded.append(ref)
        assert ref == "water.png"
        return image.getvalue()

    assert "Section 7" in text(engine.section_preview_docx(report, "water", loader))
    assert loaded == ["water.png"]


def test_visible_fingerprint_ignores_other_work_and_approvals_but_tracks_real_edits():
    report = draft()
    fingerprint = engine.section_preview_fingerprint(report, "training")
    changed = replace(report, blocks=tuple(
        replace(block, text="Unrelated new maintenance.") if block.key == "activity_summary"
        else replace(block, reviewed_fingerprint=block.fingerprint, ai_written=False)
        for block in report.blocks
    ))
    assert engine.section_preview_fingerprint(changed, "training") == fingerprint
    changed = replace(changed, blocks=tuple(
        replace(block, text="Updated training statement.") if block.key == "training_summary" else block
        for block in changed.blocks
    ))
    assert engine.section_preview_fingerprint(changed, "training") != fingerprint
    assert engine.section_preview_fingerprint(replace(report, address_line="New footer"), "training") != fingerprint
    assert engine.section_preview_fingerprint(replace(report, prepared_by="Synthetic Editor"), "cover") != engine.section_preview_fingerprint(report, "cover")


def test_vector_pdf_and_sharp_pages_keep_bounds_and_clean_temporary_outputs(monkeypatch, tmp_path):
    calls = fake_converter(monkeypatch, tmp_path)
    preview = engine.preview_section(draft(), "training")
    assert preview.pages == 2
    with fitz.open(stream=preview.pdf, filetype="pdf") as pdf:
        assert "Live vector section page" in pdf[0].get_text()
    image = Image.open(BytesIO(engine.preview_page(preview, 0)))
    assert image.size == (1275, 1650)
    assert "Table of contents" not in "\n".join(p.text for p in calls[0].paragraphs)
    assert not list(tmp_path.glob("section-preview-*.pdf"))
    monkeypatch.setattr(engine, "MAX_PREVIEW_PAGES", 1)
    with pytest.raises(ValueError, match="limited"):
        engine.preview_section(draft(), "training")
    assert not list(tmp_path.glob("section-preview-*.pdf"))


def preview_app(monkeypatch, tmp_path):
    calls = fake_converter(monkeypatch, tmp_path)
    app = AppTest.from_string('''
import streamlit as st
from dataclasses import replace
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles, default_sections
from app.monthly_report_section_preview_ui import render_section_preview
base = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
section = st.selectbox("Section", ("activity", "training"))
value = st.text_area("Current text", "Synthetic current edit")
unrelated = st.text_input("Unrelated", "")
draft = replace(base, prepared_by="", sections=default_sections(), blocks=(
    ResolvedBlock("activity_summary", "This month", text=value),
    ResolvedBlock("training_summary", "This month", text="Synthetic training"),
    ResolvedBlock("equipment_issues", "This month", text=unrelated)))
st.session_state["preview"] = render_section_preview(draft, section, {}, "synthetic")
''', default_timeout=15).run()
    assert not app.exception
    return app, calls


def test_ui_updates_on_edits_is_scrollable_and_reuses_only_unchanged_section(monkeypatch, tmp_path):
    app, calls = preview_app(monkeypatch, tmp_path)
    assert len(calls) == 1
    assert not app.button and not app.get("download_button")
    frame = app.get("iframe")[0].proto
    assert frame.scrolling
    assert "data:image/png;base64," in frame.srcdoc and "<a " not in frame.srcdoc
    app.text_input[0].set_value("Unrelated edit").run()
    assert len(calls) == 1
    app.text_area[0].set_value("New selected section text").run()
    assert len(calls) == 2
    app.selectbox[0].set_value("training").run()
    assert len(calls) == 3
    app.selectbox[0].set_value("activity").run()
    assert len(calls) == 3
    assert not app.exception


def test_failed_rerender_hides_stale_page_and_retry_preserves_the_edit(monkeypatch, tmp_path):
    app, _ = preview_app(monkeypatch, tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic renderer unavailable")

    monkeypatch.setattr(ui, "preview_section", fail)
    app.text_area[0].set_value("Still here after rendering failure").run()
    assert not app.exception
    assert not app.get("iframe")
    assert any("Your edits are still here" in value.value for value in app.warning)
    app.run()
    assert app.button[0].label == "Retry preview"
    monkeypatch.setattr(ui, "preview_section", engine.preview_section)
    app.button[0].click().run()
    assert not app.exception and app.get("iframe")
    assert app.text_area[0].value == "Still here after rendering failure"


@requires_libreoffice
def test_real_section_render_excludes_cover_toc_and_other_sections_and_keeps_text():
    report = draft()
    preview = engine.preview_section(report, "training")
    with fitz.open(stream=preview.pdf, filetype="pdf") as pdf:
        content = "\n".join(page.get_text() for page in pdf)
        assert len(pdf) == 2
        assert "Section 11" in content
        assert "Completed synthetic safety training." in content
        assert "Table of contents" not in content
        assert "Prepared by:" not in content
        assert "Inspected the synthetic pumps." not in content
    cover = engine.preview_section(report, "cover")
    with fitz.open(stream=cover.pdf, filetype="pdf") as pdf:
        content = "\n".join(page.get_text() for page in pdf)
        assert "September 2026" in content
        assert "Training Summary" not in content


def test_ordered_queue_runs_one_job_and_discards_a_result_after_edit(monkeypatch):
    from concurrent.futures import Future
    from threading import BoundedSemaphore
    jobs = []
    class Worker:
        def submit(self, fn, *args):
            future = Future()
            jobs.append((future, args))
            return future
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', slot)
    state = {'wanted': {'activity': 'new', 'training': 'train'},
             'queue': {'activity': ('old', draft(), {}, 'Activity'),
                       'training': ('train', draft(), {}, 'Training')},
             'cache': {}, 'running': None}
    ui._advance_preview_queue(state)
    ui._advance_preview_queue(state)
    assert len(jobs) == 1 and state['running'][0] == 'activity'
    jobs[0][0].set_result({'html': 'OUTDATED PAGE'})
    slot.release()
    ui._advance_preview_queue(state)
    assert 'activity' not in state['cache']
    assert len(jobs) == 2 and state['running'][0] == 'training'
    jobs[1][0].set_result({'html': 'Current training page', 'pages': 1})
    slot.release()
    ui._advance_preview_queue(state)
    assert state['cache']['training']['html'] == 'Current training page'
    assert state['running'] is None


def test_ordered_preview_failure_releases_conversion_slot(monkeypatch):
    from threading import BoundedSemaphore
    slot = BoundedSemaphore(1)
    assert slot.acquire(False)
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', slot)
    def fail(*args):
        raise RuntimeError('converter failed')
    monkeypatch.setattr(ui, 'preview_section', fail)
    result = ui._build_preview_entry(draft(), 'activity', {}, 'Activity')
    assert 'error' in result and 'edits are still here' in result['error']
    assert slot.acquire(False)


def test_ordered_preview_pane_stays_visible_and_editor_is_usable_while_rendering(monkeypatch):
    from concurrent.futures import Future
    from threading import BoundedSemaphore
    jobs = []
    class Worker:
        def submit(self, fn, *args):
            future = Future()
            jobs.append(future)
            return future
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', slot)
    app = AppTest.from_string('''
import streamlit as st
from dataclasses import replace
from app.monthly_report_model import synthetic_draft, synthetic_profiles, ReportPeriod, ResolvedBlock, default_sections
from app.monthly_report_section_preview_ui import render_section_preview
value = st.text_area("Activity", "Current activity")
draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
draft = replace(draft, sections=default_sections(), blocks=(ResolvedBlock("activity_summary", "This month", text=value),))
render_section_preview(draft, "activity", {}, "ordered", deferred=True)
''', default_timeout=15).run()
    assert not app.exception
    assert app.info and not app.get('iframe') and len(jobs) == 1
    app.text_area[0].set_value('A saved new edit').run()
    assert not app.exception and app.text_area[0].value == 'A saved new edit'
    assert len(jobs) == 1
    jobs[0].set_result({'html': '<p>Old preview</p>', 'pages': 1})
    slot.release()
    app.run()
    assert not app.get('iframe') and len(jobs) == 2
    jobs[1].set_result({'html': '<p>Current preview</p>', 'pages': 1})
    slot.release()
    app.run()
    assert not app.exception and app.get('iframe')
    assert 'Current preview' in app.get('iframe')[0].proto.srcdoc


def test_missing_preview_source_does_not_crash_the_editor(monkeypatch, tmp_path):
    def unavailable(*args):
        raise OSError('source unavailable')
    monkeypatch.setattr(ui, 'section_preview_fingerprint', unavailable)
    app, calls = preview_app(monkeypatch, tmp_path)
    assert not app.exception and not calls
    assert any('edits are still here' in value.value for value in app.warning)
    app.text_area[0].set_value('Still editable').run()
    assert not app.exception and app.text_area[0].value == 'Still editable'


def test_section_preview_refreshes_when_report_month_changes():
    from app.monthly_report_model import ReportPeriod
    original = draft()
    changed = replace(original, period=ReportPeriod(2026, 10))
    assert engine.section_preview_fingerprint(original, 'activity') != engine.section_preview_fingerprint(changed, 'activity')
