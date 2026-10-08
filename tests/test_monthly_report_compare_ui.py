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
