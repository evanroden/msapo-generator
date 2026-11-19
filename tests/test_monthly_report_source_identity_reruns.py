"""Synthetic A26 preview identity cache regressions; never source-view approval."""
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from app import monthly_report_library as library
from app import monthly_report_source_view_runtime as runtime
from app.monthly_report_compatibility_view import POLICY
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile, synthetic_draft


@pytest.fixture
def identity_case(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = b"A26 TEST ONLY original\n" * 4096
    digest = sha256(raw).hexdigest()
    profile = ReportProfile(
        "A26 Synthetic North", "north", "Synthetic North",
        (Facility("north", "Synthetic North"),), imported_from=digest,
    )
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    folder = library._profile_path(profile.contract, profile.key)
    imports = folder / "imports"
    imports.mkdir(parents=True)
    original = imports / (digest + ".docx")
    original.write_bytes(raw)
    receipt_raw = b'{"schema":1,"synthetic":"A26 receipt, not approval"}'
    receipt_sha = sha256(receipt_raw).hexdigest()
    scope = {
        "contract": profile.contract, "profile_key": profile.key,
        "period": draft.period.key, "original_sha256": digest,
        "receipt_sha256": receipt_sha, "policy": POLICY,
    }
    receipt = library._source_view_receipt_path(folder, scope)
    receipt.write_bytes(receipt_raw)
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "source_views": {"synthetic": {"scope": scope}}}))
    return draft, original, receipt, manifest


def _watch_reads(monkeypatch, *paths):
    original_open = Path.open
    observed = []
    watched = set(paths)

    def opening(self, *args, **kwargs):
        if self in watched and args and args[0] == "rb":
            observed.append(self)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opening)
    return observed


def test_noop_reruns_do_not_reopen_verified_original_manifest_or_receipt(identity_case, monkeypatch):
    draft, original, receipt, manifest = identity_case
    reads = _watch_reads(monkeypatch, original, receipt, manifest)
    first = runtime.cache_identity(draft)
    assert first and original in reads and receipt in reads and manifest in reads
    reads.clear()
    for _ in range(5):
        assert runtime.cache_identity(draft) == first
        assert runtime.preview_fingerprint(draft)
    assert reads == [], "Harmless UI reruns must not reopen previously verified evidence."


@pytest.mark.parametrize("damaged", ["original", "receipt", "manifest"])
def test_same_length_corruption_with_restored_mtime_is_detected(identity_case, damaged):
    draft, original, receipt, manifest = identity_case
    first = runtime.cache_identity(draft)
    target = {"original": original, "receipt": receipt, "manifest": manifest}[damaged]
    before = target.stat()
    raw = target.read_bytes()
    target.unlink()
    target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert target.stat().st_size == before.st_size
    with pytest.raises((ValueError, library.LibraryError)):
        runtime.cache_identity(draft)
    assert target.read_bytes() != raw
    target.unlink()
    target.write_bytes(raw)
    assert runtime.cache_identity(draft) == first


def test_manifest_revision_invalidates_even_when_old_identity_was_warm(identity_case):
    draft, original, receipt, manifest = identity_case
    prior = runtime.cache_identity(draft)
    value = json.loads(manifest.read_text())
    value["synthetic_edit_revision"] = 2
    library._atomic_write(manifest, json.dumps(value).encode())
    assert runtime.cache_identity(draft) != prior
    assert runtime.cache_identity(draft) == runtime.cache_identity(draft)


@pytest.mark.parametrize("damaged", ["original", "receipt", "manifest"])
def test_missing_evidence_never_returns_warm_success(identity_case, damaged):
    draft, original, receipt, manifest = identity_case
    assert runtime.cache_identity(draft)
    target = {"original": original, "receipt": receipt, "manifest": manifest}[damaged]
    target.unlink()
    if damaged == "manifest":
        assert runtime.cache_identity(draft) == ""
    else:
        with pytest.raises((OSError, ValueError, library.LibraryError)):
            runtime.cache_identity(draft)


def test_wrong_site_and_wrong_month_never_reuse_identity(identity_case):
    draft, original, receipt, manifest = identity_case
    assert runtime.cache_identity(draft)
    other = replace(draft, profile=replace(
        draft.profile, key="south", title="Synthetic South",
        facilities=(Facility("south", "Synthetic South"),)))
    assert runtime.cache_identity(other) == ""
    month = replace(draft, period=ReportPeriod(2026, 10))
    with pytest.raises(library.LibraryError):
        runtime.cache_identity(month)
    assert runtime.cache_identity(draft)


def test_symlink_replacement_never_hits_cached_verified_original(identity_case, tmp_path):
    draft, original, receipt, manifest = identity_case
    runtime.cache_identity(draft)
    copy = tmp_path / "foreign.docx"
    copy.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(copy)
    with pytest.raises((OSError, ValueError, library.LibraryError)):
        runtime.cache_identity(draft)


def test_an_unrecorded_legacy_manifest_does_not_grant_source_view(identity_case):
    draft, original, receipt, manifest = identity_case
    assert runtime.cache_identity(draft)
    library._atomic_write(manifest, b'{"schema":1}')
    assert runtime.cache_identity(draft) == ""


def test_identity_cache_never_weakens_final_full_byte_render_verification(identity_case, monkeypatch):
    draft, original, receipt, manifest = identity_case
    assert runtime.cache_identity(draft)
    calls = []
    def refused(*args, **kwargs):
        calls.append(True)
        raise library.LibraryError("Fresh final verification is still required")
    monkeypatch.setattr(library, "verified_render_source_view", refused)
    with pytest.raises(library.LibraryError, match="Fresh final verification"):
        with runtime.render_operation(draft, source_path=original):
            pytest.fail("No output may be yielded without independent verification")
    assert calls == [True]
