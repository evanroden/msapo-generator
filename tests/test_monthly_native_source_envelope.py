"""Native artwork admission stays finite and independently bounded."""
import pytest
from app import monthly_report_compatibility_view as view


def test_source_admission_supports_bounded_32_mib_envelope():
    assert view.MAX_VIEW_SOURCE_BYTES == 32 * 1024 * 1024
    view._budget('source byte budget', 25 * 1024 * 1024, view.MAX_VIEW_SOURCE_BYTES)
    view._budget('source byte budget', view.MAX_VIEW_SOURCE_BYTES, view.MAX_VIEW_SOURCE_BYTES)
    with pytest.raises(view.CompatibilityBudgetError, match='source byte budget'):
        view._budget('source byte budget', view.MAX_VIEW_SOURCE_BYTES + 1, view.MAX_VIEW_SOURCE_BYTES)


def test_independent_processing_budgets_are_not_raised():
    assert view.MAX_VIEW_EXPANDED_BYTES == 32 * 1024 * 1024
    assert view.MAX_VIEW_MEDIA_BYTES == 16 * 1024 * 1024
    assert view.MAX_VIEW_XML_BYTES == 20 * 1024 * 1024
    assert view.MAX_VIEW_XML_NODES == 120_000
    assert view.MAX_VIEW_PARTS == 512
    assert view.MAX_VIEW_XML_DEPTH == 64
