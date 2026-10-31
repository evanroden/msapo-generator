import importlib.util
from pathlib import Path
import subprocess

import pytest
import re
import json

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('budget', ROOT / 'scripts/ci_native_test_budget.py')
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


def test_deadline_never_resets(tmp_path):
    path = tmp_path / 'deadline'
    assert budget.remaining_budget(path, 60, 100) == 60
    assert budget.remaining_budget(path, 60, 120) == 40
    assert budget.remaining_budget(path, 60, 161) == 0
    with pytest.raises(ValueError):
        budget.remaining_budget(path, 120, 162)


@pytest.mark.parametrize('content', ['{}', '{"seconds":60,"deadline":9999}', '{"seconds":60,"deadline":"x"}', '{"seconds":60,"deadline":NaN}'])
def test_invalid_deadline_fails_closed(tmp_path, content):
    path = tmp_path / 'deadline'
    path.write_text(content)
    with pytest.raises((ValueError, TypeError)):
        budget.remaining_budget(path, 60, 100)


def test_timeout_and_exit_status(tmp_path):
    assert budget.run_command('exit 7', 1) == 7
    assert budget.run_command('false | true', 1) != 0
    assert budget.run_command('sleep 10', 0.05) == 124
    marker = tmp_path / 'not-executed'
    assert budget.run_command(f'touch {marker}', 0) == 124
    assert not marker.exists()


def parse_jobs(text):
    jobs = {}
    for block in re.split(r"(?=^  [a-z][a-z-]+:\n)", text.split("jobs:\n", 1)[1], flags=re.M):
        if not block.strip():
            continue
        name = re.match(r"  ([\w-]+):", block).group(1)
        jobs[name] = re.split(r"(?=^      - )", block, flags=re.M)
    return jobs


def validate_fresh_water_relocation(text, jobs, original):
    """Recognize only the approved intact relocation, never a generic count waiver."""
    command = 'python scripts/qa_water_fresh_page_journey.py'
    moved = [step for step in original['synthetic-dom']
             if command in step.get('commands', '')]
    assert len(moved) == 1
    assert moved[0]['commands'].strip() == command
    assert text.count(command) == 1
    assert 'fresh-water' in jobs
    actual = ''.join(jobs['fresh-water'])
    # Only comments/outer whitespace are immaterial; env, if, command, dependency,
    # artifact and every timeout must match this bounded mandatory job exactly.
    actual = ''.join(line for line in actual.splitlines(True)
                     if not line.lstrip().startswith('#'))
    expected = """  fresh-water:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
          cache-dependency-path: requirements-dev.lock
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      - name: Install locked app and fresh Water browser harness
        timeout-minutes: 5
        run: |
          sudo python3 scripts/ci_ubuntu_mirror_priority.py
          sudo apt-get update -qq
          sudo apt-get install -y --no-install-recommends libreoffice-writer libreoffice-calc
          python -m pip install -r requirements-dev.lock
          python scripts/patch_streamlit_frontend.py
          python -m pip install playwright==1.58.0
          python -m playwright install --with-deps chromium webkit
      - name: Fresh ordinary Water in both native engines
        timeout-minutes: 9
        run: |
          python scripts/ci_native_test_budget.py --minutes 8 <<'NATIVE_TEST'
          python scripts/patch_streamlit_date_input.py
          python scripts/qa_water_fresh_page_journey.py
          NATIVE_TEST
      - name: Preserve fresh Water evidence including first failures
        if: always()
        timeout-minutes: 2
        uses: actions/upload-artifact@v4
        with:
          name: fresh-water-browser-evidence-${{ github.run_attempt }}
          path: test-artifacts/water-fresh-page-journey/
          retention-days: 7
          if-no-files-found: error

"""
    assert actual.strip() == expected.strip()
    original['synthetic-dom'] = [step for step in original['synthetic-dom']
                                 if step not in moved]
    artifact_path = '            test-artifacts/water-fresh-page-journey/\n'
    uploads = [step for step in original['synthetic-dom']
               if artifact_path in step['raw']]
    assert len(uploads) == 1
    assert uploads[0]['raw'].count(artifact_path) == 1
    # Its evidence moved to the exact always-upload job above; all other frozen
    # artifact paths and all remaining DOM steps still compare byte-for-byte.
    uploads[0]['raw'] = uploads[0]['raw'].replace(artifact_path, '')


def validate_water_row_relocation(text, jobs, original):
    from test_water_row_workflow_partition import validate_partition
    validate_partition(text)
    commands = ('qa_water_page_journey.py', 'qa_report_row_cards.py')
    moved = [step for step in original['synthetic-dom']
             if any(command in step.get('commands', '') for command in commands)]
    assert len(moved) == 2
    original['synthetic-dom'] = [step for step in original['synthetic-dom'] if step not in moved]
    for directory in ('water-page-journey', 'report-row-cards'):
        path = '            test-artifacts/' + directory + '/\n'
        uploads = [step for step in original['synthetic-dom'] if path in step['raw']]
        assert len(uploads) == 1 and uploads[0]['raw'].count(path) == 1
        uploads[0]['raw'] = uploads[0]['raw'].replace(path, '')


def validate_workflow(text):
    jobs = parse_jobs(text)
    original = json.loads((ROOT / 'tests/fixtures/native_workflow_steps.json').read_text())
    # The contact journey moves intact to its own mandatory bounded job.
    contact = [step for step in original['synthetic-dom'] if 'qa_compact_contact_journey.py' in step.get('commands', '')]
    assert len(contact) == 1
    original['synthetic-dom'] = [step for step in original['synthetic-dom'] if step not in contact]
    validate_fresh_water_relocation(text, jobs, original)
    validate_water_row_relocation(text, jobs, original)
    ceilings = {'literal-labels':10, 'synthetic-history':15, 'synthetic-progress-photos':15, 'synthetic-dom':25, 'training-date':15}
    for name, ceiling in ceilings.items():
        chunks = jobs[name]
        outer = 45 if name == 'synthetic-progress-photos' else 20 + ceiling + 15
        assert f'timeout-minutes: {outer}\n' in chunks[0]
        assert len(chunks[1:]) == len(original[name])
        for step, previous in zip(chunks[1:], original[name]):
            stripped = re.sub(r'^        timeout-minutes: \d+\n', '', step, flags=re.M)
            if '        run:' in step and 'name: Install locked app' not in step and name != 'synthetic-progress-photos':
                prefix = f"        run: |\n          python scripts/ci_native_test_budget.py --minutes {ceiling} <<'NATIVE_TEST'\n"
                assert f'timeout-minutes: {ceiling + 1}\n' in step
                assert prefix in stripped
                before, commands = stripped.split(prefix)
                assert commands.rstrip().endswith('NATIVE_TEST')
                commands = commands[:commands.rfind('          NATIVE_TEST')]
                assert before == previous['before']
                assert commands.strip() == previous['commands'].strip()
            else:
                assert stripped.strip() == previous['raw'].strip()
                if 'name: Install locked app' in step:
                    assert 'timeout-minutes: 20' in step
                if 'upload-artifact' in step:
                    assert 'timeout-minutes: 3' in step
                    assert 'if: always()' in step


def test_workflow_separates_setup_from_original_aggregate_test_budgets():
    validate_workflow((ROOT / '.github/workflows/adaptive-workspaces.yml').read_text())


@pytest.mark.parametrize(('old', 'new'), [
    ('--minutes 25', '--minutes 26'),
    ('timeout-minutes: 26', 'timeout-minutes: 999'),
    ("EPC_MONTHLY_WATER_TASK: '1'", "EPC_MONTHLY_WATER_TASK: '0'"),
    ("python scripts/ci_native_test_budget.py --minutes 25", "cat"),
    ('timeout-minutes: 20', 'timeout-minutes: 999'),
    ('if: ${{ !cancelled() }}', 'if: success()'),
    ('if: always()', 'if: success()'),
    ('python scripts/qa_water_fresh_page_journey.py', 'true'),
    ('timeout-minutes: 3\n', 'timeout-minutes: 999\n'),
])
def test_workflow_gate_or_budget_weakening_is_rejected(old, new):
    text = (ROOT / '.github/workflows/adaptive-workspaces.yml').read_text()
    assert old in text
    with pytest.raises(AssertionError):
        validate_workflow(text.replace(old, new))


def test_term_resistant_descendant_is_killed_when_shell_exits(tmp_path):
    import os
    import time
    child = tmp_path / 'child.py'
    pidfile = tmp_path / 'pid'
    child.write_text("import signal,os,time,pathlib\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\npathlib.Path(" + repr(str(pidfile)) + ").write_text(str(os.getpid()))\ntime.sleep(30)\n")
    assert budget.run_command(f'python {child} & wait', 0.3) == 124
    pid = int(pidfile.read_text())
    # A killed orphan can remain as a zombie until its system reaper runs.
    for _ in range(100):
        path = Path(f'/proc/{pid}/stat')
        if not path.exists():
            break
        try:
            state = path.read_text().split()[2]
        except FileNotFoundError:
            # The kernel may reap it between exists() and this read.
            break
        if state == 'Z':
            break
        time.sleep(0.01)
    else:
        os.kill(pid, 9)
        pytest.fail('TERM-resistant descendant survived aggregate deadline')


def test_contact_job_is_mandatory_bounded_and_preserves_the_full_journey():
    text = (ROOT / '.github/workflows/adaptive-workspaces.yml').read_text()
    jobs = parse_jobs(text)
    contact = ''.join(jobs['synthetic-contact'])
    dom = ''.join(jobs['synthetic-dom'])
    assert '    timeout-minutes: 45\n' in jobs['synthetic-contact'][0]
    assert '    if:' not in jobs['synthetic-contact'][0]
    assert 'continue-on-error' not in contact
    assert contact.count('python scripts/qa_compact_contact_journey.py') == 1
    assert 'qa_compact_contact_journey.py' not in dom
    setup = next(s for s in jobs['synthetic-contact'] if 'name: Install locked app' in s)
    assert setup == next(s for s in jobs['synthetic-dom'] if 'name: Install locked app' in s)
    assert "python -m playwright install --with-deps chromium webkit" in setup
    assert contact.count("python scripts/ci_native_test_budget.py --minutes 15 <<'NATIVE_TEST'") == 2
    assert contact.count('        timeout-minutes: 16\n') == 2
    run = next(s for s in jobs['synthetic-contact'] if 'qa_compact_contact_journey.py' in s)
    assert 'if: ${{ !cancelled() }}' in run
    assert run.split("<<'NATIVE_TEST'\n", 1)[1].strip() == 'python scripts/qa_compact_contact_journey.py\n          NATIVE_TEST'
    upload = next(s for s in jobs['synthetic-contact'] if 'upload-artifact' in s)
    assert 'if: always()' in upload
    assert 'timeout-minutes: 3' in upload
    assert 'path: test-artifacts/compact-contact-journey/' in upload
    assert 'retention-days: 7' in upload


@pytest.mark.parametrize(('old', 'new'), [
    ('  fresh-water:\n', '  optional-water:\n'),
    ('    steps:\n', '    if: false\n    steps:\n'),
    ('    steps:\n', '    continue-on-error: true\n    steps:\n'),
    ('    steps:\n', '    env:\n      SKIP_WEBKIT: 1\n    steps:\n'),
    ('--minutes 8', '--minutes 9'),
    ('timeout-minutes: 15', 'timeout-minutes: 10'),
    ('timeout-minutes: 5', 'timeout-minutes: 20'),
    ('timeout-minutes: 9', 'timeout-minutes: 26'),
    ('timeout-minutes: 2', 'timeout-minutes: 9'),
    ('chromium webkit', 'chromium'),
    ('playwright==1.58.0', 'playwright'),
    ('python scripts/patch_streamlit_date_input.py', 'true'),
    ('python scripts/qa_water_fresh_page_journey.py', 'true'),
    ('if: always()', 'if: success()'),
    ('if-no-files-found: error', 'if-no-files-found: warn'),
    ('test-artifacts/water-fresh-page-journey/', 'test-artifacts/other/'),
])
def test_fresh_water_relocation_weakening_is_rejected(old, new):
    text = (ROOT / '.github/workflows/adaptive-workspaces.yml').read_text()
    lane = ''.join(parse_jobs(text)['fresh-water'])
    assert old in lane
    changed = text.replace(lane, lane.replace(old, new, 1), 1)
    assert changed != text
    with pytest.raises(AssertionError):
        validate_workflow(changed)


def test_fresh_water_duplicate_or_missing_mandatory_job_is_rejected():
    text = (ROOT / '.github/workflows/adaptive-workspaces.yml').read_text()
    lane = ''.join(parse_jobs(text)['fresh-water'])
    for changed in (text.replace(lane, ''), text + lane):
        with pytest.raises(AssertionError):
            validate_workflow(changed)
