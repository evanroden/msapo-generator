"""A64: one evidence-bearing file card per source, with one direct Edit route.

Synthetic AppTest exercises the native widget tree, not a served browser.
"""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_upload_ui as upload_ui
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock, SectionSpec,
    default_sections, synthetic_profiles,
)
from app.monthly_report_source_card_summary import source_card_evidence
from app.monthly_report_source_status import SourceManagerStatus, source_manager_status
from test_monthly_report_ui import monthly
from test_monthly_report_source_workspace_ui import uploads
from test_monthly_report_upload_ui import button, current_draft, select
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_utility_uploads import utility_pdf


def _card_button(app, source_id):
    suffix = "_source_card_" + sha256(source_id.encode()).hexdigest()[:16] + "_edit"
    return next(item for item in app.button if item.key.endswith(suffix))


def test_card_evidence_uses_observed_type_site_month_destination_and_no_review_banner():
    profile = synthetic_profiles()[0]
    source = ReportSource("synthetic-id", "synthetic.csv", "a" * 64, ".csv",
                          classification="CMMS export", service_date="",
                          facility="", page_texts=("Work order, status",))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic editor",
        (SectionSpec("activity", "2", "Monthly Activity", (BlockSpec("activity_summary", "rich_text"),)),),
        (), sources=(source,), synthetic=True)
    accepted = SourceManagerStatus(source.id, source.filename, True, "", 0,
        ("activity_summary",), False, "Totals accepted · Monthly Activity")
    before = asdict(draft)
    card = source_card_evidence(source, accepted, draft)
    assert (card.source_type, card.site, card.month, card.destination) == (
        "CMMS export (CSV)", "Not established", "Not established", "Monthly Activity")
    assert card.contribution == "Totals accepted · Monthly Activity"
    assert not card.warning
    wrong = replace(source, facility="Another site", service_date="2026-08-12")
    blocked = replace(accepted, resolved=False, reason="Check the source facility.",
                      needs_correction=True)
    card = source_card_evidence(wrong, blocked, draft)
    assert (card.site, card.month, card.warning) == (
        "Another site", "August 2026", "Check the source facility.")
    assert asdict(draft) == before, "Cards never approve or mutate source data."


def test_fresh_then_mixed_source_cards_have_one_intake_and_direct_edit(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert sum(item.label == "Add source files" for item in app.get("file_uploader")) == 1
    assert not [b for b in app.button if "_source_card_" in b.key and b.label == "Edit"]
    uploads(monkeypatch, (
        ("synthetic-workorders.csv",
         b"Work Order,Date,Status,Facility\n001,2026-09-04,Completed,Demo North\n"),
        ("synthetic-utility.pdf", utility_pdf()),
    ))
    # The synthetic intake replaces st.file_uploader itself, so AppTest cannot
    # report its native widget after upload. Count the routed uploader key
    # instead; the initial render above still checks the real native widget.
    synthetic_uploader = upload_ui.st.file_uploader
    intake_keys = set()

    def traced_uploader(label, *args, **kwargs):
        if label == "Add source files":
            intake_keys.add(kwargs["key"])
        return synthetic_uploader(label, *args, **kwargs)

    monkeypatch.setattr(upload_ui.st, "file_uploader", traced_uploader)
    app.run()
    assert not app.exception
    draft = current_draft(app)
    assert len(draft.sources) == 2
    first, second = draft.sources
    assert len(intake_keys) == 1
    assert len([b for b in app.button if b.label == "Edit" and "_source_card_" in b.key]) == 2
    captions = [item.value for item in app.caption]
    assert any("Type: " in text and "(CSV)" in text for text in captions)
    assert any("Type: " in text and "(PDF)" in text and "September 2026" in text for text in captions)
    assert any("Destination: " in text for text in captions)
    assert any("Contribution: " in text for text in captions)
    _card_button(app, second.id).click().run()
    assert not app.exception
    assert select(app, "File to review").value == second.id
    assert any("Source date" == field.label and second.id in field.key for field in app.date_input)
    _card_button(app, first.id).click().run()
    assert not app.exception
    assert select(app, "File to review").value == first.id
    # Switching cards never duplicates uploads, sources, or page identities.
    assert len(current_draft(app).sources) == 2
    assert len(intake_keys) == 1


def test_direct_edit_keeps_captions_and_metadata_buffers_across_done_reopen(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    uploads(monkeypatch, (
        ("synthetic-utility.pdf", utility_pdf()),
        ("synthetic-service.pdf", pdf_bytes(1)),
    ))
    app.run()
    assert not app.exception
    first, second = current_draft(app).sources
    date_input = next(item for item in app.date_input if first.id in item.key)
    original_id = date_input.id
    date_input.set_value(date(2026, 9, 27))
    next(item for item in app.text_input if item.label == "Page caption").set_value(
        "Card switch must carry this caption")
    _card_button(app, second.id).click().run()
    assert not app.exception
    assert select(app, "File to review").value == second.id
    assert dict(current_draft(app).sources[0].captions)[1] == "Card switch must carry this caption"
    assert current_draft(app).sources[0].service_date == first.service_date
    _card_button(app, first.id).click().run()
    assert not app.exception
    assert next(item for item in app.date_input if first.id in item.key).id == original_id
    assert next(item for item in app.date_input if first.id in item.key).value == date(2026, 9, 27)
    button(app, "Done with source files").click().run()
    button(app, "Manage source files").click().run()
    assert next(item for item in app.date_input if first.id in item.key).value == date(2026, 9, 27)
    next(item for item in app.button if item.label == "Use these source details" and first.id in item.key).click().run()
    assert current_draft(app).sources[0].service_date == "2026-09-27"
    assert current_draft(app).sources[1].service_date == second.service_date


def test_original_disappearance_and_retry_show_one_warning_without_changing_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = b"Synthetic retained source, no inferred completed work."
    content, _ = sources.ingest(profile, "synthetic-reference.txt", raw)
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic editor",
        default_sections(), (), sources=(content.source,), synthetic=True)
    original = sources._path(profile, content.source.sha256, content.source.suffix)
    assert source_card_evidence(content.source, source_manager_status(draft, (content,))[0], draft).warning == ""
    original.unlink()
    error = source_manager_status(draft, (content,))[0]
    assert not error.resolved and error.needs_correction
    assert source_card_evidence(content.source, error, draft).warning == "Restore the original source file."
    original.write_bytes(raw)  # Synthetic exact-byte reappearance, not a paid AI retry.
    restored = source_manager_status(draft, (content,))[0]
    assert source_card_evidence(content.source, restored, draft).warning == ""
    assert sources.source_bytes(profile, content.source) == raw
    assert library.draft_from_dict(asdict(draft)) == draft


def test_wrong_site_warning_opens_native_correction_and_clears_on_one_save(monkeypatch, tmp_path):
    import pymupdf
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "Utility results. Facility: Different Hospital.")
        page.insert_text((50, 80), "Report date: 2026-09-30")
        page.insert_text((50, 110), "Electricity consumption: 1250 kWh. Synthetic data.")
        raw = document.tobytes()
    app = monthly(monkeypatch, tmp_path)
    uploads(monkeypatch, (("synthetic-wrong-site.pdf", raw),))
    app.run()
    assert not app.exception
    draft = current_draft(app)
    source, = draft.sources
    original_sha = source.sha256
    # This is a source-specific warning, not a second Needs Review task.
    warnings = [item.value for item in app.warning if "Check the source facility." in item.value]
    assert len(warnings) == 1
    _card_button(app, source.id).click().run()
    assert not app.exception
    assert select(app, "File to review").value == source.id
    select(app, "Source facility").set_value(draft.profile.facilities[0].key)
    next(item for item in app.button if item.label == "Use these source details"
         and source.id in item.key).click().run()
    assert not app.exception
    revised, = current_draft(app).sources
    assert revised.sha256 == original_sha
    assert revised.facility == draft.profile.facilities[0].key
    assert not any("Check the source facility." in item.value for item in app.warning)
    assert sources.source_bytes(draft.profile, revised) == raw


def test_malformed_unsupported_and_duplicate_batch_do_not_displace_accepted_source(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    good = utility_pdf()
    contents, messages = sources.ingest_batch(profile, (
        ("synthetic-damaged.pdf", b"not a PDF"),
        ("synthetic-unsupported.bin", b"unrecognized format"),
        ("synthetic-valid.pdf", good),
        ("synthetic-duplicate.pdf", good),
    ))
    assert len(contents) == 1
    source = contents[0].source
    assert any("synthetic-damaged.pdf" in message and "Not read" in message for message in messages)
    assert any("synthetic-unsupported.bin" in message and "Not read" in message for message in messages)
    assert any("Duplicate skipped" in message for message in messages)
    assert sources.source_bytes(profile, source) == good
    edited = replace(source, vendor="Human verified annotation")
    contents = (replace(contents[0], source=edited),)
    original = sources._path(profile, source.sha256, source.suffix)
    original.unlink()
    recovered, messages = sources.ingest_batch(profile, (("synthetic-restored.pdf", good),), contents)
    assert len(recovered) == 1
    assert recovered[0].source == edited
    assert sources.source_bytes(profile, recovered[0].source) == good
    assert any("Saved source restored" in message for message in messages)
