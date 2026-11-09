"""One immutable warning-job deadline with a smaller financial command cap."""
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/ci_native_test_budget.py'
WORKFLOW = ROOT / '.github/workflows/monthly-warning-routes.yml'
spec = importlib.util.spec_from_file_location('warning_budget', HELPER)
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


def invoke(monkeypatch, tmp_path, args, command='exit 0', now=100):
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', [str(HELPER), *args])
    monkeypatch.setattr(sys, 'stdin', io.StringIO(command))
    monkeypatch.setattr(budget.time, 'monotonic', lambda: now)
    return budget.main()


def native_steps(text):
    return [s for s in re.split(r'(?=^      - )', text, flags=re.M)
            if 'scripts/ci_native_test_budget.py' in s]


def validate_workflow(text):
    assert re.findall(r'^  ([a-z_-]+):$', text, re.M) == ['pull_request', 'push', 'exact-warning-routes']
    assert '    timeout-minutes: 75\n' in text
    assert 'continue-on-error' not in text and 'RUNNER_TEMP' not in text
    assert 'msapo-native-test-budget.json' not in text
    steps = native_steps(text)
    assert len(steps) == 2
    assert steps[0].strip() == """- name: Native wide-pointer and narrow-keyboard warning, persistence and output journeys
        timeout-minutes: 35
        run: |
          python scripts/ci_native_test_budget.py --minutes 33 <<'NATIVE_TEST'
          python scripts/qa_warning_routes.py
          NATIVE_TEST"""
    assert steps[1].strip() == """- name: Preserve all original financial native admission and vendor-total gates
        timeout-minutes: 9
        run: |
          python scripts/ci_native_test_budget.py --minutes 33 --command-minutes 8 <<'NATIVE_TEST'
          python scripts/qa_financial_pages.py
          NATIVE_TEST"""
    assert text.count('python scripts/qa_warning_routes.py') == 1
    assert text.count('python scripts/qa_financial_pages.py') == 1
    assert 'chromium webkit' in text
    assert "assert not root.findall('.//skipped')" in text
    assert "assert len(root.findall('.//testcase')) >= 190" in text
    upload = next(s for s in re.split(r'(?=^      - )', text, flags=re.M) if 'uses: actions/upload-artifact@v4' in s)
    for field in ('if: always()', 'timeout-minutes: 3', 'test-artifacts/warning-routes/',
                  'test-artifacts/financial-pages/', 'retention-days: 7', 'if-no-files-found: error'):
        assert field in upload


def test_warning_workflow_keeps_both_suites_and_original_caps():
    validate_workflow(WORKFLOW.read_text())


def test_all_workflow_invocations_keep_one_aggregate_declaration_per_job():
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        text = path.read_text()
        if 'jobs:\n' not in text:
            continue
        for block in re.split(r'(?=^  [A-Za-z0-9_-]+:\n)', text.split('jobs:\n', 1)[1], flags=re.M):
            declared = re.findall(r'python scripts/ci_native_test_budget\.py --minutes (\d+)', block)
            assert len(set(declared)) <= 1, (path.name, block.splitlines()[0], declared)


def test_actual_workflow_invocations_share_one_deadline_and_financial_cap(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(budget, 'run_command', lambda command, remaining: calls.append((command, remaining)) or 0)
    steps = native_steps(WORKFLOW.read_text())
    record = tmp_path / 'msapo-native-test-budget.json'
    for index, step in enumerate(steps):
        line = next(line.strip() for line in step.splitlines() if 'scripts/ci_native_test_budget.py' in line)
        args = shlex.split(line.split(" <<'NATIVE_TEST'", 1)[0])[2:]
        command = step.split("<<'NATIVE_TEST'\n", 1)[1].rsplit('          NATIVE_TEST', 1)[0]
        assert invoke(monkeypatch, tmp_path, args, command, now=100 + index * 19 * 60) == 0
        if index == 0:
            original = record.read_bytes()
        else:
            assert record.read_bytes() == original
    assert calls == [('          python scripts/qa_warning_routes.py\n', 33 * 60),
                     ('          python scripts/qa_financial_pages.py\n', 8 * 60)]
    assert json.loads(record.read_text()) == {'seconds': 33 * 60, 'deadline': 100 + 33 * 60}


@pytest.mark.parametrize('elapsed,expected', [(0,480), (19*60,480), (32*60,60), (33*60,0), (34*60,0)])
def test_command_cap_never_extends_aggregate_and_never_rewrites_it(monkeypatch, tmp_path, elapsed, expected):
    record = tmp_path / 'msapo-native-test-budget.json'
    budget.remaining_budget(record, 33 * 60, 100)
    original = record.read_bytes()
    calls=[]
    monkeypatch.setattr(budget, 'run_command', lambda command, seconds: calls.append((command, seconds)) or 7)
    command = "printf '%s' 'literal arguments; not a second invocation'"
    assert invoke(monkeypatch, tmp_path, ['--minutes','33','--command-minutes','8'], command, 100+elapsed) == 7
    assert calls == [(command, expected)]
    assert record.read_bytes() == original


def test_omitted_command_cap_preserves_existing_behavior_and_exit_status(monkeypatch, tmp_path):
    calls=[]
    monkeypatch.setattr(budget, 'run_command', lambda command, seconds: calls.append((command, seconds)) or 9)
    assert invoke(monkeypatch,tmp_path,['--minutes','33'],'exit 9') == 9
    assert calls == [('exit 9',1980)]
    assert json.loads((tmp_path/'msapo-native-test-budget.json').read_text()) == {'seconds':1980,'deadline':2080}


@pytest.mark.parametrize('cap,expected', [('33',1980),('0.001',0.06)])
def test_valid_cap_boundaries_keep_original_aggregate_record(monkeypatch,tmp_path,cap,expected):
    calls=[];monkeypatch.setattr(budget,'run_command',lambda command,seconds:calls.append(seconds) or 0)
    assert invoke(monkeypatch,tmp_path,['--minutes','33','--command-minutes',cap]) == 0
    assert calls == [expected]
    assert json.loads((tmp_path/'msapo-native-test-budget.json').read_text()) == {'seconds':1980,'deadline':2080}


@pytest.mark.parametrize('cap',['0','-1','nan','inf','-inf','33.001'])
def test_invalid_or_larger_than_aggregate_cap_refuses_before_ledger_or_command(monkeypatch,tmp_path,cap):
    calls=[]
    monkeypatch.setattr(budget,'run_command',lambda *args:calls.append(args))
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch,tmp_path,['--minutes','33','--command-minutes='+cap])
    assert error.value.code == 2
    assert not calls and not (tmp_path/'msapo-native-test-budget.json').exists()


def test_aggregate_mismatch_still_refuses_without_executing(monkeypatch,tmp_path):
    record=tmp_path/'msapo-native-test-budget.json';budget.remaining_budget(record,1980,100);before=record.read_bytes()
    calls=[];monkeypatch.setattr(budget,'run_command',lambda *args:calls.append(args))
    with pytest.raises(ValueError,match='changed within the job'):
        invoke(monkeypatch,tmp_path,['--minutes','8','--command-minutes','1'],now=101)
    assert not calls and record.read_bytes()==before


@pytest.mark.parametrize(('old','new'),[
    ('--minutes 33 --command-minutes 8','--minutes 8'),
    ('--minutes 33 --command-minutes 8','--minutes 33'),
    ('--command-minutes 8','--command-minutes 9'),
    ('--minutes 33','--minutes 41'),
    ('timeout-minutes: 35','timeout-minutes: 36'),
    ('timeout-minutes: 9','timeout-minutes: 10'),
    ('timeout-minutes: 75','timeout-minutes: 76'),
    ('python scripts/qa_financial_pages.py','true'),
    ('python scripts/qa_warning_routes.py','true'),
    ('if: always()','if: success()'),
    ('if-no-files-found: error','if-no-files-found: warn'),
    ('chromium webkit','chromium'),
])
def test_budget_or_coverage_weakening_refuses(old,new):
    text=WORKFLOW.read_text();assert old in text
    with pytest.raises(AssertionError):validate_workflow(text.replace(old,new))


def cli(tmp_path, command, cap=None):
    args=[sys.executable,str(HELPER),'--minutes','33']
    if cap is not None:args += ['--command-minutes',str(cap)]
    return subprocess.run(args,input=command,text=True,capture_output=True,
                          env={**os.environ,'RUNNER_TEMP':str(tmp_path)},timeout=20)


def test_real_cli_exhausted_aggregate_never_launches_even_with_fresh_subcap(tmp_path):
    record=tmp_path/'msapo-native-test-budget.json';record.write_text(json.dumps({'seconds':1980,'deadline':0}))
    marker=tmp_path/'not-executed';before=record.read_bytes()
    result=cli(tmp_path,shlex.join([sys.executable,'-c',f'from pathlib import Path;Path({str(marker)!r}).write_text("bad")']),0.001)
    assert result.returncode==124 and 'aggregate test budget exhausted' in result.stderr
    assert not marker.exists() and record.read_bytes()==before


def test_real_cli_preserves_arguments_exit_failure_and_single_execution(tmp_path):
    marker=tmp_path/'execution';args=['semicolon; literal','spaces stay together','--not-an-option']
    code=f'import sys,json,pathlib;p=pathlib.Path({str(marker)!r});f=p.open("a");f.write(json.dumps(sys.argv[1:])+"\\n");f.close();raise SystemExit(7)'
    result=cli(tmp_path,shlex.join([sys.executable,'-c',code,*args]),0.02)
    assert result.returncode==7 and [json.loads(line) for line in marker.read_text().splitlines()]==[args]
    assert json.loads((tmp_path/'msapo-native-test-budget.json').read_text())['seconds']==1980


def test_real_small_subcap_uses_existing_process_group_cleanup_once(tmp_path):
    child=tmp_path/'child.py';pidfile=tmp_path/'pid';runs=tmp_path/'runs'
    child.write_text('import os,signal,time\nfrom pathlib import Path\n'
                     'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                     f'Path({str(pidfile)!r}).write_text(str(os.getpid()))\n'
                     f'with Path({str(runs)!r}).open("a") as f:f.write("once\\n")\n'
                     'time.sleep(30)\n')
    result=cli(tmp_path,shlex.join([sys.executable,str(child)])+' & wait',0.02)
    assert result.returncode==124 and 'aggregate test budget exhausted' in result.stderr
    assert runs.read_text()=='once\n'
    pid=int(pidfile.read_text())
    # Only the synthetic lifecycle check polls for kernel reap; no browser retry.
    for _ in range(100):
        status=Path(f'/proc/{pid}/stat')
        try:
            state=status.read_text().split()[2]
        except FileNotFoundError:
            break
        if state=='Z':break
        time.sleep(0.01)
    else:
        os.kill(pid,9)
        pytest.fail('TERM-resistant descendant survived command cap')


@pytest.mark.parametrize('state', ['already-gone','removed-at-read','zombie','alive','permission','io-error','malformed','removed-at-exists'])
def test_existing_process_reap_assertion_handles_only_missing_stat_read(monkeypatch,tmp_path,state):
    """Replay the actual legacy assertion, without launching any fake process."""
    spec=importlib.util.spec_from_file_location('legacy_budget_contract',ROOT/'tests/test_ci_native_test_budget.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    pid=99999991;events=[]
    def command(command,remaining):
        assert remaining==0.3
        (tmp_path/'pid').write_text(str(pid))
        events.append('command')
        return 124
    monkeypatch.setattr(legacy.budget,'run_command',command)
    class ProcStat:
        def exists(self):
            events.append('exists')
            if state=='removed-at-exists':raise FileNotFoundError('existence lookup itself failed')
            return state!='already-gone'
        def read_text(self):
            events.append('read')
            if state=='removed-at-read':raise FileNotFoundError('process reaped after exists')
            if state=='permission':raise PermissionError('not evidence of exit')
            if state=='io-error':raise OSError('not evidence of exit')
            if state=='malformed':return 'bad'
            return f'{pid} (child) '+('Z' if state=='zombie' else 'S')+' rest'
    def proc_path(value):
        assert value==f'/proc/{pid}/stat'
        return ProcStat()
    monkeypatch.setattr(legacy,'Path',proc_path)
    monkeypatch.setattr(time,'sleep',lambda seconds:events.append(('poll',seconds)))
    monkeypatch.setattr(os,'kill',lambda number,signal:events.append(('kill',number,signal)))
    run=lambda:legacy.test_term_resistant_descendant_is_killed_when_shell_exits(tmp_path)
    if state=='alive':
        with pytest.raises(pytest.fail.Exception,match='descendant survived'):
            run()
        assert events.count('read')==100 and ('kill',pid,9) in events
    elif state in ('permission','io-error','malformed','removed-at-exists'):
        error={'permission':PermissionError,'io-error':OSError,'malformed':IndexError,'removed-at-exists':FileNotFoundError}[state]
        with pytest.raises(error):run()
        assert not any(isinstance(item,tuple) and item[0]=='kill' for item in events)
    else:
        run()
        assert events==(['command','exists'] if state=='already-gone' else ['command','exists','read'])
