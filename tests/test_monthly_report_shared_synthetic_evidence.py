"""Synthetic-only regression suite for an immutable, externally shared evidence ZIP.

No customer sources, hashes, filenames or actual source artifacts enter Git.
The evidence shelf uses the existing descriptor-safe Render disk primitives.
"""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import stat
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import pytest

from app.monthly_report_fixture_vault import VaultIntegrityError, VaultQuotaExceeded
from app.monthly_report_shared_source_bundles import (
    SharedSourceBundles, SharedSyntheticEvidenceBundles,
    validate_synthetic_evidence_archive,
)


MANIFEST = "ENFRA_MSAPO_2026-10-14_evidence_manifest.json"


def evidence_archive(*, tag="", bad_hash=False, extra=False, traversal=False, symlink=False):
    sources = []
    payloads = {}
    for number in range(2):
        name = f"synthetic-browser-{number}.zip"
        if traversal and number == 0:
            name = "../unrelated.zip"
        body = ("Invented browser sample only " + str(number) + tag).encode() * 20
        digest = "0" * 64 if bad_hash and number == 0 else sha256(body).hexdigest()
        sources.append({"filename": name, "sha256": digest, "size_bytes": len(body),
                        "source_run_id": str(number + 1), "source_commit": "f" * 40,
                        "kind": "synthetic_only"})
        payloads[name] = body
    metadata = {"schema_version": "enfra-evidence-v1", "artifacts": sources}
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for index, (name, data) in enumerate(payloads.items()):
            if symlink and index == 0:
                info = ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, data)
            else:
                archive.writestr(name, data)
        archive.writestr(MANIFEST, json.dumps(metadata))
        archive.writestr("ENFRA_MSAPO_2026-10-14_evidence_README.md", "Invented evidence only.")
        if extra:
            archive.writestr("undeclared.txt", "No declaration")
    return output.getvalue()


def test_evidence_persists_across_reader_objects_without_cross_scope_writes(tmp_path):
    shelf = SharedSyntheticEvidenceBundles(tmp_path)
    content = evidence_archive()
    assert shelf.list() == ()
    receipt = shelf.upload(content)
    assert receipt.archive_sha256 == sha256(content).hexdigest()
    assert receipt.archive_size == len(content)
    assert tuple(item.filename for item in receipt.source_files) == (
        "synthetic-browser-0.zip", "synthetic-browser-1.zip")
    assert shelf.download(receipt.bundle_id) == content
    assert shelf.upload(content) == receipt, "An interrupted response never creates a second original"
    restarted = SharedSyntheticEvidenceBundles(tmp_path)
    assert restarted.list() == (receipt,)
    assert restarted.download(receipt.bundle_id) == content
    assert SharedSourceBundles(tmp_path).list() == ()
    assert {path.name for path in tmp_path.iterdir()} == {"_enfra_shared_synthetic_evidence_v1"}


def test_source_and_evidence_buckets_preserve_independent_state(tmp_path):
    shelf = SharedSyntheticEvidenceBundles(tmp_path)
    original = evidence_archive()
    receipt = shelf.upload(original)
    assert not (tmp_path / "_enfra_shared_fixtures_v1").exists()
    assert not (tmp_path / "_enfra_shared_fixture_runs_v1").exists()
    assert shelf.download(receipt.bundle_id) == original


@pytest.mark.parametrize("flags,message", [
    ({"bad_hash": True}, "SHA-256"),
    ({"extra": True}, "undeclared"),
    ({"traversal": True}, "name"),
    ({"symlink": True}, "Unsafe"),
])
def test_evidence_rejects_unknown_changed_or_unsafe_zip_without_writes(tmp_path, flags, message):
    with pytest.raises(ValueError, match=message):
        SharedSyntheticEvidenceBundles(tmp_path).upload(evidence_archive(**flags))
    assert SharedSyntheticEvidenceBundles(tmp_path).list() == ()


def test_malformed_zip_limits_and_no_overwrite(tmp_path):
    bundle = evidence_archive()
    assert len(validate_synthetic_evidence_archive(bundle)) == 2
    with pytest.raises(ValueError):
        validate_synthetic_evidence_archive(b"not a zip")
    with pytest.raises(VaultQuotaExceeded):
        SharedSyntheticEvidenceBundles(tmp_path, max_archive_bytes=len(bundle)-1).upload(bundle)
    assert not tuple(tmp_path.iterdir())


def test_evidence_quota_and_corruption_fail_closed_preserving_previous_bytes(tmp_path):
    first = evidence_archive()
    second = evidence_archive(tag="second")
    # The admission cap applies to uncompressed ZIP members as well as
    # the outer ZIP. Setting it to only the compressed bytes would reject this
    # otherwise valid fixture before the quota boundary under test.
    cap = 64 * 1024
    assert len(first) < cap and len(second) < cap
    shelf = SharedSyntheticEvidenceBundles(
        tmp_path, max_archive_bytes=cap,
        max_shelf_bytes=cap + len(first) + len(second)//2)
    receipt = shelf.upload(first)
    with pytest.raises(VaultQuotaExceeded, match="full"):
        shelf.upload(second)
    assert shelf.download(receipt.bundle_id) == first
    blob = (tmp_path / "_enfra_shared_synthetic_evidence_v1" /
            receipt.bundle_id / (receipt.archive_sha256 + ".zip"))
    data = bytearray(blob.read_bytes())
    data[15] ^= 1
    blob.write_bytes(data)
    with pytest.raises(VaultIntegrityError, match="hash/size"):
        shelf.download(receipt.bundle_id)
    assert blob.exists()
