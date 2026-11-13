"""Contract tests for scripts/ci_select_tests.py.

The selector decides which pytest files a pull request runs. These tests
pin its conservative rules on synthetic repos, so a future edit cannot
quietly widen what a PR skips: shared code, fixtures, workflows,
entrypoints, and anything unmapped must still run the full suite.
"""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ci_select_tests as selector

def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path):
    write_tree(tmp_path, {
        "app/__init__.py": "",
        "app/core.py": "VALUE = 1\n",
        "app/helper.py": "from app import core\n",
        "app/leaf.py": "VALUE = 2\n",
        "tests/test_core.py": "from app import core\n\ndef test_core():\n    assert core.VALUE == 1\n",
        "tests/test_helper.py": "from app import helper\n\ndef test_helper():\n    assert helper.core.VALUE == 1\n",
        "tests/test_unrelated.py": "def test_unrelated():\n    assert True\n",
        "tests/test_ci_workflow_concurrency.py": "def test_guard():\n    assert True\n",
        "tests/test_ci_ubuntu_mirror_priority.py": "def test_guard():\n    assert True\n",
        "tests/test_ci_affected_test_selection.py": "def test_guard():\n    assert True\n",
    })

    return tmp_path


def test_changed_test_file_selects_itself(repo):
    mode, selected, _ = selector.select(repo, ["tests/test_unrelated.py"])
    assert mode == "affected"
    assert "tests/test_unrelated.py" in selected


def test_changed_module_selects_direct_importers_only(repo):
    # test_helper imports helper, which imports core -- but helper's test
    # does NOT import core directly, so it is not selected. Direct import
    # is the rule (see the selector docstring for the measured depth curve).
    mode, selected, _ = selector.select(repo, ["app/core.py"])
    assert mode == "affected"
    assert "tests/test_core.py" in selected
    assert "tests/test_helper.py" not in selected
    assert "tests/test_unrelated.py" not in selected


def test_changed_leaf_module_selects_its_few_tests(repo):
    mode, selected, _ = selector.select(repo, ["app/leaf.py"])
    assert mode == "affected"
    # No test imports leaf; only the guard tests run.
    assert selected == sorted(selector.GUARD_TESTS)


def test_guard_tests_always_run_in_affected_mode(repo):
    _, selected, _ = selector.select(repo, ["tests/test_unrelated.py"])
    for guard in selector.GUARD_TESTS:
        assert guard in selected


def test_conftest_change_runs_full_suite(repo):
    write_tree(repo, {"tests/conftest.py": "import pytest\n"})
    mode, selected, log = selector.select(repo, ["tests/conftest.py"])
    assert mode == "full"
    assert selected == []


def test_fixture_change_runs_full_suite(repo):
    write_tree(repo, {"tests/fixtures/workspace.py": "DATA = 1\n"})
    mode, _, _ = selector.select(repo, ["tests/fixtures/workspace.py"])
    assert mode == "full"


def test_workflow_change_runs_full_suite(repo):
    mode, _, _ = selector.select(repo, [".github/workflows/tests.yml"])
    assert mode == "full"


def test_entrypoint_change_runs_full_suite(repo):
    for changed in ("run_web.py", "app/__init__.py", "pages/2_Smartsheet_PO.py"):
        mode, _, _ = selector.select(repo, [changed])
        assert mode == "full", changed


def test_app_init_change_runs_full_suite_even_when_selection_is_small(repo):
    # app/__init__.py is package init: every `from app import ...` runs
    # it, so it forces the full suite outright -- not just via the 70%
    # rule. Pad the repo so the affected set stays small (5/11 files)
    # and an "affected" answer would be possible without the explicit
    # rule.
    for name in ("test_extra_a.py", "test_extra_b.py", "test_extra_c.py",
                 "test_extra_d.py", "test_extra_e.py"):
        write_tree(repo, {f"tests/{name}": "def test_extra():\n    assert True\n"})
    mode, selected, log = selector.select(repo, ["app/__init__.py"])
    assert mode == "full"
    assert selected == []
    assert any("app/__init__.py" in line for line in log)


def test_changed_test_helper_selects_its_consumers(repo):
    # A test file that supplies shared helpers: changing it must run its
    # consumers, whether they import it by bare name (pytest puts the
    # tests directory on sys.path) or dotted name.
    write_tree(repo, {
        "tests/test_shared_ui.py": "def monthly():\n    return 'monthly'\n",
        "tests/test_consumer_bare.py": "from test_shared_ui import monthly\n\ndef test_consumer():\n    assert monthly() == 'monthly'\n",
        "tests/test_consumer_dotted.py": "from tests.test_shared_ui import monthly\n\ndef test_consumer():\n    assert monthly() == 'monthly'\n",
    })
    mode, selected, _ = selector.select(repo, ["tests/test_shared_ui.py"])
    assert mode == "affected"
    assert "tests/test_shared_ui.py" in selected
    assert "tests/test_consumer_bare.py" in selected
    assert "tests/test_consumer_dotted.py" in selected
    assert "tests/test_unrelated.py" not in selected


def test_requirements_change_runs_full_suite(repo):
    mode, _, _ = selector.select(repo, ["requirements-dev.lock"])
    assert mode == "full"


def test_unmapped_file_runs_full_suite(repo):
    mode, _, _ = selector.select(repo, ["app/widget.js"])
    assert mode == "full"


def test_docs_change_selects_tests_mentioning_it(repo):
    write_tree(repo, {
        "docs/README.md": "# docs\n",
        "tests/test_docs.py": "from pathlib import Path\n\ndef test_docs():\n    assert Path('docs/README.md').exists()\n",
    })
    mode, selected, _ = selector.select(repo, ["docs/README.md"])
    assert mode == "affected"
    assert "tests/test_docs.py" in selected
    assert "tests/test_core.py" not in selected


def test_top_level_docs_change_selects_docs_index_test(repo):
    # tests/test_docs_index.py discovers docs with DOCS.glob("*.md"), so
    # it never mentions any one file by name; a top-level docs/*.md
    # change must still select it.
    write_tree(repo, {
        "docs/NOTES.md": "# notes\n",
        "tests/test_docs_index.py": "from pathlib import Path\n\nDOCS = Path('docs')\n\ndef test_docs_index():\n    assert sorted(p for p in DOCS.glob('*.md'))\n",
    })
    mode, selected, _ = selector.select(repo, ["docs/NOTES.md"])
    assert mode == "affected"
    assert "tests/test_docs_index.py" in selected


def test_nested_docs_change_does_not_select_docs_index_test(repo):
    # The glob is top-level only, so a docs change below docs/ does not
    # select the index test.
    write_tree(repo, {
        "docs/sub/NOTES.md": "# notes\n",
        "tests/test_docs_index.py": "from pathlib import Path\n\nDOCS = Path('docs')\n\ndef test_docs_index():\n    assert sorted(p for p in DOCS.glob('*.md'))\n",
    })
    mode, selected, _ = selector.select(repo, ["docs/sub/NOTES.md"])
    assert mode == "affected"
    assert "tests/test_docs_index.py" not in selected


def test_wide_change_runs_full_suite(repo):
    # A module imported by most tests is a wide change: selecting almost
    # everything saves nothing, so the selector runs the full suite.
    write_tree(repo, {"app/core.py": "VALUE = 1\n"})
    # Make every test import core directly.
    for name in ("test_core.py", "test_helper.py", "test_unrelated.py"):
        path = repo / "tests" / name
        path.write_text("from app import core\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    mode, selected, log = selector.select(repo, ["app/core.py"])
    assert mode == "full"
    assert selected == []
    assert any("covers too much" in line for line in log)


def test_selector_cli_writes_selection_file(repo, tmp_path):
    changed = tmp_path / "changed.txt"
    changed.write_text("tests/test_unrelated.py\n", encoding="utf-8")
    out = tmp_path / "selected.txt"
    code = selector.main([
        "--event", "pull_request",
        "--changed-file", str(changed),
        "--out", str(out),
        "--repo", str(repo),
    ])
    assert code == 0
    assert "tests/test_unrelated.py" in out.read_text(encoding="utf-8")


def test_non_pr_event_runs_full_suite(repo, tmp_path):
    out = tmp_path / "selected.txt"
    code = selector.main([
        "--event", "push", "--out", str(out), "--repo", str(repo),
    ])
    assert code == 0
    assert out.read_text(encoding="utf-8") == ""
