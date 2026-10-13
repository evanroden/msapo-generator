"""Synthetic-only checks of the unconnected private storage adapter.

These do not authenticate a real owner, enable an upload route, run the report
importer or establish Render retention/private delivery acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import struct
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest

from app import monthly_report_fixture_vault as vault


@pytest.fixture
def original():
    output = BytesIO()
    with ZipFile(output, "w") as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        package.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>SYNTHETIC ONLY</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


@pytest.fixture
def metadata():
    return vault.FixtureMetadata(
        friendly_name="Synthetic previous report",
        source=vault.ReportIdentity("Synthetic contract", ("Synthetic site A",), "2026-09"),
        target=vault.ReportIdentity("Synthetic contract", ("Synthetic site A",), "2026-10"),
        scenario="AUTH01", owner_expectations="Carry standing facts; leave prior monthly work historical.",
        expected_content=(vault.ExpectedSection("Activity", excludes=("September work as October work",)),
                          vault.ExpectedSection("Organization", includes=("Synthetic contact remains at site A",))),
        confirmed_at="2026-10-13T14:00:00+00:00",
    )


class Verifier:
    def __init__(self):
        self.calls = []
        self.sessions = {"verified-session-a": "owner-a", "verified-session-b": "owner-b"}
        self.allowed_generation = None

    def __call__(self, context, request):
        self.calls.append((context, request))
        subject = self.sessions.get(context)
        if self.allowed_generation and request.generation != self.allowed_generation:
            return None
        return vault.AuthorizedOwner(subject) if subject else None


def entries(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def operation(instance, name, context, original, metadata, fixture_id="a" * 32):
    return {
        "upload": lambda: instance.upload(context, original, metadata),
        "list": lambda: instance.list(context),
        "read": lambda: instance.read(context, fixture_id),
        "download": lambda: instance.download(context, fixture_id),
        "replay-copy": lambda: instance.replay_copy(context, fixture_id, run_id="b" * 32, generation="c" * 32),
    }[name]()


@pytest.mark.parametrize("name", ["upload", "list", "read", "download", "replay-copy"])
def test_every_operation_denies_unconfigured_and_unverified_access_before_touching_storage(tmp_path, original, metadata, name):
    missing = tmp_path / "not-provisioned"
    for instance in (vault.FixtureVault(missing), vault.FixtureVault(missing, authorize_owner=Verifier())):
        with pytest.raises(vault.AuthorizationRequired):
            operation(instance, name, "anonymous-cookie", original, metadata)
    assert not entries(tmp_path)


@pytest.mark.parametrize("result", [True, "owner-a", None, vault.AuthorizedOwner("")])
def test_only_verified_owner_result_is_accepted(tmp_path, result):
    instance = vault.FixtureVault(tmp_path, authorize_owner=lambda *_: result)
    with pytest.raises(vault.AuthorizationRequired):
        instance.list("opaque-request")
    assert not entries(tmp_path)


def test_original_bytes_manifest_and_every_operation_authorization_survive_reopen(tmp_path, original, metadata):
    verifier = Verifier()
    instance = vault.FixtureVault(tmp_path, authorize_owner=verifier)
    assert instance.list("verified-session-a") == vault.VaultListing(())
    receipt = instance.upload("verified-session-a", original, metadata)
    assert receipt.original_sha256 == sha256(original).hexdigest()
    assert receipt.original_size == len(original)
    assert receipt.metadata == metadata
    reopened = vault.FixtureVault(tmp_path, authorize_owner=verifier)
    assert reopened.list("verified-session-a") == vault.VaultListing((receipt,))
    assert reopened.read("verified-session-a", receipt.fixture_id) == vault.FixtureOriginal(receipt, original)
    assert reopened.download("verified-session-a", receipt.fixture_id) == original
    copied = reopened.replay_copy("verified-session-a", receipt.fixture_id, run_id="1" * 32, generation="2" * 32)
    assert copied.original_path.read_bytes() == original
    assert copied.receipt == receipt
    assert json.loads(copied.original_path.with_name("lineage.json").read_bytes()) == {
        "schema": 1, "fixture_id": receipt.fixture_id, "original_sha256": receipt.original_sha256,
        "run_id": "1" * 32, "generation": "2" * 32,
    }
    assert {request.operation for _, request in verifier.calls} == {"list", "upload", "read", "download", "replay-copy"}
    for _, request in verifier.calls:
        if request.operation in {"read", "download", "replay-copy"}:
            assert request.fixture_id == receipt.fixture_id
        if request.operation == "replay-copy":
            assert (request.run_id, request.generation) == ("1" * 32, "2" * 32)
    for path in tmp_path.rglob("*"):
        assert path.stat().st_mode & 0o077 == 0


def test_cross_owner_selection_has_no_fallback_or_mutation(tmp_path, original, metadata):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    receipt = instance.upload("verified-session-a", original, metadata)
    before = entries(tmp_path)
    assert instance.list("verified-session-b") == vault.VaultListing(())
    with pytest.raises(FileNotFoundError):
        instance.read("verified-session-b", receipt.fixture_id)
    assert entries(tmp_path) == before
    assert instance.download("verified-session-a", receipt.fixture_id) == original


def test_named_site_metadata_roundtrips_and_older_manifests_remain_readable(tmp_path, original, metadata):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    named = replace(metadata,
                    source=vault.ReportIdentity("Synthetic contract", ("site-a",), "2026-09", ("Site A",)),
                    target=vault.ReportIdentity("Synthetic contract", ("site-a",), "2026-10", ("Site A",)))
    receipt = instance.upload("verified-session-a", original, named)
    assert instance.read("verified-session-a", receipt.fixture_id).receipt.metadata == named
    # Simulate the earlier immutable manifest schema, which omitted titles.
    # Update its recorded length as the original writer would have done.
    manifest = next(tmp_path.rglob("manifest.json"))
    value = json.loads(manifest.read_bytes())
    for identity in (value["metadata"]["source"], value["metadata"]["target"]):
        identity.pop("site_titles", None)
    encoded = json.dumps(value).encode()
    manifest.write_bytes(encoded)
    transaction = manifest.with_name(vault._TRANSACTION)
    commit = json.loads(transaction.read_bytes())
    commit["files"]["manifest.json"] = len(encoded)
    transaction.write_text(json.dumps(commit))
    reopened = instance.read("verified-session-a", receipt.fixture_id)
    assert reopened.receipt.metadata.target.site_titles == ()
    assert reopened.receipt.metadata.target.sites == ("site-a",)
    assert reopened.original == original


@pytest.mark.parametrize("titles", [("Site A", "Site B"), ("",), ["Site A"]])
def test_named_sites_require_one_nonempty_title_per_key(tmp_path, original, metadata, titles):
    named = replace(metadata, target=replace(metadata.target, site_titles=titles))
    with pytest.raises(ValueError):
        vault.FixtureVault(tmp_path, authorize_owner=Verifier()).upload("verified-session-a", original, named)
    assert not entries(tmp_path)


@pytest.mark.parametrize("name", ["list", "read", "download", "replay-copy", "upload"])
def test_revocation_is_rechecked_before_return_or_commit(tmp_path, original, metadata, name):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    receipt = instance.upload("verified-session-a", original, metadata)
    calls = 0

    def revoke_during_operation(_context, _request):
        nonlocal calls
        calls += 1
        return vault.AuthorizedOwner("owner-a") if calls == 1 else None

    revoked = vault.FixtureVault(tmp_path, authorize_owner=revoke_during_operation)
    with pytest.raises(vault.AuthorizationRequired):
        operation(revoked, name, "verified-session-a", original, metadata, receipt.fixture_id)
    assert instance.list("verified-session-a") == vault.VaultListing((receipt,))
    assert not list(tmp_path.rglob(".pending-*"))
    assert not list(tmp_path.rglob("original.docx"))


def test_owner_change_at_commit_does_not_reassign_an_original(tmp_path, original, metadata):
    calls = 0

    def change(_context, _request):
        nonlocal calls
        calls += 1
        return vault.AuthorizedOwner("owner-a" if calls == 1 else "owner-b")

    with pytest.raises(vault.AuthorizationRequired):
        vault.FixtureVault(tmp_path, authorize_owner=change).upload("verified-session-a", original, metadata)
    assert not list(tmp_path.rglob("*.docx"))


@pytest.mark.parametrize("bad_id", ["../live", "/test1", "", "a" * 31, "A" * 32, "a" * 32 + "/child"])
def test_unsafe_fixture_and_run_identifiers_cannot_escape_storage(tmp_path, original, metadata, bad_id):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    receipt = instance.upload("verified-session-a", original, metadata)
    before = entries(tmp_path)
    with pytest.raises(ValueError):
        instance.read("verified-session-a", bad_id)
    with pytest.raises(ValueError):
        instance.replay_copy("verified-session-a", receipt.fixture_id, run_id=bad_id, generation="a" * 32)
    assert entries(tmp_path) == before


def test_symlinked_root_bucket_original_and_hardlinked_original_fail_closed(tmp_path, original, metadata):
    root = tmp_path / "storage"
    root.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        vault.FixtureVault(link, authorize_owner=Verifier()).list("verified-session-a")
    instance = vault.FixtureVault(root, authorize_owner=Verifier())
    receipt = instance.upload("verified-session-a", original, metadata)
    source = next(root.rglob(receipt.original_sha256 + ".docx"))
    external = tmp_path / "outside.docx"
    external.write_bytes(original)
    source.unlink()
    source.symlink_to(external)
    with pytest.raises(OSError):
        instance.read("verified-session-a", receipt.fixture_id)
    source.unlink()
    os.link(external, source)
    with pytest.raises(vault.VaultIntegrityError):
        instance.download("verified-session-a", receipt.fixture_id)
    assert external.read_bytes() == original


def test_unmarked_partial_directory_and_changed_original_are_not_adopted(tmp_path, original, metadata):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    receipt = instance.upload("verified-session-a", original, metadata)
    source = next(tmp_path.rglob(receipt.original_sha256 + ".docx"))
    source.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(vault.VaultIntegrityError, match="hash/size"):
        instance.read("verified-session-a", receipt.fixture_id)
    source.write_bytes(original)
    (source.parent / "manifest.json").unlink()
    with pytest.raises(OSError):
        instance.list("verified-session-a")
    assert source.read_bytes() == original


def test_missing_root_and_unmarked_bucket_do_not_become_an_empty_vault(tmp_path):
    verifier = Verifier()
    with pytest.raises(FileNotFoundError):
        vault.FixtureVault(tmp_path / "missing", authorize_owner=verifier).list("verified-session-a")
    (tmp_path / "_enfra_private_fixtures_v1").mkdir(mode=0o700)
    with pytest.raises(FileNotFoundError):
        vault.FixtureVault(tmp_path, authorize_owner=verifier).list("verified-session-a")


def test_linked_bucket_cannot_redirect_an_authorized_upload(tmp_path, original, metadata):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "_enfra_private_fixtures_v1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        vault.FixtureVault(root, authorize_owner=Verifier()).upload("verified-session-a", original, metadata)
    assert not entries(outside)


def test_intermediate_link_replacement_cannot_redirect_an_open_root(tmp_path, original, metadata, monkeypatch):
    middle, outside = tmp_path / "middle", tmp_path / "outside"
    root = middle / "storage"
    root.mkdir(parents=True)
    outside.mkdir()
    instance = vault.FixtureVault(root, authorize_owner=Verifier())
    receipt = instance.upload("verified-session-a", original, metadata)
    real_open = vault.os.open
    changed = False

    def swap(path, flags, *args, **kwargs):
        nonlocal changed
        if path == "storage" and kwargs.get("dir_fd") is not None and not changed:
            changed = True
            middle.rename(tmp_path / "original-middle")
            middle.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(vault.os, "open", swap)
    assert instance.download("verified-session-a", receipt.fixture_id) == original
    assert changed and not entries(outside)
    with pytest.raises(OSError):
        instance.list("verified-session-a")


def test_report_label_never_infers_partial_status_or_source_identity(tmp_path, original, metadata):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    partial = replace(metadata, scenario="AUTH03", friendly_name="October-half-finished.docx", source=metadata.target)
    with pytest.raises(ValueError, match="explicit confirmation"):
        instance.upload("verified-session-a", original, partial)
    accepted = instance.upload("verified-session-a", original, replace(partial, partial_file_confirmed=True))
    assert accepted.metadata.source == metadata.target
    for wrong in (replace(metadata, expected_content=()), replace(metadata, confirmed_at="2026-10-13"),
                  replace(metadata, source=replace(metadata.source, month="2026-08")),
                  replace(metadata, scenario="AUTH02")):
        with pytest.raises(ValueError):
            instance.upload("verified-session-a", original, wrong)
    different_site = replace(metadata, scenario="AUTH02", target=replace(metadata.target, sites=("Synthetic site B",)))
    assert instance.upload("verified-session-a", original, different_site).metadata == different_site


def test_upload_quota_and_atomic_failure_preserve_existing_original(tmp_path, original, metadata, monkeypatch):
    verifier = Verifier()
    instance = vault.FixtureVault(tmp_path, authorize_owner=verifier)
    receipt = instance.upload("verified-session-a", original, metadata)
    tight = vault.FixtureVault(tmp_path, authorize_owner=verifier,
                              max_fixture_bytes=len(original), max_owner_bytes=len(original))
    with pytest.raises(vault.VaultQuotaExceeded):
        tight.upload("verified-session-a", original, metadata)
    real_write = vault._write_file

    def failed_write(directory, name, data):
        if name == "manifest.json":
            raise OSError("synthetic durable write failure")
        return real_write(directory, name, data)

    monkeypatch.setattr(vault, "_write_file", failed_write)
    with pytest.raises(OSError, match="synthetic durable write failure"):
        instance.upload("verified-session-a", original, metadata)
    assert instance.list("verified-session-a") == vault.VaultListing((receipt,))
    assert instance.read("verified-session-a", receipt.fixture_id).original == original
    assert not list(tmp_path.rglob(".pending-*"))


def test_concurrent_upload_admission_cannot_exceed_the_owner_quota(tmp_path, original, metadata):
    verifier = Verifier()
    seed = vault.FixtureVault(tmp_path, authorize_owner=verifier).upload("verified-session-a", original, metadata)
    manifest = next(tmp_path.rglob("manifest.json"))
    size = sum(path.stat().st_size for path in manifest.parent.iterdir())
    instance = vault.FixtureVault(tmp_path, authorize_owner=verifier,
                                 max_fixture_bytes=len(original), max_owner_bytes=2 * size)

    def attempt(_):
        try:
            return instance.upload("verified-session-a", original, metadata)
        except vault.VaultQuotaExceeded:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(instance.list("verified-session-a").fixtures) == 2
    assert instance.read("verified-session-a", seed.fixture_id).original == original


def test_disk_admission_rejects_new_upload_without_losing_saved_data(tmp_path, original, metadata, monkeypatch):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    receipt = instance.upload("verified-session-a", original, metadata)
    monkeypatch.setattr(vault.os, "fstatvfs", lambda _: SimpleNamespace(f_bavail=0, f_frsize=4096))
    with pytest.raises(vault.VaultQuotaExceeded, match="free space"):
        instance.upload("verified-session-a", original, metadata)
    assert instance.list("verified-session-a") == vault.VaultListing((receipt,))
    assert instance.download("verified-session-a", receipt.fixture_id) == original


def test_crashed_private_upload_remains_visible_as_recovery_and_counts_against_quota(tmp_path, original, metadata):
    verifier = Verifier()
    instance = vault.FixtureVault(tmp_path, authorize_owner=verifier)
    saved = instance.upload("verified-session-a", original, metadata)
    interrupted = instance.upload("verified-session-a", original, metadata)
    entry = next(path for path in tmp_path.rglob(interrupted.fixture_id) if path.is_dir())
    staging_id = uuid4().hex
    pending = entry.with_name(".pending-" + staging_id)
    entry.rename(pending)  # Crash immediately before the atomic publish.
    retained = sum(path.stat().st_size for path in pending.iterdir())
    current = instance.list("verified-session-a")
    assert current.fixtures == (saved,)
    assert len(current.recovery) == 1
    assert current.recovery[0].verified
    assert current.recovery[0].staging_id == staging_id
    assert current.recovery[0].retained_bytes == retained
    assert "review" in current.recovery[0].reason
    tight = vault.FixtureVault(tmp_path, authorize_owner=verifier,
                              max_fixture_bytes=len(original), max_owner_bytes=2 * retained)
    with pytest.raises(vault.VaultQuotaExceeded):
        tight.upload("verified-session-a", original, metadata)
    assert instance.download("verified-session-a", saved.fixture_id) == original
    assert (pending / (interrupted.original_sha256 + ".docx")).read_bytes() == original
    assert instance.list("verified-session-a") == current


def test_unmarked_crash_never_hides_saved_fixture_or_adopts_unknown_content(tmp_path, original, metadata):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    saved = instance.upload("verified-session-a", original, metadata)
    source = next(tmp_path.rglob(saved.original_sha256 + ".docx"))
    pending = source.parent.parent / (".pending-" + uuid4().hex)
    pending.mkdir(mode=0o700)
    unknown = pending / "do-not-adopt.txt"
    unknown.write_text("SYNTHETIC orphan, not a confirmed fixture")
    result = instance.list("verified-session-a")
    assert result.fixtures == (saved,)
    assert len(result.recovery) == 1 and not result.recovery[0].verified
    assert result.recovery[0].retained_bytes is None
    with pytest.raises(vault.VaultIntegrityError, match="require review"):
        instance.upload("verified-session-a", original, metadata)
    assert unknown.read_text() == "SYNTHETIC orphan, not a confirmed fixture"
    assert instance.download("verified-session-a", saved.fixture_id) == original


def test_oversized_zip_catalog_is_rejected_before_constructing_members(tmp_path, original, metadata, monkeypatch):
    data = bytearray(original)
    offset = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, offset + 8, 50000, 50000)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unbounded catalog was parsed")

    monkeypatch.setattr(vault, "ZipFile", forbidden)
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    with pytest.raises(ValueError, match="safe native-reader bound"):
        instance.upload("verified-session-a", bytes(data), metadata)
    assert not entries(tmp_path)


def test_replay_is_fresh_copied_scoped_and_bounded_without_removing_vault(tmp_path, original, metadata):
    verifier = Verifier()
    instance = vault.FixtureVault(tmp_path, authorize_owner=verifier)
    receipt = instance.upload("verified-session-a", original, metadata)
    generation = uuid4().hex
    verifier.allowed_generation = generation
    first = instance.replay_copy("verified-session-a", receipt.fixture_id, run_id=uuid4().hex, generation=generation)
    with pytest.raises(vault.VaultIntegrityError, match="already exists"):
        instance.replay_copy("verified-session-a", receipt.fixture_id, run_id=first.run_id, generation=generation)
    with pytest.raises(vault.AuthorizationRequired):
        instance.replay_copy("verified-session-a", receipt.fixture_id, run_id=uuid4().hex, generation=uuid4().hex)
    bounded = vault.FixtureVault(tmp_path, authorize_owner=verifier, max_run_copy_bytes=1)
    with pytest.raises(vault.VaultQuotaExceeded):
        bounded.replay_copy("verified-session-a", receipt.fixture_id, run_id=uuid4().hex, generation=generation)
    verifier.allowed_generation = None
    # Disposable source copy changes cannot mutate an immutable vault original.
    first.original_path.write_bytes(b"synthetic disposable change")
    assert instance.download("verified-session-a", receipt.fixture_id) == original
    shutil.rmtree(first.original_path.parent)
    assert instance.list("verified-session-a") == vault.VaultListing((receipt,))


def test_ordinary_qa_reset_does_not_touch_the_fixture_vault(tmp_path, original, metadata):
    from app import monthly_report_testing
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    receipt = instance.upload("verified-session-a", original, metadata)
    with monthly_report_testing.isolated("d" * 32):
        monthly_report_testing.data_dir(tmp_path).joinpath("synthetic-work.txt").write_text("disposable")
        monthly_report_testing.reset(tmp_path)
    assert instance.read("verified-session-a", receipt.fixture_id).original == original


@pytest.mark.parametrize("data", [b"", b"SYNTHETIC plain text, not a DOCX", b"%PDF-1.7 SYNTHETIC"])
def test_only_native_docx_originals_enter_this_starting_report_primitive(tmp_path, metadata, data):
    instance = vault.FixtureVault(tmp_path, authorize_owner=Verifier())
    with pytest.raises((ValueError, vault.VaultQuotaExceeded)):
        instance.upload("verified-session-a", data, metadata)
    assert not entries(tmp_path)
