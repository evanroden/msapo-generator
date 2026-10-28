"""Read-only installed master identity and download regressions."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import monthly_report_designs as designs
from app import monthly_report_import as report_import
from test_monthly_report_designs import master_reference
from test_monthly_report_render_profile import pair


def _snapshot(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def _stored_master(tmp_path, monkeypatch, data):
    """Small stored-byte fixture for integrity and resource boundary checks."""
    root = tmp_path / "library"
    directory = root / "designs" / "master"
    directory.mkdir(parents=True)
    digest = hashlib.sha256(data).hexdigest()
    source = directory / (digest + ".docx")
    source.write_bytes(data)
    (directory / "manifest.json").write_text(json.dumps({
        "schema": 1, "revision": 1, "default": digest, "history": [],
    }))
    monkeypatch.setattr(designs.library, "_root", lambda: root)
    return source, digest


def test_missing_master_has_no_download(monkeypatch):
    monkeypatch.setattr(designs, "master_state", lambda: {
        "revision": 0, "default": "", "history": [],
    })
    assert designs.installed_master_download() is None


def test_installed_master_download_is_exact_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    original = master_reference(tmp_path)
    data = original.read_bytes()
    digest = designs.install_master(original, actor="Synthetic Editor", expected_revision=0)
    root = designs.library._root()
    before = _snapshot(root)
    result = designs.installed_master_download()
    assert result == {
        "revision": 1, "hash": digest, "source_hash": hashlib.sha256(data).hexdigest(),
        "size": len(data), "bytes": data,
    }
    assert designs.master_state()["revision"] == 1
    assert _snapshot(root) == before


def test_only_global_master_lookup_can_omit_contract(tmp_path, monkeypatch):
    stored, digest = _stored_master(tmp_path, monkeypatch, b"synthetic master")
    profile = SimpleNamespace(contract="", template=designs.MASTER_PREFIX + digest)
    assert designs.source_for(profile) == stored
    contract_profile = SimpleNamespace(contract="", template=designs.PREFIX + digest, key="site")
    with pytest.raises(designs.library.LibraryError, match="valid contract"):
        designs.source_for(contract_profile)


def test_corrupted_installed_master_refuses_download(tmp_path, monkeypatch):
    stored, _ = _stored_master(tmp_path, monkeypatch, b"original")
    stored.write_bytes(b"invalid changed version")
    before = _snapshot(designs.library._root())
    with pytest.raises(ValueError, match="integrity check"):
        designs.installed_master_download()
    assert _snapshot(designs.library._root()) == before


def test_replacement_during_download_keeps_snapshot_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    original = master_reference(tmp_path).read_bytes()
    first = designs.install_master(tmp_path / "master.docx", actor="First Editor", expected_revision=0)
    replacement = master_reference(tmp_path, "replacement", "Later synthetic master")
    resolve = designs.source_for
    replaced = {}

    def replace_after_resolution(profile):
        source = resolve(profile)
        replaced["digest"] = designs.install_master(
            replacement, actor="Second Editor", expected_revision=1,
        )
        replaced["files"] = _snapshot(designs.library._root())
        return source

    monkeypatch.setattr(designs, "source_for", replace_after_resolution)
    result = designs.installed_master_download()
    assert result["revision"] == 1
    assert result["hash"] == first
    assert result["source_hash"] == hashlib.sha256(original).hexdigest()
    assert result["bytes"] == original
    assert result["size"] == len(original)
    assert designs.master_state()["revision"] == 2
    assert designs.master_state()["default"] == replaced["digest"] != first
    assert _snapshot(designs.library._root()) == replaced["files"]


@pytest.mark.parametrize("stray_source_hash", [False, True])
def test_download_rechecks_pinned_bytes_after_resolution(tmp_path, monkeypatch, stray_source_hash):
    original = b"original synthetic master"
    changed = b"modified synthetic master"
    stored, digest = _stored_master(tmp_path, monkeypatch, original)
    if stray_source_hash:
        metadata = stored.parent / "metadata" / (digest + ".json")
        metadata.parent.mkdir()
        metadata.write_text(json.dumps({
            "schema": 1, "hash": digest,
            "source_sha256": hashlib.sha256(changed).hexdigest(),
        }))
    resolve = designs.source_for

    def change_after_verification(profile):
        source = resolve(profile)
        source.write_bytes(changed)
        return source

    monkeypatch.setattr(designs, "source_for", change_after_verification)
    with pytest.raises(ValueError, match="integrity check"):
        designs.installed_master_download()
    assert designs.master_state()["default"] == digest


def test_paired_master_download_uses_original_word_hash_and_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    source, companion = pair(tmp_path)
    original = source.read_bytes()
    digest = designs.install_master(source, actor="Synthetic Editor", expected_revision=0,
                                    companion_pdf=companion)
    source_hash = hashlib.sha256(original).hexdigest()
    assert digest != source_hash
    before = _snapshot(designs.library._root())
    assert designs.installed_master_download() == {
        "revision": 1, "hash": digest, "source_hash": source_hash,
        "size": len(original), "bytes": original,
    }
    assert _snapshot(designs.library._root()) == before


@pytest.mark.parametrize("corruption", ["companion", "profile"])
def test_paired_master_download_retains_integrity_gates(tmp_path, monkeypatch, corruption):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    source, companion = pair(tmp_path)
    digest = designs.install_master(source, actor="Synthetic Editor", expected_revision=0,
                                    companion_pdf=companion)
    directory = designs.library._root() / "designs" / "master"
    metadata_path = directory / "metadata" / (digest + ".json")
    metadata = json.loads(metadata_path.read_text())
    if corruption == "companion":
        saved_companion = directory / (metadata["companion_sha256"] + ".pdf")
        saved_companion.unlink()
        saved_companion.write_bytes(b"changed companion")
    else:
        metadata["render_profile"]["cover_zero_origin"] = not metadata["render_profile"]["cover_zero_origin"]
        metadata_path.write_text(json.dumps(metadata))
    before = _snapshot(designs.library._root())
    with pytest.raises(ValueError, match="integrity check"):
        designs.installed_master_download()
    assert _snapshot(designs.library._root()) == before


@pytest.mark.parametrize("limit_delta", [0, -1])
def test_download_respects_word_byte_limit(tmp_path, monkeypatch, limit_delta):
    original = b"small synthetic master"
    stored, _ = _stored_master(tmp_path, monkeypatch, original)
    limit = len(original) + limit_delta
    monkeypatch.setattr(report_import, "MAX_DOCX_BYTES", limit)
    if limit_delta == 0:
        assert designs.installed_master_download()["bytes"] == original
    else:
        with pytest.raises(ValueError, match="limit|too large|exceeds|at most"):
            designs.installed_master_download()
    assert stored.read_bytes() == original


def test_download_bounds_read_when_source_grows_after_stat(tmp_path, monkeypatch):
    original = b"small synthetic master"
    stored, _ = _stored_master(tmp_path, monkeypatch, original)
    limit = len(original)
    monkeypatch.setattr(report_import, "MAX_DOCX_BYTES", limit)
    resolve = designs.source_for
    open_file = Path.open
    observed = {"resolved": False, "reads": []}

    def resolved(profile):
        source = resolve(profile)
        observed["resolved"] = True
        return source

    class TrackedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            assert 0 < size <= limit + 1, "download read must remain within its byte budget"
            observed["reads"].append(size)
            return self.stream.read(size)

    def grow_before_open(path, mode="r", *args, **kwargs):
        if path == stored and mode == "rb" and observed["resolved"]:
            with open_file(stored, "wb") as output:
                output.write(original * 3)
            return TrackedReader(open_file(path, mode, *args, **kwargs))
        return open_file(path, mode, *args, **kwargs)

    monkeypatch.setattr(designs, "source_for", resolved)
    monkeypatch.setattr(Path, "open", grow_before_open)
    with pytest.raises(ValueError, match="limit|too large|exceeds|at most"):
        designs.installed_master_download()
    assert observed["reads"]
