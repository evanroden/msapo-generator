"""Real process interruption and lock checks for #292, using synthetic temp data.

These are local/CI durability checks, not hosted-browser or authentic-fixture
acceptance. A killed interpreter cannot run the admission context's cleanup.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

import pytest


_REPO = Path(__file__).resolve().parents[1]
_QA = "_enfra_monthly_report_qa_v1"
_ADMISSION = "_enfra_fixture_run_admission_v1"
_TOKENS = ("a" * 32, "b" * 32, "c" * 32)
_WORKER = r"""
import fcntl
import json
from pathlib import Path
import sys
from app import memory
from app import monthly_report_fixture_admission as admission
from app import monthly_report_testing as testing
from app.monthly_report_fixture_runs import FixtureRunContext
from app.monthly_report_fixture_vault import VaultQuotaExceeded

mode, root, token = sys.argv[1:]
root = Path(root)

def pause(value):
    print(json.dumps(value), flush=True)
    sys.stdin.buffer.read(1)
    raise AssertionError('The paused process must be terminated by the test')

if mode == 'recover':
    saved = json.loads((root / admission._BUCKET / 'reservations.json').read_bytes())
    testing.recover_set_aside(root, {(x['scope'], x['generation']) for x in saved['reservations']})
    print(json.dumps({'recovered': True}))
elif mode == 'lock':
    # Open the existing namespace without recording a new visit. The test
    # isolates the kernel lock from the separate recent-activity safeguard.
    with testing.isolated(token) as scope:
        with testing._namespace_lock(root / testing._BUCKET / scope, fcntl.LOCK_SH):
            pause({'locked': scope})
else:
    with testing.isolated(token):
        data = memory._data_dir()
        context = FixtureRunContext(testing.scope(), testing.generation(), data)
        if mode == 'before-index':
            def before(*args):
                pause({'checkpoint': 'before-index'})
            admission._admit = before
        elif mode == 'after-index':
            original = admission._save
            def after(*args):
                original(*args)
                pause({'checkpoint': 'after-index'})
            admission._save = after
        try:
            # A partial install can legitimately retain the full reservation.
            # This fills the metadata budget without writing 128 MiB per test.
            size = admission.MAX_ACTIVE_COPY_BYTES if mode == 'seed' else 4096
            with admission.admit_run_copy(context, size):
                (data / 'synthetic-copy.bin').write_bytes(b'SYNTHETIC partial staged copy')
        except VaultQuotaExceeded as exc:
            print(json.dumps({'quota': str(exc)}))
        else:
            print(json.dumps({'scope': context.scope, 'generation': context.generation}))
"""


def _start(root, mode, token=_TOKENS[0]):
    env = dict(os.environ, EPC_DATA_DIR=str(root), PYTHONPATH=str(_REPO))
    return subprocess.Popen(
        [sys.executable, "-u", "-c", _WORKER, mode, str(root), token],
        cwd=_REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )


def _finish(process):
    try:
        stdout, stderr = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        pytest.fail("Synthetic fixture worker did not complete within 20 seconds")
    assert process.returncode == 0, stderr
    return json.loads(stdout)


def _ready(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=20), "Synthetic fixture worker did not reach its checkpoint"
    line = process.stdout.readline()
    assert line, process.stderr.read()
    return json.loads(line)


def _kill(process):
    process.kill()
    process.communicate(timeout=10)
    assert process.returncode == -signal.SIGKILL


def _reservations(root):
    return json.loads((root / _ADMISSION / "reservations.json").read_bytes())["reservations"]


def _age(path):
    timestamp = time.time() - 25 * 3600
    for directory, folders, files in os.walk(path):
        for name in (*folders, *files):
            os.utime(Path(directory) / name, (timestamp, timestamp), follow_symlinks=False)
    os.utime(path, (timestamp, timestamp))


@pytest.fixture
def staged(tmp_path):
    original = tmp_path / "_enfra_shared_fixtures_v1" / "synthetic" / "source.docx"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"SYNTHETIC immutable original; never a real customer document")
    original_hash = sha256(original.read_bytes()).hexdigest()
    first = _finish(_start(tmp_path, "seed"))
    abandoned = tmp_path / _QA / first["scope"]
    _age(abandoned)
    yield tmp_path, first, abandoned
    assert sha256(original.read_bytes()).hexdigest() == original_hash


@pytest.mark.parametrize("checkpoint", ["before-index", "after-index"])
def test_sigkill_recovery_follows_the_persisted_admission_index(staged, checkpoint):
    root, first, abandoned = staged
    worker = _start(root, checkpoint, _TOKENS[1])
    try:
        assert _ready(worker) == {"checkpoint": checkpoint}
        assert not abandoned.exists()
        tombstones = list((root / _QA).glob(".reclaimed-*"))
        assert len(tombstones) == 1
        assert (tombstones[0] / "synthetic-copy.bin").read_bytes() == b"SYNTHETIC partial staged copy"
    finally:
        _kill(worker)

    # This interpreter has no inherited globals, open descriptors or finally
    # handlers from the killed process. Only the durable index decides recovery.
    saved = _reservations(root)
    assert _finish(_start(root, "recover")) == {"recovered": True}
    assert _reservations(root) == saved
    if checkpoint == "before-index":
        assert saved == [dict(first, added_bytes=128 * 1024 * 1024)]
        assert (abandoned / "synthetic-copy.bin").read_bytes() == b"SYNTHETIC partial staged copy"
    else:
        assert len(saved) == 1 and saved[0]["scope"] != first["scope"]
        assert saved[0]["added_bytes"] == 4096
        assert not abandoned.exists()
    assert not list((root / _QA).glob(".reclaimed-*"))
    assert not list((root / _QA).glob(".discarding-*"))

    # Fresh admission remains usable after either recovery: it releases the
    # restored idle copy, or preserves the already-committed new reservation.
    third = _finish(_start(root, "admit", _TOKENS[2]))
    assert "scope" in third
    assert not abandoned.exists()
    expected_scopes = ({third["scope"]} if checkpoint == "before-index"
                       else {saved[0]["scope"], third["scope"]})
    assert {item["scope"] for item in _reservations(root)} == expected_scopes


def test_another_process_holding_namespace_lock_prevents_idle_reclaim(staged):
    root, first, abandoned = staged
    holder = _start(root, "lock")
    try:
        assert _ready(holder) == {"locked": first["scope"]}
        denied = _finish(_start(root, "admit", _TOKENS[1]))
        assert "128 MiB budget" in denied["quota"]
        assert "24 hours" in denied["quota"]
        assert abandoned.exists()
        assert _reservations(root) == [dict(first, added_bytes=128 * 1024 * 1024)]
    finally:
        _kill(holder)

    # SIGKILL releases the real kernel lock; no Python cleanup participates.
    admitted = _finish(_start(root, "admit", _TOKENS[1]))
    assert "scope" in admitted
    assert not abandoned.exists()
    assert _reservations(root) == [dict(admitted, added_bytes=4096)]
