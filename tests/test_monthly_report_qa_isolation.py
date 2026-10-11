"""X01-X10 synthetic isolation boundaries; never use private customer data."""
from contextvars import copy_context
from dataclasses import replace
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import fitz
import pytest

from app import memory
from app import monthly_report_library as library
from app import monthly_report_directory as directory
from app import monthly_report_sources as sources
from app import monthly_report_testing as qa
from app import monthly_report_qa_fixture as fixtures
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_preview_store import STORE
from app.monthly_report_preview import ReportPreview
from app.receipt_jobs import start_receipt


COOKIE_A = "a" * 32
COOKIE_B = "b" * 32


def test_two_testers_and_live_root_have_no_shared_directory_history_or_source(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    live_root = library._root()
    same = fixtures.profile()
    library.save_profile(same, expected_revision=0, actor="Synthetic Live", confirmed=True)
    live_source, _ = sources.ingest(same, "synthetic-workorders.csv", fixtures.WO_CSV)
    assert library.load_profile(same.contract, same.key).revision == 1
    with qa.isolated(COOKIE_A):
        qa_root = library._root()
        assert qa_root != live_root and not qa_root.is_relative_to(live_root)
        prefill = fixtures.prepare("prefill")
        saved = library.load_snapshot(same.contract, same.key, fixtures.PERIOD)
        assert saved and saved.draft.synthetic
        assert not saved.draft.sources
        assert library.load_profile(same.contract, same.key).revision == 1
        assert directory.load_directory(same.contract) is not None
        assert not sources._path(same, live_source.source.sha256, ".csv").exists()
        replay = fixtures.prepare("replay")
        assert replay.sources and replay.sources[0].filename == "synthetic-workorders.csv"
        assert fixtures.compare(replay)["checks"]["source identity and hashes"]
    assert library._root() == live_root
    assert library.load_snapshot(same.contract, same.key, fixtures.PERIOD) is None
    assert directory.load_directory(same.contract) is None
    assert sources.source_bytes(same, live_source.source) == fixtures.WO_CSV
    with qa.isolated(COOKIE_B):
        assert library.load_snapshot(same.contract, same.key, fixtures.PERIOD) is None
        assert library.list_profiles(same.contract) == ()
    with qa.isolated(COOKIE_A):
        assert library.load_snapshot(same.contract, same.key, fixtures.PERIOD)


def test_test_reset_is_scoped_and_recovers_cleanly(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    same = fixtures.profile()
    library.save_profile(same, expected_revision=0, actor="Synthetic Live", confirmed=True)
    with qa.isolated(COOKIE_A):
        fixtures.prepare("prefill")
        assert library.load_snapshot(same.contract, same.key, fixtures.PERIOD)
        qa.reset(tmp_path)
        assert library.load_snapshot(same.contract, same.key, fixtures.PERIOD) is None
        assert directory.load_directory(same.contract) is None
        assert fixtures.prepare("replay").sources
    assert library.load_profile(same.contract, same.key).revision == 1
    assert library.load_snapshot(same.contract, same.key, fixtures.PERIOD) is None


def test_invalid_context_never_falls_back_to_live(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        with qa.isolated("not-a-cookie"):
            pass
    with pytest.raises(ValueError):
        qa.reset(tmp_path)
    with qa.isolated(COOKIE_A):
        assert library._root() != tmp_path / "monthly_reports"
    missing = tmp_path / "missing-root"
    monkeypatch.setenv("EPC_DATA_DIR", str(missing))
    with qa.isolated(COOKIE_A), pytest.raises(OSError, match="Isolated report storage"):
        library._root()
    assert not missing.exists()


def test_qa_preview_pdf_and_memory_are_separate_from_live(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with fitz.open() as document:
        document.new_page().insert_text((40, 50), "Invented QA preview")
        sample = ReportPreview(document.tobytes(), 1, "synthetic", "September 2026")
    ticket_live = STORE.put("same-owner", sample)
    db_live = memory._db_path()
    with qa.isolated(COOKIE_A):
        assert not STORE.available("same-owner", ticket_live)
        db_qa = memory._db_path()
        ticket_qa = STORE.put("same-owner", sample)
        assert STORE.available("same-owner", ticket_qa)
        assert db_qa != db_live
        assert not db_live.is_relative_to(db_qa.parent)
        assert db_qa.parent != db_live.parent
    assert STORE.available("same-owner", ticket_live)
    assert not STORE.available("same-owner", ticket_qa)
    STORE.discard("same-owner", ticket_live)
    with qa.isolated(COOKIE_A):
        STORE.discard("same-owner", ticket_qa)


def test_reset_qa_cache_removes_only_current_tester_not_live_or_another_test(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with fitz.open() as document:
        document.new_page().insert_text((40, 50), "Invented QA preview")
        page = ReportPreview(document.tobytes(), 1, "synthetic", "September 2026")
    live = STORE.put("reused-owner", page)
    with qa.isolated(COOKIE_A):
        tester_a = STORE.put("reused-owner", page)
    with qa.isolated(COOKIE_B):
        tester_b = STORE.put("reused-owner", page)
        assert not STORE.available("reused-owner", tester_a)
    with qa.isolated(COOKIE_A):
        assert not STORE.available("reused-owner", tester_b)
        STORE.reset_scope()
        assert not STORE.available("reused-owner", tester_a)
    with qa.isolated(COOKIE_B):
        assert STORE.available("reused-owner", tester_b)
        STORE.discard("reused-owner", tester_b)
    assert STORE.available("reused-owner", live)
    STORE.discard("reused-owner", live)


def test_copied_background_context_stays_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    live_root = library._root()
    with qa.isolated(COOKIE_A):
        isolated_root = library._root()
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker = executor.submit(copy_context().run, library._root)
            assert worker.result() == isolated_root
        # The central bounded receipt worker automatically propagates QA mode.
        job = start_receipt(lambda: "invented", lambda _: str(library._root()))
        assert job is not None and job.result() == str(isolated_root)
    assert library._root() == live_root


def test_prefill_and_replay_are_not_interchangeable(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="blocked outside"):
        fixtures.prepare("prefill")
    with qa.isolated(COOKIE_A):
        first = fixtures.prepare("prefill")
        assert not first.sources
        assert all(fixtures.compare(first)["checks"].values())
        second = fixtures.prepare("replay")
        assert len(second.sources) == 2
        assert first.fingerprint != second.fingerprint
        results = fixtures.compare(second)
        assert results["mode"] == "source replay", results
        assert all(results["checks"].values()), results
        again = fixtures.prepare("replay")
        assert again.fingerprint == second.fingerprint
