"""Fail-closed source-scope checks for malformed included references.

All fixtures are synthetic, with no customer source files or external readers.
Refs #298 and #270.
"""
from dataclasses import replace

import pytest

from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock,
    SectionSpec, synthetic_profiles, used_source_ids,
)
from app.monthly_report_source_scope import (
    included_scope_valid, source_uses,
)

SOURCE_ID = "a" * 64
SHA = "b" * 64
PERIOD = ReportPeriod(2026, 10)
PROFILE = synthetic_profiles()[0]
TEXT = "Synthetic engineer inspected the air handling equipment."
SOURCE = ReportSource(
    SOURCE_ID, "synthetic-unknown-site.txt", SHA, ".txt",
    classification="Vendor service", facility="",
    service_date="2026-10-08", page_texts=(TEXT,),
)
SECTIONS = (SectionSpec(
    "activity", "2", "Monthly Activity",
    (BlockSpec("activity_summary", "rich_text"),),
),)


def _draft(page="1", *, source="This month", include=True, cited=True):
    origin = f"{SOURCE_ID}:{page}:{SOURCE.fingerprint}"
    block = ResolvedBlock(
        "activity_summary", source, TEXT,
        references=(origin,) if cited else (),
    )
    return ReportDraft(
        PROFILE, PERIOD, "Synthetic editor",
        (replace(SECTIONS[0], included=include),),
        (block,), synthetic=True, sources=(SOURCE,),
    )


def _site_blockers(draft):
    return tuple(check for check in preflight(draft)
                 if check.blocking and check.code == "source_facility")


@pytest.mark.parametrize("page", ["0", "000", "000000", "²", "٥", "９", "1234567"])
def test_included_malformed_reference_never_bypasses_unknown_site_scope(page):
    draft = _draft(page)
    # The existing broad dependency scan already treats this source as used.
    assert SOURCE_ID in used_source_ids(draft)
    # Strict source-use parsing cannot credit the malformed source/page token.
    assert source_uses(draft, SOURCE_ID) == ()
    # Missing recognized uses must not be misread as approved site evidence.
    assert not included_scope_valid(draft, SOURCE)
    checks = _site_blockers(draft)
    assert len(checks) == 1
    assert "Establish the site scope" in checks[0].message


def test_direct_word_generation_blocks_unverified_orphaned_reference():
    draft = _draft("0")
    with pytest.raises(ValueError, match="Establish the site scope"):
        assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)


def test_canonical_source_reference_still_requires_scope_decision():
    draft = _draft("1")
    assert SOURCE_ID in used_source_ids(draft)
    assert len(source_uses(draft, SOURCE_ID)) == 1
    assert not included_scope_valid(draft, SOURCE)
    assert len(_site_blockers(draft)) == 1


@pytest.mark.parametrize("change", [{"source": "Omit"}, {"include": False}, {"cited": False}])
def test_unused_or_explicitly_omitted_source_never_gets_a_false_site_block(change):
    draft = _draft("0", **change)
    assert SOURCE_ID not in used_source_ids(draft)
    assert source_uses(draft, SOURCE_ID) == ()
    assert included_scope_valid(draft, SOURCE)
    assert _site_blockers(draft) == ()


def test_no_source_citation_does_not_fabricate_acceptance_or_delete_text():
    draft = _draft("0", cited=False)
    assert draft.blocks[0].text == TEXT
    assert draft.sources == (SOURCE,)
    assert _site_blockers(draft) == ()
