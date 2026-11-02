"""Filesystem-safe Monthly Word/PDF output names, without changing short names.

All contract/site names are synthetic; no real report or source file is read.
"""

import errno
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.monthly_report_model import (
    MAX_REPORT_FILENAME_BYTES, ReportDraft, ReportPeriod, report_filename,
    synthetic_profiles,
)


def synthetic_draft(title="UMMC Central Plant", contract="ENFRA"):
    return SimpleNamespace(profile=SimpleNamespace(title=title, contract=contract),
                           period=ReportPeriod(2026, 9))


@pytest.mark.parametrize("extension", ["docx", "pdf"])
def test_short_existing_filename_stays_byte_identical(extension):
    assert report_filename(synthetic_draft(), extension) == (
        f"ENFRA - UMMC Central Plant September 2026 Monthly Report.{extension}")


@pytest.mark.parametrize("title,contract", [
    ("A" * 251, "ENFRA"), ("站点" * 94, "ENFRA"),
    ("🏭" * 75, "ENFRA"), ("Central Plant", "Client" * 50),
    ("Long Name " * 60, "Contract" * 40),
    ("先📄" * 120, "合同" * 56),
])
def test_long_utf8_names_are_bounded_paired_and_readable(title, contract):
    draft = synthetic_draft(title=title, contract=contract)
    docx = report_filename(draft, "docx")
    pdf = report_filename(draft, "pdf")
    assert len(docx.encode("utf-8")) <= MAX_REPORT_FILENAME_BYTES
    assert len(pdf.encode("utf-8")) <= MAX_REPORT_FILENAME_BYTES
    assert docx.removesuffix(".docx") == pdf.removesuffix(".pdf")
    assert docx.endswith(" September 2026 Monthly Report.docx")
    assert re.search(r"\[[0-9a-f]{12}\] September 2026 Monthly Report.docx$", docx)
    assert docx == report_filename(draft, "docx")


def test_long_unicode_names_can_be_written_to_actual_filesystem(tmp_path):
    draft = synthetic_draft(title="📄" * 100)
    filename = report_filename(draft, "docx")
    (tmp_path / filename).write_bytes(b"synthetic only")
    assert (tmp_path / filename).read_bytes() == b"synthetic only"


def test_distinct_truncated_names_keep_distinct_paths():
    prefix = "North " * 70
    a = report_filename(synthetic_draft(prefix + "alpha"), "docx")
    b = report_filename(synthetic_draft(prefix + "beta"), "docx")
    assert a != b
    assert len(a.encode()) <= MAX_REPORT_FILENAME_BYTES
    assert len(b.encode()) <= MAX_REPORT_FILENAME_BYTES


def test_truncation_never_splits_multibyte_unicode():
    draft = synthetic_draft(title="🏭" * 91)
    filename = report_filename(draft, "docx")
    assert filename.encode("utf-8").decode("utf-8") == filename


@pytest.mark.parametrize("extension", ["docx", "pdf"])
def test_boundary_safe_short_name_remains_identical(extension):
    suffix = " September 2026 Monthly Report"
    prefix = "ENFRA - "
    capacity = MAX_REPORT_FILENAME_BYTES - len(".docx") - len((prefix + suffix).encode())
    filename = report_filename(synthetic_draft("A" * capacity), extension)
    assert filename == f"{prefix}{'A' * capacity}{suffix}.{extension}"


@pytest.mark.parametrize("extension", ["docx", "pdf"])
def test_first_over_limit_name_is_shortened(extension):
    suffix = " September 2026 Monthly Report"
    capacity = MAX_REPORT_FILENAME_BYTES - len(".docx") - len(("ENFRA - " + suffix).encode())
    filename = report_filename(synthetic_draft("A" * (capacity + 1)), extension)
    assert len(filename.encode("utf-8")) <= MAX_REPORT_FILENAME_BYTES
    assert filename.endswith(f"{suffix}.{extension}")
    assert "[" in filename


def test_existing_path_separator_and_control_sanitization_is_preserved():
    filename = report_filename(synthetic_draft(title='Bldg/5:Foam\\Heat\nControl?'), "pdf")
    assert filename == "ENFRA - Bldg-5-Foam-Heat-Control- September 2026 Monthly Report.pdf"


@pytest.mark.parametrize("extension", [
    "", "PDF", "txt", "../pdf", ".docx", "docx\nSet-Cookie:x",
])
def test_unexpected_extension_cannot_create_unsafe_path(extension):
    with pytest.raises(ValueError, match="extension"):
        report_filename(synthetic_draft(), extension)


@pytest.mark.parametrize("title", ["\ud800", "\udfff", "U\ud800M\udfffM" * 90])
def test_invalid_unicode_surrogates_are_sanitized(title):
    filename = report_filename(synthetic_draft(title), "docx")
    assert filename.encode("utf-8")
    assert len(filename.encode("utf-8")) <= MAX_REPORT_FILENAME_BYTES
    assert "\ud800" not in filename and "\udfff" not in filename


def test_unbounded_baseline_really_fails_filesystem_component_limit(tmp_path):
    raw_title = "Very-Long-Synthetic-Title-" * 20
    original_name = f"ENFRA - {raw_title} September 2026 Monthly Report.docx"
    with pytest.raises(OSError) as failure:
        (tmp_path / original_name).write_bytes(b"synthetic")
    assert failure.value.errno == errno.ENAMETOOLONG


def test_real_report_draft_preserves_paired_filenames_and_exact_period():
    profile = replace(synthetic_profiles()[0], contract="Synthetic Client",
                      title="Long Multi-Word Facility Name " * 20)
    draft = ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic Preparer", (), ())
    docx, pdf = (report_filename(draft, ext) for ext in ("docx", "pdf"))
    assert docx.removesuffix(".docx") == pdf.removesuffix(".pdf")
    assert docx.endswith(" October 2026 Monthly Report.docx")
    assert len(docx.encode()) <= MAX_REPORT_FILENAME_BYTES
