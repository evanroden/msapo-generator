"""Deterministic synthetic proof that function-level sharding preserves tests."""
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from scripts import ci_full_test_shards as shards


def write(repo, files):
    for rel, source in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def synthetic_repo(tmp_path, failing=False):
    hot = (
        "import pytest\n"
        "@pytest.mark.parametrize('value', [0, 1, 2])\n"
        "def test_cases(value): assert value >= 0\n"
        "def test_other(): assert True\n"
    )
    if failing:
        hot += "def test_failure(): assert False\n"
    write(tmp_path, {
        shards.SPLIT_FILE: hot,
        "tests/test_unrelated.py": "def test_outside(): assert True\n",
        "tests/nested/test_extra.py": "def test_extra(): assert True\n",
    })
    return tmp_path


def test_baseline_one_hot_file_would_run_on_only_one_shard(tmp_path):
    repo = synthetic_repo(tmp_path)
    files = shards.test_files(repo)
    baseline = shards.partition(files, {shards.SPLIT_FILE: 90.0}, 2)
    assert sum(shards.SPLIT_FILE in group for group in baseline) == 1
    items, weighted = shards.expanded_test_items(repo, files, {shards.SPLIT_FILE: 90.0})
    groups = shards.partition(items, weighted, 2)
    assert sum(any(name.startswith(shards.SPLIT_FILE + "::") for name in group)
               for group in groups) == 2
    assert sorted(name for group in groups for name in group) == items
    assert weighted[shards.SPLIT_FILE + "::test_cases"] == pytest.approx(45.0)


def test_parametrized_control_and_unrelated_tests_execute_once(tmp_path):
    repo = synthetic_repo(tmp_path)
    items, weights = shards.expanded_test_items(
        repo, shards.test_files(repo), {shards.SPLIT_FILE: 90.0}
    )
    groups = shards.partition(items, weights, 2)
    names = []
    for index, group in enumerate(groups):
        xml = repo / f"results-{index}.xml"
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--junitxml={xml}", *group],
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        names.extend(case.attrib["name"] for case in
                     ET.parse(xml).iter("testcase"))
    assert sum(name.startswith("test_cases[") for name in names) == 3
    assert names.count("test_other") == 1
    assert names.count("test_outside") == 1
    assert names.count("test_extra") == 1


def test_failure_propagates_from_own_shard(tmp_path):
    repo = synthetic_repo(tmp_path, failing=True)
    items, weights = shards.expanded_test_items(
        repo, shards.test_files(repo), {shards.SPLIT_FILE: 90.0}
    )
    groups = shards.partition(items, weights, 2)
    failing = [g for g in groups
               if any(name.endswith("::test_failure") for name in g)]
    assert len(failing) == 1
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *failing[0]],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )
    assert run.returncode != 0
    assert "test_failure" in run.stdout
    assert "1 failed" in run.stdout


@pytest.mark.parametrize("unexpected", [
    "def test_foo(: pass\n",
    "class TestGroup:\n    def test_case(self): pass\n\ndef test_case(): pass\n",
    "def pytest_generate_tests(metafunc): pass\ndef test_case(): pass\n",
    "def pytest_collection_modifyitems(items): pass\ndef test_case(): pass\n",
    "def test_only(): pass\n",
])
def test_unrecognized_collection_stays_a_whole_file(tmp_path, unexpected):
    repo = synthetic_repo(tmp_path)
    write(repo, {shards.SPLIT_FILE: unexpected})
    files = shards.test_files(repo)
    items, _ = shards.expanded_test_items(repo, files, {shards.SPLIT_FILE: 90.0})
    assert items == files


def test_missing_hot_file_and_duplicate_nodes_fail_closed(tmp_path):
    write(tmp_path, {"tests/test_unrelated.py": "def test_unrelated(): pass\n"})
    files = shards.test_files(tmp_path)
    items, _ = shards.expanded_test_items(tmp_path, files, {})
    assert items == files
    with pytest.raises(ValueError, match="unique"):
        shards.partition(["tests/test_a.py", "tests/test_a.py"], {}, 2)


def test_real_frontend_parametrized_collection_is_exact():
    """Compare actual pytest node IDs, not merely AST function names."""
    repo = Path(__file__).resolve().parents[1]
    files = shards.test_files(repo)
    items, _ = shards.expanded_test_items(repo, files, shards.read_durations())
    hot = [item for item in items if item.startswith(shards.SPLIT_FILE + "::")]
    assert hot, "The hot file must be split on this pinned checkout"

    def collect(selectors):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *selectors],
            cwd=repo, capture_output=True, text=True, timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return [
            line.strip() for line in result.stdout.splitlines()
            if line.startswith(shards.SPLIT_FILE + "::")
        ]

    original = collect([shards.SPLIT_FILE])
    distributed = collect(hot)
    assert original, "Full-file collection unexpectedly returned no tests"
    assert len(distributed) == len(set(distributed))
    assert sorted(distributed) == sorted(original)


def test_every_real_test_file_is_covered_exactly_once():
    repo = Path(__file__).resolve().parents[1]
    files = shards.test_files(repo)
    items, weights = shards.expanded_test_items(repo, files, shards.read_durations())
    groups = shards.partition(items, weights, 5)
    assigned = [item for group in groups for item in group]
    assert sorted(assigned) == items
    assert len(assigned) == len(set(assigned))
    assert {item.split("::", 1)[0] for item in assigned} == set(files)
    assert sum(any(item.startswith(shards.SPLIT_FILE + "::") for item in group)
               for group in groups) >= 2
    assert all(groups)

def test_measured_function_weights_are_used_and_stale_nodes_rejected(tmp_path):
    repo = synthetic_repo(tmp_path)
    durations = {
        shards.SPLIT_FILE: 100.0,
        shards.SPLIT_FILE + "::test_cases": 90.0,
        shards.SPLIT_FILE + "::test_other": 10.0,
    }
    items, weights = shards.expanded_test_items(repo, shards.test_files(repo), durations)
    assert len([name for name in items if name.startswith(shards.SPLIT_FILE + "::")]) == 2
    assert weights[shards.SPLIT_FILE + "::test_cases"] == 90.0
    assert weights[shards.SPLIT_FILE + "::test_other"] == 10.0
    with pytest.raises(ValueError, match="Invalid"):
        invalid = tmp_path / "bad-durations.tsv"
        invalid.write_text(shards.SPLIT_FILE + "::helper_wrong\t15.0\n")
        shards.read_durations(invalid)


def test_actual_measured_function_times_match_latest_baseline():
    durations = shards.read_durations()
    hot = shards.SPLIT_FILE + "::"
    assert durations[hot + "test_previous_overlay_generations_upgrade_without_losing_date_or_history"] > 240.0
    assert durations[hot + "test_published_83_member_generation_upgrades_without_losing_originals_or_date"] > 210.0
    repo = Path(__file__).resolve().parents[1]
    items, weights = shards.expanded_test_items(repo, shards.test_files(repo), durations)
    assert weights[hot + "test_previous_overlay_generations_upgrade_without_losing_date_or_history"] == pytest.approx(243.09)
    assert len([name for name in items if name.startswith(hot)]) == 20
