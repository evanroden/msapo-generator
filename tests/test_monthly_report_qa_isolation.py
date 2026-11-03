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
        assert fixtures.compare(replay)["checks"]["source manifests exact"]
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
        # An old context is invalidated rather than immediately reusing the
        # removed directory. Restart as a new isolated session.
        with pytest.raises(OSError, match="reset"):
            library.load_snapshot(same.contract, same.key, fixtures.PERIOD)
    with qa.isolated(COOKIE_A):
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
        # Test mode may not initiate external reader work or consume allowance.
        ran = []
        with pytest.raises(ValueError, match="disabled in isolated testing"):
            start_receipt(lambda: ran.append("prepared"), lambda _: ran.append("sent"))
        assert ran == []
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


def test_training_and_capacity_nr_are_per_test_storage_and_old_snapshot_stays_pinned(monkeypatch, tmp_path):
    from app import monthly_report_capacity as capacity
    from app import monthly_report_training as training
    from app.monthly_report_model import ReportDraft, ReportTable, ReportPeriod
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = fixtures.profile()
    with qa.isolated(COOKIE_A):
        old = fixtures.prepare("prefill")
        unchanged = library.load_snapshot(profile.contract, profile.key, fixtures.PERIOD)
        contents, _ = sources.ingest(
            profile, "synthetic-capacity.txt",
            b"Site,Service,Capacity\nDemo North,Chilled water,NR\n",
        )
        table = capacity.CapacityTable(
            "synthetic-nr", "Chilled water", ("Site", "Service", "Capacity"),
            (("Demo North", "Chilled water", "NR"),), ("qa-north",),
            contents.source.sha256, contents.source.filename, ".txt", 1, site_column=0,
        )
        revision = capacity.save_capacity(profile, (table,), expected_revision=0,
                                          actor=fixtures.ACTOR,
                                          reviewed_fingerprint=capacity.review_fingerprint((table,)))
        assert revision.revision == 1
        matrix = ReportTable(("Team member", "Site", "Lockout"),
                             (("Synthetic Person North", "Demo North", "Pending"),), training.MATRIX_REF)
        training.save_training(profile, matrix, expected_revision=0, actor=fixtures.ACTOR)
        fresh = ReportDraft(profile, ReportPeriod(2026, 10), fixtures.ACTOR,
                            old.sections, old.blocks, synthetic=True)
        filled = capacity.resolve_capacity(fresh)
        assert any("NR" in row for block in filled.blocks
                   for tab in block.extra_tables for row in tab.rows)
        assert library.load_snapshot(profile.contract, profile.key, fixtures.PERIOD) == unchanged
    with qa.isolated(COOKIE_B):
        assert capacity.load_capacity(profile.contract) is None
        assert training.load_training(profile.contract)["revision"] == 0
    assert capacity.load_capacity(profile.contract) is None
    assert training.load_training(profile.contract)["revision"] == 0



def test_reset_generation_rejects_late_worker_and_old_tab(monkeypatch, tmp_path):
    """A test reset must not allow old fragment/receipt jobs to resurrect files."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with qa.isolated(COOKIE_A):
        before = memory._data_dir()
        old_generation = qa.generation()
        snapshot = copy_context()
        assert old_generation
        qa.reset(tmp_path)
        with pytest.raises(OSError, match="reset|changed"):
            snapshot.run(memory._data_dir)
        with pytest.raises(OSError, match="reset|changed"):
            memory._data_dir()
    with qa.isolated(COOKIE_A):
        restarted = memory._data_dir()
        assert restarted == before
        assert qa.generation() and qa.generation() != old_generation
        assert not library.list_profiles(fixtures.CONTRACT)
        with pytest.raises(OSError, match="another generation|older"):
            snapshot.run(qa.reset, tmp_path)


def test_test_generation_rejects_changed_marker_without_live_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with qa.isolated(COOKIE_A):
        isolated_root = memory._data_dir()
        marker = isolated_root / ".enfra-qa-namespace"
        original = marker.read_text()
        marker.write_text(original.split("|")[0] + "|" + "f" * 32)
        try:
            with pytest.raises(OSError, match="stale|changed"):
                memory._data_dir()
        finally:
            marker.write_text(original)
        assert library._root().is_relative_to(isolated_root)


def test_old_task_cannot_write_cached_path_after_test_reset(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with qa.isolated(COOKIE_A):
        qa_root = library._root()
        destination = qa_root / "library" / "synthetic.json"
        snapshot = copy_context()
        qa.reset(tmp_path)
        with pytest.raises(OSError, match="reset"):
            snapshot.run(library._atomic_write, destination,
                         b'{"schema":1,"fake":"old"}')
    assert not destination.exists()
    with qa.isolated(COOKIE_A):
        library._root()
        with pytest.raises(library.LibraryError, match="outside its isolated storage"):
            library._atomic_write(tmp_path / "monthly_reports" / "live.json",
                                  b'{"schema":1,"fake":"outside"}')
        assert not (tmp_path / "monthly_reports" / "live.json").exists()



def test_active_journals_master_design_and_branding_are_separate(monkeypatch, tmp_path):
    """Same named report and cookie must not share design, journal or approved logo."""
    from io import BytesIO
    from PIL import Image
    from app import monthly_report_active_work as active
    from app import monthly_report_designs as designs
    from app import monthly_report_branding as branding
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    chosen = fixtures.profile()
    live_draft = fixtures.prepare if False else None  # No QA fixture in live scope.
    from app.monthly_report_model import ReportDraft, profile_sections
    live_draft = ReportDraft(chosen, fixtures.PERIOD, fixtures.ACTOR,
                             profile_sections(chosen),
                             (ResolvedBlock("activity_summary", "This month",
                                            text="Synthetic LIVE boundary marker."),),
                             synthetic=True)
    library.save_profile(chosen, expected_revision=0, actor=fixtures.ACTOR, confirmed=True)
    live_journal = active.save(COOKIE_A, live_draft, expected_revision=0,
                               base_snapshot_revision=0)
    assert live_journal.revision == 1
    manifest = library._root() / "designs" / "master" / "manifest.json"
    library._atomic_write(manifest, library._json({
        "schema": 1, "revision": 1, "default": "a" * 64, "history": []}))
    assert designs.master_state()["default"] == "a" * 64
    image = BytesIO()
    Image.new("RGB", (80, 40), "white").save(image, "PNG")
    raw = image.getvalue()
    ref = library.asset_reference(raw, "png")
    logo = branding.BrandLogo("qa-logo", "Synthetic ENFRA", (fixtures.CONTRACT,),
                             ref, "https://example.invalid/logo", "https://example.invalid/asset",
                             "2026-10-01")
    branding.save_branding((logo,), {ref: raw}, expected_revision=0,
                           actor=fixtures.ACTOR, confirmed=True)
    assert branding.read_logo(logo) == raw
    with qa.isolated(COOKIE_A):
        assert active.load(COOKIE_A, chosen.contract, chosen.key, fixtures.PERIOD) is None
        assert designs.master_state()["revision"] == 0
        assert branding.load_branding() is None
        independent = fixtures.prepare("prefill")
        result = active.save(COOKIE_A, independent, expected_revision=0,
                             base_snapshot_revision=1)
        assert result.revision == 1
        assert "Synthetic LIVE boundary marker" not in next(b.text for b in result.draft.blocks if b.key == "activity_summary")
    assert designs.master_state()["default"] == "a" * 64
    assert branding.load_branding().revision == 1
    assert branding.read_logo(logo) == raw
    recovered = active.load(COOKIE_A, chosen.contract, chosen.key, fixtures.PERIOD)
    assert recovered.draft.fingerprint == live_draft.fingerprint


def test_completed_old_preview_worker_cannot_repopulate_cache_after_qa_reset(monkeypatch, tmp_path):
    """The old PDF ticket and a late post-reset page must both stay unavailable."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with fitz.open() as document:
        document.new_page().insert_text((40, 50), "Old synthetic QA page")
        page = ReportPreview(document.tobytes(), 1, "old", "September 2026")
    with qa.isolated(COOKIE_A):
        stale = STORE.put("same-browser", page)
        old_task = copy_context()
        qa.reset(tmp_path)
        STORE.reset_scope()
        with pytest.raises(OSError, match="reset|changed"):
            old_task.run(STORE.put, "same-browser", page)
    with qa.isolated(COOKIE_A):
        assert not STORE.available("same-browser", stale)
        fresh = STORE.put("same-browser", page)
        assert STORE.available("same-browser", fresh)
        STORE.discard("same-browser", fresh)



@pytest.mark.parametrize("route", ("prefill", "replay"))
def test_complete_synthetic_qa_fixture_generates_native_word_and_application_pdf(route, monkeypatch, tmp_path):
    """X03/X05/X06: both routes generate full-page actual outputs, not a form stub."""
    from io import BytesIO
    from docx import Document
    from app.monthly_report_docx import generate_report
    from tests.conftest import requires_libreoffice
    import os
    if not __import__("shutil").which("libreoffice") and not __import__("shutil").which("soffice"):
        pytest.skip("The required document renderer is unavailable here.")
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with qa.isolated(COOKIE_A):
        draft = fixtures.prepare(route)
        checked = fixtures.compare(draft)
        assert all(checked["checks"].values()), checked
        if route == "replay":
            from dataclasses import asdict
            from app.monthly_report_checks import preflight
            from app.monthly_report_source_scope import correct_scope
            source = next(source for source in draft.sources if source.filename == "synthetic-activity.txt")
            original = sources.source_bytes(draft.profile, source)
            assert any(check.code == "source_facility" and check.blocking
                       and check.block_key == source.id for check in preflight(draft))
            with pytest.raises(ValueError, match="Establish the site scope"):
                generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
            # Explicit reviewer intent for this invented scenario: the TXT is
            # Demo North work. Its bytes deliberately do not state a site; this
            # is a test action after import, never an extraction/fixture default.
            corrected = correct_scope(source, draft.profile, ("qa-north",))
            draft = replace(draft, sources=tuple(corrected if item.id == source.id else item
                                                 for item in draft.sources))
            draft = library.draft_from_dict(asdict(draft))
            assert sources.source_bytes(draft.profile, corrected) == original == fixtures.ACTIVITY_TXT
            assert not any(check.code == "source_facility" and check.blocking for check in preflight(draft))
            assert all(fixtures.compare(draft)["checks"].values())
            assert not next(item for item in library.load_snapshot(draft.profile.contract,
                draft.profile.key, draft.period).draft.sources if item.id == source.id).scope_review
        result = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
        assert result.docx and result.pdf, result.pdf_error
        doc = Document(BytesIO(result.docx))
        cells = "\\n".join(cell.text for table in doc.tables for row in table.rows
                             for cell in row.cells)
        assert "Q-TEST-731" in cells and "Pending" in cells
        assert cells.count("NR") >= 2
        assert len(doc.inline_shapes) >= 1, "Rendered org chart must be retained in the real Word file"
        with fitz.open(stream=result.pdf, filetype="pdf") as pdf:
            text = "\\n".join(page.get_text() for page in pdf)
            assert len(pdf) >= 10
            assert "Q-TEST-731" in text and "SYNTHETIC" in text
            assert "3 total, 2 completed, 1 open" in text
            assert "66.7%" in text
            for price in ("$12,345.67", "$987.65", "$13,333.32", "$456.78", "$222.22"):
                assert price not in text
