"""A03: deterministic, entirely synthetic source-parse/cache acceptance probes.

No real customer material, paid model calls, or served-release claims.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from threading import Barrier, Lock
from time import sleep
from types import SimpleNamespace

import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_source_recovery import restore_sources


CSV = b"Item,Completion\nDEMO-001,Inspected pump\nDEMO-002,Pending replacement\n"


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Tester", confirmed=True)
    return profile


def cache_for(profile, item):
    return sources._path(profile, item.source.sha256, ".json")


def test_manifest_contains_authenticated_derived_inventory_and_policy(profile):
    from app import monthly_source_parse_manifest as parse

    content, _ = sources.ingest(profile, "source.csv", CSV)
    record = library._read(cache_for(profile, content))
    manifest = record["parse_manifest"]
    assert manifest["source_sha256"] == sha256(CSV).hexdigest()
    assert manifest["source_revision"] == sha256(CSV).hexdigest()
    assert manifest["parser_policy"] == parse.PARSER_POLICY_VERSION
    assert manifest["source_size"] == len(CSV)
    assert len(manifest["page_items"]) == len(content.source.page_texts)
    assert len(manifest["tables"]) == len(content.tables)
    assert manifest["tables"][0]["rows"] == len(content.tables[0].rows)
    assert parse.valid(manifest, content, len(CSV))
    assert sources.ingest(profile, "renamed.csv", CSV)[0].tables == content.tables


def test_parser_policy_change_rebuilds_once_without_replacing_original(profile, monkeypatch):
    from app import monthly_source_parse_manifest as parse

    original, _ = sources.ingest(profile, "source.csv", CSV)
    path = sources._path(profile, original.source.sha256, ".csv")
    stat = path.stat()
    old = library._read(cache_for(profile, original))["parse_manifest"]["parser_policy"]
    parsed = []
    parser = sources._spreadsheet

    with monkeypatch.context() as patch:
        patch.setattr(parse, "PARSER_POLICY_VERSION", old + 1)
        patch.setattr(sources, "_spreadsheet", lambda raw, suffix: (parsed.append(suffix), parser(raw, suffix))[1])
        current, _ = sources.ingest(profile, "source.csv", CSV)
        assert current == original
        assert parsed == [".csv"]
        assert sources.ingest(profile, "source.csv", CSV)[0] == original
        assert parsed == [".csv"]
        assert library._read(cache_for(profile, original))["parse_manifest"]["parser_policy"] == old + 1
    assert path.read_bytes() == CSV
    assert (path.stat().st_ino, path.stat().st_mtime_ns) == (stat.st_ino, stat.st_mtime_ns)


def test_same_name_changed_bytes_and_two_sites_cannot_share_review_state(profile):
    from app import monthly_source_parse_manifest as parse

    alternative = replace(profile, key="synthetic-other", facilities=(Facility("other", "Other synthetic site"),))
    library.save_profile(alternative, expected_revision=0, actor="Synthetic Tester", confirmed=True)
    first, _ = sources.ingest(profile, "shared.csv", CSV)
    revised = CSV.replace(b"Pending replacement", b"Replacement completed")
    second, _ = sources.ingest(profile, "shared.csv", revised)
    foreign, _ = sources.ingest(alternative, "shared.csv", CSV)
    assert first.source.sha256 != second.source.sha256
    assert foreign.tables == first.tables
    assert sources._path(profile, first.source.sha256, ".json") != sources._path(alternative, foreign.source.sha256, ".json")
    assert parse.valid(library._read(cache_for(alternative, foreign))["parse_manifest"], foreign, len(CSV))
    reviewed = replace(first.source, findings="Human correction", selected_pages=(), captions=((1, "Reviewed page"),))
    draft = replace(synthetic_draft(profile, ReportPeriod(2026, 9)), sources=(reviewed,))
    library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Tester")
    cache_for(profile, first).write_bytes(b'{"schema":')
    reopened, missing = restore_sources(profile, (reviewed,))
    assert missing == () and reopened[0].source == reviewed
    assert library.load_snapshot(profile.contract, profile.key, draft.period).draft == draft
    assert library._read(cache_for(profile, first))["parse_manifest"]["source_sha256"] == first.source.sha256


def test_interrupted_after_parse_stage_resumes_without_second_archive_read(profile, monkeypatch):
    parser = sources._spreadsheet
    original_facts = sources.suggest_facts
    calls = []

    def counted(raw, suffix):
        calls.append(suffix)
        return parser(raw, suffix)

    with monkeypatch.context() as patch:
        patch.setattr(sources, "_spreadsheet", counted)
        patch.setattr(sources, "suggest_facts", lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic interruption")))
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            sources.ingest(profile, "interrupted.csv", CSV)
    assert calls == [".csv"]
    path = sources._path(profile, sha256(CSV).hexdigest(), ".csv")
    assert path.read_bytes() == CSV
    with monkeypatch.context() as patch:
        patch.setattr(sources, "_spreadsheet", lambda *_: pytest.fail("completed stage parsed again"))
        patch.setattr(sources, "suggest_facts", original_facts)
        content, _ = sources.ingest(profile, "interrupted.csv", CSV)
    assert content.tables[0].rows[-1][1] == "Pending replacement"
    assert sources.ingest(profile, "interrupted.csv", CSV)[0] == content


def test_same_scope_inflight_identical_content_is_parsed_once(profile, monkeypatch):
    parse = sources._spreadsheet
    calls, lock = [], Lock()
    ready = Barrier(2)

    def slow(raw, suffix):
        with lock:
            calls.append(suffix)
        sleep(0.1)
        return parse(raw, suffix)

    monkeypatch.setattr(sources, "_spreadsheet", slow)

    def work(index):
        ready.wait(timeout=5)
        return sources.ingest(profile, f"independent-{index}.csv", CSV)

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = tuple(executor.map(work, (1, 2)))
    assert a[0].tables == b[0].tables
    assert {a[0].source.filename, b[0].source.filename} == {"independent-1.csv", "independent-2.csv"}
    assert calls == [".csv"]


def test_one_upload_batch_hashes_each_immutable_payload_once(profile, monkeypatch):
    native = sources.hashlib.sha256
    calls = []

    def tracked(data=b""):
        if data is CSV:
            calls.append(True)
        return native(data)

    # Track only *sources* direct hashing, not object-store integrity hashing.
    monkeypatch.setattr(sources, "hashlib", SimpleNamespace(sha256=tracked))
    records, messages = sources.ingest_batch(profile, (("a.csv", CSV),))
    assert not messages and len(records) == 1
    assert len(calls) <= 1


def test_completed_stage_write_failure_does_not_publish_partial_cache(profile, monkeypatch):
    digest = sha256(CSV).hexdigest()
    original = library._atomic_write
    writes = []

    def interrupted(path, raw):
        if path.name == digest + ".parse-stage.json":
            writes.append(path)
            raise OSError("synthetic interrupted stage write")
        return original(path, raw)

    with monkeypatch.context() as patch:
        patch.setattr(library, "_atomic_write", interrupted)
        with pytest.raises(OSError, match="interrupted stage write"):
            sources.ingest(profile, "interrupted.csv", CSV)
    assert writes
    assert not sources._path(profile, digest, ".json").exists()
    content, _ = sources.ingest(profile, "interrupted.csv", CSV)
    assert content.tables[0].rows[0] == ("DEMO-001", "Inspected pump")


def test_synthetic_pdf_cold_warm_thumbnail_cost_and_content(profile):
    """Per-action QA numbers in test logs; machine-dependent, not a speed SLA.

    This is a single-process runner measurement, *not* a real served UI test,
    not a 0.5-vCPU/512-MiB emulator, and not a production/real-source pass.
    """
    import gc
    import resource
    import time
    import tracemalloc
    import warnings
    from test_monthly_report_sources import pdf_bytes

    payload = pdf_bytes(20)

    def timed():
        gc.collect()
        tracemalloc.start()
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        item, _ = sources.ingest(profile, "synthetic-evidence.pdf", payload)
        thumb = sources.page_image(profile, item, 1, preview=True)
        ms = (time.perf_counter() - start_wall) * 1000
        cpu_ms = (time.process_time() - start_cpu) * 1000
        _, heap_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return item, thumb, (round(ms, 2), round(cpu_ms, 2),
                             round(heap_peak / 1024 / 1024, 2),
                             resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

    cold, thumb, cold_cost = timed()
    warm, again, warm_cost = timed()
    assert warm == cold and thumb.data == again.data
    assert thumb.width == again.width and thumb.height == again.height
    assert sources.source_bytes(profile, warm.source) == payload
    warnings.warn(
        "A03_SYNTHETIC_PDF20_P1: cold(wall_ms,cpu_ms,heap_peak_MiB,rss_peak_KiB)="
        + str(cold_cost) + " warm=" + str(warm_cost)
        + "; identical digest/page geometry; GitHub-hosted runner, not constrained",
        UserWarning, stacklevel=1,
    )


def test_operation_digest_ttl_and_size_footprint(monkeypatch):
    from app import content_cache
    clock = [1000.0]
    monkeypatch.setattr(content_cache.time, "monotonic", lambda: clock[0])
    original_hash = content_cache.hashlib.sha256
    calls = []

    def measured(payload):
        calls.append(payload)
        return original_hash(payload)

    monkeypatch.setattr(content_cache, "hashlib",
                        SimpleNamespace(sha256=measured))
    cache = content_cache.ContentDigests(max_bytes=24, max_entries=2, ttl_seconds=10)
    a, b, c = b"ABCDEFG", b"1234567", b"1234567890123456789"
    assert cache.digest(a) == sha256(a).digest()
    assert cache.digest(a) == sha256(a).digest()
    assert calls == [a]
    assert cache._size <= 24 and cache.resident_bytes > cache._size
    cache.digest(b)
    cache.digest(c)
    assert cache._size <= 24 and len(cache._entries) <= 2
    clock[0] += 11
    cache.digest(a)
    assert calls.count(a) == 2
    cache.retain(())
    assert cache._size == 0 and not cache._entries


def test_pdf_page_operation_uses_one_original_read_plus_final_integrity(profile, monkeypatch):
    from test_monthly_report_sources import pdf_bytes
    raw = pdf_bytes(3)
    content, _ = sources.ingest(profile, "three-pages.pdf", raw)
    original, original_check = sources.source_bytes, sources._stream_verified_original
    read_calls, check_calls = [], []

    def measured(*args, **kwargs):
        read_calls.append(args[1].sha256)
        return original(*args, **kwargs)

    def checked(*args, **kwargs):
        check_calls.append(args[1].sha256)
        return original_check(*args, **kwargs)

    monkeypatch.setattr(sources, "source_bytes", measured)
    monkeypatch.setattr(sources, "_stream_verified_original", checked)
    with sources._page_read_scope():
        first = [sources.page_image(profile, content, i, preview=True) for i in (1, 2, 3)]
    # One full original read for all three pages, then one streamed check.
    assert (len(read_calls), len(check_calls)) == (1, 1)
    read_calls.clear()
    check_calls.clear()
    with sources._page_read_scope():
        warm = [sources.page_image(profile, content, i, preview=True) for i in (1, 2, 3)]
    assert warm == first
    # Warm images read no original, but it is still reauthenticated.
    assert (len(read_calls), len(check_calls)) == (0, 1)


def test_final_integrity_check_streams_a_large_original(profile):
    """The exit check needs no bytes: a large DOCX must not be held in memory.

    Reading the whole original to hash it peaked at 128 MiB for a 100 MiB DOCX
    (Codex on #955). The streamed check keeps source_bytes' messages.
    """
    import os
    import tracemalloc
    big = os.urandom(24 * 1024 * 1024)
    source = SimpleNamespace(sha256=sha256(big).hexdigest(), suffix=".docx")
    path = sources._path(profile, source.sha256, source.suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(big)
    del big
    tracemalloc.start()
    try:
        sources._stream_verified_original(profile, source)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024, peak
    path.write_bytes(b"same saved path, different bytes")
    with pytest.raises(ValueError, match="failed its integrity check"):
        sources._stream_verified_original(profile, source)


def test_warm_prepared_page_refuses_original_replacement_before_publication(profile):
    from test_monthly_report_sources import pdf_bytes
    raw = pdf_bytes(1)
    content, _ = sources.ingest(profile, "verified.pdf", raw)
    expected = sources.page_image(profile, content, 1, preview=True)
    path = sources._path(profile, content.source.sha256, ".pdf")
    path.unlink()
    path.write_bytes(b"same saved path, different bytes")
    # Prepared JPEG/PNG remains valid. It is *not* proof of the original.
    with pytest.raises(ValueError, match="integrity check"):
        with sources._page_read_scope():
            assert sources.page_image(profile, content, 1, preview=True) == expected
    assert path.read_bytes() == b"same saved path, different bytes"


def test_interrupted_stage_is_invalidated_on_parser_policy_upgrade(profile, monkeypatch):
    from app import monthly_source_parse_manifest as parse
    with monkeypatch.context() as patch:
        patch.setattr(sources, "suggest_facts", lambda *_: (_ for _ in ()).throw(RuntimeError("interrupted")))
        with pytest.raises(RuntimeError, match="interrupted"):
            sources.ingest(profile, "stage.csv", CSV)
    count = []
    original = sources._spreadsheet
    with monkeypatch.context() as patch:
        patch.setattr(parse, "PARSER_POLICY_VERSION", parse.PARSER_POLICY_VERSION + 1)
        patch.setattr(sources, "_spreadsheet", lambda *args: (count.append(True), original(*args))[1])
        sources.ingest(profile, "stage.csv", CSV)
    assert count == [True]


def test_disk_cache_ttl_reparses_derived_metadata_but_not_immutable_original(profile, monkeypatch):
    import os
    import time
    from app import monthly_source_parse_manifest as parse
    original, _ = sources.ingest(profile, "ttl.csv", CSV)
    cache = cache_for(profile, original)
    source = sources._path(profile, original.source.sha256, ".csv")
    source_stat = source.stat()
    old = time.time() - parse.DISK_PARSE_TTL_SECONDS - 60
    os.utime(cache, (old, old))
    calls = []
    parser = sources._spreadsheet
    monkeypatch.setattr(sources, "_spreadsheet", lambda *args: (calls.append(True), parser(*args))[1])
    again, _ = sources.ingest(profile, "ttl.csv", CSV)
    assert again == original and calls == [True]
    assert (source.stat().st_ino, source.stat().st_mtime_ns) == (
        source_stat.st_ino, source_stat.st_mtime_ns)
    sources.ingest(profile, "ttl.csv", CSV)
    assert calls == [True]


def test_local_qa_metrics_do_not_expose_filename_contract_or_digest(profile, monkeypatch, caplog):
    import logging
    monkeypatch.setenv("MSAPO_LOCAL_QA_SOURCE_CACHE", "1")
    with caplog.at_level(logging.INFO, logger="msapo.local.source_cache"):
        first, _ = sources.ingest(profile, "private-FILE-source.csv", CSV)
        sources.ingest(profile, "private-FILE-source.csv", CSV)
    messages = "\n".join(r.getMessage() for r in caplog.records
                         if r.name == "msapo.local.source_cache")
    assert "outcome=miss" in messages and "outcome=hit" in messages
    assert "wall_ms=" in messages and "derived_bytes=" in messages
    assert "private-FILE" not in messages
    assert profile.contract not in messages and first.source.sha256 not in messages


def test_rejected_batch_upload_does_not_leave_unapproved_parse_text(profile, monkeypatch):
    raw = b"Asset,Note\nDEMO-99,Do not retain unapproved content\n"
    digest = sha256(raw).hexdigest()
    accepted, _ = sources.ingest(profile, "kept.csv", CSV)
    original_facts = sources.suggest_facts

    def reject(record, current_profile):
        if record.sha256 == digest:
            raise ValueError("synthetic policy refusal after parse")
        return original_facts(record, current_profile)

    monkeypatch.setattr(sources, "suggest_facts", reject)
    records, notes = sources.ingest_batch(profile, (("rejected.csv", raw),),
                                         existing=(accepted,))
    assert records == (accepted,)
    assert len(notes) == 1 and "Not read: rejected.csv" in notes[0]
    assert not sources._path(profile, digest, ".csv").exists()
    assert not sources._path(profile, digest, ".json").exists()
    assert not sources._path(profile, digest, ".json").with_name(
        digest + ".parse-stage.json").exists()
    assert sources.source_bytes(profile, accepted.source) == CSV


def test_resumed_checkpoint_uses_this_uploads_filename(profile, monkeypatch):
    """A checkpoint from an interrupted upload never carries its old name forward."""
    original_facts = sources.suggest_facts
    with monkeypatch.context() as patch:
        patch.setattr(sources, "suggest_facts",
                      lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic interruption")))
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            sources.ingest(profile, "first-name.csv", CSV)
    seen = []

    def facts(record, current_profile):
        seen.append(record.filename)
        return original_facts(record, current_profile)

    with monkeypatch.context() as patch:
        patch.setattr(sources, "_spreadsheet", lambda *_: pytest.fail("completed stage parsed again"))
        patch.setattr(sources, "suggest_facts", facts)
        content, _ = sources.ingest(profile, "second-name.csv", CSV)
    assert seen == ["second-name.csv"]
    assert content.source.filename == "second-name.csv"
    assert library._read(cache_for(profile, content))["source"]["filename"] == "second-name.csv"


def test_interrupted_stage_is_invalidated_when_an_extraction_policy_changes(profile, monkeypatch):
    """Checkpoints carry the same policy markers as the published cache."""
    from app import monthly_source_parse_manifest as parse
    with monkeypatch.context() as patch:
        patch.setattr(sources, "suggest_facts",
                      lambda *_: (_ for _ in ()).throw(RuntimeError("interrupted")))
        with pytest.raises(RuntimeError, match="interrupted"):
            sources.ingest(profile, "stage.csv", CSV)
    digest = sha256(CSV).hexdigest()
    stage = sources._path(profile, digest, ".json").with_name(digest + ".parse-stage.json")
    record = library._read(stage)
    assert record["extraction_policies"]["csv_headerless_policy"] == 1
    # The same checkpoint as an earlier release would have written it.
    record["extraction_policies"]["csv_headerless_policy"] = 0
    record["payload_sha256"] = parse._digest({k: v for k, v in record.items() if k != "payload_sha256"})
    library._atomic_write(stage, library._json(record))
    count = []
    original = sources._spreadsheet
    with monkeypatch.context() as patch:
        patch.setattr(sources, "_spreadsheet", lambda *args: (count.append(True), original(*args))[1])
        content, _ = sources.ingest(profile, "stage.csv", CSV)
    assert count == [True]
    assert library._read(cache_for(profile, content))["csv_headerless_policy"] == 1
    assert not stage.exists()


def _staged(tmp_path, name, raw):
    from app.monthly_report_streamed_upload import StagedUpload
    path = tmp_path / ("staged-" + name)
    path.write_bytes(raw)
    return StagedUpload(path, len(raw), sha256(raw).hexdigest())


def test_streamed_non_csv_upload_stays_warm_with_a_parse_manifest(profile, monkeypatch, tmp_path):
    """A streamed TXT/PDF upload has no bytes at cache lookup; its manifest still validates."""
    raw = b"Synthetic pump inspection completed on schedule.\n"
    first, _ = sources.ingest(profile, "streamed.txt", _staged(tmp_path, "one.txt", raw))
    assert "parse_manifest" in library._read(cache_for(profile, first))
    calls = []
    original = sources.suggest_facts
    monkeypatch.setattr(sources, "suggest_facts", lambda *args: (calls.append(True), original(*args))[1])
    again, _ = sources.ingest(profile, "streamed.txt", _staged(tmp_path, "two.txt", raw))
    assert calls == []  # A cache hit, not a rebuild.
    assert again.source.page_texts == first.source.page_texts


def test_streamed_upload_resumes_checkpoint_and_publishes_its_original(profile, monkeypatch, tmp_path):
    digest = sha256(CSV).hexdigest()
    with monkeypatch.context() as patch:
        patch.setattr(sources, "suggest_facts",
                      lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic interruption")))
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            sources.ingest(profile, "first.csv", _staged(tmp_path, "first.csv", CSV))
    original_path = sources._path(profile, digest, ".csv")
    assert not original_path.exists()  # Streamed originals publish only after validation.
    with monkeypatch.context() as patch:
        patch.setattr(sources, "_spreadsheet", lambda *_: pytest.fail("completed stage parsed again"))
        content, _ = sources.ingest(profile, "second.csv", _staged(tmp_path, "second.csv", CSV))
    assert content.source.filename == "second.csv"
    assert original_path.read_bytes() == CSV
    assert sources.source_bytes(profile, content.source) == CSV


def test_resumed_checkpoint_meets_the_streamed_text_budget(profile, monkeypatch, tmp_path):
    with monkeypatch.context() as patch:
        patch.setattr(sources, "suggest_facts",
                      lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic interruption")))
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            sources.ingest(profile, "budget.csv", _staged(tmp_path, "budget.csv", CSV))
    with monkeypatch.context() as patch:
        patch.setattr(sources, "_spreadsheet", lambda *_: pytest.fail("completed stage parsed again"))
        with pytest.raises(ValueError, match="Total extracted text exceeds"):
            sources.ingest(profile, "budget.csv", _staged(tmp_path, "again.csv", CSV), max_new_text=10)


def test_parse_lock_stays_exclusive_after_a_holder_removes_its_lock_file(profile, monkeypatch):
    """A waiter on the removed lock file must not run beside a newer caller."""
    import fcntl
    import threading

    entered, inside, gates = [], [], {name: threading.Event() for name in "ABC"}
    state = Lock()
    waiting = threading.Event()
    real_flock = fcntl.flock

    def flock(fd, operation):
        if operation == fcntl.LOCK_EX and threading.current_thread().name == "B":
            waiting.set()  # B has opened the lock file and is about to wait on it.
        return real_flock(fd, operation)

    def parse(*_args, **_kwargs):
        name = threading.current_thread().name
        with state:
            entered.append((name, tuple(inside)))
            inside.append(name)
        gates[name].wait(timeout=10)
        with state:
            inside.remove(name)
        return "parsed", ()

    monkeypatch.setattr(fcntl, "flock", flock)
    monkeypatch.setattr(sources, "_ingest_locked", parse)
    run = lambda name: threading.Thread(target=sources.ingest, args=(profile, "same.csv", CSV), name=name)
    a, b, c = run("A"), run("B"), run("C")
    a.start()
    while not inside:
        sleep(.01)
    b.start()
    assert waiting.wait(timeout=10)
    sleep(.1)
    gates["A"].set()  # A finishes and removes the lock file B is waiting on.
    a.join(timeout=10)
    while "B" not in inside:
        sleep(.01)
    c.start()
    sleep(.3)  # With a stale lock, C would enter now, beside B.
    assert [name for name, _ in entered] == ["A", "B"]
    gates["B"].set()
    b.join(timeout=10)
    gates["C"].set()
    c.join(timeout=10)
    assert entered == [("A", ()), ("B", ()), ("C", ())]
    digest = sha256(CSV).hexdigest()
    assert not (sources._path(profile, digest, ".json").parent / ".parse-locks").exists()


def test_parse_lock_leaves_nothing_behind_when_the_parse_fails(profile, monkeypatch):
    """A rejected upload must not leave its lock directories in the profile."""
    def parse(*_args, **_kwargs):
        raise ValueError("Not read: synthetic parse failure")

    monkeypatch.setattr(sources, "_ingest_locked", parse)
    with pytest.raises(ValueError, match="synthetic parse failure"):
        sources.ingest(profile, "same.csv", CSV)
    digest = sha256(CSV).hexdigest()
    assert not (sources._path(profile, digest, ".json").parent / ".parse-locks").exists()


def test_resumed_pdf_checkpoint_keeps_local_ocr_spans(profile, monkeypatch):
    """OCR offsets survive an interruption, so OCR text is never taken as native."""
    import pymupdf as fitz
    from app import monthly_report_pdf_reader as reader

    lines = ("PUMP PX-72 NOT STARTED", "Synthetic follow-up visit pending")
    tsv = ["\t".join(("level", "page_num", "block_num", "par_num", "line_num", "word_num",
                      "left", "top", "width", "height", "conf", "text"))]
    for line_number, line in enumerate(lines, 1):
        for word_number, word in enumerate(line.split(), 1):
            tsv.append("\t".join(str(v) for v in (5, 1, 1, 1, line_number, word_number,
                                                   20 + 60 * word_number, 30 * line_number, 50, 20, 91, word)))
    which = reader.shutil.which
    monkeypatch.setattr(reader.shutil, "which",
                        lambda name, *a, **k: "/usr/bin/tesseract" if name == "tesseract" else which(name, *a, **k))
    monkeypatch.setattr(reader, "_ocr_image", lambda data, *, timeout: "\n".join(tsv) + "\n")
    with fitz.open() as drawing:
        page = drawing.new_page()
        page.insert_text((50, 70), "\n".join(lines), fontsize=11)
        image = page.get_pixmap().tobytes("png")
    with fitz.open() as scanned:
        scanned.new_page().insert_image(scanned[0].rect, stream=image)
        raw = scanned.tobytes()
    original_facts = sources.suggest_facts
    with monkeypatch.context() as patch:
        patch.setattr(sources, "suggest_facts",
                      lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic interruption")))
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            sources.ingest(profile, "scan.pdf", raw)
    with monkeypatch.context() as patch:
        patch.setattr(reader, "read_page", lambda *a, **k: pytest.fail("completed stage parsed again"))
        patch.setattr(sources, "suggest_facts", original_facts)
        resumed, _ = sources.ingest(profile, "scan.pdf", raw)
    assert list(resumed.source.page_texts) == ["\n".join(lines)]
    assert [(span[0], resumed.source.page_texts[0][span[1]:span[2]], span[3])
            for span in resumed.ocr_spans] == [(1, line, 91.0) for line in lines]
    assert library._read(cache_for(profile, resumed))["ocr_spans"]
