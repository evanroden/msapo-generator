from dataclasses import replace
from io import BytesIO

from PIL import Image
from streamlit.testing.v1 import AppTest

from app.monthly_report_compare_ui import compare_drafts
from app.monthly_report_model import (
    ReportDraft, ReportFollowUp, ReportPeriod, ReportSource, ResolvedBlock,
    default_sections, synthetic_profiles,
)


def example():
    return ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), "Synthetic Editor",
                       default_sections(), (ResolvedBlock("activity_summary", "This month", text="Saved inspection."),))


def test_recovery_times_use_recorded_timezone_and_label_missing_or_ambiguous_values():
    from app.monthly_report_compare_ui import recovery_time
    assert recovery_time('2026-10-17T16:20:30-05:00') == '2026-10-17 21:20:30 UTC'
    for value in ('', None, 'not a date', '2026-10-17T21:20:30'):
        assert recovery_time(value) == 'Time unavailable'


def test_source_comparison_shows_reviewed_sites_and_artwork_without_receipt_tokens():
    from app.monthly_report_source_scope import correct_scope
    profile = synthetic_profiles()[1]
    source = ReportSource('synthetic-source', 'Synthetic source.pdf', 'source-sha', 'pdf')
    saved = replace(example(), profile=profile, sources=(source,))
    combined = correct_scope(source, profile, tuple(site.key for site in profile.facilities))
    change, = compare_drafts(replace(saved, sources=(combined,)), saved)
    assert 'Site not established' in change.saved
    assert all(site.title in change.working for site in profile.facilities)
    assert combined.scope_review not in change.working
    artwork = correct_scope(source, profile, contract_artwork=True, artwork_keys=('client_logo',))
    change, = compare_drafts(replace(saved, sources=(artwork,)), saved)
    assert 'Shared contract artwork' in change.working
    assert artwork.scope_review not in change.working
    stale = replace(combined, actions='New extraction changed this source.')
    change, = compare_drafts(replace(saved, sources=(stale,)), saved)
    assert 'Scope needs review' in change.working


def test_comparison_covers_membership_sections_tables_and_followups_without_internal_ids():
    saved = example()
    saved = replace(saved, blocks=(*saved.blocks, ResolvedBlock("thermal_capacity", "This month", rows=(("Synthetic Site", "Steam", 0, False),))))
    followup = ReportFollowUp("secret-followup-id", "issue", "Synthetic pump inspection", "August 2026")
    saved = replace(saved, follow_ups=(followup,))
    working = replace(saved, profile=replace(saved.profile, title="Synthetic New Title", facilities=(replace(saved.profile.facilities[0], aliases=("Synthetic alternate",)),)),
                      sections=tuple(reversed(tuple(replace(s, included=False) if s.key == "activity" else s for s in saved.sections))),
                      blocks=(replace(saved.blocks[0], text="Updated inspection."), replace(saved.blocks[1], rows=(("Synthetic Site", "Steam", 12, True),))),
                      follow_ups=(replace(followup, status="resolved", update="Verified repair", included=False),))
    changes = compare_drafts(working, saved)
    titles = {c.title for c in changes}
    assert {"Report name", "Sites and alternate names", "Report section order", "Monthly Activity Summary — inclusion", "Work completed this month", "Thermal capacity", "Open issues and proposals"} <= titles
    thermal = next(c for c in changes if c.title == "Thermal capacity")
    assert "Capacity: 0" in thermal.saved and "Units: False" in thermal.saved
    assert "Capacity: 12" in thermal.working and "Units: True" in thermal.working
    follow = next(c for c in changes if c.title == "Open issues and proposals")
    assert "Resolved" in follow.working and "Verified repair" in follow.working
    assert "secret-followup-id" not in follow.working
    assert compare_drafts(saved, saved) == ()


def test_picture_only_and_evidence_only_changes_are_not_reported_as_identical():
    saved = replace(example(), blocks=(ResolvedBlock("org_chart", "Library", asset_hashes=("private-old-hash.png",)),))
    working = replace(saved, blocks=(replace(saved.blocks[0], asset_hashes=("private-new-hash.png",)),))
    change, = compare_drafts(working, saved)
    assert change.saved_images == ("private-old-hash.png",)
    assert "hash" not in change.saved + change.working
    source = ReportSource("source-secret-id", "Synthetic vendor report.pdf", "secret-sha", "pdf", selected_pages=(1, 3))
    saved = replace(saved, sources=(source,))
    working = replace(saved, sources=(replace(source, selected_pages=(3,)),))
    change, = compare_drafts(working, saved)
    assert "1, 3" in change.saved and "3" in change.working
    assert "secret" not in change.saved + change.working


def test_comparison_ui_is_read_only_shows_editors_and_loads_real_previews(monkeypatch):
    import app.monthly_report_compare_ui as ui
    from app.monthly_report_library import SavedReport
    saved = replace(example(), blocks=(ResolvedBlock("client_logo", "Library", asset_hashes=("old.png",)),))
    working = replace(saved, blocks=(replace(saved.blocks[0], asset_hashes=("new.png",)),))
    snapshot = SavedReport(saved, "2026-10-08T12:00:00Z", 7, entered_editor="Synthetic Colleague")
    image = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(image, "PNG")
    calls = []

    def loader(reference):
        calls.append(reference)
        return image.getvalue()

    monkeypatch.setattr(ui, "_test_inputs", (working, snapshot), raising=False)
    monkeypatch.setattr(ui, "_test_loader", loader, raising=False)
    app = AppTest.from_string("""
from app import monthly_report_compare_ui as ui
ui.render_conflict_comparison(*ui._test_inputs, working_asset_loader=ui._test_loader, saved_asset_loader=ui._test_loader)
""").run()
    assert not app.exception
    assert calls == ["old.png", "new.png"]
    assert any("Synthetic Colleague" in w.value and "version 7" in w.value for w in app.markdown)
    assert not app.button and not app.checkbox and not app.json
    assert snapshot.draft == saved and working.blocks[0].asset_hashes == ("new.png",)


def test_failed_preview_is_explained_and_image_reads_are_bounded(monkeypatch):
    import app.monthly_report_compare_ui as ui
    from app.monthly_report_library import SavedReport
    saved = example()
    working = replace(saved, blocks=(*saved.blocks, ResolvedBlock("vendor_reports", "This month", asset_hashes=tuple(f"page-{n}.png" for n in range(8)))))
    calls = []

    def loader(reference):
        calls.append(reference)
        raise OSError("private storage path")

    monkeypatch.setattr(ui, "_test_inputs", (working, SavedReport(saved, "", 2)), raising=False)
    monkeypatch.setattr(ui, "_test_loader", loader, raising=False)
    app = AppTest.from_string("""
from app import monthly_report_compare_ui as ui
ui.render_conflict_comparison(*ui._test_inputs, working_asset_loader=ui._test_loader)
""").run()
    assert not app.exception and len(calls) == 4
    assert len(app.warning) == 4
    assert all("private storage path" not in warning.value for warning in app.warning)
    assert any("first 4 of 8" in caption.value for caption in app.caption)



def test_comparison_does_not_show_migration_as_a_change_or_text_edit_as_picture_review():
    from app.monthly_report_asset_review import normalize_asset_reviews, preserve_asset_reviews

    block = ResolvedBlock("activity_summary", "Library", text="Original summary", asset_hashes=("one.png", "two.png"), asset_captions=("One", "Two"))
    block = replace(block, client_reviewed_fingerprint=block.fingerprint)
    saved = replace(example(), blocks=(block,))
    migrated = normalize_asset_reviews(block)
    assert compare_drafts(replace(saved, blocks=(migrated,)), saved) == ()
    edited = preserve_asset_reviews(migrated, replace(migrated, text="Updated summary", client_reviewed_fingerprint=""))
    change, = compare_drafts(replace(saved, blocks=(edited,)), saved)
    assert "Pictures/pages reviewed" in change.working
    assert "need review" not in change.working
    caption_edit = replace(edited, asset_captions=("A changed caption", "Two"))
    change, = compare_drafts(replace(saved, blocks=(caption_edit,)), saved)
    assert "1 of 2 pictures/pages need review" in change.working


def test_history_inspection_can_reach_every_saved_picture_without_loading_them_all(monkeypatch):
    from app import monthly_report_compare_ui as ui
    from app.monthly_report_library import SavedReport
    saved = example()
    saved = replace(saved, blocks=(*saved.blocks, ResolvedBlock(
        "vendor_reports", "This month", asset_hashes=tuple(f"page-{n}.png" for n in range(8)))))
    working = replace(saved, blocks=tuple(block for block in saved.blocks if block.key != "vendor_reports"))
    calls = []

    def loader(reference):
        calls.append(reference)
        raise OSError("Synthetic missing old picture")

    monkeypatch.setattr(ui, "_test_inputs", (working, SavedReport(saved, "", 2)), raising=False)
    monkeypatch.setattr(ui, "_test_loader", loader, raising=False)
    app = AppTest.from_string("""
from app import monthly_report_compare_ui as ui
ui.render_conflict_comparison(*ui._test_inputs, saved_asset_loader=ui._test_loader,
                             can_accept=False, image_key='history_version_2')
""").run()
    assert not app.exception and calls == [f"page-{n}.png" for n in range(4)]
    calls.clear()
    next(item for item in app.selectbox if item.label == "Saved report pictures/pages").set_value(4).run()
    assert not app.exception and calls == [f"page-{n}.png" for n in range(4, 8)]
    assert not any("Use the full report preview" in item.value for item in app.caption)


def test_picture_page_resets_when_working_images_shrink_without_losing_saved_access(monkeypatch):
    from app import monthly_report_compare_ui as ui
    from app.monthly_report_library import SavedReport
    saved = replace(example(), blocks=(ResolvedBlock(
        "vendor_reports", "This month", asset_hashes=tuple(f"saved-{n}.png" for n in range(12))),))
    working = replace(saved, blocks=(replace(saved.blocks[0], asset_hashes=tuple(
        f"working-{n}.png" for n in range(12))),))
    snapshot = SavedReport(saved, "", 7)
    calls = []

    def loader(reference):
        calls.append(reference)
        raise OSError("Synthetic picture unavailable")

    monkeypatch.setattr(ui, "_test_inputs", (working, snapshot), raising=False)
    monkeypatch.setattr(ui, "_test_loader", loader, raising=False)
    app = AppTest.from_string("""
from app import monthly_report_compare_ui as ui
ui.render_conflict_comparison(*ui._test_inputs, saved_asset_loader=ui._test_loader,
                             working_asset_loader=ui._test_loader,
                             image_key='history_version_7')
""").run()
    assert not app.exception
    calls.clear()
    next(item for item in app.selectbox if item.label == "Saved report pictures/pages").set_value(4).run()
    assert calls[:4] == [f"saved-{n}.png" for n in range(4, 8)]
    next(item for item in app.selectbox if item.label == "Saved report pictures/pages").set_value(8).run()
    next(item for item in app.selectbox if item.label == "Your current work pictures/pages").set_value(8).run()
    assert not app.exception
    working = replace(working, blocks=(replace(working.blocks[0], asset_hashes=working.blocks[0].asset_hashes[:5]),))
    monkeypatch.setattr(ui, "_test_inputs", (working, snapshot))
    calls.clear()
    app.run()
    assert not app.exception
    assert next(item for item in app.selectbox if item.label == "Your current work pictures/pages").value == 0
    assert calls == [*(f"saved-{n}.png" for n in range(8, 12)), *(f"working-{n}.png" for n in range(4))]
    assert snapshot.draft == saved and len(working.blocks[0].asset_hashes) == 5


def test_inserted_or_removed_picture_comparison_does_not_reuse_another_blocks_page(monkeypatch):
    from app import monthly_report_compare_ui as ui
    from app.monthly_report_library import SavedReport
    saved = example()
    vendor = ResolvedBlock("vendor_reports", "This month", asset_hashes=tuple(f"vendor-{n}.png" for n in range(12)))
    organization = ResolvedBlock("org_chart", "This month", asset_hashes=tuple(f"organization-{n}.png" for n in range(12)))
    working = replace(saved, blocks=(*saved.blocks, vendor))
    snapshot = SavedReport(saved, "", 2)
    calls = []

    def loader(reference):
        calls.append(reference)
        raise OSError("Synthetic picture unavailable")

    monkeypatch.setattr(ui, "_test_inputs", (working, snapshot), raising=False)
    monkeypatch.setattr(ui, "_test_loader", loader, raising=False)
    app = AppTest.from_string("""
from app import monthly_report_compare_ui as ui
ui.render_conflict_comparison(*ui._test_inputs, working_asset_loader=ui._test_loader,
                             image_key='history_version_2')
""").run()
    app.selectbox[0].set_value(8).run()
    assert not app.exception
    working = replace(working, blocks=(*saved.blocks, organization, vendor))
    monkeypatch.setattr(ui, "_test_inputs", (working, snapshot))
    calls.clear()
    app.run()
    assert not app.exception
    assert [item.value for item in app.selectbox] == [0, 8]
    assert calls == [*(f"organization-{n}.png" for n in range(4)), *(f"vendor-{n}.png" for n in range(8, 12))]
    working = replace(working, blocks=(*saved.blocks, vendor))
    monkeypatch.setattr(ui, "_test_inputs", (working, snapshot))
    calls.clear()
    app.run()
    assert not app.exception and app.selectbox[0].value == 8
    assert calls == [f"vendor-{n}.png" for n in range(8, 12)]
    assert snapshot.draft == saved and working.blocks[-1] == vendor


def test_reordered_working_pictures_reset_page_while_historical_page_stays_selected(monkeypatch):
    from app import monthly_report_compare_ui as ui
    from app.monthly_report_library import SavedReport
    saved = replace(example(), blocks=(ResolvedBlock(
        "vendor_reports", "This month", asset_hashes=tuple(f"saved-{n}.png" for n in range(12))),))
    working = replace(saved, blocks=(replace(saved.blocks[0], asset_hashes=tuple(
        f"working-{n}.png" for n in range(12))),))
    snapshot = SavedReport(saved, "", 9)
    calls = []

    def loader(reference):
        calls.append(reference)
        raise OSError("Synthetic picture unavailable")

    monkeypatch.setattr(ui, "_test_inputs", (working, snapshot), raising=False)
    monkeypatch.setattr(ui, "_test_loader", loader, raising=False)
    app = AppTest.from_string("""
from app import monthly_report_compare_ui as ui
ui.render_conflict_comparison(*ui._test_inputs, saved_asset_loader=ui._test_loader,
                             working_asset_loader=ui._test_loader,
                             image_key='history_version_9')
""").run()
    next(item for item in app.selectbox if item.label == "Saved report pictures/pages").set_value(8).run()
    next(item for item in app.selectbox if item.label == "Your current work pictures/pages").set_value(8).run()
    working = replace(working, blocks=(replace(working.blocks[0], asset_hashes=tuple(reversed(
        working.blocks[0].asset_hashes))),))
    monkeypatch.setattr(ui, "_test_inputs", (working, snapshot))
    calls.clear()
    app.run()
    assert not app.exception
    assert [item.value for item in app.selectbox] == [8, 0]
    assert calls == [*(f"saved-{n}.png" for n in range(8, 12)), *(f"working-{n}.png" for n in range(11, 7, -1))]
    assert snapshot.draft == saved and working.blocks[0].asset_hashes[0] == "working-11.png"
