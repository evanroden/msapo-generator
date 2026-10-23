"""The one source workspace keeps selected-file inputs and direct writing."""
from datetime import date
from io import BytesIO

from app import monthly_report_upload_ui as ui
from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import button, current_draft, select
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_utility_uploads import utility_pdf


def uploads(monkeypatch, files):
    original = ui.st.file_uploader
    streams = []
    for filename, raw in files:
        stream = BytesIO(raw); stream.name = filename; streams.append(stream)
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *args, **kwargs:
        streams if label == "Add source files" else original(label, *args, **kwargs))
    return original


def test_one_source_intake_stays_below_writing_and_hidden_raster_work_stops(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    editor = next(item for item in app.text_area if item.label == "Activity summary")
    editor.set_value("My direct Activity wording.").run()
    identity = editor.id
    button(app, "Manage source files").click().run()
    assert sum(item.label == "Add source files" for item in app.get("file_uploader")) == 1
    assert not any(item.label in ("Monthly source files", "Add activity files (optional)")
                   for item in app.get("file_uploader"))
    uploads(monkeypatch, (("synthetic-utility.pdf", utility_pdf()),))
    app.run()
    assert not app.exception
    assert sum(item.label == "Source date" for item in app.date_input) == 1
    editor = next(item for item in app.text_area if item.label == "Activity summary")
    assert editor.id == identity and editor.value == "My direct Activity wording."
    assert list(app.main).index(editor) < list(app.main).index(select(app, "File to review"))
    assert not next(block for block in current_draft(app).blocks if block.key == "activity_summary").references
    button(app, "Done with source files").click().run()
    source = current_draft(app).sources[0]
    field_id = next(item for item in app.date_input if source.id in item.key).id
    original_page_image = ui.sources.page_image
    def forbidden(*args, **kwargs):
        import inspect
        assert not any(frame.function == "render_uploads" for frame in inspect.stack()), (
            "A closed source manager must not rasterize its source page.")
        return original_page_image(*args, **kwargs)
    monkeypatch.setattr(ui.sources, "page_image", forbidden)
    app.run()
    assert not app.exception
    assert next(item for item in app.date_input if source.id in item.key).id == field_id
    assert any("_source_manager_panel{display:none" in item.value for item in app.markdown)


def test_switching_sources_captures_old_caption_and_keeps_each_form_identity(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    button(app, "Manage source files").click().run()
    uploads(monkeypatch, (("synthetic-utility.pdf", utility_pdf()), ("synthetic-service.pdf", pdf_bytes(1))))
    app.run()
    assert not app.exception
    draft = current_draft(app)
    first, second = draft.sources
    first_date = next(item for item in app.date_input if first.id in item.key)
    second_date = next(item for item in app.date_input if second.id in item.key)
    ids = first_date.id, second_date.id
    first_date.set_value(date(2026, 9, 27))
    next(item for item in app.text_input if item.label == "Page caption").set_value("Delivered with file selection")
    select(app, "File to review").set_value(second.id).run()
    assert not app.exception
    current = current_draft(app)
    assert dict(current.sources[0].captions)[1] == "Delivered with file selection"
    assert dict(current.sources[1].captions).get(1) != "Delivered with file selection"
    assert current.sources[0].service_date == first.service_date, "A separate file click must not submit a metadata form."
    assert (next(item for item in app.date_input if first.id in item.key).id,
            next(item for item in app.date_input if second.id in item.key).id) == ids
    select(app, "File to review").set_value(first.id).run()
    assert next(item for item in app.date_input if first.id in item.key).value == date(2026, 9, 27)
    assert next(item for item in app.text_input if item.label == "Page caption").value == "Delivered with file selection"
    button(app, "Done with source files").click().run()
    button(app, "Manage source files").click().run()
    assert next(item for item in app.date_input if first.id in item.key).id == ids[0]
    assert next(item for item in app.date_input if first.id in item.key).value == date(2026, 9, 27)
    next(control for control in app.button if control.label == "Use these source details" and first.id in control.key).click().run()
    assert not app.exception
    assert current_draft(app).sources[0].service_date == "2026-09-27"
    assert current_draft(app).sources[1].service_date == second.service_date
    # AppTest proves the stable native identity and submit boundary. The live
    # browser journey separately covers a genuinely browser-only form buffer.


def test_source_correction_survives_a_design_without_activity(monkeypatch, tmp_path):
    from dataclasses import replace
    from streamlit.testing.v1 import AppTest
    from app.monthly_report_model import ReportDraft, ReportPeriod, SectionSpec, synthetic_profiles
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = ui.sources.ingest(profile, "synthetic-other-section.txt", b"Source content for another section.")
    content = replace(content, source=replace(content.source, facility="", service_date=""))
    app = AppTest.from_string('''
import streamlit as st
from dataclasses import replace
from app.monthly_report_source_manager_ui import render_guided_source_manager
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state["_monthly_source_detail_forms"] = {}
st.session_state["_monthly_source_details_managed"] = True
draft = st.session_state["current"]
draft, blocks = render_guided_source_manager(draft, {b.key:b for b in draft.blocks}, "custom", field,
    lambda draft, blocks, additions, specs, prefix: (draft, blocks), lambda prefix, sources: sources)
st.session_state["current"] = replace(draft, blocks=tuple(blocks.values()))
''')
    app.session_state["current"] = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic editor",
        (SectionSpec("scorecards", "3", "Scorecards", ()),), (), sources=(content.source,))
    app.session_state["custom_evidence"] = (content,)
    app.run()
    button(app, "Manage source files").click().run()
    assert not app.exception
    assert sum(item.label == "Source date" for item in app.date_input) == 1
    next(item for item in app.date_input if item.label == "Source date").set_value(date(2026, 9, 20))
    select(app, "Source facility").set_value(profile.facilities[0].key)
    button(app, "Use these source details").click().run()
    assert not app.exception
    assert app.session_state["current"].sources[0].service_date == "2026-09-20"
    assert app.session_state["current"].blocks == ()
    assert ui.sources.source_bytes(profile, app.session_state["current"].sources[0]) == b"Source content for another section."
