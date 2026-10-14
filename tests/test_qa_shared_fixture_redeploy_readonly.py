"""Hash-only live fixture persistence verifier: pure local contract tests.

No test starts Playwright, visits Render, downloads an owner file, changes a
fixture, or depends on a locally mounted production drive.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts.qa_shared_fixture_redeploy_readonly import (
    KIND, ORIGIN, _browser_route, _save_new, _valid_commit, _valid_hash,
    _valid_id, _selector_id, _validate_manifest, compare, verify_one,
)


ID = "a" * 32
SHA = "b" * 64
BEFORE = "c" * 40
AFTER = "d" * 40


def sample(phase="before", *, commit=BEFORE, when=None):
    return {
        "schema": 1, "kind": KIND, "phase": phase, "endpoint": ORIGIN,
        "fixture_id": ID, "original_sha256": SHA, "original_size": 12000,
        "served_commit": commit,
        "verified_at_utc": when or (
            "2026-10-14T03:00:00+00:00" if phase == "before"
            else "2026-10-14T04:00:00+00:00"
        ),
        "read_only_checks": [
            "exact_served_commit", "selected_original_identity",
            "original_download_sha256",
        ],
    }


def test_valid_hash_only_before_and_after_distinct_served_builds():
    result = compare(sample(), sample("after", commit=AFTER))
    assert result["hash_identical_across_distinct_served_builds"] is True
    assert result["original_sha256"] == SHA
    assert result["fixture_id"] == ID
    assert result["before_commit"] == BEFORE
    assert result["after_commit"] == AFTER
    # No original bytes, source text or human-submitted metadata in the output.
    assert "original_bytes" not in result
    assert not any(k in result for k in (
        "raw", "body", "contract", "site", "filename", "email", "phone",
    ))
    assert "authentic report" in result["limits"].lower()


@pytest.mark.parametrize("change", [
    ("fixture_id", "c" * 32),
    ("original_sha256", "0" * 64),
    ("original_size", 12001),
    ("served_commit", BEFORE),  # Identical deploy is NOT a restart proof.
    ("endpoint", "https://another.example"),
    ("read_only_checks", ["exact_served_commit"]),
])
def test_comparison_rejects_mismatched_or_unverified_original(change):
    key, value = change
    after = sample("after", commit=AFTER)
    after[key] = value
    with pytest.raises(ValueError):
        compare(sample(), after)


def test_comparison_rejects_reversed_timeline():
    after = sample("after", commit=AFTER, when="2026-10-14T02:00:00+00:00")
    with pytest.raises(ValueError, match="after observation"):
        compare(sample(), after)


@pytest.mark.parametrize("phase,value", [
    ("before", {"schema": 2}),
    ("before", {"fixture_id": "abc"}),
    ("before", {"original_sha256": "short"}),
    ("before", {"original_size": -1}),
    ("before", {"original_size": 25 * 1024 * 1024 + 1}),
    ("before", {"served_commit": "x" * 40}),
    ("before", {"verified_at_utc": "2026-10-14T03:00:00"}),
])
def test_exact_manifest_validation_rejects_bad_attestations(phase, value):
    record = sample(phase)
    record.update(value)
    with pytest.raises(ValueError):
        _validate_manifest(record, phase)


def test_before_manifest_cannot_claim_after_phase():
    with pytest.raises(ValueError, match="phase"):
        _validate_manifest(sample("before"), "after")


@pytest.mark.parametrize("bad", [
    "", "../fixtures", "ABC" * 11, "a" * 31, "a" * 33,
    "0123456789abcdef0123456789abcdeG",
])
def test_invalid_fixture_ids_fail_before_any_browser_request(bad):
    with pytest.raises(ValueError):
        _valid_id(bad)
    with pytest.raises(ValueError):
        _selector_id(bad)
    with pytest.raises(ValueError):
        verify_one(bad, SHA, BEFORE, "before")


def test_visible_eight_character_fixture_prefix_is_supported_without_guessing_full_id():
    assert _selector_id(ID[:8]) == ID[:8]
    assert _selector_id(ID) == ID
    with pytest.raises(ValueError):
        _valid_id(ID[:8])  # Evidence must still contain the resolved full ID.


def test_unknown_served_revision_and_hash_are_rejected_before_browser():
    with pytest.raises(ValueError):
        _valid_commit(BEFORE[:10])
    with pytest.raises(ValueError):
        _valid_hash(SHA[:63])
    with pytest.raises(ValueError):
        verify_one(ID, SHA, "no-deployment", "after")
    with pytest.raises(ValueError):
        verify_one(ID, SHA, BEFORE, "unapproved-phase")


def test_output_is_new_only_and_keeps_an_earlier_evidence_receipt(tmp_path):
    target = tmp_path / "evidence" / "before.json"
    payload = sample()
    _save_new(target, payload)
    assert json.loads(target.read_text()) == payload
    with pytest.raises(FileExistsError):
        _save_new(target, sample("after", commit=AFTER))
    assert json.loads(target.read_text()) == payload


class FakeRoute:
    def __init__(self, uri):
        self.request = type("Request", (), {"url": uri})()
        self.actions = []

    def continue_(self):
        self.actions.append("allowed")

    def abort(self):
        self.actions.append("blocked")


@pytest.mark.parametrize("uri,expected", [
    ("https://msapo-generator.onrender.com/?workflow=monthly", "allowed"),
    ("https://msapo-generator.onrender.com/static/app.js", "allowed"),
    ("data:application/octet-stream;base64,QQ==", "allowed"),
    ("blob:https://msapo-generator.onrender.com/abc", "allowed"),
    ("https://other.example/collect", "blocked"),
    ("http://msapo-generator.onrender.com/", "blocked"),
    ("https://msapo-generator.onrender.com.evil.example/", "blocked"),
    ("file:///etc/passwd", "blocked"),
])
def test_fixture_probe_browser_blocks_foreign_requests(uri, expected):
    route, denied = FakeRoute(uri), []
    _browser_route(route, denied)
    assert route.actions == [expected]
    assert bool(denied) == (expected == "blocked")
