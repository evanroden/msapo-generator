"""Malformed DEFLATE in the shared source/evidence shelves is a recoverable read error.

All archives are invented synthetic fixtures. This never uses private originals.
"""
from io import BytesIO
import struct
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from app.monthly_report_shared_source_bundles import (
    SharedSourceBundles, SharedSyntheticEvidenceBundles,
    validate_reference_archive, validate_synthetic_evidence_archive,
)
from test_monthly_report_shared_source_bundles import portable_bundle
from test_monthly_report_shared_synthetic_evidence import evidence_archive, MANIFEST


SOURCE_MANIFEST = "ENFRA_Original_QA_Source_Manifest_2026-10-14.json"


def damaged_deflate_member(data: bytes, member: str) -> bytes:
    """Change only DEFLATE's block-type bits, not the ZIP index or source files."""
    result = bytearray(data)
    with ZipFile(BytesIO(data)) as archive:
        info = archive.getinfo(member)
        assert info.compress_type == ZIP_DEFLATED and info.compress_size > 0
        fields = struct.unpack_from("<IHHHHHIIIHH", result, info.header_offset)
        assert fields[0] == 0x04034B50
        name_length, extra_length = fields[-2:]
        position = info.header_offset + 30 + name_length + extra_length
        # BTYPE=3 is reserved in DEFLATE. The original central directory,
        # compressed-length receipts, SHA declarations and all sibling bytes
        # remain untouched so this reaches the actual decompression boundary.
        assert position < len(result)
        result[position] = 0x06
    assert bytes(result) != data
    return bytes(result)


@pytest.mark.parametrize("kind,member_kind", [
    ("reference", "manifest"),
    ("reference", "original"),
    ("evidence", "manifest"),
    ("evidence", "original"),
])
def test_bad_deflate_is_recoverable_and_never_changes_an_approved_shelf(
        tmp_path, kind, member_kind):
    if kind == "reference":
        valid = portable_bundle(suffix="-before")
        proposed = portable_bundle(suffix="-after")
        owner = SharedSourceBundles(tmp_path)
        validator = validate_reference_archive
        target = SOURCE_MANIFEST if member_kind == "manifest" else "originals/synthetic-source-0.docx"
        message = "Invalid immutable six-source reference archive"
        bucket = "_enfra_shared_source_bundles_v1"
    else:
        valid = evidence_archive(tag="-before")
        proposed = evidence_archive(tag="-after")
        owner = SharedSyntheticEvidenceBundles(tmp_path)
        validator = validate_synthetic_evidence_archive
        target = MANIFEST if member_kind == "manifest" else "synthetic-browser-0.zip"
        message = "Invalid manifest-bound synthetic evidence ZIP"
        bucket = "_enfra_shared_synthetic_evidence_v1"

    approved = owner.upload(valid)
    previous = owner.list()
    assert previous == (approved,)
    assert owner.download(approved.bundle_id) == valid

    damaged = damaged_deflate_member(proposed, target)
    # Before the repair both validators leaked zlib.error, rather than the
    # ValueError understood by the normal recoverable upload boundary.
    with pytest.raises(ValueError, match=message):
        validator(damaged)
    with pytest.raises(ValueError, match=message):
        owner.upload(damaged)
    assert owner.list() == previous
    assert owner.download(approved.bundle_id) == valid
    assert {entry.name for entry in tmp_path.iterdir()} == {bucket}
    assert owner.upload(valid) == approved  # No duplicate on retry.

    # A genuinely valid upload after the rejected member still works, without
    # rewriting the earlier immutable original or its exact receipt.
    recovered = owner.upload(proposed)
    assert recovered.bundle_id != approved.bundle_id
    assert owner.download(recovered.bundle_id) == proposed
    assert owner.download(approved.bundle_id) == valid
    assert set(owner.list()) == {approved, recovered}
