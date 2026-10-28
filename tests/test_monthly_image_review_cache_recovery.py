"""Recover corrupt disposable image-reading results; preserve the 20-image ledger.

Synthetic review identities and result text only; no client images or network work.
Refs #300 and #270.
"""

from contextlib import contextmanager
from hashlib import sha256
import json

import pytest

from app import monthly_report_image_review as review


SCOPE = "Synthetic report scope"
FIRST = sha256(b"synthetic first image").hexdigest()
SECOND = sha256(b"synthetic second image").hexdigest()
CONTENT = [{"type": "text", "text": "Invented image-reading request"}]


@pytest.fixture(autouse=True)
def private_review_directory(tmp_path, monkeypatch):
    # Keep the actual library's bounded JSON/atomic write/lock primitives; only
    # route storage to a new synthetic scope instead of a shared report disk.
    monkeypatch.setattr(review, "review_directory", lambda scope:
                        tmp_path / "image_reviews" / sha256(scope.encode()).hexdigest())


def _cache(digest=FIRST):
    return review.review_directory(SCOPE) / (digest + ".json")


def _reserve(digest=FIRST):
    return review.reserve_review(SCOPE, digest, CONTENT)


def _store(digest=FIRST, text="Synthetic inspection finished"):
    review.library._atomic_write(_cache(digest),
                                 review.library._json({"schema": 1, "text": text}))


def _initial(digest=FIRST):
    assert _reserve(digest) == (digest, "", CONTENT)
    assert review.remaining_reviews(SCOPE) == review.MAX_IMAGE_REVIEWS - 1


def test_valid_cached_result_reused_without_another_request_or_quota_charge():
    _initial()
    _store()
    assert _reserve() == (FIRST, "Synthetic inspection finished", None)
    assert review.remaining_reviews(SCOPE) == 19


@pytest.mark.parametrize("damaged", [
    b"{incomplete",
    b"[]",
    b'{"schema": 2}',
    b'{"schema": 1}',
    b'{"schema": 1, "text": null}',
    b'{"schema": 1, "text": []}',
    b'{"schema": 1, "text": ""}',
    b'{"schema": 1, "text": "   "}',
    json.dumps({"schema": 1, "text": "x" * 40001}).encode(),
])
def test_bad_disposable_result_can_retry_without_double_charging(damaged):
    _initial()
    _cache().write_bytes(damaged)
    assert _reserve() == (FIRST, "", CONTENT)
    assert review.remaining_reviews(SCOPE) == 19
    _store()
    assert _reserve() == (FIRST, "Synthetic inspection finished", None)


def test_one_bad_result_never_changes_other_cached_images():
    _initial()
    assert _reserve(SECOND) == (SECOND, "", CONTENT)
    _store(FIRST, "First finding")
    _store(SECOND, "Second finding")
    unaffected = _cache(SECOND).read_bytes()
    _cache(FIRST).write_bytes(b"{corrupt")
    assert _reserve(FIRST) == (FIRST, "", CONTENT)
    assert _reserve(SECOND) == (SECOND, "Second finding", None)
    assert _cache(SECOND).read_bytes() == unaffected
    assert review.remaining_reviews(SCOPE) == 18


def test_full_budget_allows_only_previously_charged_digest_to_retry():
    for n in range(review.MAX_IMAGE_REVIEWS):
        digest = f"{n:064x}"
        assert _reserve(digest) == (digest, "", CONTENT)
    assert review.remaining_reviews(SCOPE) == 0
    old = f"{9:064x}"
    review.library._atomic_write(_cache(old), b"{corrupt")
    assert _reserve(old) == (old, "", CONTENT)
    with pytest.raises(ValueError, match="20-image"):
        _reserve(f"{review.MAX_IMAGE_REVIEWS:064x}")
    assert review.remaining_reviews(SCOPE) == 0


def test_completion_while_waiting_for_existing_lock_is_used(monkeypatch):
    original_lock = review.library._locked

    @contextmanager
    def complete_while_waiting(path):
        with original_lock(path):
            _store(FIRST, "Completed while waiting")
            yield

    monkeypatch.setattr(review.library, "_locked", complete_while_waiting)
    assert _reserve() == (FIRST, "Completed while waiting", None)
    assert not (review.review_directory(SCOPE) / "budget.json").exists()


@pytest.mark.parametrize("digest", ["../escape", "A" * 64, "a" * 63,
                                    "G" * 65, "", "b" * 10000])
def test_non_sha_digest_is_rejected_before_disk_access(digest):
    with pytest.raises(ValueError, match="identity"):
        _reserve(digest)
    assert not review.review_directory(SCOPE).exists()


@pytest.mark.parametrize("text", ["", "  ", None, [], "x" * 40001])
def test_bad_completed_response_cannot_replace_valid_cached_result(text):
    _initial()
    _store(text="Retained successful result")
    previous = _cache().read_bytes()
    with pytest.raises(ValueError, match="Image reading was empty"):
        review.complete_review(SCOPE, FIRST, text)
    assert _cache().read_bytes() == previous
    assert _reserve() == (FIRST, "Retained successful result", None)


def test_bad_quota_manifest_is_not_reset_or_silently_ignored():
    _initial()
    budget = review.review_directory(SCOPE) / "budget.json"
    budget.write_bytes(b"{bad quota")
    with pytest.raises(review.library.LibraryError):
        _reserve(SECOND)
    with pytest.raises(review.library.LibraryError):
        review.remaining_reviews(SCOPE)
    assert budget.read_bytes() == b"{bad quota"


def test_symlink_cached_result_is_ignored_without_reading_other_scope(tmp_path):
    _initial()
    foreign = tmp_path / "private-other-report.json"
    foreign.write_bytes(review.library._json({"schema": 1, "text": "Other report finding"}))
    _cache().symlink_to(foreign)
    assert _reserve() == (FIRST, "", CONTENT)
    assert foreign.read_bytes() == review.library._json({"schema": 1,
                                                       "text": "Other report finding"})
    assert review.remaining_reviews(SCOPE) == 19
    review.complete_review(SCOPE, FIRST, "Local correction")
    assert not _cache().is_symlink()
    assert _reserve() == (FIRST, "Local correction", None)
    assert foreign.read_bytes() == review.library._json({"schema": 1,
                                                       "text": "Other report finding"})


def test_normal_completion_roundtrip_uses_same_cache_budget():
    _initial()
    review.complete_review(SCOPE, FIRST, "Synthetic monthly image finding")
    assert _reserve() == (FIRST, "Synthetic monthly image finding", None)
    assert review.remaining_reviews(SCOPE) == 19
