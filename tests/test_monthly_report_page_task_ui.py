"""Source-page decisions and corrections keep one canonical metadata owner."""
from datetime import date
from io import BytesIO

from app import monthly_report_active_work as active, monthly_report_sources as sources
from app import monthly_report_testing as qa, monthly_report_qa_fixture as fixture
from app.monthly_report_editor import _signature
from test_monthly_report_qa_ui import ACTOR_COOKIE, visit
from test_monthly_report_source_workspace_geometry import _water_source, _path
from test_monthly_report_water_compact import water_app


def _button(app, label):
    matches = [item for item in app.button if item.label == label]
    assert len(matches) == 1, (label, [x.label for x in app.button])
    return matches[0]


def test_page_decisions_name_the_item_and_make_automatic_advance_visible(monkeypatch, tmp_path):
    app = water_app(monkeypatch, tmp_path, 2)
    assert any("After each decision, the next unreviewed page opens" in x.value for x in app.caption)
    _button(app, "Include page").click().run()
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 2
    _button(app, "Exclude page").click().run()
    app.run()
    assert len(app.session_state["test_blocks"]["water_reports"].asset_hashes) == 1
    _button(app, "Report pages").click().run()
    _button(app, "Close report pages").click().run()
    assert not any(w.label == "Page to review" for w in app.selectbox)


def test_water_correction_opens_matching_page_beside_the_existing_form(monkeypatch, tmp_path):
    app = visit(monkeypatch, tmp_path)
    _button(app, "Load known-value report").click().run()
    prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
    raw = _water_source()
    stream = BytesIO(raw); stream.name = "Synthetic water treatment.pdf"
    import streamlit as st
    native = st.file_uploader
    def selected(label, *args, **kwargs):
        result = native(label, *args, **kwargs)
        return [stream] if label == "Water-treatment files" else result
    monkeypatch.setattr(st, "file_uploader", selected)
    app.run()
    include = _button(app, "Include page")
    include.click().run()
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 2
    source, = app.session_state[prefix + "_draft"].sources
    date_field, = [w for w in app.date_input if w.label == "Source date"]
    identity = date_field.id
    date_path = _path(app._tree, date_field)
    captions = [w for w in app.text_input if w.label == "Page caption"
                and "_evidence_section_water_reports_" in w.key]
    assert len(captions) == 1
    captions[0].set_value("A deliberate second-page caption.")
    _button(app, "Correct source details").click().run()
    assert not app.exception
    assert app.session_state[prefix + "_batch_files_open"] is True
    assert app.session_state[prefix + "_evidence_selected"] == source.id
    assert not any(w.label == "Preview page / item" for w in app.selectbox)
    assert sum(w.label == "Source date" for w in app.date_input) == 1
    assert next(w for w in app.date_input if w.label == "Source date").id == identity
    assert _path(app._tree, next(w for w in app.date_input if w.label == "Source date")) == date_path
    details, = [x for x in app.expander if source.filename in x.label]
    assert len(details.get("image")) == 1
    assert any("Source page 2 of 2" == x.value for x in app.caption)
    assert not any(w.label == "File details (optional)" for w in app.expander)
    assert sum(w.label == "Vendor" and source.id in w.key for w in app.text_input) == 1
    current = app.session_state[prefix + "_draft"]
    assert dict(current.sources[0].captions)[2] == "A deliberate second-page caption."
    date_field = next(w for w in app.date_input if w.label == "Source date")
    date_field.set_value(date(2026, 9, 18))
    _button(app, "Use these source details").click().run()
    assert not app.exception
    current = app.session_state[prefix + "_draft"]
    assert current.sources[0].service_date == "2026-09-18"
    assert dict(current.sources[0].captions)[2] == "A deliberate second-page caption."
    with qa.isolated(ACTOR_COOKIE):
        journal = active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        assert journal.draft.fingerprint == current.fingerprint
        assert sources.source_bytes(fixture.profile(), current.sources[0]) == raw
    _button(app, "Open report pages").click().run()
    assert app.session_state[prefix + "_batch_files_open"] is False
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 2
    assert _button(app, "Include page")
    assert next(w for w in app.text_input if w.label == "Page caption").value == "A deliberate second-page caption."
    assert app.session_state[prefix + "_draft"].fingerprint == current.fingerprint


def test_page_caption_acknowledgement_cannot_approve_other_source_changes(monkeypatch):
    from dataclasses import replace
    from app.monthly_report_model import ReportSource
    from app import monthly_report_upload_ui as ui
    source = ReportSource("synthetic", "invented.pdf", "a" * 64, ".pdf", service_date="2026-09-17")
    key = "test_evidence_synthetic_source_details_baseline"
    for changed in (replace(source, captions=((1, "Delivered caption"),), service_date="2026-09-18"),
                    replace(source, captions=((1, "Delivered caption"),), sha256="b" * 64)):
        state = {"_monthly_source_details_managed": True,
                 "_monthly_source_detail_forms": {source.id: source}, key: source.fingerprint}
        monkeypatch.setattr(ui.st, "session_state", state)
        ui._acknowledge_managed_page_edit(source, changed, "test")
        assert state[key] == source.fingerprint
    state[key] = "another revision"
    ui._acknowledge_managed_page_edit(source, replace(source, captions=((1, "Caption"),)), "test")
    assert state[key] == "another revision"


def test_compact_water_keeps_replacement_inside_its_report_pages_task(monkeypatch, tmp_path):
    app = visit(monkeypatch, tmp_path)
    _button(app, "Load known-value report").click().run()
    prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
    stream = BytesIO(_water_source()); stream.name = "Synthetic water treatment.pdf"
    import streamlit as st
    native = st.file_uploader
    def selected(label, *args, **kwargs):
        result = native(label, *args, **kwargs)
        return [stream] if label == "Water-treatment files" else result
    monkeypatch.setattr(st, "file_uploader", selected)
    app.run()
    _button(app, "Include page").click().run()
    _button(app, "Include page").click().run()
    app.run()
    assert not app.exception
    action_style = ".st-key-" + prefix + "_edit_water_reports_page_replacement_actions{display:"
    assert any(action_style + "none" in x.value for x in app.markdown)
    before = app.session_state[prefix + "_draft"].fingerprint
    replacement, = [w for w in app.get("file_uploader") if w.label == "Replacement image for Water treatment reports"]
    identity = replacement.id
    _button(app, "Report pages").click().run()
    assert any(action_style + "block" in x.value for x in app.markdown)
    assert next(w for w in app.get("file_uploader") if w.label == replacement.label).id == identity
    _button(app, "Close report pages").click().run()
    assert any(action_style + "none" in x.value for x in app.markdown)
    assert app.session_state[prefix + "_draft"].fingerprint == before


def test_delivered_source_widget_identity_rejects_a_stale_or_external_revision(monkeypatch):
    from dataclasses import replace
    from app.monthly_report_model import ReportSource
    from app import monthly_report_upload_ui as ui
    old = ReportSource("synthetic", "invented.pdf", "a" * 64, ".pdf", vendor="Before")
    new = replace(old, vendor="Delivered correction")
    state = {"_monthly_source_details_managed": True, "section_canonical_view": old}
    monkeypatch.setattr(ui.st, "session_state", state)
    assert ui._page_widget_source(new, "section", "report") == new
    ui._remember_delivered_source_edit("report", old, new)
    assert ui._page_widget_source(new, "section", "report") == old
    state["section_canonical_view"] = replace(old, service_date="2026-08-03")
    assert ui._page_widget_source(new, "section", "report") == new
    state["section_canonical_view"] = old
    assert ui._page_widget_source(replace(new, sha256="b" * 64), "section", "report") != old
