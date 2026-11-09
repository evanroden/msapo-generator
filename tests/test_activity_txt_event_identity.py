"""TXT originals retain per-event evidence without a false global identity."""
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import tempfile

from docx import Document
import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_native_layout import _build_native_docx, build_native_docx


PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)
PLAIN = ("Vendor: Alpha Mechanical\nService date: 2026-09-04\nInspected pump P-1.\n\n"
         "Vendor: Beta Controls\nService date: 2026-09-18\nCalibrated panel C-2.\n")
TAGGED = ("2026-09-04 | WO-01 | Vendor service\nVendor: Alpha Mechanical\nInspected pump P-1.\n"
          "2026-09-18 | WO-02 | Vendor service\nVendor: Beta Controls\nCalibrated panel C-2.\n")


def _temporary_atomic_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


@pytest.fixture
def ingest_txt(monkeypatch, tmp_path):
    # Actual ingest, UTF-8 parsing, suggestions and original integrity reader.
    # Supply only persistence/path seams on Windows; never replace locks.
    monkeypatch.setattr(sources, "_path", lambda profile, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", _temporary_atomic_write)

    def read(body):
        raw = body.encode("utf-8")
        content, attachments = sources.ingest(PROFILE, "synthetic-maintenance report.txt", raw)
        assert not attachments
        assert content.source.sha256 == sha256(raw).hexdigest()
        assert sources.source_bytes(PROFILE, content.source) == raw
        return content, raw
    return read


def extract_unchanged(content, raw, existing=None):
    before = asdict(content)
    result = structured.native_update((content,), "activity_summary", existing)
    assert asdict(content) == before
    assert sources.source_bytes(PROFILE, content.source) == raw
    return result


@pytest.mark.parametrize("body, expected", [
    (PLAIN, "Inspected pump P-1.\n\nCalibrated panel C-2."),
    (PLAIN.replace("Beta Controls", "Alpha Mechanical"),
     "Alpha Mechanical — Inspected pump P-1.\n\nAlpha Mechanical — Calibrated panel C-2."),
    (PLAIN.replace("2026-09-18", "2026-09-04"),
     "2026-09-04 — Inspected pump P-1.\n\n2026-09-04 — Calibrated panel C-2."),
])
def test_plain_txt_suppresses_only_ambiguous_global_fields(ingest_txt, body, expected):
    content, raw = ingest_txt(body)
    assert content.source.vendor == "Alpha Mechanical" and content.source.service_date == "2026-09-04"
    result = extract_unchanged(content, raw)
    assert result.text == expected
    assert result.references == (sources.source_reference(content.source, 1),)


def test_tagged_txt_keeps_each_event_date_without_false_vendor(ingest_txt):
    content, raw = ingest_txt(TAGGED)
    result = extract_unchanged(content, raw)
    assert result.text == "2026-09-04 — Inspected pump P-1.\n\n2026-09-18 — Calibrated panel C-2."
    assert content.source.vendor == "Alpha Mechanical" and content.source.service_date == ""


def test_tagged_single_vendor_still_keeps_both_event_dates(ingest_txt):
    content, raw = ingest_txt(TAGGED.replace("Beta Controls", "Alpha Mechanical"))
    assert extract_unchanged(content, raw).text == (
        "2026-09-04 · Alpha Mechanical — Inspected pump P-1.\n\n"
        "2026-09-18 · Alpha Mechanical — Calibrated panel C-2.")


@pytest.mark.parametrize("extra", ["", "Vendor: alpha   mechanical\nCompleted date: 09/04/2026\n",
                                    "Wrong date: 2026-99-99\n"])
def test_single_repeated_or_invalid_second_identity_retains_verified_prefix(ingest_txt, extra):
    content, raw = ingest_txt("Vendor: Alpha Mechanical\nService date: 2026-09-04\n" + extra + "Inspected pump P-1.\n")
    assert extract_unchanged(content, raw).text == "2026-09-04 · Alpha Mechanical — Inspected pump P-1."


def test_user_corrected_source_metadata_remains_saved_without_blanket_attribution(ingest_txt):
    content, raw = ingest_txt(PLAIN)
    content = replace(content, source=replace(content.source, vendor="Operator corrected company",
        service_date="2026-09-22", actions="Operator retained source note", facility=PROFILE.facilities[0].key))
    assert extract_unchanged(content, raw).text == "Inspected pump P-1.\n\nCalibrated panel C-2."
    assert content.source.vendor == "Operator corrected company"
    assert content.source.service_date == "2026-09-22"
    assert content.source.actions == "Operator retained source note"


@pytest.mark.parametrize("manual", ["Operator deliberately edited this Activity.", ""])
def test_source_metadata_correction_cannot_restore_manual_edits_or_deletions(ingest_txt, manual):
    content, raw = ingest_txt(PLAIN)
    initial = extract_unchanged(content, raw)
    kept = replace(initial, text=manual)
    corrected = replace(content, source=replace(content.source, vendor="Corrected company", service_date="2026-09-20"))
    assert extract_unchanged(corrected, raw, kept) == kept


def test_negative_outcomes_and_contact_exclusion_remain_intact(ingest_txt):
    body = PLAIN.replace("Inspected pump P-1.", "Inspected pump P-1. Replacement was not completed.").replace(
        "Calibrated panel C-2.", "Checked panel C-2 and it\nwould not stabilize. Contact: person@example.invalid")
    content, raw = ingest_txt(body)
    result = extract_unchanged(content, raw)
    assert "Replacement was not completed." in result.text
    assert "Checked panel C-2 and it would not stabilize." in result.text
    assert "person@example.invalid" not in result.text
    assert "Alpha Mechanical —" not in result.text


def test_priced_plain_source_stays_out_and_manual_wording_is_unchanged(ingest_txt):
    content, raw = ingest_txt(PLAIN + "Invoice total: $500\n")
    existing = ResolvedBlock("activity_summary", "This month", text="Operator's retained manual words.")
    assert extract_unchanged(content, raw, existing) == existing


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_table_sources_keep_their_separate_identity_path(ingest_txt, suffix):
    content, _ = ingest_txt(PLAIN)
    source = replace(content.source, suffix=suffix)
    assert structured._non_table_activity_identity(source) is source


def draft_for(content, block):
    section = SectionSpec("activity", "2", "Monthly Activity Summary", (BlockSpec("activity_summary", "rich_text"),))
    return ReportDraft(PROFILE, PERIOD, "Synthetic Editor", (section,), (block,), sources=(content.source,), synthetic=True)


def template(tmp_path):
    document = Document()
    document.add_heading("2 Monthly Activity Summary", 1)
    document.add_paragraph("Original placeholder")
    path = tmp_path / "synthetic-activity.docx"
    document.save(path)
    return path


@pytest.mark.parametrize("body, expected", [(PLAIN, "Calibrated panel C-2."),
                                           (TAGGED, "2026-09-18 — Calibrated panel C-2.")])
def test_actual_native_word_keeps_events_without_wrong_first_identity(ingest_txt, tmp_path, body, expected):
    content, raw = ingest_txt(body)
    block = extract_unchanged(content, raw)
    path = template(tmp_path)
    original = path.read_bytes()
    output = Document(BytesIO(_build_native_docx(draft_for(content, block), path, section_key="activity")))
    text = "\n".join(paragraph.text for paragraph in output.paragraphs)
    assert expected in text
    assert "Alpha Mechanical —" not in text and "2026-09-04 — Calibrated panel C-2." not in text
    assert text.count("Inspected pump P-1.") == text.count("Calibrated panel C-2.") == 1
    assert path.read_bytes() == original


def test_public_storage_saved_metadata_history_and_word_remain_intact(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    content, _ = sources.ingest(PROFILE, "synthetic-maintenance report.txt", PLAIN.encode())
    previous = ResolvedBlock("activity_summary", "This month", text="Earlier manual observation.")
    saved = library.save_snapshot(draft_for(content, previous), expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    result = structured.native_update((content,), "activity_summary", reopened.blocks[0])
    assert result.text == previous.text + "\n\nInspected pump P-1.\n\nCalibrated panel C-2."
    next_draft = replace(reopened, blocks=(result,))
    library.save_snapshot(next_draft, expected_revision=saved.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    assert next_draft.sources == reopened.sources
    assert sources.source_bytes(PROFILE, content.source) == PLAIN.encode()
    output = Document(BytesIO(build_native_docx(next_draft, template(tmp_path), section_key="activity")))
    text = "\n".join(paragraph.text for paragraph in output.paragraphs)
    assert "Calibrated panel C-2." in text and "Alpha Mechanical —" not in text


def test_public_storage_guided_txt_upload_preserves_manual_work_and_original_identity(monkeypatch, tmp_path):
    import streamlit as st
    from tests.test_monthly_report_activity_intake_commit import setup_app, activity, draft, editor

    app, profile = setup_app(monkeypatch, tmp_path / "guided")
    manual = "Operator retained an existing observation."
    editor(app).set_value(manual).run()
    original_uploader = st.file_uploader

    def uploaded(label, *args, **kwargs):
        native = original_uploader(label, *args, **kwargs)
        if label != "Add source files":
            return native
        stream = BytesIO(PLAIN.encode())
        stream.name = "synthetic-maintenance report.txt"
        return [stream]

    monkeypatch.setattr(st, "file_uploader", uploaded)
    app.run()
    assert not app.exception
    assert activity(app).text == manual + "\n\nInspected pump P-1.\n\nCalibrated panel C-2."
    assert editor(app).value == activity(app).text
    source, = draft(app).sources
    assert source.vendor == "Alpha Mechanical" and source.service_date == "2026-09-04"
    assert sources.source_bytes(profile, source) == PLAIN.encode()
