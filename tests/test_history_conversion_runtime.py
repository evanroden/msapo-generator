"""Conversion leases are transient runtime state, not standing report records."""
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app import monthly_report_testing as testing
from scripts.workspace_history_observations import storage_state


TOKEN = "c" * 32


def prepare(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    with testing.isolated(TOKEN):
        return testing.data_dir(tmp_path) / "monthly_reports"


def test_actual_converter_record_and_clear_do_not_change_durable_inventory(monkeypatch, tmp_path):
    root = prepare(monkeypatch, tmp_path)
    from app import monthly_report_library as library, office_process
    monkeypatch.setattr(library, "_root", lambda: root)
    monkeypatch.setattr(office_process, "_boot_id", lambda: "synthetic-boot")
    before = storage_state(tmp_path, TOKEN)
    office_process._record(123456)
    marker = root / "render-jobs/.active-office.json"
    assert marker.exists() and json.loads(marker.read_text())["pid"] == 123456
    during = storage_state(tmp_path, TOKEN)
    office_process._clear(123456)
    assert not marker.exists()
    after = storage_state(tmp_path, TOKEN)
    assert before == during == after


@pytest.mark.parametrize("name", [".active-office.json", ".active-office.tmp", ".conversion-lock"])
def test_only_exact_converter_runtime_paths_are_excluded(monkeypatch, tmp_path, name):
    root = prepare(monkeypatch, tmp_path)
    before = storage_state(tmp_path, TOKEN)
    runtime = root / "render-jobs" / name
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"SYNTHETIC RUNTIME")
    assert storage_state(tmp_path, TOKEN) == before
    standing = root / "directory" / name
    standing.parent.mkdir()
    standing.write_bytes(b"SYNTHETIC STANDING")
    after = storage_state(tmp_path, TOKEN)
    assert after != before
    assert sha256(str(standing.relative_to(root)).encode()).hexdigest() in after["entries"]


def test_unknown_render_folder_file_is_not_waived(monkeypatch, tmp_path):
    root = prepare(monkeypatch, tmp_path)
    before = storage_state(tmp_path, TOKEN)
    target = root / "render-jobs/standing.json"
    target.parent.mkdir(parents=True)
    target.write_text("SYNTHETIC UNEXPECTED FILE")
    assert storage_state(tmp_path, TOKEN) != before


def test_converter_path_link_is_rejected_before_any_exclusion(monkeypatch, tmp_path):
    root = prepare(monkeypatch, tmp_path)
    target = root / "render-jobs/.active-office.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="link"):
        storage_state(tmp_path, TOKEN)


def test_converter_path_still_counts_toward_size_bound(monkeypatch, tmp_path):
    root = prepare(monkeypatch, tmp_path)
    target = root / "render-jobs/.active-office.json"
    target.parent.mkdir(parents=True)
    with target.open("wb") as stream:
        stream.truncate(32 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="byte bound"):
        storage_state(tmp_path, TOKEN)


@pytest.mark.parametrize("relative,allowed", [
    ("render-jobs/.active-office.json", True), ("directory/manifest.json", False),
])
def test_only_known_runtime_removal_during_inventory_is_tolerated(monkeypatch, tmp_path, relative, allowed):
    root = prepare(monkeypatch, tmp_path)
    before = storage_state(tmp_path, TOKEN)
    target = root / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(b"SYNTHETIC")
    real = Path.is_file
    def removed_after_is_file(path):
        result = real(path)
        if path == target:
            path.unlink()
        return result
    monkeypatch.setattr(Path, "is_file", removed_after_is_file)
    if allowed:
        assert storage_state(tmp_path, TOKEN) == before
    else:
        with pytest.raises(FileNotFoundError):
            storage_state(tmp_path, TOKEN)
