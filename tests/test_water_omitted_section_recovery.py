"""Retained omitted pages need deliberate section-scoped re-inclusion."""
from dataclasses import replace

import pytest

from app.monthly_report_asset_review import pending_asset_indexes
from app.monthly_report_content_policy import page_allowed
from app.monthly_report_model import ReportTable
from test_monthly_report_page_manager import _prepared
from test_monthly_report_section_uploads import button
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_water_auto_include import _water_app


def omitted_app(monkeypatch, tmp_path, *, pending=False):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(2))
    button(app, "Include page and continue").click().run()
    button(app, "Include page and continue").click().run()
    app.run()
    original = app.session_state["test_blocks"]["water_reports"]
    omitted = replace(original, source="Omit", text="Retained operating note.",
                      extra_tables=(ReportTable(("Operational finding",), (("Keep this table",),)),))
    app.session_state["test_blocks"]["water_reports"] = omitted
    if pending:
        content = app.session_state["synthetic_evidence"][0]
        source = replace(content.source, client_page_reviews=())
        app.session_state["synthetic_evidence"] = (replace(content, source=source),)
    app.run()
    assert not app.exception
    return app, omitted


def test_opening_omitted_water_reports_zero_included_without_changing_retained_content(monkeypatch, tmp_path):
    app, omitted = omitted_app(monkeypatch, tmp_path)
    sources = app.session_state["test_sources"]
    assert any(item.value == "**Report pages (0)**" for item in app.markdown)
    assert not any("included in this draft" in item.value for item in app.caption)
    button(app, "Edit pages").click().run()
    assert not any(item.value.startswith("Included in this report") for item in app.caption)
    button(app, "Done reviewing pages").click().run()
    app.run()
    assert app.session_state["test_blocks"]["water_reports"] == omitted
    assert app.session_state["test_sources"] == sources


def test_reviewing_one_omitted_page_cannot_restore_other_pages_or_native_content(monkeypatch, tmp_path):
    app, omitted = omitted_app(monkeypatch, tmp_path, pending=True)
    assert button(app, "Include Water treatment section in this report").disabled
    # Omitted source pages whose reviews were invalidated open directly.
    next(w for w in app.selectbox if w.label == "Page to review").set_value(1).run()
    button(app, "Review retained page and continue").click().run()
    actual = app.session_state["test_blocks"]["water_reports"]
    source = app.session_state["test_sources"][0]
    assert actual.source == "Omit" and actual.asset_hashes == omitted.asset_hashes
    assert actual.text == omitted.text
    assert actual.extra_tables == omitted.extra_tables
    assert page_allowed(source, 1) and not page_allowed(source, 2)
    assert button(app, "Include Water treatment section in this report").disabled


def test_explicit_section_reinclusion_restores_all_retained_content_after_review(monkeypatch, tmp_path):
    from app.monthly_report_sources import source_bytes
    app, omitted = omitted_app(monkeypatch, tmp_path)
    source = app.session_state["test_sources"][0]
    from app.monthly_report_model import synthetic_profiles
    original = source_bytes(synthetic_profiles()[0], source)
    assert any("all 2 retained pages and any retained wording or tables" in c.value for c in app.caption)
    button(app, "Include Water treatment section in this report").click().run()
    assert not app.exception
    actual = app.session_state["test_blocks"]["water_reports"]
    assert actual.source == "This month"
    assert actual.asset_hashes == omitted.asset_hashes
    assert actual.asset_captions == omitted.asset_captions
    assert actual.text == omitted.text
    assert actual.extra_tables == omitted.extra_tables
    assert pending_asset_indexes(actual, app.session_state["test_sources"]) == ()
    assert source_bytes(synthetic_profiles()[0], source) == original
    app.run()
    assert not any(b.label == "Include Water treatment section in this report" for b in app.button)
    assert app.session_state["test_blocks"]["water_reports"] == actual


def test_newly_submitted_caption_cannot_bypass_section_review_gate(monkeypatch, tmp_path):
    app, omitted = omitted_app(monkeypatch, tmp_path)
    button(app, "Edit pages").click().run()
    next(w for w in app.text_input if w.label == "Page caption").set_value("Late caption edit")
    button(app, "Include Water treatment section in this report").click().run()
    actual = app.session_state["test_blocks"]["water_reports"]
    assert actual.source == "Omit" and actual.asset_hashes == omitted.asset_hashes
    assert "Late caption edit" in actual.asset_captions
    assert any("changed after" in warning.value for warning in app.warning)
    assert button(app, "Include Water treatment section in this report").disabled


def test_omitted_section_keeps_native_content_after_removing_all_retained_pages(monkeypatch, tmp_path):
    app, omitted = omitted_app(monkeypatch, tmp_path)
    button(app, "Edit pages").click().run()
    for number in (1, 2):
        next(w for w in app.selectbox if w.label == "Page to review").set_value(number).run()
        button(app, "Remove retained page from this section").click().run()
    actual = app.session_state["test_blocks"]["water_reports"]
    assert actual.source == "Omit" and not actual.asset_hashes
    assert actual.text == omitted.text and actual.extra_tables == omitted.extra_tables
    assert button(app, "Include page and continue").disabled
    button(app, "Include Water treatment section in this report").click().run()
    actual = app.session_state["test_blocks"]["water_reports"]
    assert actual.source == "This month" and not actual.asset_hashes
    assert actual.text == omitted.text and actual.extra_tables == omitted.extra_tables


def test_old_auto_inclusion_cannot_replace_an_omitted_sections_retained_content(monkeypatch, tmp_path):
    from app.monthly_report_saved_pictures_ui import remove_saved_picture
    app, omitted = omitted_app(monkeypatch, tmp_path)
    retained = remove_saved_picture(omitted, 1)
    app.session_state["test_blocks"]["water_reports"] = retained
    source = app.session_state["test_sources"][0]
    request_key = "synthetic_evidence_section_water_reports_auto_include"
    app.session_state[request_key] = {"source_id": source.id, "fingerprint": source.fingerprint, "pages": (2,)}
    count = app.session_state["test_apply_count"]
    app.run()
    assert app.session_state["test_blocks"]["water_reports"] == retained
    assert app.session_state["test_apply_count"] == count
    assert request_key not in app.session_state.filtered_state
    button(app, "Edit pages").click().run()
    next(w for w in app.selectbox if w.label == "Page to review").set_value(2).run()
    assert button(app, "Include page and continue").disabled
    button(app, "Include Water treatment section in this report").click().run()
    actual = app.session_state["test_blocks"]["water_reports"]
    assert actual.source == "This month" and actual.asset_hashes == retained.asset_hashes
    assert actual.text == omitted.text and actual.extra_tables == omitted.extra_tables


@pytest.mark.parametrize("changed", ["block", "source", "incarnation"])
def test_section_reinclusion_cannot_apply_an_old_action_to_newer_content(monkeypatch, tmp_path, changed):
    from app.monthly_report_page_controls import omitted_section_request, apply_omitted_section_request
    _, content, block = _prepared(monkeypatch, tmp_path)
    block = replace(block, source="Omit")
    request = omitted_section_request(block, (content,))
    if changed == "block":
        block = replace(block, text="Newer retained wording")
    elif changed == "source":
        content = replace(content, source=replace(content.source, vendor="Corrected vendor"))
    with pytest.raises(ValueError, match="changed after"):
        apply_omitted_section_request((content,), {block.key: block}, request,
                                     scope="new-incarnation" if changed == "incarnation" else "")
    assert block.source == "Omit"


@pytest.mark.parametrize("unready", ["page-review", "picture-review", "selection", "ambiguous"])
def test_section_reinclusion_keeps_all_content_omitted_until_every_retained_page_is_ready(monkeypatch, tmp_path, unready):
    from app.monthly_report_page_controls import omitted_section_request, apply_omitted_section_request
    _, content, block = _prepared(monkeypatch, tmp_path)
    block = replace(block, source="Omit")
    if unready == "page-review":
        content = replace(content, source=replace(content.source,
            client_page_reviews=tuple(item for item in content.source.client_page_reviews if item[0] != 2)))
    elif unready == "picture-review":
        block = replace(block, client_asset_reviews=block.client_asset_reviews[:1], client_reviewed_fingerprint="")
    elif unready == "selection":
        content = replace(content, source=replace(content.source, selected_pages=(1,)))
    else:
        block = replace(block, asset_provenance=tuple((asset, block.references) for asset in block.asset_hashes))
    request = omitted_section_request(block, (content,))
    with pytest.raises(ValueError, match="Review every retained page"):
        apply_omitted_section_request((content,), {block.key: block}, request)
    assert block.source == "Omit" and len(block.asset_hashes) == 2
