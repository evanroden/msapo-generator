"""Synthetic saved-metadata recovery for the two existing shared ZIP shelves.

These tests exercise real bounded files and the delivered shelf AppTest
consumers. They do not establish native download or production acceptance.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import stat

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_fixture_vault as storage
from app.monthly_report_shared_source_bundles import (
    SharedSourceBundles, SharedSyntheticEvidenceBundles, SourceBundle,
)
from test_monthly_report_shared_source_bundles import portable_bundle
from test_monthly_report_shared_synthetic_evidence import evidence_archive


@dataclass(frozen=True)
class ShelfKind:
    shelf_type: type
    build_archive: object
    bucket: str
    selection_key: str
    prepare_label: str
    download_label: str
    recovery_message: str


KINDS = {
    "reference": ShelfKind(
        SharedSourceBundles, portable_bundle, "_enfra_shared_source_bundles_v1",
        "_shared_fixture_source_bundle_select", "Prepare verified ZIP download",
        "Download unchanged source archive",
        "Shared source archive storage needs recovery. Existing files were not reset.",
    ),
    "evidence": ShelfKind(
        SharedSyntheticEvidenceBundles, evidence_archive, "_enfra_shared_synthetic_evidence_v1",
        "_shared_fixture_evidence_bundle_select", "Prepare evidence ZIP download",
        "Download unchanged synthetic evidence archive",
        "Synthetic evidence storage needs recovery. No originals were removed.",
    ),
}


@dataclass(frozen=True)
class SavedArchive:
    root: Path
    kind: ShelfKind
    shelf: SharedSourceBundles
    receipt: SourceBundle
    original: bytes

    @property
    def entry(self):
        return self.root / self.kind.bucket / self.receipt.bundle_id


@pytest.fixture(params=tuple(KINDS))
def archive_case(tmp_path, request):
    archives = {}
    for name, kind in KINDS.items():
        shelf = kind.shelf_type(tmp_path)
        original = kind.build_archive()
        receipt = shelf.upload(original)
        archives[name] = SavedArchive(tmp_path, kind, shelf, receipt, original)
    other = "evidence" if request.param == "reference" else "reference"
    return archives[request.param], archives[other]


def _tree(root):
    """Include every retained path, byte and permission, including originals."""
    return {
        path.relative_to(root).as_posix(): (
            stat.S_IMODE(path.stat().st_mode),
            None if path.is_dir() else path.read_bytes(),
        )
        for path in sorted(root.rglob("*"))
    }


def _assert_rejected_without_writes(archive_case, *, match=None):
    damaged, other = archive_case
    before = _tree(damaged.root)
    failures = []
    operations = (
        damaged.shelf.list,
        lambda: damaged.shelf.download(damaged.receipt.bundle_id),
        lambda: damaged.shelf.upload(damaged.original),
    )
    for operation in operations:
        try:
            with pytest.raises(storage.VaultIntegrityError, match=match) as failure:
                operation()
        finally:
            assert _tree(damaged.root) == before
        failures.append(failure.value)
    assert other.shelf.list() == (other.receipt,)
    assert other.shelf.download(other.receipt.bundle_id) == other.original
    assert _tree(damaged.root) == before
    return failures


@pytest.mark.parametrize("payload", [
    pytest.param(b"[]", id="list"),
    pytest.param(b"null", id="null"),
    pytest.param(b'"archive"', id="string"),
    pytest.param(b"7", id="integer"),
    pytest.param(b"false", id="boolean"),
])
def test_nonobject_transaction_is_rejected_without_losing_either_shelf(archive_case, payload):
    damaged, _other = archive_case
    (damaged.entry / storage._TRANSACTION).write_bytes(payload)
    _assert_rejected_without_writes(archive_case, match="Reference archive transaction is invalid")


@pytest.mark.parametrize("filename,depth,limit", [
    pytest.param("receipt.json", 30000, 64 * 1024, id="deep-receipt"),
    pytest.param(storage._TRANSACTION, 2047, 4096, id="deep-transaction"),
])
def test_deep_metadata_uses_existing_recovery_boundary_within_real_byte_limits(
        archive_case, filename, depth, limit):
    damaged, _other = archive_case
    payload = b"[" * depth + b"0" + b"]" * depth
    assert len(payload) <= limit
    (damaged.entry / filename).write_bytes(payload)
    failures = _assert_rejected_without_writes(archive_case)
    if filename == "receipt.json":
        assert all(isinstance(error.__cause__, RecursionError) for error in failures)
    # The 4,095-byte transaction can reach either the decoder's native depth
    # limit or object validation, depending on the runner's existing recursion
    # limit. Both must use recovery; neither limit is changed by this test.


@pytest.mark.parametrize("filename,payload", [
    pytest.param("receipt.json", b"{bad-json", id="receipt-syntax"),
    pytest.param("receipt.json", b"[]", id="receipt-schema"),
    pytest.param(storage._TRANSACTION, b"{bad-json", id="transaction-syntax"),
    pytest.param(storage._TRANSACTION, b"{}", id="transaction-schema"),
    pytest.param("receipt.json", b" " * (64 * 1024 + 1), id="receipt-over-bound"),
    pytest.param(storage._TRANSACTION, b" " * 4097, id="transaction-over-bound"),
    pytest.param("receipt.json", None, id="noncanonical-receipt"),
])
def test_existing_metadata_validation_still_refuses_without_repairing_files(
        archive_case, filename, payload):
    damaged, _other = archive_case
    path = damaged.entry / filename
    if payload is None:
        payload = json.dumps(json.loads(path.read_bytes()), indent=2).encode("utf-8")
    path.write_bytes(payload)
    _assert_rejected_without_writes(archive_case)


@pytest.mark.parametrize("target,mode,message", [
    pytest.param("entry", 0o755, "unsafe permissions", id="entry-permissions"),
    pytest.param("original", 0o644, "unsafe disk geometry", id="original-permissions"),
])
def test_existing_permission_checks_remain_fail_closed(archive_case, target, mode, message):
    damaged, _other = archive_case
    path = (damaged.entry if target == "entry" else
            damaged.entry / (damaged.receipt.archive_sha256 + ".zip"))
    path.chmod(mode)
    _assert_rejected_without_writes(archive_case, match=message)


@pytest.mark.parametrize("filename,payload", [
    pytest.param(storage._TRANSACTION, b"[]", id="nonobject-transaction"),
    pytest.param("receipt.json", b"[" * 30000 + b"0" + b"]" * 30000, id="deep-receipt"),
])
def test_actual_shelves_report_recovery_keep_current_control_and_restore_download(
        archive_case, filename, payload):
    damaged, other = archive_case
    healthy_tree = _tree(damaged.root)
    path = damaged.entry / filename
    healthy_metadata = path.read_bytes()
    script = f'''
import streamlit as st
from app.monthly_report_shared_testing_ui import (
    _render_reference_bundle_shelf, _render_synthetic_evidence_shelf,
)
_render_reference_bundle_shelf({str(damaged.root)!r})
_render_synthetic_evidence_shelf({str(damaged.root)!r})
st.text_input("Continue synthetic editing", key="archive_recovery_current_edit")
'''
    app = AppTest.from_string(script, default_timeout=20).run()
    assert not app.exception
    assert not app.error
    assert app.selectbox(key=damaged.kind.selection_key).value == damaged.receipt.bundle_id
    assert not app.get("download_button"), "Passive listing must not prepare a download"
    app.text_input(key="archive_recovery_current_edit").set_value("Keep this current synthetic edit").run()
    assert not app.exception
    assert _tree(damaged.root) == healthy_tree

    path.write_bytes(payload)
    damaged_tree = _tree(damaged.root)
    try:
        app.run()
        assert not app.exception, [error.message for error in app.exception]
        assert [error.value for error in app.error] == [damaged.kind.recovery_message]
        assert app.text_input(key="archive_recovery_current_edit").value == "Keep this current synthetic edit"
        assert app.selectbox(key=other.kind.selection_key).value == other.receipt.bundle_id
        assert not any(widget.key == damaged.kind.selection_key for widget in app.selectbox)
        assert not any(button.label == damaged.kind.prepare_label for button in app.button)
        assert not app.get("download_button")
    finally:
        assert _tree(damaged.root) == damaged_tree

    # Restore only this test's deliberately changed metadata. Recovery itself
    # must not rewrite, delete, normalize or replace any stored bytes.
    path.write_bytes(healthy_metadata)
    app.run()
    assert not app.exception
    assert not app.error
    assert app.text_input(key="archive_recovery_current_edit").value == "Keep this current synthetic edit"
    assert app.selectbox(key=damaged.kind.selection_key).value == damaged.receipt.bundle_id
    next(button for button in app.button if button.label == damaged.kind.prepare_label).click().run()
    assert not app.exception
    assert any(button.label == damaged.kind.download_label for button in app.get("download_button"))
    assert damaged.shelf.download(damaged.receipt.bundle_id) == damaged.original
    assert other.shelf.download(other.receipt.bundle_id) == other.original
    assert _tree(damaged.root) == healthy_tree
