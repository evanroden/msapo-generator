"""Synthetic malformed source/page reference tests; no private report data.

Refs #284, #298 and #270. All sources/asset identities are invented.
"""

from types import SimpleNamespace

import pytest

from app.monthly_report_page_reference import page_identity


SOURCE_ID = "a" * 64
SOURCE_REVISION = "b" * 64


def ref(number):
    return f"{SOURCE_ID}:{number}:{SOURCE_REVISION}"


@pytest.mark.parametrize("page,expected", [
    ("1", 1), ("2", 2), ("001", 1), ("500", 500),
])
def test_canonical_and_padded_ascii_source_pages_preserve_identity(page, expected):
    assert page_identity(ref(page)) == (SOURCE_ID, expected)


@pytest.mark.parametrize("page", [
    "²", "①", "٤", "９", "0", "000", "-1", "+1", "1.0", "",
    "1" * 4301, "9" * 10_000, "1234567", " 1", "1 ",
], ids=lambda page: f"{page[:8]}...len={len(page)}" if len(page) > 32 else repr(page))
def test_invalid_or_unbounded_numerals_never_raise_or_claim_page_identity(page):
    assert page_identity(ref(page)) is None


@pytest.mark.parametrize("reference", [
    "", "invalid", f"{SOURCE_ID}:1", f"{SOURCE_ID}:1:{SOURCE_REVISION}:extra",
    f"asset-source-context:v1:{SOURCE_ID}:1:{SOURCE_REVISION}",
    None, 1, (SOURCE_ID, 1, SOURCE_REVISION),
])
def test_other_legacy_routes_and_non_string_values_are_not_page_ids(reference):
    assert page_identity(reference) is None


def test_malformed_asset_reference_cannot_displace_valid_page_owner():
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_section_uploads import included_pages
    broken = ResolvedBlock("water_reports", "This month", asset_hashes=("synthetic-a.png",),
                           references=(ref("²"),))
    healthy = ResolvedBlock("vendor_reports", "This month", asset_hashes=("synthetic-b.png",),
                            references=(ref("2"),))
    result = included_pages({"water_reports": broken, "vendor_reports": healthy})
    assert result == {(SOURCE_ID, 2): {"vendor_reports"}}
    assert broken.references == (ref("²"),) and healthy.references == (ref("2"),)


def test_bad_source_reference_never_authorizes_page_review():
    from app.monthly_report_asset_review import (current_source_page_review_matches,
                                                 refresh_asset_source_context)
    from app.monthly_report_model import ResolvedBlock
    malformed = ref("²")
    block = ResolvedBlock("water_reports", "This month", asset_hashes=("synthetic.png",),
                          references=(malformed,),
                          asset_provenance=(("synthetic.png", (malformed,)),))
    source = SimpleNamespace(id=SOURCE_ID, page_texts=("Synthetic page",))
    assert current_source_page_review_matches(block, 0, source, 1) is False
    updated = refresh_asset_source_context(block, (source,))
    assert updated.client_asset_reviews == ()
    assert any(item.endswith(":invalid:missing")
               for _, refs in updated.asset_provenance for item in refs)
    assert block.references == (malformed,)


def test_exact_approved_ascii_page_ref_still_enters_same_owner():
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_section_uploads import included_pages
    block = ResolvedBlock("mbcx_report", "This month", asset_hashes=("synthetic.png",),
                          references=(ref("1"),))
    assert included_pages({"mbcx_report": block}) == {(SOURCE_ID, 1): {"mbcx_report"}}
