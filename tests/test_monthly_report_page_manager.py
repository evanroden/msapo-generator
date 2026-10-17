"""Canonical Water page changes must not require a second picture editor."""
from dataclasses import replace

from test_monthly_report_water_auto_include import _water_app
from test_monthly_report_section_uploads import button
from test_monthly_report_sources import pdf_bytes


def test_included_water_removal_is_in_the_same_page_reviewer(monkeypatch, tmp_path):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(1))
    button(app, "Include page and continue").click().run()
    app.run()
    original = app.session_state["test_blocks"]["water_reports"]
    assert len(original.asset_hashes) == 1
    button(app, "Edit pages").click().run()
    assert not app.exception
    assert any(b.label == "Leave page out and continue" for b in app.button), (
        "Removing an included page requires a second picture editor.")
    button(app, "Leave page out and continue").click().run()
    assert not app.exception
    assert not app.session_state["test_blocks"]["water_reports"].asset_hashes
    source = app.session_state["test_sources"][0]
    assert source.selected_pages == ()
    assert 1 in dict(source.client_page_exclusions)
    app.run()
    assert not app.session_state["test_blocks"]["water_reports"].asset_hashes
    assert app.session_state["test_apply_count"] == 1
    button(app, "Include page and continue").click().run()
    assert len(app.session_state["test_blocks"]["water_reports"].asset_hashes) == 1
    assert app.session_state["test_apply_count"] == 2


def _prepared(monkeypatch, tmp_path, pages=2):
    from test_monthly_report_section_uploads import reviewed_content
    from app.monthly_report_section_uploads import prepare_section_pages
    profile, content = reviewed_content(monkeypatch, tmp_path, pages)
    block = prepare_section_pages(profile, (content,), "water_reports", {})["water_reports"]
    return profile, content, block


def test_caption_and_review_change_only_the_selected_page(monkeypatch, tmp_path):
    from app.monthly_report_page_controls import revise_included_page
    from app.monthly_report_asset_review import pending_asset_indexes
    from app.monthly_report_content_policy import page_allowed
    from app.monthly_report_sources import source_bytes
    profile, content, block = _prepared(monkeypatch, tmp_path)
    raw = source_bytes(profile, content.source)
    updated, source = revise_included_page(block, content.source, 1, "caption", caption="Updated treatment caption", all_sources=(content.source,))
    assert updated.asset_captions[0] == "Updated treatment caption"
    assert not page_allowed(source, 1) and page_allowed(source, 2)
    assert pending_asset_indexes(updated) == (0,)
    approved, source = revise_included_page(updated, source, 1, "review", all_sources=(source,))
    assert not pending_asset_indexes(approved) and page_allowed(source, 1)
    assert source_bytes(profile, source) == raw
    assert updated.asset_hashes == block.asset_hashes


def test_removed_picture_does_not_own_a_page_retained_only_as_narrative_evidence(monkeypatch, tmp_path):
    from app.monthly_report_page_controls import revise_included_page
    from app.monthly_report_section_uploads import included_pages
    _, content, block = _prepared(monkeypatch, tmp_path)
    block = replace(block, text="A report note referring to both original pages.")
    updated, source = revise_included_page(block, content.source, 1, "omit")
    assert updated.text == block.text and updated.references == block.references
    assert (source.id, 1) not in included_pages({updated.key: updated})
    assert (source.id, 2) in included_pages({updated.key: updated})
    assert source.selected_pages == (2,)


def test_order_changes_keep_captions_provenance_and_reviews(monkeypatch, tmp_path):
    from app.monthly_report_page_controls import revise_included_page
    from app.monthly_report_asset_review import pending_asset_indexes
    _, content, block = _prepared(monkeypatch, tmp_path)
    updated, source = revise_included_page(block, content.source, 2, "earlier")
    assert updated.asset_hashes == tuple(reversed(block.asset_hashes))
    assert updated.asset_captions == tuple(reversed(block.asset_captions))
    assert updated.references == block.references
    assert not pending_asset_indexes(updated)
    assert source == content.source


def test_ambiguous_artwork_keeps_its_recovery_editor(monkeypatch, tmp_path):
    import pytest
    from app.monthly_report_page_controls import source_managed_pages, revise_included_page
    _, content, block = _prepared(monkeypatch, tmp_path)
    ambiguous = replace(block, asset_provenance=tuple((a, block.references) for a in block.asset_hashes))
    assert not source_managed_pages(ambiguous, (content,))
    with pytest.raises(ValueError, match="not mapped to one source page"):
        revise_included_page(ambiguous, content.source, 1, "omit")
    assert source_managed_pages(block, (content,))
    assert not source_managed_pages(block, ())


def test_new_caption_cannot_approve_pricing(monkeypatch, tmp_path):
    import pytest
    from app.monthly_report_page_controls import revise_included_page
    from app.monthly_report_content_policy import page_allowed
    _, content, block = _prepared(monkeypatch, tmp_path)
    updated, source = revise_included_page(block, content.source, 1, "caption", caption="Invoice $500", all_sources=(content.source,))
    assert not page_allowed(source, 1)
    with pytest.raises(ValueError, match="cannot be included"):
        revise_included_page(updated, source, 1, "review", all_sources=(source,))
    assert content.source != source and block.asset_captions != updated.asset_captions


def test_stale_page_action_preserves_newer_source_and_report(monkeypatch, tmp_path):
    import pytest
    from app.monthly_report_page_controls import apply_page_request
    _, content, block = _prepared(monkeypatch, tmp_path)
    request = dict(source_id=content.source.id, source_fingerprint=content.source.fingerprint,
                   block_key=block.key, block_fingerprint=block.fingerprint, number=1, action="omit")
    changed = replace(block, text="New manual note")
    with pytest.raises(ValueError, match="changed after the action"):
        apply_page_request((content,), {block.key: changed}, request)
    new_content = replace(content, source=replace(content.source, vendor="Corrected vendor"))
    with pytest.raises(ValueError, match="changed after the action"):
        apply_page_request((new_content,), {block.key: block}, request)


def test_included_water_caption_review_and_order_use_one_editor(monkeypatch, tmp_path):
    from app.monthly_report_asset_review import pending_asset_indexes
    from app.monthly_report_content_policy import page_allowed
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(2))
    button(app, "Include page and continue").click().run()
    button(app, "Include page and continue").click().run()
    app.run()
    original = app.session_state["test_blocks"]["water_reports"]
    button(app, "Edit pages").click().run()
    next(w for w in app.selectbox if w.label == "Page to review").set_value(1).run()
    next(w for w in app.text_input if w.label == "Page caption").set_value("Updated first page").run()
    block = app.session_state["test_blocks"]["water_reports"]
    assert block.asset_captions[0] == "Updated first page"
    assert pending_asset_indexes(block) == (0,)
    assert not page_allowed(app.session_state["test_sources"][0], 1)
    button(app, "Include page and continue").click().run()
    assert not pending_asset_indexes(app.session_state["test_blocks"]["water_reports"])
    button(app, "Move page later").click().run()
    assert not app.exception
    assert app.session_state["test_blocks"]["water_reports"].asset_hashes == tuple(reversed(original.asset_hashes))
    assert app.session_state["test_blocks"]["water_reports"].asset_captions[-1] == "Updated first page"
    assert app.session_state["test_apply_count"] == 1
    assert not any(b.label in ("View or change pictures", "Done editing pictures") for b in app.button)


def test_opening_external_caption_mismatch_never_edits_the_attached_page(monkeypatch, tmp_path):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(1))
    button(app, "Include page and continue").click().run()
    app.run()
    block = app.session_state["test_blocks"]["water_reports"]
    content = app.session_state["synthetic_evidence"][0]
    changed = replace(content, source=replace(content.source, captions=((1, "External correction"),)))
    app.session_state["synthetic_evidence"] = (changed,)
    app.run()
    assert not app.exception
    assert app.session_state["test_blocks"]["water_reports"] == block
    assert any("changed since its review" in w.value for w in app.warning)


def test_removed_page_keeps_narrative_evidence_without_blocking_remaining_picture(monkeypatch, tmp_path):
    from app.monthly_report_page_controls import revise_included_page
    from app.monthly_report_model import synthetic_draft, ReportPeriod, synthetic_profiles, default_sections
    from app.monthly_report_checks import preflight
    _, content, block = _prepared(monkeypatch, tmp_path)
    block = replace(block, text="Inspection notes refer to both original pages.")
    revised, source = revise_included_page(block, content.source, 1, "omit")
    report = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), sections=default_sections(), blocks=(revised,), sources=(source,))
    issues = [c for c in preflight(report) if c.code in {"client_source_page", "client_pages"}]
    assert not issues
    assert revised.references == block.references and source.selected_pages == (2,)


def test_remaining_included_page_still_requires_its_source_review(monkeypatch, tmp_path):
    from app.monthly_report_page_controls import revise_included_page
    from app.monthly_report_model import synthetic_draft, ReportPeriod, synthetic_profiles, default_sections
    from app.monthly_report_checks import preflight
    _, content, block = _prepared(monkeypatch, tmp_path)
    block = replace(block, text="Inspection notes refer to both original pages.")
    revised, source = revise_included_page(block, content.source, 1, "omit")
    changed = replace(source, client_page_reviews=())
    report = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), sections=default_sections(), blocks=(revised,), sources=(changed,))
    assert any(c.code == "client_source_page" and "page 2" in c.message for c in preflight(report))
    missing = replace(report, sources=())
    assert any(c.code == "client_source_missing" for c in preflight(missing))
