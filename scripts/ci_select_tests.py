"""Select the pytest files affected by a pull request.

Policy (see .github/workflows/tests.yml): pull requests run only the tests
affected by the PR; pushes to main always run the complete suite. The
selection is deliberately conservative -- whenever the mapping is uncertain
the selector falls back to the full suite instead of silently skipping
tests. A knock-on regression a PR selection misses is therefore still
caught by the full suite on the main push, but only after the merge; that
residual risk is the price of the faster PR runs and is stated on every PR
that uses this selector.

How a changed file maps to tests:

* A changed ``tests/test_*.py`` file selects itself.
* A changed Python module selects every test file that imports it
  *directly* (including imports inside test functions), plus every test
  file that mentions the module's dotted name or file name in its text.
  Direct import is the rule on purpose, and the depth curve was measured
  on this repo (2026-11-12): for ``app.monthly_report_guided`` direct
  importers are 78 test files, two hops already reach 184, and full
  transitive closure reaches 82% of the suite -- the UI modules import
  each other so densely that transitive closure saves nothing for core
  modules. A test that reaches a changed module only through another
  module is the known residual risk of this selector (see the note at the
  top of this file); the full suite on the main push is the backstop.
* A changed documentation or data file under ``docs/`` selects the test
  files that mention its path (tests do read docs files, e.g. the ownership
  matrix), plus the CI-guard tests.
* Anything else falls back to the full suite: shared code and entrypoints
  (``run_web.py``, ``app/__init__.py``, ``pages/`` -- Streamlit pages are
  exercised by AppTest journey tests that never import them, so the import
  graph is systematically blind there), fixtures and ``conftest.py``,
  requirements/locks, the Dockerfile, any ``.github/`` change, JavaScript,
  and any path the selector cannot classify. A changed workflow file is a
  full-suite change by definition.
* The CI-guard tests (the tests that pin workflow behaviour, and this
  selector's own tests) always run in affected mode.
* If the affected set would still cover more than 70% of the test files,
  the selector runs the full suite instead -- there is no meaningful saving
  in selecting almost everything, and the full run is the safer choice.

Output: the ``--out`` file lists one selected test path per line. An empty
file means "run the full suite" -- the workflow runs bare ``pytest`` in
that case. The selector always exits 0: any failure to compute a selection
(unknown git state, unparsable file, ...) prints a warning and falls back
to the full suite rather than failing CI or running nothing.
"""

from __future__ import annotations

import argparse
from ast import parse as parse_ast
from ast import Import, ImportFrom, walk
from pathlib import Path
import subprocess
import sys

# Test files that pin CI/workflow behaviour and this selector itself. They
# are cheap and always run in affected mode, whatever else changed.
GUARD_TESTS = (
    "tests/test_ci_workflow_concurrency.py",
    "tests/test_ci_ubuntu_mirror_priority.py",
    "tests/test_ci_affected_test_selection.py",
)

# More than this share of the suite selected means "just run everything".
FULL_FRACTION = 0.70

# Directories whose Python files take part in the import graph.
GRAPH_DIRS = ("app", "pages", "scripts", "runtime", "tests")
GRAPH_ROOTS = ("run_web.py",)

# A changed file matching any of these forces the full suite.
FULL_SUFFIXES = (".js", ".cjs", ".mjs", ".ts", ".yml", ".yaml", ".toml", ".cfg", ".ini")
FULL_NAMES = {
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements.lock",
    "requirements-dev.lock",
    "pyproject.toml",
    "setup.cfg",
    "run_web.py",
}
FULL_DIRS = (".github", "tests/fixtures")


def module_name(path: Path, repo: Path) -> str:
    """Repo-relative dotted module name for a Python file."""
    rel = path.relative_to(repo).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def parse_imports(path: Path, repo: Path) -> set[str]:
    """All repo-internal module names imported by one Python file.

    Imports inside functions and conditional blocks count: tests in this
    repo commonly import app modules lazily inside the test function.
    """
    try:
        tree = parse_ast(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    own = module_name(path, repo)
    package = own.rsplit(".", 1)[0] if "." in own else ""
    found: set[str] = set()
    for current in walk(tree):
        if isinstance(current, Import):
            found.update(alias.name for alias in current.names)
        elif isinstance(current, ImportFrom):
            level = current.level
            base = current.module or ""
            if level:
                parts = package.split(".") if package else []
                up = level - 1
                prefix = ".".join(parts[: len(parts) - up]) if up < len(parts) else ""
                base = f"{prefix}.{base}" if prefix and base else prefix or base
            if base:
                found.add(base)
                for alias in current.names:
                    found.add(f"{base}.{alias.name}")
    return found


class ImportGraph:
    """Reverse import reachability: which test files can reach a module."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.edges: dict[str, set[str]] = {}
        self.test_modules: dict[str, Path] = {}
        self._build()

    def _python_files(self):
        for dirname in GRAPH_DIRS:
            root = self.repo / dirname
            if root.is_dir():
                yield from sorted(root.rglob("*.py"))
        for name in GRAPH_ROOTS:
            path = self.repo / name
            if path.is_file():
                yield path

    def _build(self) -> None:
        modules: dict[str, Path] = {}
        for path in self._python_files():
            # conftest.py and test helpers are nodes too: a test that
            # imports a helper inherits the helper's imports.
            modules[module_name(path, self.repo)] = path
        for module, path in modules.items():
            self.edges[module] = {
                imported
                for imported in parse_imports(path, self.repo)
                if imported in modules or imported.startswith(("app.", "pages.", "scripts.", "runtime.", "tests."))
            }
        for module, path in modules.items():
            if module.startswith("tests.test_"):
                self.test_modules[module] = path

    def tests_importing(self, changed: set[str]) -> set[Path]:
        """Test files that import a changed module directly.

        Deliberately depth 1, not transitive: following the import graph
        further explodes through the densely-importing UI modules (see the
        module docstring) and saves nothing on core modules.
        """
        selected = set()
        for module, path in self.test_modules.items():
            if self.edges.get(module, set()) & changed:
                selected.add(path)
        return selected


def changed_files(repo: Path, base: str, head: str) -> list[str] | None:
    """Files changed between base and head, or None if git cannot tell."""
    try:
        merge_base = subprocess.run(
            ["git", "merge-base", base, head],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
        result = subprocess.run(
            ["git", "diff", "--name-only", merge_base, head],
            cwd=repo, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def _is_test_file(rel: str) -> bool:
    return rel.startswith("tests/") and rel.rsplit("/", 1)[-1].startswith("test_") and rel.endswith(".py")


def _is_docs_file(rel: str) -> bool:
    return (rel.startswith("docs/") or "/" not in rel) and rel.endswith((".md", ".rst", ".txt", ".json"))


def _forces_full(rel: str) -> str | None:
    """Reason a changed file forces the full suite, or None."""
    if rel in FULL_NAMES or any(rel.startswith(d + "/") or rel == d for d in FULL_DIRS):
        return f"{rel} is shared/config (full suite)"
    if rel.startswith(".github/"):
        return f"{rel} changes CI configuration (full suite)"
    if rel.startswith("pages/"):
        return f"{rel} is a Streamlit entry page the import graph cannot see (full suite)"
    if rel.endswith(FULL_SUFFIXES):
        return f"{rel} is not mapped by the import graph (full suite)"
    if rel.startswith("tests/") and not _is_test_file(rel):
        return f"{rel} is shared test support (full suite)"
    if "/" not in rel and "." not in rel.rsplit("/", 1)[-1]:
        return f"{rel} is an unmapped top-level file (full suite)"
    return None


def select(repo: Path, changed: list[str]) -> tuple[str, list[str], list[str]]:
    """Return (mode, selected test paths, log lines).

    Mode is "full" or "affected". In "full" mode the selected list is
    empty, which the caller treats as "run bare pytest".
    """
    log = [f"changed files ({len(changed)}): " + ", ".join(sorted(changed))]
    graph = ImportGraph(repo)
    all_tests = sorted(
        str(p.relative_to(repo)) for p in graph.test_modules.values()
    )
    if not changed:
        return "full", [], log + ["no changed files reported; running the full suite"]

    full_reasons = [r for r in (_forces_full(rel) for rel in changed) if r]
    if full_reasons:
        return "full", [], log + ["FULL SUITE: " + "; ".join(full_reasons)]

    selected: set[str] = set()
    changed_modules: set[str] = set()
    for rel in changed:
        path = repo / rel
        if _is_test_file(rel):
            selected.add(rel)
            log.append(f"selected {rel} (changed test file)")
        elif rel.endswith(".py") and path.is_file():
            changed_modules.add(module_name(path, repo))
        elif _is_docs_file(rel):
            # Tests read docs files; select the ones mentioning this file.
            needle = Path(rel).name
            hits = {
                str(p.relative_to(repo))
                for p in graph.test_modules.values()
                if needle in p.read_text(encoding="utf-8", errors="ignore")
            }
            selected.update(hits)
            log.append(f"selected {len(hits)} test(s) mentioning {needle}")
        else:
            return "full", [], log + [f"FULL SUITE: {rel} cannot be mapped"]

    if changed_modules:
        reached = graph.tests_importing(changed_modules)
        selected.update(str(p.relative_to(repo)) for p in reached)
        log.append(
            f"import graph: {len(changed_modules)} changed module(s) imported "
            f"directly by {len(reached)} test file(s)"
        )
        # Text mentions catch tests that reference a module by name without
        # importing it (node ids, fixture names, data paths).
        for module in sorted(changed_modules):
            short = module.rsplit(".", 1)[-1]
            if len(short) < 10:
                continue
            hits = {
                str(p.relative_to(repo))
                for p in graph.test_modules.values()
                if short in p.read_text(encoding="utf-8", errors="ignore")
            }
            new = hits - selected
            selected.update(hits)
            if new:
                log.append(f"text mentions of {short}: +{len(new)} test file(s)")

    selected.update(g for g in GUARD_TESTS if (repo / g).is_file())
    selected = {s for s in selected if (repo / s).is_file()}
    if len(selected) > FULL_FRACTION * max(len(all_tests), 1):
        return "full", [], log + [
            f"FULL SUITE: affected set ({len(selected)}/{len(all_tests)} test files) "
            "covers too much of the suite to save anything"
        ]
    return "affected", sorted(selected), log + [
        f"AFFECTED: {len(selected)}/{len(all_tests)} test files selected"
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default="pull_request")
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--out", required=True, help="file to write selected test paths to (empty = full suite)")
    parser.add_argument("--changed-file", default="", help="file listing changed paths, one per line (local use/testing)")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    out = Path(args.out)
    try:
        if args.event != "pull_request":
            mode, selected, log = "full", [], [f"event is {args.event!r}, not a pull request; running the full suite"]
        elif args.changed_file:
            changed = [
                line.strip()
                for line in Path(args.changed_file).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            mode, selected, log = select(repo, changed)
        else:
            if not args.base or not args.head:
                mode, selected, log = "full", [], ["no base/head given; running the full suite"]
            else:
                changed = changed_files(repo, args.base, args.head)
                if changed is None:
                    mode, selected, log = "full", [], ["git diff failed; running the full suite"]
                else:
                    mode, selected, log = select(repo, changed)
    except Exception as exc:  # never fail CI because selection broke
        print(f"WARNING: test selection failed ({exc}); running the full suite", file=sys.stderr)
        mode, selected, log = "full", [], [f"selection error: {exc}"]
    for line in log:
        print(f"[ci_select_tests] {line}")
    print(f"[ci_select_tests] mode={mode} selected={len(selected)}")
    out.write_text("".join(f"{path}\n" for path in selected), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
