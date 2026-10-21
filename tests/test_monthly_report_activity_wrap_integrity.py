"""Real synthetic PDF ingestion must keep a service event's complete meaning."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

from docx import Document
import fitz
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, SectionSpec, synthetic_profiles,
)
from app.monthly_report_structured_uploads import native_update, reader_update
from tests.conftest import requires_libreoffice


def ingest_lines(monkeypatch, tmp_path, lines):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with fitz.open() as pdf:
        page = pdf.new_page(width=750, height=500)
        for index, line in enumerate(lines):
            if line:
                page.insert_text((40, 50 + index * 16), line, fontsize=10)
        original = pdf.tobytes()
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-wrap-service.pdf", original)
    assert sources.source_bytes(profile, content.source) == original
    return profile, content


@pytest.mark.parametrize("opening,tail", [
    ("The technician checked exhaust fan EF-31 and confirmed it", "did not start."),
    ("The service team exercised isolation valve IV-8 and verified it", "would not close."),
    ("The technician inspected the motor starter and found it", "locked out."),
    ("The service team repaired the controller but the unit was", "not yet returned to service."),
])
@pytest.mark.parametrize("wrapped", [True, False])
def test_complete_negative_event_survives_native_and_separate_reader(
        monkeypatch, tmp_path, opening, tail, wrapped):
    expected = opening + " " + tail
    _, content = ingest_lines(monkeypatch, tmp_path,
                              (opening, tail) if wrapped else (expected,))
    native = native_update((content,), "activity_summary")
    assert native.text == expected
    # This is a separately supplied grounded reader result, not an external call.
    read, _ = reader_update((content,), "activity_summary", {
        "items": [{"source": content.source.id, "page": 1, "text": expected,
                   "row": [], "include_page": False}],
    }, native)
    assert read.text == expected
    assert read.references == native.references
    assert read.text.count(expected) == 1


def test_complete_separate_bullets_keep_identity_and_one_prefix(monkeypatch, tmp_path):
    _, content = ingest_lines(monkeypatch, tmp_path, (
        "- Inspected fan EF-31 and confirmed it", "did not start.",
        "- Replaced the actuator on valve IV-8 and confirmed normal operation.",
    ))
    content = replace(content, source=replace(content.source,
        service_date="2026-09-10", vendor="Synthetic Mechanical"))
    result = native_update((content,), "activity_summary")
    paragraphs = result.text.split("\n\n")
    assert len(paragraphs) == 2
    assert paragraphs[0] == (
        "2026-09-10 · Synthetic Mechanical — - Inspected fan EF-31 and confirmed it did not start.")
    assert paragraphs[1] == (
        "2026-09-10 · Synthetic Mechanical — - Replaced the actuator on valve IV-8 and confirmed normal operation.")
    assert result.text.count("2026-09-10 · Synthetic Mechanical") == 2


def test_unpunctuated_separate_bullets_are_not_joined(monkeypatch, tmp_path):
    _, content = ingest_lines(monkeypatch, tmp_path, (
        "- Inspected the condenser drive belt",
        "- Replaced the intake filter",
    ))
    result = native_update((content,), "activity_summary")
    assert result.text.split("\n\n") == [
        "- Inspected the condenser drive belt", "- Replaced the intake filter"]


@requires_libreoffice
def test_wrapped_negative_event_prints_once_in_real_docx_and_pdf(monkeypatch, tmp_path):
    from app.monthly_report_docx import generate_report
    from app import monthly_report_library as library
    from app.monthly_report_source_details import correct_source_details

    expected = "The technician inspected fan EF-31 and confirmed it did not start."
    profile, content = ingest_lines(monkeypatch, tmp_path, (
        "The technician inspected fan EF-31 and confirmed it", "did not start."))
    content = replace(content, source=correct_source_details(
        content.source, profile, None, profile.facilities[0].key))
    activity = native_update((content,), "activity_summary")
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Reviewer",
        (SectionSpec("activity", "2", "Monthly Activity Summary",
                     (BlockSpec("activity_summary", "rich_text"),)),),
        (activity,), sources=(content.source,))
    # Real versioned serialization/readback precedes normal assembly/conversion.
    saved = library.save_snapshot(draft, expected_revision=0,
                                  entered_editor=draft.prepared_by)
    restored = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert restored.revision == saved.revision
    assert restored.draft.blocks[0].text == expected
    package = generate_report(restored.draft,
                              acknowledged_fingerprint=restored.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    output = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    (output / "wrapped_activity.docx").write_bytes(package.docx)
    (output / "wrapped_activity.pdf").write_bytes(package.pdf)
    (output / "wrapped_activity.json").write_text(json.dumps({
        "tested_revision": os.environ.get("MSAPO_SHA", "unrecorded"),
        "source_sha256": content.source.sha256,
        "source_fingerprint": content.source.fingerprint,
        "draft_fingerprint": restored.draft.fingerprint,
        "saved_revision": restored.revision,
        "docx_bytes": len(package.docx), "docx_sha256": sha256(package.docx).hexdigest(),
        "pdf_bytes": len(package.pdf), "pdf_sha256": sha256(package.pdf).hexdigest(),
    }, indent=2) + "\n")
    docx_text = "\n".join(p.text for p in Document(BytesIO(package.docx)).paragraphs)
    assert docx_text.count(expected) == 1
    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        pdf_text = " ".join(" ".join(page.get_text().split()) for page in pdf)
        for index, page in enumerate(pdf, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(
                output / f"wrapped_activity_page_{index}.png")
    assert pdf_text.count(expected) == 1
