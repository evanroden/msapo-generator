"""A02: deterministic resource admission and concurrent conversion boundaries.

Synthetic documents only. The real LibreOffice check is skipped when the
runner does not have the binary or enough physical/cgroup memory.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from threading import Event
import os
import time

import pytest

from app import monthly_report_render_jobs as jobs
from app import monthly_report_resource_scheduler as scheduler
from app import office_process


@pytest.fixture
def parallel(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    # Admission locks are container-wide by design; keep this test's locks
    # hermetic while still proving live and isolated namespaces share them.
    monkeypatch.setenv("MSAPO_RESOURCE_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("MSAPO_RENDER_PARALLEL", "1")
    monkeypatch.setattr(scheduler, "_memory_limit", lambda: 4 * 1024**3)
    monkeypatch.setattr(scheduler, "_cpu_capacity", lambda: 4)
    monkeypatch.setattr(jobs, "memory_headroom", lambda: 3 * 1024**3)
    assert scheduler.parallel_enabled()
    yield


def _eventually(predicate, seconds=3):
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        if predicate():
            return
        time.sleep(.005)
    assert predicate()


def test_unconfigured_or_512_mib_never_parallelizes(monkeypatch):
    monkeypatch.delenv("MSAPO_RENDER_PARALLEL", raising=False)
    monkeypatch.setattr(scheduler, "_memory_limit", lambda: 8 * 1024**3)
    monkeypatch.setattr(scheduler, "_cpu_capacity", lambda: 4)
    assert not scheduler.parallel_enabled()
    monkeypatch.setenv("MSAPO_RENDER_PARALLEL", "1")
    monkeypatch.setattr(scheduler, "_memory_limit", lambda: 512 * scheduler.MIB)
    monkeypatch.setattr(scheduler, "_cpu_capacity", lambda: .5)
    assert not scheduler.parallel_enabled()
    ready, finish = Event(), Event()
    def slow():
        with jobs.work_slot():
            ready.set()
            assert finish.wait(4)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(slow)
        assert ready.wait(2)
        with pytest.raises(jobs.RenderBusy):
            with jobs.work_slot(preview=True):
                raise AssertionError("512 MiB work slot should remain serial")
        finish.set()
        first.result(timeout=3)
    assert scheduler.snapshot()["running"]["heavy"] == 0


def test_slow_export_no_longer_blocks_small_visible_preview(parallel):
    started, release, fast = Event(), Event(), Event()
    def slow():
        with jobs.work_slot():
            started.set()
            assert release.wait(4)
    def small():
        with jobs.work_slot(preview=True):
            fast.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow_future = pool.submit(slow)
        assert started.wait(2)
        # Before A02 this preview fails immediately while the slow export
        # holds _WORK_SLOT, even with a large healthy cgroup.
        small_future = pool.submit(small)
        assert fast.wait(2), "A visible small job must bypass the occupied heavy lane"
        assert not slow_future.done()
        release.set()
        small_future.result(timeout=3)
        slow_future.result(timeout=3)
    assert scheduler.snapshot()["running"]["heavy"] == 0


def test_foreground_priority_is_fifo_within_class(parallel, monkeypatch):
    # One lane makes the visible execution order the actual admission order.
    monkeypatch.setitem(scheduler.CAPACITIES, "heavy", 1)
    entered = []
    release = Event()
    holders_ready = Event()
    def holder():
        with scheduler.lease("heavy", priority="optional", wait_seconds=1,
                             headroom=jobs.memory_headroom):
            entered.append("holder")
            holders_ready.set()
            assert release.wait(4)
    def contender(name, priority):
        with scheduler.lease("heavy", priority=priority, wait_seconds=3,
                             headroom=jobs.memory_headroom):
            entered.append(name)
    with ThreadPoolExecutor(max_workers=3) as pool:
        hold = pool.submit(holder)
        assert holders_ready.wait(2)
        optional = pool.submit(contender, "optional", "optional")
        _eventually(lambda: scheduler.snapshot()["queued"]["heavy"] == 1)
        export = pool.submit(contender, "export", "export")
        _eventually(lambda: scheduler.snapshot()["queued"]["heavy"] == 2)
        release.set()
        for task in (hold, optional, export):
            task.result(timeout=4)
    assert entered == ["holder", "export", "optional"]
    assert scheduler.snapshot()["queued"]["heavy"] == 0


def test_cancel_queued_revision_and_retry_release_all_reservations(parallel):
    old = Event()
    hold = Event()
    def occupying():
        with scheduler.lease("heavy", priority="export", wait_seconds=1,
                             headroom=jobs.memory_headroom):
            old.set()
            assert hold.wait(4)
    with ThreadPoolExecutor(max_workers=3) as pool:
        owners = [pool.submit(occupying) for _ in range(2)]
        _eventually(lambda: scheduler.snapshot()["running"]["heavy"] == 2)
        current = Event()
        current.set()
        def cancelled():
            with pytest.raises(scheduler.AdmissionUnavailable, match="superseded"):
                with scheduler.lease("heavy", priority="visible", wait_seconds=2,
                                     headroom=jobs.memory_headroom, is_current=current.is_set):
                    raise AssertionError("obsolete preview must never start")
        pending = pool.submit(cancelled)
        _eventually(lambda: scheduler.snapshot()["queued"]["heavy"] == 1)
        current.clear()
        pending.result(timeout=2)
        hold.set()
        for task in owners:
            task.result(timeout=4)
    with scheduler.lease("heavy", priority="visible", headroom=jobs.memory_headroom):
        pass
    assert scheduler.snapshot()["queued"]["heavy"] == 0
    assert scheduler.snapshot()["running"]["heavy"] == 0


def test_memory_fails_closed_and_failure_releases_leases(parallel, monkeypatch):
    monkeypatch.setattr(jobs, "memory_headroom", lambda: 600 * scheduler.MIB)
    with pytest.raises(jobs.RenderBusy, match="memory is constrained"):
        with jobs.work_slot(wait_seconds=0):
            raise AssertionError("cannot start without headroom for its peak")
    monkeypatch.setattr(jobs, "memory_headroom", lambda: 3 * 1024**3)
    with pytest.raises(ValueError, match="injected"):
        with jobs.work_slot():
            with jobs.conversion_slot():
                assert office_process._marker().name in {".active-office.json", ".active-office-1.json"}
                raise ValueError("injected conversion failure")
    assert scheduler.snapshot()["running"]["heavy"] == 0
    assert scheduler.snapshot()["running"]["conversion"] == 0
    with jobs.work_slot(preview=True), jobs.conversion_slot(wait_seconds=0):
        pass


def test_both_conversion_lanes_have_disjoint_marker_names(parallel):
    held = Event()
    finished = Event()
    observed = set()
    entered = []
    def conversion(label):
        with jobs.conversion_slot(wait_seconds=2):
            observed.add(office_process._marker().name)
            entered.append(label)
            held.set()
            assert finished.wait(4)
            return label
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(conversion, "a")
        assert held.wait(2)
        b = pool.submit(conversion, "b")
        # The scheduler counts a conversion lease before its Office lane is
        # taken; wait until both are inside their lanes, or "a" can finish
        # first and "b" would then reuse lane 0.
        _eventually(lambda: scheduler.snapshot()["running"]["conversion"] == 2
                    and len(entered) == 2)
        finished.set()
        assert {a.result(timeout=3), b.result(timeout=3)} == {"a", "b"}
    assert observed == {".active-office.json", ".active-office-1.json"}
    assert not office_process._marker().exists()


def test_legacy_mode_detects_unfinished_parallel_child(parallel, monkeypatch):
    marker = office_process._marker().parent / ".active-office-1.json"
    marker.write_text('{"pid": 43210, "boot": ""}')
    monkeypatch.setattr(office_process, "_group_running", lambda pid: pid == 43210)
    # A downsized/reconfigured instance must not ignore orphaned lane 1.
    monkeypatch.delenv("MSAPO_RENDER_PARALLEL")
    with pytest.raises(jobs.RenderBusy, match="still stopping"):
        with jobs.conversion_slot(wait_seconds=0):
            raise AssertionError("must quarantine active prior child")


def test_real_parallel_office_outputs_are_distinct_and_originals_unchanged(parallel, monkeypatch, tmp_path):
    from shutil import which
    import pymupdf
    from docx import Document
    from app import pdf_converter
    if not (which("libreoffice") or which("soffice")):
        pytest.skip("LibreOffice unavailable")
    actual_cap = scheduler._read_int("/sys/fs/cgroup/memory.max")
    if actual_cap is None:
        try:
            import psutil
            actual_cap = psutil.virtual_memory().available
        except ImportError:
            pytest.skip("Real available memory not measurable")
    if actual_cap < 2048 * scheduler.MIB:
        pytest.skip("Real memory too small to run two LibreOffice processes")
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    one, two = tmp_path / "a.docx", tmp_path / "b.docx"
    for path, message in ((one, "SYNTHETIC A-ONLY"), (two, "SYNTHETIC B-ONLY")):
        document = Document()
        document.add_paragraph(message)
        document.save(path)
    input_hashes = [sha256(p.read_bytes()).hexdigest() for p in (one, two)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(pdf_converter.convert_to_pdf, p) for p in (one, two)]
        pdfs = [f.result(timeout=150) for f in futures]
    text = []
    for path in pdfs:
        with pymupdf.open(path) as document:
            assert len(document) == 1
            assert document[0].rect.width > 0 and document[0].rect.height > 0
            text.append(document[0].get_text())
    assert "A-ONLY" in text[0] and "B-ONLY" not in text[0]
    assert "B-ONLY" in text[1] and "A-ONLY" not in text[1]
    assert sha256(pdfs[0].read_bytes()).hexdigest() != sha256(pdfs[1].read_bytes()).hexdigest()
    assert [sha256(p.read_bytes()).hexdigest() for p in (one, two)] == input_hashes
    assert not list(tmp_path.glob(".office-*"))
    assert not list(office_process._marker().parent.glob(".active-office*.json"))
    _evidence("real-office", {
        "level": "synthetic-real-LibreOffice",
        "pdf_sha256": [sha256(p.read_bytes()).hexdigest() for p in pdfs],
        "docx_sha256": input_hashes,
        "page_count": [1, 1],
        "cross_profile_text_isolated": True,
    })


def _evidence(name, result):
    """CI retains synthetic evidence; never serialize client bytes or paths."""
    destination = os.environ.get("INDEPENDENT_OUTPUT")
    if not destination:
        return
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ("a02-" + name + ".json")).write_text(
        json.dumps(result, sort_keys=True, indent=2), encoding="utf-8")


def test_admission_cold_warm_and_512_control_samples(parallel, monkeypatch):
    """Measured *synthetic* queue admission, not a served/browser first paint."""
    import resource
    samples = []
    for label in ("cold", "warm"):
        wall = time.perf_counter()
        cpu = time.process_time()
        with scheduler.lease("heavy", priority="visible", wait_seconds=1,
                             headroom=jobs.memory_headroom):
            pass
        samples.append({"case": label, "wall_ms": round(1000 * (time.perf_counter() - wall), 3),
                        "cpu_ms": round(1000 * (time.process_time() - cpu), 3),
                        "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    monkeypatch.setattr(scheduler, "_memory_limit", lambda: 512 * scheduler.MIB)
    monkeypatch.setattr(scheduler, "_cpu_capacity", lambda: .5)
    assert not scheduler.parallel_enabled()
    wall = time.perf_counter()
    with jobs.work_slot(wait_seconds=0):
        pass
    samples.append({"case": "512MiB-0.5CPU-serial-control",
                    "wall_ms": round(1000 * (time.perf_counter() - wall), 3),
                    "cpu_ms": None,
                    "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    _evidence("admission", {"level": "synthetic-admission-only",
                             "samples": samples, "first_paint_ms": None,
                             "live_cgroup_512MiB": False})
    assert scheduler.snapshot()["running"]["heavy"] == 0


def test_same_owner_revision_never_submits_duplicate_preview(monkeypatch):
    from concurrent.futures import Future
    from threading import BoundedSemaphore
    from app import monthly_report_section_preview_ui as ui

    pending = Future()
    calls = []
    class Worker:
        def submit(self, fn, *args):
            calls.append(args)
            return pending
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(ui, "_PREVIEW_WORKER", Worker())
    monkeypatch.setattr(ui, "_PREVIEW_SLOT", slot)
    state = {"owner": "synthetic-owner", "wanted": {"activity": "rev-1"},
             "queue": {"activity": ("rev-1", "synthetic-draft", {}, "Activity")},
             "cache": {}, "running": None, "visible": {"activity": True}}
    ui._advance_preview_queue(state)
    ui._advance_preview_queue(state)
    assert len(calls) == 1 and not slot.acquire(False)
    assert state["running"][:2] == ("activity", "rev-1")
    # On a later revision the old work is not reused as current.
    state["wanted"]["activity"] = "rev-2"
    state["queue"]["activity"] = ("rev-2", "new-synthetic-draft", {}, "Activity")
    ui._advance_preview_queue(state)
    assert len(calls) == 1
    slot.release()


def test_two_processes_cannot_spend_the_same_800mib_headroom(parallel):
    """Review regression: independent exec process cannot double-spend 800 MiB.

    A fresh Python interpreter must respect another worker's reserved memory
    even before its allocated RSS rises. No fork of Streamlit/test threads.
    """
    import subprocess
    import sys
    code = """from app import monthly_report_resource_scheduler as s
s._memory_limit = lambda: 4 * 1024**3
s._cpu_capacity = lambda: 4
try:
    with s.lease('heavy', priority='visible', wait_seconds=.12,
                 headroom=lambda: 800 * s.MIB):
        print('acquired')
except s.AdmissionUnavailable:
    print('denied-overcommit')
"""
    def attempt():
        run = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=8,
                             env=os.environ.copy())
        assert run.returncode == 0, run.stderr[:1000]
        return run.stdout.strip()
    with scheduler.lease("heavy", priority="export", wait_seconds=.2,
                         headroom=lambda: 800 * scheduler.MIB):
        assert attempt() == "denied-overcommit"
    assert attempt() == "acquired", "budget must be reusable after release"


def test_resource_lock_folder_ignores_report_namespace(monkeypatch, tmp_path):
    """Review regression: admission locks must not follow the isolated QA root."""
    monkeypatch.delenv("MSAPO_RESOURCE_LOCK_DIR", raising=False)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "live"))
    live_folder = scheduler._lock_folder()
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "isolated"))
    assert scheduler._lock_folder() == live_folder
    assert "monthly_reports" not in live_folder.parts


def test_heavy_lease_in_one_namespace_blocks_another_namespace(parallel, tmp_path):
    """Review regression: an isolated QA heavy lease shares the live budget locks.

    The two processes use different report namespaces (EPC_DATA_DIR) but the
    same cgroup headroom; the second heavy must still be denied at 800 MiB.
    """
    import subprocess
    import sys
    code = """from app import monthly_report_resource_scheduler as s
s._memory_limit = lambda: 4 * 1024**3
s._cpu_capacity = lambda: 4
try:
    with s.lease('heavy', priority='visible', wait_seconds=.12,
                 headroom=lambda: 800 * s.MIB):
        print('acquired')
except s.AdmissionUnavailable:
    print('denied-overcommit')
"""
    env = os.environ.copy()
    env["EPC_DATA_DIR"] = str(tmp_path / "other-namespace")

    def attempt():
        run = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=8, env=env)
        assert run.returncode == 0, run.stderr[:1000]
        return run.stdout.strip()
    with scheduler.lease("heavy", priority="export", wait_seconds=.2,
                         headroom=lambda: 800 * scheduler.MIB):
        assert attempt() == "denied-overcommit"
    assert attempt() == "acquired", "budget must be reusable after release"


def test_two_heavies_at_1400mib_headroom_both_reach_conversion(parallel):
    """Codex review: two heavies admitted at 1,400 MiB must not deadlock on conversion.

    At 1,400 MiB both heavies are admitted (512 + 512 + 160). Each conversion
    runs inside its own heavy lease, whose reservation covers it, so neither
    waits for the other's reservation to be released: both convert promptly.
    """
    from threading import Barrier
    headroom = lambda: 1400 * scheduler.MIB
    both_heavy = Barrier(2)
    converted = []

    def convert():
        with scheduler.lease("heavy", priority="export", wait_seconds=5, headroom=headroom):
            both_heavy.wait(timeout=5)
            with scheduler.lease("conversion", priority="export", wait_seconds=2,
                                 headroom=headroom, nested=True):
                converted.append(True)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(convert) for _ in range(2)]
        for task in results:
            task.result(timeout=15)
    assert len(converted) == 2
    assert time.monotonic() - started < 2, "neither conversion waited for the other heavy"
    assert scheduler.snapshot()["running"]["heavy"] == 0
    assert scheduler.snapshot()["running"]["conversion"] == 0


def test_admitted_heavy_reaches_conversion_after_assembly_uses_memory(parallel):
    """Codex review: a heavy admitted at 800 MiB must not block its own conversion.

    Assembly then uses 200 MiB, leaving 600 MiB live. The conversion's 320 MiB
    plus the 160 MiB reserve fit; charging the heavy's full 512 MiB again on
    top of the memory it already used would deny it.
    """
    free = {"bytes": 800 * scheduler.MIB}
    headroom = lambda: free["bytes"]
    with scheduler.lease("heavy", priority="export", wait_seconds=0, headroom=headroom):
        free["bytes"] = 600 * scheduler.MIB
        with scheduler.lease("conversion", priority="export", wait_seconds=0,
                             headroom=headroom, nested=True):
            assert scheduler.snapshot()["running"]["conversion"] == 1
    assert scheduler.snapshot()["running"] == {k: 0 for k in scheduler.CAPACITIES}


def test_nested_conversion_still_fails_closed_without_live_memory(parallel):
    free = {"bytes": 800 * scheduler.MIB}
    headroom = lambda: free["bytes"]
    with scheduler.lease("heavy", priority="export", wait_seconds=0, headroom=headroom):
        free["bytes"] = 400 * scheduler.MIB  # below 320 + 160
        with pytest.raises(scheduler.AdmissionUnavailable, match="memory is constrained"):
            with scheduler.lease("conversion", priority="export", wait_seconds=0,
                                 headroom=headroom, nested=True):
                raise AssertionError("conversion must not start without its own peak free")
    assert scheduler.snapshot()["running"] == {k: 0 for k in scheduler.CAPACITIES}


def test_conversion_outside_a_heavy_lease_still_charges_every_reservation(parallel):
    headroom = lambda: 800 * scheduler.MIB
    with scheduler.lease("heavy", priority="export", wait_seconds=0, headroom=headroom):
        # 512 reserved + 320 + 160 exceeds 800: only a nested conversion may
        # borrow the heavy reservation.
        with pytest.raises(scheduler.AdmissionUnavailable):
            with scheduler.lease("conversion", priority="export", wait_seconds=0, headroom=headroom):
                raise AssertionError("an unrelated conversion cannot spend another job's reservation")
