"""Synthetic shared-storage checks, not hidden-route or authentic acceptance."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app import monthly_report_fixture_vault as vault
from app.monthly_report_shared_fixtures import SharedFixtureLibrary


@pytest.fixture
def original():
    result = BytesIO()
    with ZipFile(result, "w") as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        package.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>SYNTHETIC SHARED REPORT ONLY</w:t></w:r></w:p></w:body></w:document>')
    return result.getvalue()


@pytest.fixture
def metadata():
    return vault.FixtureMetadata(
        friendly_name="Synthetic shared previous report",
        source=vault.ReportIdentity("Synthetic contract", ("Synthetic site A",), "2026-09"),
        target=vault.ReportIdentity("Synthetic contract", ("Synthetic site A",), "2026-10"),
        scenario="AUTH01", owner_expectations="Carry reusable contacts; keep prior monthly work historical.",
        expected_content=(vault.ExpectedSection("Activity", excludes=("September as current work",)),
                          vault.ExpectedSection("Organization", includes=("Synthetic site A contact",))),
        confirmed_at="2026-10-13T15:45:00+00:00",
    )


def test_distinct_visitors_and_reopened_instances_share_all_originals(tmp_path, original, metadata):
    coworker, agent = {"anonymous-session": "coworker"}, {"anonymous-session": "agent"}
    first = SharedFixtureLibrary(tmp_path)
    assert first.audience.audience == "all-visitors"
    assert first.audience.authentication == "none"
    assert first.list(visitor_context=coworker) == vault.VaultListing(())
    receipt = first.upload(original, metadata, visitor_context=coworker)
    reopened = SharedFixtureLibrary(tmp_path)
    assert reopened.list(visitor_context=agent) == vault.VaultListing((receipt,))
    assert reopened.read(receipt.fixture_id, visitor_context=agent) == vault.FixtureOriginal(receipt, original)
    assert reopened.download(receipt.fixture_id) == original  # No context is required.
    second = reopened.upload(original, replace(metadata, friendly_name="Agent-selected scenario"), visitor_context=agent)
    assert {item.fixture_id for item in first.list(visitor_context=coworker).fixtures} == {receipt.fixture_id, second.fixture_id}
    assert first.read(second.fixture_id, visitor_context=coworker).original == original


def test_shared_markers_are_explicit_and_do_not_create_private_buckets(tmp_path, original, metadata):
    SharedFixtureLibrary(tmp_path).upload(original, metadata)
    assert {path.name for path in tmp_path.iterdir()} == {"_enfra_shared_fixtures_v1"}
    bucket = tmp_path / "_enfra_shared_fixtures_v1"
    marker = json.loads((bucket / ".enfra-private-fixture-storage").read_bytes())
    # The engine's marker filename is reused; its actual storage/audience
    # identity is distinct and cannot match any private bucket marker.
    assert marker == {"schema": 1, "bucket": bucket.name, "audience": "all-visitors", "authentication": "none"}
    for path in tmp_path.rglob("*"):
        assert path.stat().st_mode & 0o077 == 0  # OS permissions are not visitor authentication.


def test_root_is_explicit_existing_absolute_and_never_a_live_fallback(tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    (live / "standing-data.txt").write_text("Synthetic standing data")
    monkeypatch.setenv("EPC_DATA_DIR", str(live))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        SharedFixtureLibrary(tmp_path / "missing").list()
    with pytest.raises(vault.VaultIntegrityError):
        SharedFixtureLibrary(Path("live")).list()
    with pytest.raises(vault.VaultIntegrityError):
        SharedFixtureLibrary(tmp_path / ".." / tmp_path.name).list()
    assert sorted(path.name for path in live.iterdir()) == ["standing-data.txt"]
    assert not (tmp_path / "missing").exists()


def test_root_and_bucket_symlinks_cannot_redirect_shared_storage(tmp_path, original, metadata):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        SharedFixtureLibrary(linked).list()
    (root / "_enfra_shared_fixtures_v1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        SharedFixtureLibrary(root).upload(original, metadata)
    assert not list(outside.iterdir())


def test_wrong_audience_marker_is_not_adopted(tmp_path, original, metadata):
    library = SharedFixtureLibrary(tmp_path)
    receipt = library.upload(original, metadata)
    marker = tmp_path / "_enfra_shared_fixtures_v1" / ".enfra-private-fixture-storage"
    marker.write_text('_enfra_private_fixtures_v1|1')
    with pytest.raises(vault.VaultIntegrityError):
        library.list()
    with pytest.raises(vault.VaultIntegrityError):
        library.read(receipt.fixture_id)
    assert next(tmp_path.rglob(receipt.original_sha256 + ".docx")).read_bytes() == original


def test_repeat_upload_preserves_original_receipt_and_selected_metadata(tmp_path, original, metadata):
    library = SharedFixtureLibrary(tmp_path)
    first = library.upload(original, metadata)
    partial_identity = vault.ReportIdentity("Synthetic contract", ("Synthetic site B",), "2026-11")
    partial = replace(metadata, friendly_name="Explicitly selected partial report",
                      source=partial_identity, target=partial_identity, scenario="AUTH03",
                      partial_file_confirmed=True, owner_expectations="Preserve the intentional blank and unfinished row.",
                      expected_content=(vault.ExpectedSection("Training", includes=("unfinished row",), excludes=("invented completion",)),))
    second = library.upload(original, partial)
    assert first.fixture_id != second.fixture_id
    assert first.original_sha256 == second.original_sha256 == sha256(original).hexdigest()
    assert library.read(first.fixture_id) == vault.FixtureOriginal(first, original)
    assert library.read(second.fixture_id).receipt.metadata == partial
    assert len(library.list().fixtures) == 2
    assert not hasattr(library, "purge")
    assert not hasattr(library, "delete")


def test_partial_file_confirmation_is_still_required(tmp_path, original, metadata):
    identity = metadata.target
    unconfirmed = replace(metadata, source=identity, target=identity, scenario="AUTH03")
    with pytest.raises(ValueError, match="explicit confirmation"):
        SharedFixtureLibrary(tmp_path).upload(original, unconfirmed)
    assert not list(tmp_path.iterdir())


def test_fixture_limits_and_replay_limits_preserve_saved_originals(tmp_path, original, metadata):
    library = SharedFixtureLibrary(tmp_path, max_fixture_bytes=len(original), max_library_bytes=8192,
                                   max_run_copy_bytes=1)
    receipt = library.upload(original, metadata)
    with pytest.raises(vault.VaultQuotaExceeded):
        library.upload(original + b"too much", metadata)
    bounded = SharedFixtureLibrary(tmp_path, max_fixture_bytes=len(original), max_library_bytes=len(original))
    with pytest.raises(vault.VaultQuotaExceeded):
        bounded.upload(original, metadata)
    with pytest.raises(vault.VaultQuotaExceeded):
        library.replay_copy(receipt.fixture_id, run_id="1" * 32, generation="2" * 32)
    assert library.download(receipt.fixture_id) == original
    assert library.list().fixtures == (receipt,)


def test_fresh_replay_copy_has_separate_marked_storage_and_cannot_replace_a_run(tmp_path, original, metadata):
    library = SharedFixtureLibrary(tmp_path)
    receipt = library.upload(original, metadata)
    replay = library.replay_copy(receipt.fixture_id, run_id="1" * 32, generation="2" * 32,
                                 visitor_context={"agent": "another session"})
    assert replay.original_path.parent.parent == tmp_path / "_enfra_shared_fixture_runs_v1"
    assert replay.original_path.read_bytes() == original
    assert json.loads(replay.original_path.with_name("lineage.json").read_bytes()) == {
        "schema": 1, "fixture_id": receipt.fixture_id, "original_sha256": receipt.original_sha256,
        "run_id": "1" * 32, "generation": "2" * 32,
    }
    replay.original_path.write_bytes(b"synthetic disposable modified copy")
    with pytest.raises(vault.VaultIntegrityError, match="immutable"):
        library.replay_copy(receipt.fixture_id, run_id="1" * 32, generation="3" * 32)
    assert replay.original_path.read_bytes() == b"synthetic disposable modified copy"
    assert library.download(receipt.fixture_id) == original


def test_interrupted_upload_is_reported_and_preserved_without_hiding_saved_original(tmp_path, original, metadata):
    library = SharedFixtureLibrary(tmp_path)
    receipt = library.upload(original, metadata)
    pending = tmp_path / "_enfra_shared_fixtures_v1" / (".pending-" + "9" * 32)
    pending.mkdir(mode=0o700)
    listing = library.list()
    assert listing.fixtures == (receipt,)
    assert len(listing.recovery) == 1
    assert listing.recovery[0].verified is False
    with pytest.raises(vault.VaultIntegrityError, match="interrupted"):
        library.upload(original, metadata)
    assert pending.is_dir()
    assert library.read(receipt.fixture_id).original == original


def test_changed_original_is_detected_in_shared_downloads(tmp_path, original, metadata):
    library = SharedFixtureLibrary(tmp_path)
    receipt = library.upload(original, metadata)
    saved = next(tmp_path.rglob(receipt.original_sha256 + ".docx"))
    saved.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(vault.VaultIntegrityError, match="hash/size"):
        library.download(receipt.fixture_id)


@pytest.mark.parametrize("operation", ["list", "read", "upload", "download", "replay_copy"])
def test_shared_access_does_not_authorize_an_owner_only_vault(tmp_path, original, metadata, operation):
    shared = SharedFixtureLibrary(tmp_path)
    receipt = shared.upload(original, metadata)
    owner_only = vault.FixtureVault(tmp_path)
    action = {
        "list": lambda: owner_only.list("anonymous-coworker"),
        "read": lambda: owner_only.read("anonymous-coworker", receipt.fixture_id),
        "upload": lambda: owner_only.upload("anonymous-coworker", original, metadata),
        "download": lambda: owner_only.download("anonymous-coworker", receipt.fixture_id),
        "replay_copy": lambda: owner_only.replay_copy("anonymous-coworker", receipt.fixture_id,
                                                     run_id="1" * 32, generation="2" * 32),
    }[operation]
    with pytest.raises(vault.AuthorizationRequired):
        action()
    assert shared.download(receipt.fixture_id) == original


def test_shared_and_authorized_private_libraries_do_not_expose_each_others_entries(tmp_path, original, metadata):
    owner_only = vault.FixtureVault(tmp_path, authorize_owner=lambda *_: vault.AuthorizedOwner("verified-owner"))
    private_receipt = owner_only.upload("verified-session", original, metadata)
    shared = SharedFixtureLibrary(tmp_path)
    assert shared.list() == vault.VaultListing(())
    with pytest.raises(FileNotFoundError):
        shared.read(private_receipt.fixture_id)
    shared_receipt = shared.upload(original, replace(metadata, friendly_name="Shared copy"))
    assert shared.list().fixtures == (shared_receipt,)
    assert owner_only.list("verified-session").fixtures == (private_receipt,)
    with pytest.raises(FileNotFoundError):
        owner_only.read("verified-session", shared_receipt.fixture_id)
    assert owner_only.download("verified-session", private_receipt.fixture_id) == original
