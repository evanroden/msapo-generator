"""The real shared test shelf accepts one bounded immutable owner-source ZIP.

Entirely synthetic data: no customer documents, hashes, names, or test outputs
are committed to CI. This is reference storage, not a competing AUTH importer.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import os
import stat
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import pytest

from app.monthly_report_fixture_vault import VaultIntegrityError, VaultQuotaExceeded
from app.monthly_report_shared_source_bundles import (
    SharedSourceBundles, validate_reference_archive,
)


def portable_bundle(*, suffix="", forged_hash=False, extra=False, path_traversal=False, symlink=False):
    manifest = {"manifest_version": 1, "source_count": 6, "source_files": []}
    entries = []
    for index in range(6):
        filename = f"synthetic-source-{index}.{'docx' if index < 3 else 'pdf'}"
        if path_traversal and index == 0:
            filename = "../outside.docx"
        raw = (f"synthetic-only-{index}-{suffix}").encode() * (index + 1)
        digest = sha256(raw).hexdigest()
        if forged_hash and index == 0:
            digest = "0" * 64
        manifest["source_files"].append({"filename": filename, "bytes": len(raw), "sha256": digest})
        entries.append(("originals/" + filename, raw))
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as zipped:
        for index, (name, data) in enumerate(entries):
            if symlink and index == 1:
                info = ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zipped.writestr(info, data)
            else:
                zipped.writestr(name, data)
        zipped.writestr("ENFRA_Original_QA_Source_Manifest_2026-10-14.json",
                        json.dumps(manifest, sort_keys=True))
        zipped.writestr("README.md", "Synthetic testing only — no client files.")
        if extra:
            zipped.writestr("originals/undeclared.pdf", b"unexpected")
    return payload.getvalue()


def test_reference_bundle_roundtrip_dedup_and_new_reader_preserve_immutable_bytes(tmp_path):
    original = portable_bundle()
    first = SharedSourceBundles(tmp_path)
    assert first.list() == ()
    receipt = first.upload(original)
    assert receipt.archive_sha256 == sha256(original).hexdigest()
    assert receipt.archive_size == len(original)
    assert len(receipt.source_files) == 6
    assert receipt.source_files[0].filename.startswith("synthetic-")
    assert first.download(receipt.bundle_id) == original
    assert first.upload(original).bundle_id == receipt.bundle_id, "Lost acknowledgement must not double-store a source"
    restarted = SharedSourceBundles(tmp_path)
    assert restarted.list() == (receipt,)
    assert restarted.download(receipt.bundle_id) == original


def test_reference_bundle_never_uses_disposable_qa_runs_or_existing_fixture_bucket(tmp_path):
    root = tmp_path
    receipt = SharedSourceBundles(root).upload(portable_bundle())
    names = {child.name for child in root.iterdir()}
    assert names == {"_enfra_shared_source_bundles_v1"}
    assert "_enfra_shared_fixtures_v1" not in names
    assert "_enfra_shared_fixture_runs_v1" not in names
    assert "_enfra_private_fixtures_v1" not in names
    assert SharedSourceBundles(root).download(receipt.bundle_id)


@pytest.mark.parametrize("options,expected", [
    ({"forged_hash": True}, "SHA-256"),
    ({"extra": True}, "extraneous"),
    ({"path_traversal": True}, "name"),
    ({"symlink": True}, "Unsafe"),
])
def test_archive_rejects_unknown_or_changed_originals_without_writes(tmp_path, options, expected):
    blob = portable_bundle(**options)
    with pytest.raises(ValueError, match=expected):
        SharedSourceBundles(tmp_path).upload(blob)
    assert SharedSourceBundles(tmp_path).list() == ()


def test_archive_rejects_missing_bytes_and_bounded_sizes(tmp_path):
    original = portable_bundle()
    with pytest.raises(VaultQuotaExceeded, match="bounded"):
        SharedSourceBundles(tmp_path, max_archive_bytes=len(original)-1).upload(original)
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError):
        validate_reference_archive(b"not-a-zip")


def test_reference_shelf_quota_does_not_erase_first_original(tmp_path):
    first = portable_bundle()
    second = portable_bundle(suffix="-another-version")
    shelf = SharedSourceBundles(tmp_path, max_archive_bytes=max(len(first), len(second)),
                                max_shelf_bytes=max(len(first), len(second)) + len(first) + 256)
    saved = shelf.upload(first)
    with pytest.raises(VaultQuotaExceeded, match="full"):
        shelf.upload(second)
    assert shelf.download(saved.bundle_id) == first


def test_changed_disk_bytes_fail_closed_instead_of_being_called_downloaded(tmp_path):
    shelf = SharedSourceBundles(tmp_path)
    receipt = shelf.upload(portable_bundle())
    root = tmp_path / "_enfra_shared_source_bundles_v1" / receipt.bundle_id
    blob = root / (receipt.archive_sha256 + ".zip")
    changed = bytearray(blob.read_bytes())
    changed[15] ^= 0x01
    blob.write_bytes(changed)
    with pytest.raises(VaultIntegrityError, match="hash/size"):
        shelf.download(receipt.bundle_id)
    assert blob.exists()
    assert len(shelf.list()) == 1, "A metadata listing alone does not verify full source bytes"


def test_unrecognized_interrupted_upload_fails_closed_and_retains_original(tmp_path):
    shelf = SharedSourceBundles(tmp_path)
    receipt = shelf.upload(portable_bundle())
    bucket = tmp_path / "_enfra_shared_source_bundles_v1"
    orphan = bucket / (".pending-" + "f" * 32)
    orphan.mkdir()
    with pytest.raises(VaultIntegrityError, match="recovery review"):
        shelf.list()
    assert (bucket / receipt.bundle_id / (receipt.archive_sha256 + ".zip")).exists()


def test_no_symlink_following_for_external_archive(tmp_path):
    shelf = SharedSourceBundles(tmp_path)
    receipt = shelf.upload(portable_bundle())
    parent = tmp_path / "_enfra_shared_source_bundles_v1" / receipt.bundle_id
    blob = parent / (receipt.archive_sha256 + ".zip")
    content = blob.read_bytes()
    blob.unlink()
    elsewhere = tmp_path / "other.zip"
    elsewhere.write_bytes(content)
    blob.symlink_to(elsewhere)
    with pytest.raises((VaultIntegrityError, OSError)):
        shelf.download(receipt.bundle_id)
    assert elsewhere.read_bytes() == content
