"""The retained detailed editor consumes accepted intake on later native actions."""
import pytest
from dataclasses import replace

from test_monthly_report_editor import app_with_library, mock_chart_upload, org_source, review_pages, generate_button
from test_monthly_report_upload_ui import upload, button, select
from test_monthly_report_sources import pdf_bytes


@pytest.mark.parametrize("reviewed", [(), (1,), (2,), (1, 2)])
def test_first_failed_source_preparation_stays_pending_until_corrected(monkeypatch, tmp_path, reviewed):
    from app import monthly_report_upload_ui as upload_ui
    app, _ = app_with_library(monkeypatch, tmp_path)
    mock_chart_upload(monkeypatch)
    org_source(app).set_value("Replace once").run()
    review_pages(app)
    upload(monkeypatch, "synthetic-first-batch.pdf", pdf_bytes(2))
    app.run()
    button(app, "Read monthly files").click().run()
    select(app, "Classification").set_value("Water treatment").run()
    for page in reviewed:
        select(app, "Preview page / item").set_value(page).run()
        button(app, "Include page").click().run()
    prepare = upload_ui.sources.prepare_pages
    if len(reviewed) == 2:
        def fail(*args, **kwargs):
            raise OSError("Synthetic first-batch conversion failed")
        monkeypatch.setattr(upload_ui.sources, "prepare_pages", fail)
    button(app, "Add selected pages and tables to report").click().run()
    assert not app.exception
    assert any("Nothing was added" in item.value for item in app.caption)
    assert not any(key.endswith("_accepted_batch") for key in app.session_state.filtered_state)
    assert any("pending file selection" in item.value for item in app.error)
    assert generate_button(app).disabled
    app.run()
    assert any("pending file selection" in item.value for item in app.error)
    assert generate_button(app).disabled
    next(w for w in app.text_input if w.label == "Page caption").set_value("Corrected first-batch caption").run()
    assert any("pending file selection" in item.value for item in app.error)
    monkeypatch.setattr(upload_ui.sources, "prepare_pages", prepare)
    for page in (1, 2):
        select(app, "Preview page / item").set_value(page).run()
        button(app, "Include page").click().run()
    button(app, "Add selected pages and tables to report").click().run()
    assert not app.exception
    assert not any("pending file selection" in item.value for item in app.error)
    accepted = next(value for key, value in app.session_state.filtered_state.items()
                    if key.endswith("_accepted_batch"))
    assert len(accepted[1]["water_reports"].asset_hashes) == 2


def accepted_water(monkeypatch, tmp_path):
    from app import monthly_report_editor as editor
    observed = []
    preflight = editor.preflight
    def observe(draft, *args, **kwargs):
        observed.append(draft)
        return preflight(draft, *args, **kwargs)
    monkeypatch.setattr(editor, "preflight", observe)
    app, profile = app_with_library(monkeypatch, tmp_path)
    mock_chart_upload(monkeypatch)
    org_source(app).set_value("Replace once").run()
    upload(monkeypatch, "synthetic-water.pdf", pdf_bytes(1))
    app.run()
    button(app, "Read monthly files").click().run()
    select(app, "Classification").set_value("Water treatment").run()
    # This synthetic PDF has no printed site. Use the real item correction;
    # the warning acknowledgment is no longer a site-scope authorization.
    select(app, "Source facility").set_value(profile.facilities[0].key)
    button(app, "Use these source details").click().run()
    button(app, "Include page").click().run()
    button(app, "Add selected pages and tables to report").click().run()
    next(w for w in app.selectbox if w.key.endswith("_water_reports_source")).set_value("This month").run()
    next(w for w in app.toggle if w.key.endswith("_water_include")).set_value(True).run()
    review_pages(app)
    assert not app.exception
    assert len(next(b for b in observed[-1].blocks if b.key == "water_reports").asset_hashes) == 1
    return app, profile, observed


@pytest.mark.parametrize("action", ["move", "remove"])
def test_saved_source_retirement_keeps_independent_old_destination_content(monkeypatch, tmp_path, action):
    from app import monthly_report_library as library, monthly_report_sources as sources
    from app.monthly_report_model import ReportTable
    app, profile, observed = accepted_water(monkeypatch, tmp_path)
    accepted = observed[-1]
    water = next(b for b in accepted.blocks if b.key == "water_reports")
    original = sources.source_bytes(profile, accepted.sources[0])
    # A real saved report can contain human notes/tables beside imported pages.
    human = replace(water, text="Independent operator note.",
                    extra_tables=(ReportTable(("Operator", "Observation"), (("Human", "Keep this row"),)),))
    saved_draft = replace(accepted, blocks=tuple(human if b.key == water.key else b for b in accepted.blocks))
    assets = next(value for key, value in app.session_state.filtered_state.items()
                  if key.startswith("report_draft_") and key.endswith("_assets"))
    saved = library.save_snapshot(saved_draft, expected_revision=0,
                                  entered_editor="Synthetic editor", assets=tuple(assets.items()))
    app.run()
    # Switch the retained editor to the newly saved report through its own UI.
    next(w for w in app.radio if w.label == "Start from").set_value("Saved work for this month").run()
    next(w for w in app.selectbox if w.key.endswith("_water_reports_source")).set_value("This month").run()
    if action == "move":
        select(app, "Report section for synthetic-water.pdf").set_value("mbcx_report").run()
        button(app, "Add selected pages and tables to report").click().run()
        next(w for w in app.selectbox if w.key.endswith("_mbcx_report_source")).set_value("This month").run()
    else:
        button(app, "Remove source from this selection").click().run()
        button(app, "Remove last added pages and tables from this report").click().run()
    assert not app.exception
    retired = next(b for b in observed[-1].blocks if b.key == "water_reports")
    assert retired.asset_hashes == ()
    assert retired.text == human.text and retired.extra_tables == human.extra_tables
    if action == "move":
        moved = next(b for b in observed[-1].blocks if b.key == "mbcx_report")
        assert moved.asset_hashes == water.asset_hashes
    app.run()
    assert next(b for b in observed[-1].blocks if b.key == "water_reports") == retired
    assert library.load_snapshot(profile.contract, profile.key, accepted.period) == saved
    assert sources.source_bytes(profile, accepted.sources[0]) == original


def test_source_retirement_uses_provenance_and_preserves_omission_equal_human_text_and_tables():
    from app.monthly_report_model import ResolvedBlock, ReportTable
    from app.monthly_report_source_retirement import retire_contributions
    owned = ResolvedBlock("water_reports", "This month", asset_hashes=("source.png",),
                          asset_captions=("Source caption",), references=("source:1:receipt",),
                          asset_provenance=(("source.png", ("source:1:receipt",)),))
    table = ReportTable(("Observation",), (("Human entered row",),))
    block = replace(owned, text="Source caption", extra_tables=(table,),
                    asset_hashes=("source.png", "human.png"),
                    asset_captions=("Source caption", "Independent human picture"),
                    asset_provenance=(*owned.asset_provenance, ("human.png", ())))
    retired = retire_contributions(block, (owned,))
    assert retired.text == block.text and retired.extra_tables == (table,)
    assert retired.asset_hashes == ("human.png",)
    assert retired.asset_captions == ("Independent human picture",)
    assert retire_contributions(retired, (owned,)) == retired
    omitted = replace(block, source="Omit")
    assert retire_contributions(omitted, (owned,)) == omitted
    same_bytes_human = replace(owned, asset_provenance=(("source.png", ()),))
    assert retire_contributions(same_bytes_human, (owned,)) == same_bytes_human
    rows = ResolvedBlock("work_orders", "This month", rows=(("Human entered row",),), references=("sheet:1:receipt",))
    assert retire_contributions(rows, (rows,)).rows == ()
    independent = replace(rows, references=())
    assert retire_contributions(independent, (rows,)) == independent


@pytest.mark.parametrize("edit", ["caption", "selection"])
def test_detailed_source_proposal_keeps_last_added_report_until_successful_replace(monkeypatch, tmp_path, edit):
    from app import monthly_report_library as library
    app, profile, observed = accepted_water(monkeypatch, tmp_path)
    accepted = observed[-1]
    if edit == "caption":
        next(w for w in app.text_input if w.label == "Page caption").set_value("Proposed caption awaiting review").run()
    else:
        next(w for w in app.multiselect if w.label == "Included pages / extracted items").set_value([]).run()
    assert not app.exception
    assert observed[-1] == accepted
    assert any("last added selection" in item.value for item in app.info)
    assert next(w for w in app.radio if w.label == "This month's content").value == "Uploaded content"
    assert generate_button(app).disabled
    assert any("pending file selection" in error.value for error in app.error)
    assert library.load_snapshot(profile.contract, profile.key, accepted.period) is None


def test_failed_replacement_keeps_accepted_page_caption_and_source_snapshot(monkeypatch, tmp_path):
    app, _, observed = accepted_water(monkeypatch, tmp_path)
    accepted = observed[-1]
    next(w for w in app.text_input if w.label == "Page caption").set_value("Replacement caption awaiting review").run()
    button(app, "Add selected pages and tables to report").click().run()
    assert not app.exception
    assert any("Check page 1" in error.value for error in app.error)
    assert observed[-1] == accepted
    button(app, "Include page").click().run()
    button(app, "Add selected pages and tables to report").click().run()
    assert not app.exception
    updated = observed[-1]
    page = next(b for b in updated.blocks if b.key == "water_reports")
    assert len(page.asset_hashes) == 1 and page.asset_captions == ("Replacement caption awaiting review",)
    assert dict(updated.sources[0].captions)[1] == page.asset_captions[0]
    assert updated.sources[0].fingerprint != accepted.sources[0].fingerprint
    app.run()
    assert observed[-1] == updated


def test_removing_selected_source_requires_explicit_last_batch_removal(monkeypatch, tmp_path):
    from app import monthly_report_library as library, monthly_report_sources as sources
    app, profile, observed = accepted_water(monkeypatch, tmp_path)
    accepted = observed[-1]
    original = sources.source_bytes(profile, accepted.sources[0])
    standing = library.load_profile(profile.contract, profile.key)
    button(app, "Remove source from this selection").click().run()
    assert not app.exception and observed[-1] == accepted
    assert generate_button(app).disabled
    button(app, "Remove last added pages and tables from this report").click().run()
    assert not app.exception
    assert not next(b for b in observed[-1].blocks if b.key == "water_reports").asset_hashes
    assert observed[-1].sources == ()
    assert sources.source_bytes(profile, accepted.sources[0]) == original
    assert library.load_profile(profile.contract, profile.key) == standing


def test_failed_preparation_blocks_generation_until_explicit_success_even_without_source_change(monkeypatch, tmp_path):
    from app import monthly_report_upload_ui as upload_ui
    app, _, observed = accepted_water(monkeypatch, tmp_path)
    accepted = observed[-1]
    prepare = upload_ui.sources.prepare_pages
    def fail(*args, **kwargs):
        raise OSError("Invented source preparation failure")
    monkeypatch.setattr(upload_ui.sources, "prepare_pages", fail)
    button(app, "Add selected pages and tables to report").click().run()
    assert not app.exception and observed[-1] == accepted
    assert generate_button(app).disabled
    app.run()
    assert observed[-1] == accepted and generate_button(app).disabled
    assert any("pending file selection" in error.value for error in app.error)
    monkeypatch.setattr(upload_ui.sources, "prepare_pages", prepare)
    button(app, "Add selected pages and tables to report").click().run()
    assert observed[-1] == accepted
    assert not any("pending file selection" in error.value for error in app.error)


def test_same_native_generate_event_cannot_publish_a_pending_caption(monkeypatch, tmp_path):
    from app import monthly_report_editor as editor, monthly_report_library as library
    app, profile, observed = accepted_water(monkeypatch, tmp_path)
    ack = next((w for w in app.checkbox if w.label == "I've checked these warnings"), None)
    if ack:
        ack.check().run()
    accepted = observed[-1]
    generate = generate_button(app)
    assert not generate.disabled
    monkeypatch.setattr(editor, "generate_report", lambda *args, **kwargs: pytest.fail("Pending source edit reached generation"))
    # Submit both native values together; no intermediate blur/rerun makes
    # the old Generate button disappear before this stale click is delivered.
    next(w for w in app.text_input if w.label == "Page caption").set_value("Pending same-event correction")
    generate.click().run()
    assert not app.exception and observed[-1] == accepted
    assert generate_button(app).disabled
    assert library.load_snapshot(profile.contract, profile.key, accepted.period) is None


def test_detailed_editor_keeps_accepted_pages_through_generation_rerun(monkeypatch, tmp_path):
    from app import monthly_report_editor as editor
    app, profile = app_with_library(monkeypatch, tmp_path)
    mock_chart_upload(monkeypatch)
    org_source(app).set_value("Replace once").run()
    upload(monkeypatch, "synthetic-water.pdf", pdf_bytes(1))
    app.run()
    button(app, "Read monthly files").click().run()
    select(app, "Classification").set_value("Water treatment").run()
    select(app, "Source facility").set_value(profile.facilities[0].key)
    button(app, "Use these source details").click().run()
    button(app, "Include page").click().run()
    button(app, "Add selected pages and tables to report").click().run()
    assert not app.exception
    source = next(w for w in app.selectbox if w.key.endswith("_water_reports_source"))
    assert "This month" in source.options
    source.set_value("This month").run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.key.endswith("_water_reports_source")).value == "This month"
    assert any(w.label == "This month's content" for w in app.radio)
    next(w for w in app.toggle if w.key.endswith("_water_include")).set_value(True).run()
    review_pages(app)
    assert not app.exception
    ack = next((w for w in app.checkbox if w.label == "I've checked these warnings"), None)
    if ack:
        ack.check().run()
    assert not generate_button(app).disabled, [w.value for w in app.error]
    observed = []
    original = editor.generate_report
    def generate(draft, **kwargs):
        observed.append(draft)
        return original(draft, **kwargs)
    monkeypatch.setattr(editor, "generate_report", generate)
    generate_button(app).click().run()
    assert not app.exception
    assert len(observed) == 1
    added = next(b for b in observed[0].blocks if b.key == "water_reports")
    assert len(added.asset_hashes) == 1 and len(added.references) == 1
    app.run()
    assert next(w for w in app.selectbox if w.key.endswith("_water_reports_source")).value == "This month"
    assert any(w.label == "This month's content" for w in app.radio)
    next(w for w in app.text_input if w.label == "Page caption").set_value("Pending correction after export").run()
    assert not app.exception and generate_button(app).disabled
    assert not any(key.startswith("report_draft_") and key.endswith("_package")
                   for key in app.session_state.filtered_state)
    assert any("pending file selection" in error.value for error in app.error)
