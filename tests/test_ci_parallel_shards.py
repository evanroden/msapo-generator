"""Synthetic-file invariants for the full-suite matrix sharding plan."""
from pathlib import Path

from scripts import ci_full_test_shards as shards


def test_each_file_is_assigned_once_and_new_files_are_included(tmp_path):
    for name in ("test_one.py", "test_two.py", "test_three.py", "test_new.py", "test_heavy.py"):
        path = tmp_path / "tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok(): assert True\n", encoding="utf-8")
    all_files = shards.test_files(tmp_path)
    durations = {"tests/test_heavy.py": 300.0, "tests/test_one.py": 35.0}
    plan = shards.partition(all_files, durations, 3)
    assert all(plan)
    assert sorted(file for group in plan for file in group) == all_files
    assert "tests/test_new.py" in {file for group in plan for file in group}
    assert plan == shards.partition(list(reversed(all_files)), durations, 3)


def test_recorded_duration_weights_keep_the_heavy_file_separate():
    files = [f"tests/test_{name}.py" for name in ("heavy", "a", "b", "c", "d")]
    plan = shards.partition(files, {"tests/test_heavy.py": 1486.6}, 4)
    assert any(group == ["tests/test_heavy.py"] for group in plan)


def test_duplicate_paths_and_empty_shards_fail_closed():
    import pytest
    with pytest.raises(ValueError):
        shards.partition(["tests/test_one.py"] * 2, {}, 2)
    with pytest.raises(ValueError):
        shards.partition(["tests/test_one.py"], {}, 2)


def test_cli_writes_only_one_full_suite_shard(tmp_path):
    for i in range(6):
        path = tmp_path / "tests" / f"test_{i}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok(): assert True\n", encoding="utf-8")
    assigned = []
    for i in range(5):
        output = tmp_path / f"shard-{i}.txt"
        assert shards.main(["--shard", str(i), "--shards", "5", "--repo", str(tmp_path), "--out", str(output)]) == 0
        assigned.extend(output.read_text(encoding="utf-8").splitlines())
    assert sorted(assigned) == shards.test_files(tmp_path)


def test_snapshot_has_measured_slowest_file():
    # Main f0af9956, Tests 44203272158: 66 passed in 1041.26 seconds.
    duration = shards.read_durations()["tests/test_streamlit_frontend_compat.py"]
    assert 1000 < duration < 1100
