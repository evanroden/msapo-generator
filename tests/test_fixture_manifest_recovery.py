"""Bounded saved-fixture decoder recovery using synthetic native Word files.

These API/AppTest checks preserve the existing shared/private access policies;
they do not establish native-browser delivery or production recovery.
"""
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from docx import Document
import pytest
import requests
from streamlit.testing.v1 import AppTest

from app import monthly_report_fixture_vault as vault
from app.monthly_report_shared_fixtures import SharedFixtureLibrary


DEEP_MANIFEST = b"[" * 30000 + b"0" + b"]" * 30000
# The deepest array fitting the existing transaction read bound, plus padding
# to exercise exactly 4096 bytes. No decoder or recursion setting is changed.
DEEP_TRANSACTION = b"[" * 2047 + b"0" + b"]" * 2047 + b" "
VERIFIED = "synthetic-verified-session"
OWNER = "synthetic-fixture-owner"
TOKEN = "e" * 32
RECOVERY_ERROR = "Shared fixture storage is unavailable or needs recovery. Existing originals were preserved."


def stored_bytes(root):
    return {str(path.relative_to(root)): (
        path.stat().st_mode & 0o777, None if path.is_dir() else path.read_bytes())
        for path in sorted(root.rglob("*"))}


@dataclass
class SavedFixture:
    root: Path
    library: object
    audience: str
    receipt: vault.FixtureReceipt
    original: bytes
    manifest: Path

    def call(self, operation, *, context=VERIFIED):
        arguments = () if self.audience == "shared" else (context,)
        if operation == "list":
            return self.library.list(*arguments)
        if operation == "upload":
            return self.library.upload(*arguments, self.original, self.receipt.metadata)
        if operation == "replay":
            return self.library.replay_copy(*arguments, self.receipt.fixture_id,
                                           run_id="b" * 32, generation="c" * 32)
        return getattr(self.library, operation)(*arguments, self.receipt.fixture_id)

    @property
    def bucket(self):
        return self.manifest.parent.parent


@pytest.fixture
def saved_fixture(request, monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-no-call")

    def no_external(*_args, **_kwargs):
        pytest.fail("Synthetic fixture recovery must not make external reader calls.")

    monkeypatch.setattr(requests.sessions.Session, "request", no_external)
    document = Document()
    document.add_heading("Synthetic Fixture Site", 0)
    document.add_paragraph("October 2026: inspected the synthetic equipment.")
    output = BytesIO()
    document.save(output)
    original = output.getvalue()
    identity = vault.ReportIdentity("Synthetic contract", ("synthetic-site",), "2026-10",
                                    ("Synthetic Fixture Site",))
    metadata = vault.FixtureMetadata("Synthetic saved fixture", identity, identity, "AUTH03",
        "Preserve the original and report damaged saved metadata.",
        (vault.ExpectedSection("Activity", includes=("synthetic equipment",)),),
        "2026-11-04T06:10:00+00:00", True)
    audience = getattr(request, "param", "shared")
    if audience == "shared":
        library = SharedFixtureLibrary(tmp_path)
        receipt = library.upload(original, metadata)
        bucket = tmp_path / "_enfra_shared_fixtures_v1"
    else:
        library = vault.FixtureVault(tmp_path, authorize_owner=lambda context, _request:
            vault.AuthorizedOwner(OWNER) if context == VERIFIED else None)
        receipt = library.upload(VERIFIED, original, metadata)
        bucket = tmp_path / vault._VAULT / sha256(OWNER.encode()).hexdigest()
    manifest = bucket / receipt.fixture_id / "manifest.json"
    return SavedFixture(tmp_path, library, audience, receipt, original, manifest)


@pytest.mark.parametrize("saved_fixture", ("shared", "private"), indirect=True)
@pytest.mark.parametrize("operation", ("list", "read", "download", "replay", "upload"))
def test_nested_saved_manifest_is_rejected_without_losing_originals(saved_fixture, operation):
    saved = saved_fixture
    assert saved.call("list") == vault.VaultListing((saved.receipt,))
    assert saved.call("read") == vault.FixtureOriginal(saved.receipt, saved.original)
    healthy_manifest = saved.manifest.read_bytes()
    healthy_tree = stored_bytes(saved.root)
    assert len(DEEP_MANIFEST) == 60001 < vault._MANIFEST_LIMIT
    saved.manifest.write_bytes(DEEP_MANIFEST)
    damaged_tree = stored_bytes(saved.root)
    with pytest.raises(vault.VaultIntegrityError, match="manifest is invalid"):
        saved.call(operation)
    assert stored_bytes(saved.root) == damaged_tree
    assert (saved.manifest.parent / (saved.receipt.original_sha256 + ".docx")).read_bytes() == saved.original
    # Repairing only our disposable manifest restores the exact old receipt;
    # no API request adopts the malformed entry or overwrites another file.
    saved.manifest.write_bytes(healthy_manifest)
    assert saved.call("list") == vault.VaultListing((saved.receipt,))
    assert saved.call("download") == saved.original
    assert stored_bytes(saved.root) == healthy_tree


def shared_script(root):
    return f'''
from pathlib import Path
import streamlit as st
from app import memory
from app import monthly_report_testing as testing
from app import monthly_report_shared_testing_ui as ui
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
with testing.isolated({TOKEN!r}):
    memory._data_dir()
    ui.render({TOKEN!r}, "UTC", field, lambda *_: None, Path({str(root)!r}))
st.text_input("Following report note", key="fixture_recovery_following_note")
'''


def test_actual_shared_render_shows_recovery_without_aborting_following_input(saved_fixture):
    saved = saved_fixture
    app = AppTest.from_string(shared_script(saved.root), default_timeout=30).run()
    assert not app.exception and len(app.get("download_button")) == 1
    next(value for value in app.text_input if value.label == "Following report note").set_value(
        "Keep this independent synthetic note.").run()
    assert not app.exception
    healthy_manifest = saved.manifest.read_bytes()
    saved.manifest.write_bytes(DEEP_MANIFEST)
    before = stored_bytes(saved.bucket)
    app.run()
    assert not app.exception, "A bounded malformed manifest must reach the existing recovery boundary."
    assert [value.value for value in app.error] == [RECOVERY_ERROR]
    assert not app.get("download_button")
    assert not any(value.label == "Reset this test workspace" for value in app.button)
    assert next(value for value in app.text_input if value.label == "Following report note").value == (
        "Keep this independent synthetic note.")
    assert stored_bytes(saved.bucket) == before
    saved.manifest.write_bytes(healthy_manifest)
    app.run()
    assert not app.exception and not app.error
    assert len(app.get("download_button")) == 1
    assert any(value.label == "Reset this test workspace" for value in app.button)
    assert next(value for value in app.text_input if value.label == "Following report note").value == (
        "Keep this independent synthetic note.")
    assert saved.call("download") == saved.original


@pytest.mark.parametrize("saved_fixture", ("private",), indirect=True)
@pytest.mark.parametrize("operation", ("list", "read", "download", "replay", "upload"))
def test_denied_private_operation_never_reads_the_nested_manifest(saved_fixture, monkeypatch, operation):
    saved = saved_fixture
    saved.manifest.write_bytes(DEEP_MANIFEST)
    before = stored_bytes(saved.root)
    reads = []
    real_read = vault._read_file

    def observed_read(*args, **kwargs):
        reads.append(args[1])
        return real_read(*args, **kwargs)

    monkeypatch.setattr(vault, "_read_file", observed_read)
    with pytest.raises(vault.AuthorizationRequired):
        saved.call(operation, context="unverified-synthetic-session")
    assert reads == [], "Authorization must precede reading any data that could be parsed."
    assert stored_bytes(saved.root) == before


@pytest.mark.parametrize("saved_fixture", ("shared", "private"), indirect=True)
@pytest.mark.parametrize("extra", (b"", b" "), ids=("exact-bound", "over-bound"))
def test_committed_transaction_keeps_existing_bounded_rejection(saved_fixture, extra):
    saved = saved_fixture
    transaction = saved.manifest.parent / vault._TRANSACTION
    healthy_transaction = transaction.read_bytes()
    assert len(DEEP_TRANSACTION) == 4096
    transaction.write_bytes(DEEP_TRANSACTION + extra)
    before = stored_bytes(saved.root)
    with pytest.raises(vault.VaultIntegrityError):
        saved.call("list")
    with pytest.raises(vault.VaultIntegrityError):
        saved.call("download")
    assert stored_bytes(saved.root) == before
    transaction.write_bytes(healthy_transaction)
    assert saved.call("download") == saved.original


def add_pending_transaction(saved):
    pending = saved.bucket / (".pending-" + "9" * 32)
    pending.mkdir(mode=0o700)
    transaction = pending / vault._TRANSACTION
    transaction.write_bytes(DEEP_TRANSACTION)
    transaction.chmod(0o600)
    return pending


@pytest.mark.parametrize("saved_fixture", ("shared", "private"), indirect=True)
def test_pending_transaction_keeps_healthy_fixture_available_and_blocks_admission(saved_fixture):
    saved = saved_fixture
    pending = add_pending_transaction(saved)
    before = stored_bytes(saved.root)
    listing = saved.call("list")
    assert listing.fixtures == (saved.receipt,)
    recovery, = listing.recovery
    assert recovery.staging_id == pending.name.removeprefix(".pending-")
    assert recovery.verified is False and recovery.retained_bytes is None
    assert saved.call("read") == vault.FixtureOriginal(saved.receipt, saved.original)
    assert saved.call("download") == saved.original
    with pytest.raises(vault.VaultIntegrityError, match="interrupted uploads require review"):
        saved.call("upload")
    assert stored_bytes(saved.root) == before


def test_pending_transaction_uses_the_existing_shared_warning_and_controls(saved_fixture):
    saved = saved_fixture
    add_pending_transaction(saved)
    before = stored_bytes(saved.bucket)
    app = AppTest.from_string(shared_script(saved.root), default_timeout=30).run()
    assert not app.exception and not app.error
    assert any("An interrupted upload was retained for recovery" in value.value for value in app.warning)
    assert len(app.get("download_button")) == 1
    assert any(value.label == "Reset this test workspace" for value in app.button)
    assert any(value.label == "Following report note" for value in app.text_input)
    assert stored_bytes(saved.bucket) == before
    assert saved.call("download") == saved.original
