"""Water pages attach after the final deliberate review, never merely on rerender."""

import fitz

from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_allowed
from app.monthly_report_saved_pictures_ui import remove_saved_picture
from test_monthly_report_section_uploads import button, section_app
from test_monthly_report_sources import pdf_bytes


def _water_app(monkeypatch, tmp_path, raw):
    # The same binary uploader is used by the real Water Treatment editor.
    app = section_app(monkeypatch, tmp_path, raw, label="Water-treatment files")
    next(w for w in app.radio if w.label == "Section").set_value("water_reports").run()
    assert not app.exception
    assert not any(w.label == "Add reviewed pages" for w in app.button)
    return app


def test_water_only_includes_after_final_page_decision(monkeypatch, tmp_path):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(2))
    button(app, "Include page").click().run()
    assert not app.exception
    assert "water_reports" not in app.session_state["test_blocks"]
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 2

    # Completing the final decision automatically adds only the page kept.
    button(app, "Exclude page").click().run()
    assert not app.exception
    included = app.session_state["test_blocks"]["water_reports"]
    source = app.session_state["test_sources"][0]
    assert source.selected_pages == (1,)
    assert len(included.asset_hashes) == 1
    assert len(included.references) == 1
    assert app.session_state["test_apply_count"] == 1
    assert page_allowed(source, 1)
    assert not page_allowed(source, 2)

    app.run()
    assert not app.exception
    assert app.session_state["test_apply_count"] == 1
    assert len(app.session_state["test_blocks"]["water_reports"].asset_hashes) == 1
    assert "synthetic_evidence_section_water_reports_auto_include" not in app.session_state.filtered_state


def test_removing_an_included_water_page_never_readds_it(monkeypatch, tmp_path):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(1))
    button(app, "Include page").click().run()
    assert not app.exception
    assert app.session_state["test_apply_count"] == 1
    app.run()  # Ensure the exact accepted review receipt is consumed.

    original = app.session_state["test_blocks"]["water_reports"]
    assert len(original.asset_hashes) == 1
    app.session_state["test_blocks"]["water_reports"] = remove_saved_picture(original, 0)
    app.run()
    assert not app.exception
    assert not app.session_state["test_blocks"]["water_reports"].asset_hashes
    assert app.session_state["test_apply_count"] == 1

    # A refresh cannot turn a previously reviewed source into an automatic
    # re-import. Re-including requires a NEW explicit Include page action.
    app.run()
    assert not app.session_state["test_blocks"]["water_reports"].asset_hashes
    assert app.session_state["test_apply_count"] == 1
    button(app, "Include page").click().run()
    assert len(app.session_state["test_blocks"]["water_reports"].asset_hashes) == 1
    assert app.session_state["test_apply_count"] == 2


def test_changed_caption_requires_new_water_review_before_auto_add(monkeypatch, tmp_path):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(2))
    button(app, "Include page").click().run()
    pages = next(w for w in app.selectbox if w.label == "Page to review")
    pages.set_value(1).run()
    next(w for w in app.text_input if w.label == "Page caption").set_value(
        "New caption requiring review"
    ).run()
    assert not page_allowed(app.session_state["test_sources"][0], 1)

    pages = next(w for w in app.selectbox if w.label == "Page to review")
    pages.set_value(2).run()
    button(app, "Exclude page").click().run()
    assert "water_reports" not in app.session_state["test_blocks"]
    assert app.session_state.filtered_state.get("test_apply_count", 0) == 0

    pages = next(w for w in app.selectbox if w.label == "Page to review")
    pages.set_value(1).run()
    button(app, "Include page").click().run()
    assert not app.exception
    assert len(app.session_state["test_blocks"]["water_reports"].asset_hashes) == 1
    assert app.session_state["test_apply_count"] == 1


def test_rejected_price_page_never_auto_enters_water(monkeypatch, tmp_path):
    with fitz.open() as pdf:
        p = pdf.new_page()
        p.insert_text((48, 60), "Chemical service report, invoice amount $1,250.00.")
        priced = pdf.tobytes()
    app = _water_app(monkeypatch, tmp_path, priced)
    assert button(app, "Include page").disabled
    button(app, "Exclude page").click().run()
    assert not app.exception
    assert "water_reports" not in app.session_state["test_blocks"]
    assert app.session_state.filtered_state.get("test_apply_count", 0) == 0


def test_preparation_failure_keeps_review_and_requires_explicit_retry(monkeypatch, tmp_path):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(1))
    original = sources.prepare_pages
    def fail(*args, **kwargs):
        raise ValueError("Synthetic page preparation failure")
    monkeypatch.setattr(sources, "prepare_pages", fail)

    button(app, "Include page").click().run()
    assert not app.exception
    assert any("Synthetic page preparation failure" in w.value for w in app.error)
    assert "water_reports" not in app.session_state["test_blocks"]
    app.run()
    assert any(b.label == "Retry including reviewed pages" for b in app.button)
    assert "water_reports" not in app.session_state["test_blocks"]

    monkeypatch.setattr(sources, "prepare_pages", original)
    button(app, "Retry including reviewed pages").click().run()
    assert not app.exception
    assert len(app.session_state["test_blocks"]["water_reports"].asset_hashes) == 1
    assert app.session_state["test_apply_count"] == 1
