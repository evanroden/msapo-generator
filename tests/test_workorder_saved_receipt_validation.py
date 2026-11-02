"""Damaged saved review JSON is rejected without losing source or review evidence."""
from dataclasses import asdict, replace
import json

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_work_order_review_flow as flow
from test_monthly_report_work_order_review_flow import draft_source
from test_monthly_report_work_order_review_ui import SCRIPT


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    return draft_source()


@pytest.mark.parametrize('text', ['[]', 'null', '123', 'true', '"text"', '{broken'])
def test_snapshot_load_rejects_nonobject_or_malformed_receipt(source, text):
    draft, content = source
    record = asdict(replace(draft, source_row_reviews=(text,)))
    with pytest.raises(library.LibraryError):
        library.draft_from_dict(record)
    assert record['source_row_reviews'] == (text,)
    assert record['sources'][0]['id'] == content.source.id


@pytest.mark.parametrize('part,bad', [('groups', [1]), ('groups', {}),
                                    ('published', [1]), ('published', {}),
                                    ('groups', [{'record': []}])])
def test_snapshot_load_rejects_nested_malformed_containers(source, part, bad):
    draft, content = source
    bundle = flow.prepare_bundle(draft, content)
    bundle[part] = bad
    text = flow.encoded(bundle)
    with pytest.raises(library.LibraryError):
        library.draft_from_dict(asdict(replace(draft, source_row_reviews=(text,))))


@pytest.mark.parametrize('text', ['[]', 'null', '123'])
def test_native_review_handles_preexisting_inmemory_bad_receipts_without_exception(source, text):
    draft, content = source
    broken = replace(draft, source_row_reviews=(text,))
    with pytest.raises(ValueError):
        flow.saved_bundle(broken, content.source.id, 'workorders')
    app = AppTest.from_string(SCRIPT, default_timeout=20)
    app.session_state['draft'] = broken
    app.session_state['content'] = content
    app.run()
    assert not app.exception
    assert app.warning
    assert app.session_state['draft'] == broken


def test_valid_and_stale_receipts_roundtrip_without_granting_current_authority(source):
    draft, content = source
    bundle = flow.prepare_bundle(draft, content)
    stored = flow.store_bundle(draft, bundle)
    restored = library.draft_from_dict(asdict(stored))
    assert restored == stored
    assert flow.saved_bundle(restored, content.source.id, 'workorders') == bundle
    stale = replace(stored, period=replace(stored.period, month=10))
    reopened = library.draft_from_dict(asdict(stale))
    assert reopened.source_row_reviews == stored.source_row_reviews
    assert flow.saved_bundle(reopened, content.source.id, 'workorders') is None
    assert reopened.blocks == stored.blocks


def test_oversized_individual_receipt_rejected_before_restore(source):
    draft, content = source
    bundle = flow.prepare_bundle(draft, content)
    bundle['filename'] = 'x' * 4_000_001
    with pytest.raises(library.LibraryError):
        library.draft_from_dict(asdict(replace(draft, source_row_reviews=(flow.encoded(bundle),))))
