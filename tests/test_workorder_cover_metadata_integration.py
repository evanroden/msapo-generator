"""Work-order receipts and private cover intent retain distinct contracts."""
from dataclasses import asdict, replace

import pytest

from app.monthly_report_library import LibraryError, draft_from_dict
from app.monthly_report_model import CoverRecoveryRequest, ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_setup import new_month_draft


def example():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    request = CoverRecoveryRequest('a' * 32, 'b' * 64, 'c' * 64, 'd' * 64,
                                   128, 'e' * 64, 0)
    return draft, request


def test_cover_intent_is_private_but_nonempty_row_receipts_bind_content():
    draft, request = example()
    covered = replace(draft, cover_recovery_request=request)
    reviewed = replace(covered, source_row_reviews=('{"schema":1,"scope":"synthetic","source_id":"synthetic","source_fingerprint":"synthetic","filename":"synthetic.csv","kind":"workorders","date_order":"","groups":[],"published":[]}',))
    assert covered.fingerprint == draft.fingerprint
    assert reviewed.fingerprint != covered.fingerprint
    assert replace(reviewed, cover_recovery_request=None).fingerprint == reviewed.fingerprint
    assert draft_from_dict(asdict(reviewed)) == reviewed
    assert draft_from_dict(asdict(reviewed)).fingerprint == reviewed.fingerprint


def test_new_month_clears_both_metadata_types_only_at_period_boundary():
    draft, request = example()
    both = replace(draft, cover_recovery_request=request,
                   source_row_reviews=('{"schema":1,"scope":"synthetic","source_id":"synthetic","source_fingerprint":"synthetic","filename":"synthetic.csv","kind":"workorders","date_order":"","groups":[],"published":[]}',))
    assert new_month_draft(both, both.period) == both
    changed = new_month_draft(both, ReportPeriod(2026, 10))
    assert changed.cover_recovery_request is None
    assert changed.source_row_reviews == ()
    assert both.cover_recovery_request == request
    assert both.source_row_reviews == ('{"schema":1,"scope":"synthetic","source_id":"synthetic","source_fingerprint":"synthetic","filename":"synthetic.csv","kind":"workorders","date_order":"","groups":[],"published":[]}',)


@pytest.mark.parametrize('receipts', ['not-a-sequence', [1], ['x'] * 101, ['x' * 16_000_001]])
def test_receipt_validation_still_rejects_invalid_saved_records_with_cover(receipts):
    draft, request = example()
    record = asdict(replace(draft, cover_recovery_request=request))
    record['source_row_reviews'] = receipts
    with pytest.raises(LibraryError):
        draft_from_dict(record)


def test_cover_validation_is_not_bypassed_by_valid_receipt_container():
    draft, request = example()
    record = asdict(replace(draft, cover_recovery_request=request,
                           source_row_reviews=('{"schema":1,"scope":"synthetic","source_id":"synthetic","source_fingerprint":"synthetic","filename":"synthetic.csv","kind":"workorders","date_order":"","groups":[],"published":[]}',)))
    record['cover_recovery_request']['byte_count'] = -1
    with pytest.raises(LibraryError):
        draft_from_dict(record)
