"""Impossible dates in vendor-native PDF metadata require ordinary source review.

Refs #791/#270. All examples and document bytes here are synthetic.
"""

import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_structured_uploads import native_update
from app.monthly_report_vendor_passages import (
    safe_remainder, typed_metadata, unsupported_fields,
)
from test_vendor_pdf_passages import fixture


@pytest.mark.parametrize("line", [
    "Report date: 2026-02-30",
    "Date: 2026-13-01",
    "Service date: 99/99/2026",
    "Date: 02/30/26",
    "Date: 31/31/2026",
    "Date: 00/00/26",
    "Report date: 1900-02-29",
    "Service date: 02/29/2026",
])
def test_impossible_date_is_never_ignored_as_typed_metadata(line):
    assert not typed_metadata(line)
    assert not safe_remainder("Vendor service report\n" + line)
    assert unsupported_fields("Actions: Inspected the invented valve.\n" + line)


@pytest.mark.parametrize("line", [
    "Report date: 2024-02-29",
    "Service date: 02/29/2024",
    "Date: 29/02/2024",
    "Date: 11/06/2026",
    "Date: 06/11/2026",
    "Report date: 2026-12-31",
    "Date: 02/29/00",
    "Report date: 02/28/99",
    "Date: 3/4/123",
])
def test_real_calendar_date_remains_valid_non_authoritative_metadata(line):
    assert typed_metadata(line)
    assert safe_remainder("Vendor service report\n" + line)
    assert not unsupported_fields(line + "\nActions: Inspected the invented valve.")


@pytest.mark.parametrize("position", ["before", "after"])
def test_bad_pdf_report_date_blocks_automatic_action_and_preserves_source(
    monkeypatch, tmp_path, position,
):
    action = "Actions: Inspected the synthetic valve."
    bad_date = "Report date: 2026-02-30"
    fields = ([bad_date, action] if position == "before" else [action, bad_date])
    content, raw = fixture(monkeypatch, tmp_path, fields)
    source = content.source
    assert bad_date in source.page_texts[0]
    assert source.actions == ""
    assert not sources.action_evidence(source)[0]
    assert action not in native_update((content,), "activity_summary").text
    assert any("review" in message.casefold() for message in source.notices)
    assert sources.source_bytes(synthetic_profiles()[0], source) == raw


def test_valid_pdf_report_date_does_not_block_genuine_action(
    monkeypatch, tmp_path,
):
    action = "Actions: Inspected the synthetic valve."
    content, raw = fixture(monkeypatch, tmp_path, [
        "Report date: 2024-02-29", action,
    ])
    assert content.source.actions == action
    assert action in native_update((content,), "activity_summary").text
    assert sources.source_bytes(synthetic_profiles()[0], content.source) == raw
