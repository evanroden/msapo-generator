from dataclasses import replace
import pytest
from app import monthly_report_cover_originals as originals
from app.monthly_report_model import ReportProfile, Facility

@pytest.fixture
def profile(tmp_path, monkeypatch):
    from app import monthly_report_library as library
    monkeypatch.setattr(library, '_root', lambda: tmp_path)
    return ReportProfile('Contract A', 'site_a', 'Site A', (Facility('a','A'),))


def test_original_stored_once_integrity_checked_and_profile_scoped(profile):
    raw = b'original photograph bytes'
    ref = originals.store_cover_original(profile, raw)
    path = originals.cover_original_path(profile, ref)
    before = path.stat().st_mtime_ns
    assert originals.store_cover_original(profile, raw) == ref
    assert path.stat().st_mtime_ns == before
    assert path.read_bytes() == raw
    with pytest.raises(ValueError, match='scope'):
        originals.cover_original_path(replace(profile, contract='Contract B'), ref)
    path.chmod(0o600)  # Simulate external disk corruption, not an application write.
    path.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='integrity'):
        originals.cover_original_path(profile, ref)


def test_quota_does_not_evict_originals_and_dedup_does_not_consume_more(profile, monkeypatch):
    monkeypatch.setattr(originals, 'MAX_ORIGINAL_STORE_BYTES', 10)
    ref = originals.store_cover_original(profile, b'123456')
    assert originals.store_cover_original(profile, b'123456') == ref
    with pytest.raises(ValueError, match='storage'):
        originals.store_cover_original(profile, b'abcdef')
    assert originals.cover_original_path(profile, ref).read_bytes() == b'123456'


def test_size_admission_before_any_write(profile, monkeypatch):
    monkeypatch.setattr(originals, 'MAX_ORIGINAL_BYTES', 3)
    with pytest.raises(ValueError):
        originals.store_cover_original(profile, b'1234')
    with pytest.raises(ValueError):
        originals.store_cover_original(profile, b'')
