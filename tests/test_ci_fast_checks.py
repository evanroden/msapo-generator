"""Fast CI guards: syntax errors fail in seconds; slow mirrors do not eat the budget."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _job(path, name):
    text = path.read_text(encoding="utf-8").split("\njobs:\n", 1)[1]
    section = text.split(f"\n  {name}:\n", 1)[1] if not text.startswith(f"  {name}:\n") else text.split(f"  {name}:\n", 1)[1]
    return re.split(r"(?m)^  [a-z][a-z0-9-]*:\n", section, maxsplit=1)[0]


def test_pr_tests_compile_every_python_file_before_selecting_tests():
    select = _job(WORKFLOWS / "tests.yml", "select-pr-tests")
    command = "run: python -m compileall -q app scripts tests pages run_web.py"
    assert select.count(command) == 1
    assert select.index(command) < select.index("scripts/ci_select_tests.py")


def test_every_python_file_compiles_now():
    import compileall
    for folder in ("app", "scripts", "tests", "pages"):
        assert compileall.compile_dir(ROOT / folder, quiet=1, force=False), folder
    assert compileall.compile_file(ROOT / "run_web.py", quiet=1)


def test_finished_pdf_browser_prefers_mirror_and_bounds_the_install():
    path = WORKFLOWS / "monthly-finished-pdf-viewer.yml"
    workflow = path.read_text(encoding="utf-8")
    job = _job(path, "current-session-pdf-browser")
    install = job.split("      - name: Install locked application and browser runtime\n", 1)[1]
    install = install.split("      - name:", 1)[0]
    assert "        timeout-minutes: 20\n" in install
    command = "sudo python3 scripts/ci_ubuntu_mirror_priority.py"
    assert install.count(command) == 1
    assert install.index(command) < install.index("python -m playwright install --with-deps")
    assert "    timeout-minutes: 30\n" in job
    paths = workflow.split("\n  workflow_dispatch:", 1)[0]
    assert "      - 'scripts/ci_ubuntu_mirror_priority.py'" in paths
    assert "      - 'tests/test_ci_ubuntu_mirror_priority.py'" in paths
