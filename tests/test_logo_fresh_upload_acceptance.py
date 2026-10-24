"""Synthetic acceptance rejects old bytes, wrong roles and missing fresh uploads."""
from hashlib import sha256
from types import SimpleNamespace

import pytest

from scripts import qa_single_logo_admin as qa


def receipt(raw=b'new synthetic upload'):
    return dict(selected_key='synthetic-recovery', catalog_revision=3,
                upload_present=True, upload_size=len(raw), upload_sha256=sha256(raw).hexdigest())


@pytest.mark.parametrize('field,value', [
    ('selected_key', 'synthetic-control'), ('catalog_revision', 2),
    ('upload_present', False), ('upload_size', 0),
    ('upload_sha256', sha256(b'old synthetic upload').hexdigest()),
])
def test_fresh_receipt_rejects_wrong_identity_or_retained_bytes(field, value):
    state = receipt(); state[field] = value
    with pytest.raises(AssertionError):
        qa.validate_upload_state(state, 'synthetic-recovery', 3, b'new synthetic upload')


def test_empty_and_missing_upload_are_not_interchangeable():
    absent = dict(selected_key='synthetic-recovery', catalog_revision=3,
                  upload_present=False, upload_size=0, upload_sha256='')
    assert qa.validate_upload_state(absent, 'synthetic-recovery', 3, None) == absent
    with pytest.raises(AssertionError):
        qa.validate_upload_state(absent, 'synthetic-recovery', 3, b'')
    assert qa.validate_upload_state(receipt(), 'synthetic-recovery', 3, b'new synthetic upload') == receipt()


def test_three_cycles_clear_before_switch_and_use_distinct_payloads(monkeypatch):
    events = []; payloads = []
    class Page:
        def get_by_role(self, role, *, name, exact):
            assert exact
            if role == 'button':
                assert name == 'Remove synthetic-approved.png'
                return SimpleNamespace(click=lambda: events.append('remove'))
            assert role == 'checkbox'
            return object()
        def get_by_text(self, text, *, exact):
            assert exact
            return object()
    monkeypatch.setattr(qa, 'expect', lambda target: SimpleNamespace(
        to_have_count=lambda n: events.append('no-confirm'),
        to_be_visible=lambda: None), raising=False)
    def observation(page, raw):
        events.append('absent' if raw is None else 'fresh')
        return {'digest': sha256(raw).hexdigest()} if raw is not None else {}
    monkeypatch.setattr(qa, 'upload_receipt', observation)
    monkeypatch.setattr(qa, 'choose', lambda page,label,value: events.append(value))
    monkeypatch.setattr(qa, 'revision', lambda page,value: events.append('revision3'))
    monkeypatch.setattr(qa, 'review', lambda page,raw: (events.append('fast-review'), payloads.append(raw)))
    monkeypatch.setattr(qa, 'approve_review', lambda page: events.append('approve'))
    record = {}; qa.fresh_switch_upload_cycles(Page(), record)
    assert events == ['remove','absent','no-confirm','Synthetic healthy logo','revision3',
                      'Synthetic recovery logo','fast-review','fresh','revision3','approve'] * 3
    assert len(payloads) == len(set(payloads)) == 3
    assert len(record['fresh_upload_cycles']) == 3


def test_first_failed_cycle_stops_without_rescue_or_retry(monkeypatch):
    class Page:
        def get_by_role(self, *args, **kwargs):
            return SimpleNamespace(click=lambda: None)
    attempts = []
    def reject(page, raw):
        attempts.append(raw)
        raise AssertionError('first fresh-state failure')
    monkeypatch.setattr(qa, 'upload_receipt', reject)
    record = {}
    with pytest.raises(AssertionError, match='first fresh-state failure'):
        qa.fresh_switch_upload_cycles(Page(), record)
    assert attempts == [None] and record['fresh_upload_cycles'] == []
    assert record['stage'] == 'fresh switch/upload cycle 1'
