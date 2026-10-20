"""PDF retry preserves legacy admission without downgrading scoped evidence."""
from contextlib import contextmanager
from dataclasses import replace
import json

import pytest

from app import monthly_report_docx as word, monthly_report_library as library
from app import monthly_report_render_jobs as jobs
from app.monthly_report_asset_review import approve_all_assets
from test_monthly_report_native_art_review import sample
from test_monthly_report_native_art_lifecycle import save_sample


def cached_package(sample, monkeypatch):
    draft, loader = save_sample(sample)
    draft = replace(draft, blocks=tuple(approve_all_assets(block) for block in draft.blocks))
    monkeypatch.setattr(word, '_convert_report_pdf', lambda *a: (b'%PDF-synthetic-adapter', ''))
    package = word.generate_report(draft, asset_loader=loader,
                                  acknowledged_fingerprint=draft.fingerprint)
    assert package.pdf and package.source_view_digest and package.source_view_art_digest
    return draft, package


def test_cached_scoped_retry_rederives_once_under_one_admission(sample, monkeypatch):
    draft, package = cached_package(sample, monkeypatch)
    events = []
    original_slot = jobs.work_slot
    original_verify = library.verified_render_source_view

    @contextmanager
    def slot(**kwargs):
        if not getattr(jobs._WORK_LOCAL, 'active', False):
            events.append('slot')
        with original_slot(**kwargs):
            yield

    def verify(*args, **kwargs):
        assert jobs._WORK_LOCAL.active
        events.append('verify')
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(jobs, 'work_slot', slot)
    monkeypatch.setattr(library, 'verified_render_source_view', verify)
    monkeypatch.setattr(word, '_convert_report_pdf', lambda *a: pytest.fail('Cached PDF must not convert'))
    assert word.retry_report_pdf(draft, package) is package
    assert events == ['slot', 'verify']


@pytest.mark.parametrize('damage', ['untagged', 'digest-only', 'word-only', 'art-only',
                                   'malformed-index', 'receipt', 'suitability'])
def test_cached_retry_never_downgrades_present_scoped_evidence(sample, monkeypatch, damage):
    draft, package = cached_package(sample, monkeypatch)
    folder = library._profile_path(draft.profile.contract, draft.profile.key)
    if damage in ('untagged', 'digest-only', 'word-only', 'art-only'):
        package = replace(package,
            source_view_digest=package.source_view_digest if damage == 'digest-only' else '',
            source_view_docx_sha256=package.source_view_docx_sha256 if damage == 'word-only' else '',
            source_view_art_digest=package.source_view_art_digest if damage == 'art-only' else '')
    elif damage == 'receipt':
        next((folder/'imports').glob('*.source-view.json')).write_bytes(b'{}')
    else:
        path = folder/'manifest.json'
        value = json.loads(path.read_bytes())
        if damage == 'malformed-index':
            value['source_views'] = []
            # All tags cleared still must not turn malformed persisted evidence
            # into an ordinary cached result.
            package = replace(package, source_view_digest='', source_view_docx_sha256='',
                              source_view_art_digest='')
        else:
            value.pop('source_view_art_reviews')
        path.write_text(json.dumps(value))
    monkeypatch.setattr(word, '_convert_report_pdf', lambda *a: pytest.fail('Invalid retry must not convert'))
    with pytest.raises(ValueError):
        word.retry_report_pdf(draft, package)


def test_scoped_retry_stale_fingerprint_refuses_before_admission(sample, monkeypatch):
    draft, package = cached_package(sample, monkeypatch)
    monkeypatch.setattr(jobs, 'work_slot', lambda **kw: pytest.fail('Stale retry must not acquire work'))
    with pytest.raises(ValueError, match='earlier draft'):
        word.retry_report_pdf(replace(draft, prepared_by='Changed editor'), package)
