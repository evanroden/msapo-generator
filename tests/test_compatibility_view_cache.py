"""The native source view is reused for identical bytes and rebuilt otherwise."""
from app import monthly_report_compatibility_view as cv


def test_same_bytes_reuse_one_derivation_and_new_bytes_rebuild(monkeypatch):
    cv.clear_view_cache()
    calls = []

    def fake(raw):
        calls.append(raw)
        return ('view', raw)

    monkeypatch.setattr(cv, '_derive_compatibility_view', fake)
    first = cv.derive_compatibility_view(b'report one')
    assert cv.derive_compatibility_view(b'report one') is first
    assert len(calls) == 1
    assert cv.derive_compatibility_view(b'report two') == ('view', b'report two')
    assert len(calls) == 2
    cv.clear_view_cache()


def test_cache_keeps_only_the_newest_two_files(monkeypatch):
    cv.clear_view_cache()
    calls = []
    monkeypatch.setattr(cv, '_derive_compatibility_view', lambda raw: calls.append(raw) or raw)
    for raw in (b'a', b'b', b'c', b'a'):
        cv.derive_compatibility_view(raw)
    assert calls == [b'a', b'b', b'c', b'a']
    cv.clear_view_cache()


def test_failed_derivation_is_not_cached(monkeypatch):
    cv.clear_view_cache()
    calls = []

    def boom(raw):
        calls.append(raw)
        raise cv.CompatibilityError('bad package')

    monkeypatch.setattr(cv, '_derive_compatibility_view', boom)
    for _ in range(2):
        try:
            cv.derive_compatibility_view(b'broken')
        except cv.CompatibilityError:
            pass
    assert len(calls) == 2
    cv.clear_view_cache()


def test_a_changed_limit_derives_again(monkeypatch):
    cv.clear_view_cache()
    calls = []
    monkeypatch.setattr(cv, '_derive_compatibility_view', lambda raw: calls.append(raw) or raw)
    cv.derive_compatibility_view(b'report')
    monkeypatch.setattr(cv, 'MAX_VIEW_XML_NODES', cv.MAX_VIEW_XML_NODES - 1)
    cv.derive_compatibility_view(b'report')
    assert len(calls) == 2
    cv.clear_view_cache()
