"""Previously included Water pages stay compact; new or changed ones remain visible."""

from dataclasses import replace
from datetime import date
from io import BytesIO

import fitz

from app import monthly_report_sources as sources, monthly_report_upload_ui as ui
from app.monthly_report_content_policy import page_allowed
from app.monthly_report_model import synthetic_profiles
from test_monthly_report_section_uploads import button, section_app
from test_monthly_report_sources import pdf_bytes


def water_app(monkeypatch, tmp_path, pages):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(pages),
                      label="Water-treatment files")
    next(w for w in app.radio if w.label == "Section").set_value("water_reports").run()
    assert not app.exception
    return app


def test_included_water_page_has_compact_status_and_explicit_edit(monkeypatch, tmp_path):
    app = water_app(monkeypatch, tmp_path, 1)
    button(app, "Include page and continue").click().run()
    assert not app.exception
    app.run()
    block = app.session_state["test_blocks"]["water_reports"]
    before = block.fingerprint
    assert len(block.asset_hashes) == 1
    assert sum(item.value == "**Report pages (1)**" for item in app.markdown) == 1
    assert not any("included in this draft" in item.value for item in app.get("caption"))
    assert not any(w.label == "Page to review" for w in app.selectbox)
    assert not any(w.label == "Add reviewed pages" for w in app.button)
    assert button(app, "Edit pages")

    button(app, "Edit pages").click().run()
    assert not app.exception
    assert any(w.label == "Page to review" for w in app.selectbox)
    assert button(app, "Done reviewing pages")
    assert app.session_state["test_blocks"]["water_reports"].fingerprint == before

    button(app, "Done reviewing pages").click().run()
    assert not app.exception
    assert not any(w.label == "Page to review" for w in app.selectbox)
    assert app.session_state["test_blocks"]["water_reports"].fingerprint == before
    assert app.session_state["test_apply_count"] == 1


def test_resolved_water_summary_hides_file_forms_until_its_one_editor_reopens(monkeypatch, tmp_path):
    app = water_app(monkeypatch, tmp_path, 1)
    next(w for w in app.date_input if w.label == "Source date").set_value(date(2026, 9, 16))
    next(w for w in app.selectbox if w.label == "Source facility").set_value("north")
    button(app, "Use these source details").click().run()
    button(app, "Include page and continue").click().run()
    app.run()
    before = app.session_state["test_blocks"]["water_reports"]
    source = app.session_state["test_sources"][0]
    original = sources.source_bytes(synthetic_profiles()[0], source)
    assert not any(w.label == "Source date" for w in app.date_input)
    assert not any(w.label == "File details (optional)" for w in app.expander)
    assert not any("Reviewing " in item.value for item in app.get("caption"))
    assert sum(item.value == source.filename for item in app.get("caption")) == 1

    button(app, "Edit pages").click().run()
    assert next(w for w in app.date_input if w.label == "Source date").value == date(2026, 9, 16)
    assert next(w for w in app.selectbox if w.label == "Source facility").value == "north"
    assert any(w.label == "File details (optional)" for w in app.expander)
    assert any(w.label == "Page caption" for w in app.text_input)
    button(app, "Done reviewing pages").click().run()
    assert not app.exception
    assert app.session_state["test_blocks"]["water_reports"] == before
    assert app.session_state["test_sources"][0] == source
    assert sources.source_bytes(synthetic_profiles()[0], source) == original
    assert not any(w.label == "Source date" for w in app.date_input)
    assert button(app, "Edit pages")


def test_unreviewed_water_page_remains_visible_until_final_decision(monkeypatch, tmp_path):
    app = water_app(monkeypatch, tmp_path, 2)
    button(app, "Include page and continue").click().run()
    assert not app.exception
    assert "water_reports" not in app.session_state["test_blocks"]
    assert any(w.label == "Page to review" for w in app.selectbox)
    assert not any(w.label == "Edit pages" for w in app.button)
    button(app, "Leave page out and continue").click().run()
    assert not app.exception
    assert app.session_state["test_apply_count"] == 1
    app.run()
    assert not any(w.label == "Page to review" for w in app.selectbox)


def test_changed_included_water_source_never_hides_required_review(monkeypatch, tmp_path):
    app = water_app(monkeypatch, tmp_path, 1)
    button(app, "Include page and continue").click().run()
    app.run()
    assert not any(w.label == "Page to review" for w in app.selectbox)

    content = app.session_state["synthetic_evidence"][0]
    source = replace(content.source, captions=((1, "Changed caption requiring review"),))
    assert not page_allowed(source, 1)
    app.session_state["synthetic_evidence"] = (replace(content, source=source),)
    app.run()
    assert not app.exception
    assert any(w.label == "Page to review" for w in app.selectbox)
    assert any("changed since its review" in w.value for w in app.warning)
    assert len(app.session_state["test_blocks"]["water_reports"].asset_hashes) == 1
    assert app.session_state["test_apply_count"] == 1


def test_finished_file_names_and_opens_the_next_unreviewed_file(monkeypatch, tmp_path):
    app = water_app(monkeypatch, tmp_path, 1)
    button(app, "Include page and continue").click().run()
    app.run()
    first = app.session_state["test_sources"][0]
    before = app.session_state["test_blocks"]["water_reports"].fingerprint
    with fitz.open(stream=pdf_bytes(2), filetype="pdf") as document:
        # Make the second file's included image genuinely different. The
        # ordinary PDF helper otherwise repeats the first file's exact page.
        document[0].insert_text((50, 90), "A distinct synthetic second-file inspection.")
        second_raw = document.tobytes()
    uploads = []
    for name, raw in ((first.filename, sources.source_bytes(synthetic_profiles()[0], first)),
                      ("synthetic-second.pdf", second_raw)):
        stream = BytesIO(raw)
        stream.name = name
        uploads.append(stream)
    monkeypatch.setattr(ui.st, "file_uploader", lambda name, **kwargs: uploads)
    app.run()
    assert not app.exception
    assert not any(w.label == "Page to review" for w in app.selectbox)
    assert any(w.value == "synthetic-second.pdf: 2 pages need review."
               for w in app.get("caption"))
    button(app, "Review synthetic-second.pdf").click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label == "File to review").value != first.id
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 1
    assert app.session_state["test_blocks"]["water_reports"].fingerprint == before
    assert app.session_state["test_apply_count"] == 1
    # The shortcut opens the ordinary native review; it never approves pages.
    assert not any(w.label.startswith("Review synthetic-") for w in app.button)
    button(app, "Include page and continue").click().run()
    button(app, "Leave page out and continue").click().run()
    app.run()
    assert app.session_state["test_apply_count"] == 2
    assert len(app.session_state["test_blocks"]["water_reports"].asset_hashes) == 2
    assert not any("need review" in w.value or "remaining pages" in w.value
                   for w in app.get("caption"))


def test_reviewed_removed_page_does_not_prompt_review_or_restore_itself(monkeypatch, tmp_path):
    app = water_app(monkeypatch, tmp_path, 1)
    button(app, "Include page and continue").click().run()
    app.run()
    # A report-only removal can retain the original source's reviewed selection.
    # Reopening is not a new Include action and must not suggest unfinished review.
    app.session_state["test_blocks"] = {}
    app.run()
    assert not app.exception
    assert page_allowed(app.session_state["test_sources"][0], 1)
    assert app.session_state["test_sources"][0].selected_pages == (1,)
    assert app.session_state["test_blocks"] == {}
    assert app.session_state["test_apply_count"] == 1
    assert not any("remaining pages" in w.value for w in app.get("caption"))
    assert not any(w.label.startswith("Review synthetic-") for w in app.button)
