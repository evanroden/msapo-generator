"""Read-only installed master identity and download regressions."""

import hashlib

import pytest

from app import monthly_report_designs as designs


def test_missing_master_has_no_download(monkeypatch):
    monkeypatch.setattr(designs, "master_state", lambda: {
        "revision": 0, "default": "", "history": [],
    })
    assert designs.installed_master_download() is None


def test_installed_master_download_is_exact_and_read_only(tmp_path, monkeypatch):
    data = b"synthetic-original-docx-bytes"
    digest = hashlib.sha256(data).hexdigest()
    root = tmp_path / "library"
    directory = root / "designs" / "master"
    directory.mkdir(parents=True)
    (directory / (digest + ".docx")).write_bytes(data)
    monkeypatch.setattr(designs.library, "_root", lambda: root)
    state = {"revision": 2, "default": digest, "history": []}
    monkeypatch.setattr(designs, "master_state", lambda: dict(state))
    before = tuple(sorted(p.name for p in directory.iterdir()))
    result = designs.installed_master_download()
    assert result == {
        "revision": 2, "hash": digest, "source_hash": digest,
        "size": len(data), "bytes": data,
    }
    assert state["revision"] == 2
    assert tuple(sorted(p.name for p in directory.iterdir())) == before


def test_corrupted_installed_master_refuses_download(tmp_path, monkeypatch):
    actual = b"invalid changed version"
    intended = hashlib.sha256(b"original").hexdigest()
    root = tmp_path / "library"
    directory = root / "designs" / "master"
    directory.mkdir(parents=True)
    (directory / (intended + ".docx")).write_bytes(actual)
    monkeypatch.setattr(designs.library, "_root", lambda: root)
    monkeypatch.setattr(designs, "master_state", lambda: {
        "revision": 1, "default": intended, "history": [],
    })
    with pytest.raises(ValueError, match="integrity check"):
        designs.installed_master_download()


def test_replacement_during_download_keeps_snapshot_identity(tmp_path, monkeypatch):
    original = b"first synthetic master"
    first = hashlib.sha256(original).hexdigest()
    second = hashlib.sha256(b"later synthetic master").hexdigest()
    root = tmp_path / "library"
    directory = root / "designs" / "master"
    directory.mkdir(parents=True)
    (directory / (first + ".docx")).write_bytes(original)
    (directory / (second + ".docx")).write_bytes(b"later synthetic master")
    monkeypatch.setattr(designs.library, "_root", lambda: root)
    state = {"revision": 1, "default": first, "history": []}
    monkeypatch.setattr(designs, "master_state", lambda: dict(state))
    result = designs.installed_master_download()
    state.update(revision=2, default=second)
    assert result["revision"] == 1
    assert result["hash"] == first
    assert result["bytes"] == original
