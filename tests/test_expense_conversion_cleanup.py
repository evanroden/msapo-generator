"""Calc owns its launched descendants until timeout/cancellation cleanup ends.

The timeout launcher is synthetic. Its child answers a private Unix socket,
so liveness evidence does not depend on /proc or ps in the isolated harness.
The final output control runs the actual installed LibreOffice Calc.
"""
from concurrent.futures import CancelledError
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

import fitz
from openpyxl import Workbook
import pytest

from app import expense_report as expense
from app import monthly_report_render_jobs as jobs
from conftest import requires_libreoffice


def workbook_bytes():
    workbook = Workbook()
    workbook.active.title = 'Synthetic conversion check'
    workbook.active.append(('Expense', 'USD'))
    workbook.active.append(('Synthetic corrected supply purchase', 18.75))
    workbook.active.column_dimensions['A'].width = 52
    workbook.active.column_dimensions['B'].width = 12
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


@pytest.fixture
def owned_calc(monkeypatch, tmp_path):
    if not hasattr(os, 'fork') or not hasattr(socket, 'AF_UNIX'):
        pytest.skip('Controlled Linux/POSIX process-tree probe')
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(expense, 'PDF_BACKEND', 'libreoffice')
    executable = tmp_path / 'synthetic-calc'
    ledger = tmp_path / 'owned-processes.json'
    address = '\0enfra-synthetic-calc-' + uuid4().hex
    executable.write_text(f'''#!{sys.executable}
import json, os, socket, time
from pathlib import Path
if os.getpgrp() != os.getpid():
    os.setsid()
leader = os.getpid()
child = os.fork()
if child == 0:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind({address!r})
    server.listen(2)
    Path({str(ledger)!r}).write_text(json.dumps({{'leader':leader,'child':os.getpid(),'group':os.getpgrp()}}))
    while True:
        connection, _ = server.accept()
        connection.sendall(b'owned-child-running')
        connection.close()
else:
    time.sleep(30)
''')
    executable.chmod(0o700)
    original_which = expense.shutil.which
    monkeypatch.setattr(expense.shutil, 'which', lambda name:
                        str(executable) if name in {'libreoffice', 'soffice'} else original_which(name))
    actual_popen = subprocess.Popen
    state = {'mode': 'timeout', 'started': []}
    def ready():
        deadline = time.monotonic() + 3
        while not ledger.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert ledger.exists(), 'Synthetic converter must start its owned child before the interruption.'
        assert child_running(), 'The owned child must answer before the interruption.'
    def bounded_popen(command, *args, **kwargs):
        process = actual_popen(command, *args, **kwargs)
        if str(command[0]) != str(executable):
            return process
        state['started'].append(process)
        communicate, wait = process.communicate, process.wait
        def deadline(method, *args, **kwargs):
            if kwargs.get('timeout') == 120:
                ready()
                if state['mode'] == 'cancel':
                    raise CancelledError('Synthetic cancellation during the converter wait')
                kwargs['timeout'] = .15
            return method(*args, **kwargs)
        process.communicate = lambda *a, **kw: deadline(communicate, *a, **kw)
        process.wait = lambda timeout=None: deadline(wait, timeout=timeout)
        return process
    monkeypatch.setattr(subprocess, 'Popen', bounded_popen)
    unrelated = actual_popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
    def child_running():
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(.3)
        try:
            connection.connect(address)
            return connection.recv(40) == b'owned-child-running'
        except (ConnectionRefusedError, FileNotFoundError, ConnectionResetError):
            return False
        finally:
            connection.close()
    try:
        yield state, ledger, child_running, unrelated
    finally:
        if ledger.exists():
            owned = json.loads(ledger.read_text())
            assert owned['leader'] == owned['group']
            try:
                os.killpg(owned['group'], signal.SIGKILL)
            except ProcessLookupError:
                pass
        for process in state['started']:
            process.wait(timeout=5)
        unrelated.kill()
        unrelated.wait(timeout=5)


@pytest.mark.parametrize('mode', ['timeout', 'cancel'])
def test_calc_interrupt_stops_owned_child_before_another_conversion_is_admitted(owned_calc, mode):
    state, ledger, child_running, unrelated = owned_calc
    state['mode'] = mode
    caught = None
    try:
        expense.convert_expense_workbook_to_pdf(workbook_bytes())
    except (Exception, KeyboardInterrupt) as exc:
        caught = exc
    assert ledger.exists(), 'No process-lifecycle claim without an actually started child.'
    with jobs.conversion_slot(wait_seconds=0):
        assert not child_running(), 'The conversion slot was released while its child still executes.'
    assert unrelated.poll() is None, 'Cleanup must not kill another owned test process.'
    if mode == 'cancel':
        assert isinstance(caught, CancelledError)
    else:
        assert isinstance(caught, expense.ExpenseReportError)
        assert 'took too long' in str(caught) and 'stopped' in str(caught)
        assert 'synthetic-calc' not in str(caught) and str(ledger.parent) not in str(caught)


def test_failed_calc_message_has_recovery_without_server_output(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(expense, 'PDF_BACKEND', 'libreoffice')
    binary = tmp_path / 'synthetic-failed-calc'
    binary.write_text(f'#!{sys.executable}\nimport sys\nsys.stderr.write("/private/server/source/client-data.xlsx")\nsys.exit(3)\n')
    binary.chmod(0o700)
    monkeypatch.setattr(expense.shutil, 'which', lambda _: str(binary))
    with pytest.raises(expense.ExpenseReportError) as failure:
        expense.convert_expense_workbook_to_pdf(workbook_bytes())
    assert '/private/server' not in str(failure.value)
    assert 'retry' in str(failure.value).lower()


@requires_libreoffice
def test_small_real_calc_output_remains_valid_after_timeout_cleanup(owned_calc, monkeypatch):
    from app import office_process
    state, ledger, child_running, unrelated = owned_calc
    with pytest.raises(expense.ExpenseReportError, match='took too long'):
        expense.convert_expense_workbook_to_pdf(workbook_bytes())
    assert not child_running()
    # Restore the executable lookup while keeping the same shared conversion
    # lease/storage. The following call uses the real installed Calc binary.
    real_bin = next(path / name for path in map(Path, os.environ['PATH'].split(os.pathsep))
                    for name in ('libreoffice', 'soffice') if (path / name).is_file())
    monkeypatch.setattr(expense.shutil, 'which', lambda _: str(real_bin))
    original = workbook_bytes()
    rendered = expense.convert_expense_workbook_to_pdf(original)
    with fitz.open(stream=rendered, filetype='pdf') as pdf:
        assert len(pdf) == 1
        text = ' '.join(pdf[0].get_text().split())
        assert 'Synthetic corrected supply purchase' in text and '18.75' in text
        target = Path(os.environ.get('INDEPENDENT_OUTPUT', str(ledger.parent)))
        target.mkdir(exist_ok=True, parents=True)
        (target / 'expense_calc_cleanup.xlsx').write_bytes(original)
        (target / 'expense_calc_cleanup.pdf').write_bytes(rendered)
        pdf[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(target / 'expense_calc_cleanup_page_1.png')
        (target / 'expense_calc_cleanup.json').write_text(json.dumps({
            'source_sha': os.environ.get('MSAPO_SHA', 'unrecorded'),
            'workbook_bytes': len(original), 'workbook_sha256': sha256(original).hexdigest(),
            'pdf_bytes': len(rendered), 'pdf_sha256': sha256(rendered).hexdigest(),
            'renderer': 'Actual installed LibreOffice Calc; synthetic workbook, not approved expense-form acceptance',
            'timeout_evidence': 'Synthetic owned descendant answered a private Unix socket before timeout; no /proc observation',
        }, indent=2) + '\n')
    assert unrelated.poll() is None and not office_process._marker().exists()
