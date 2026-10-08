from app.monthly_report_storage import storage_summary


def test_storage_counts_monthly_files_without_following_links_or_changing_files(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    root = tmp_path / "monthly_reports"
    root.mkdir()
    (root / "asset.png").write_bytes(b"synthetic")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "not-monthly").write_bytes(b"not-counted")
    (root / "link").symlink_to(outside, target_is_directory=True)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    result = storage_summary()
    assert result["monthly"] == 9 and result["files"] == 1 and result["complete"]
    assert 0 <= result["free"] <= result["total"]
    assert before == sorted(str(p) for p in tmp_path.rglob("*"))
    assert not storage_summary(max_entries=0)["complete"]


def test_storage_empty_monthly_library_is_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    result = storage_summary()
    assert result["monthly"] == 0 and result["complete"]
    assert not (tmp_path / "monthly_reports").exists()
