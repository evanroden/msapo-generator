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


def validate_workflow(text):
    jobs = parse_jobs(text)
    original = json.loads((ROOT / 'tests/fixtures/native_workflow_steps.json').read_text())
    # The contact journey moves intact to its own mandatory bounded job.
    contact = [step for step in original['synthetic-dom'] if 'qa_compact_contact_journey.py' in step.get('commands', '')]
    assert len(contact) == 1
    original['synthetic-dom'] = [step for step in original['synthetic-dom'] if step not in contact]
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
        if not path.exists() or path.read_text().split()[2] == 'Z':
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
