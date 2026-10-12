"""Previously included Water pages stay compact; new or changed ones remain visible."""

from dataclasses import replace

from app.monthly_report_content_policy import page_allowed
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
    assert any("1 page included in this draft" in item.value for item in app.get("caption"))
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
