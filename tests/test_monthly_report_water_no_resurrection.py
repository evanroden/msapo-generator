"""A newly reviewed Water page may not resurrect an earlier deliberate removal."""

import pytest

from app.monthly_report_saved_pictures_ui import remove_saved_picture
from app.monthly_report_section_uploads import page_identity, prepare_section_pages
from app.monthly_report_sources import source_reference
from test_monthly_report_section_uploads import (
    button, reviewed_content, section_app,
)
from test_monthly_report_sources import pdf_bytes


def _water_app(monkeypatch, tmp_path, pages):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(pages), label="Water-treatment files")
    next(w for w in app.radio if w.label == "Section").set_value("water_reports").run()
    assert not app.exception
    return app


def _open_page_review(app):
    if not any(w.label == "Page to review" for w in app.selectbox):
        button(app, "Report pages").click().run()
    assert any(w.label == "Page to review" for w in app.selectbox)


def test_only_exact_explicit_pages_are_prepared_with_original_source_fingerprint(
        monkeypatch, tmp_path):
    profile, content = reviewed_content(monkeypatch, tmp_path, pages=2)
    assert content.source.selected_pages == (1, 2)
    requested = frozenset({(content.source.id, 2)})
    prepared = prepare_section_pages(
        profile, (content,), "water_reports", {}, only_pages=requested)
    block = prepared["water_reports"]
    assert len(block.asset_hashes) == len(block.references) == 1
    assert block.references == (source_reference(content.source, 2),)
    assert page_identity(block.references[0]) == (content.source.id, 2)
    assert content.source.selected_pages == (1, 2), "The canonical source must not be truncated"

    with pytest.raises(ValueError, match="selection changed"):
        prepare_section_pages(profile, (content,), "water_reports", {},
                              only_pages=frozenset({(content.source.id, 3)}))


def test_new_water_review_does_not_resurrect_prior_removed_page(
        monkeypatch, tmp_path):
    app = _water_app(monkeypatch, tmp_path, pages=2)
    button(app, "Include page").click().run()
    button(app, "Exclude page").click().run()
    assert not app.exception
    included = app.session_state["test_blocks"]["water_reports"]
    assert tuple(page_identity(ref)[1] for ref in included.references) == (1,)
    assert app.session_state["test_apply_count"] == 1
    # Unlike the deployed guided editor, this minimal AppTest wrapper waits
    # until its next rerun to consume the successful auto-include receipt.
    # Ack the preceding merge before simulating a later operator removal.
    app.run()
    assert "synthetic_evidence_section_water_reports_auto_include" not in app.session_state.filtered_state

    # The source is preserved; only its report page is deliberately removed.
    app.session_state["test_blocks"]["water_reports"] = remove_saved_picture(included, 0)
    app.run()
    assert not app.exception
    assert not app.session_state["test_blocks"]["water_reports"].asset_hashes
    assert app.session_state["test_sources"][0].selected_pages == (1,)

    # Now explicitly include the *other* page, formerly excluded.
    _open_page_review(app)
    next(w for w in app.selectbox if w.label == "Page to review").set_value(2).run()
    button(app, "Include page").click().run()
    assert not app.exception
    after = app.session_state["test_blocks"]["water_reports"]
    assert len(after.asset_hashes) == 1
    assert tuple(page_identity(ref)[1] for ref in after.references) == (2,)
    assert app.session_state["test_apply_count"] == 2
    app.run()
    assert tuple(page_identity(ref)[1] for ref in
                 app.session_state["test_blocks"]["water_reports"].references) == (2,)

    # Page 1 comes back only after a *new* explicit Include click for page 1.
    _open_page_review(app)
    next(w for w in app.selectbox if w.label == "Page to review").set_value(1).run()
    button(app, "Include page").click().run()
    assert not app.exception
    restored = app.session_state["test_blocks"]["water_reports"]
    assert len(restored.asset_hashes) == 2
    assert set(page_identity(ref)[1] for ref in restored.references) == {1, 2}
    assert app.session_state["test_apply_count"] == 3
