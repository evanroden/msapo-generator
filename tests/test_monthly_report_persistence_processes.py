"""Restart and process-concurrency evidence for existing storage rules (Refs #475).

Synthetic only. These exercise real filesystem storage in fresh interpreters,
not browser sessions, deployment upgrades, or proposed contract-master policies.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import multiprocessing
import os
import sys

from PIL import Image
import pymupdf

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft


def _image(color):
    output = BytesIO()
    Image.new("RGB", (24, 24), color).save(output, "PNG")
    raw = output.getvalue()
    return library.asset_reference(raw, "png"), raw


def _pdf(label):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "Synthetic original " + label)
        return document.tobytes()


def _fresh_reader(root, scopes, results):
    os.environ["EPC_DATA_DIR"] = str(root)
    found = []
    for contract, key in scopes:
        state = library.load_profile(contract, key)
        snapshots = []
        for month in (9, 10):
            saved = library.load_snapshot(contract, key, ReportPeriod(2026, month))
            original, = saved.draft.sources
            chart = next(block for block in saved.draft.blocks if block.key == "org_chart")
            snapshots.append({
                "draft": saved.draft,
                "revision": saved.revision,
                "original": sha256(sources.source_bytes(saved.draft.profile, original)).hexdigest(),
                "chart": sha256(library.read_asset(contract, key, chart.asset_hashes[0])).hexdigest(),
                "history": library.load_snapshot_version(contract, key, saved.draft.period, 1),
            })
        found.append((state, snapshots))
    results.put(found)


def _competing_writer(root, contract, key, writer, ready, start, results):
    os.environ["EPC_DATA_DIR"] = str(root)
    saved = library.load_snapshot(contract, key, ReportPeriod(2026, 9))
    candidate = replace(saved.draft, prepared_by=writer)
    ready.put(writer)  # Both processes must load the same revision before either saves.
    if not start.wait(20):
        raise RuntimeError("Synthetic competing writer was not released")
    try:
        published = library.save_snapshot(candidate, expected_revision=saved.revision)
        results.put((writer, "saved", published.revision, candidate.prepared_by))
    except library.RevisionConflict:
        # The losing caller still owns its unsaved edit for normal recovery UI.
        results.put((writer, "conflict", saved.revision, candidate.prepared_by))


def _start_spawned_workers(monkeypatch, children):
    # Full-suite Streamlit AppTest can leave __main__.__file__ pointing at a
    # generated UI script. Spawn would execute that script outside Streamlit,
    # fail before entering our worker, and leave the IPC queue empty.
    # Bootstrap from this side-effect-free test module instead. This preserves
    # fresh interpreters and leaves the parent's __main__ unchanged.
    with monkeypatch.context() as temporary:
        temporary.setattr(sys.modules["__main__"], "__file__", __file__, raising=False)
        for child in children:
            child.start()


def _finish(children):
    for child in children:
        if child.is_alive():
            child.terminate()
        child.join(timeout=5)


def _draft(profile, original, chart):
    return ReportDraft(
        profile, ReportPeriod(2026, 9), "Synthetic preparer",
        (
            SectionSpec("contacts", "1", "Contacts", (BlockSpec("org_chart", "image_page"),)),
            SectionSpec("activity", "2", "Activity", (BlockSpec("activity_summary", "rich_text"),)),
        ),
        (chart, ResolvedBlock("activity_summary", "This month", text="September-only inspection.")),
        sources=(original,), synthetic=True,
    )


def test_fresh_process_reopens_scoped_originals_and_pinned_reports_after_rollover(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    scopes, expected = [], []
    base = synthetic_profiles()[1]
    # Identical display slugs and profile keys across contracts must not collide.
    for contract_index, contract in enumerate(("Synthetic Contract A", "Synthetic-Contract-A")):
        for site_index, site in enumerate(base.facilities):
            profile = replace(base, contract=contract, key=site.key, facilities=(site,), scope_type="individual")
            library.save_profile(profile, expected_revision=0, actor="Synthetic editor", confirmed=True)
            original_bytes = _pdf(contract + " / " + site.key)
            content, _ = sources.ingest(profile, "synthetic-original.pdf", original_bytes)
            original = replace(content.source, service_date="2026-09-12", facility=site.key)
            standing_ref, standing_bytes = _image("red")
            standing = ResolvedBlock("org_chart", "Library", asset_hashes=(standing_ref,))
            library.replace_block(contract, site.key, "org_chart", standing, label="Original standing chart",
                                  expected_revision=1, actor="Synthetic editor", confirmed=True,
                                  assets=((standing_ref, standing_bytes),))
            override_ref, override_bytes = _image((30 + contract_index * 80, 70 + site_index * 80, 45))
            override = replace(standing, source="This month", asset_hashes=(override_ref,),
                               references=(sources.source_reference(original, 1),))
            september = _draft(profile, original, override)
            first = library.save_snapshot(september, expected_revision=0, assets=((override_ref, override_bytes),))
            updated_ref, updated_bytes = _image("blue")
            latest = library.replace_block(contract, site.key, "org_chart", replace(standing, asset_hashes=(updated_ref,)),
                                           label="Later explicit library update", expected_revision=2,
                                           actor="Synthetic editor", confirmed=True, assets=((updated_ref, updated_bytes),))
            october = new_month_draft(september, ReportPeriod(2026, 10))
            assert next(block for block in october.blocks if block.key == "activity_summary").text == ""
            assert october.sources == (original,), "Carry references must retain original dates and identities."
            second = library.save_snapshot(october, expected_revision=0)
            scopes.append((contract, site.key))
            expected.append((latest, [
                {"draft": draft, "revision": 1, "original": sha256(original_bytes).hexdigest(),
                 "chart": sha256(override_bytes).hexdigest(), "history": saved}
                for draft, saved in ((september, first), (october, second))
            ]))
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    child = context.Process(target=_fresh_reader, args=(tmp_path, scopes, results))
    try:
        _start_spawned_workers(monkeypatch, (child,))
        assert results.get(timeout=30) == expected
        child.join(timeout=10)
        assert child.exitcode == 0
    finally:
        _finish([child])
        results.close()
        results.join_thread()
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before, "Reopen must not promote overrides, rewrite originals, or change history."


def test_independent_process_writers_preserve_the_winner_history_and_losing_edit(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    original_bytes = _pdf("process race")
    original, _ = sources.ingest(profile, "synthetic-original.pdf", original_bytes)
    reference, raw = _image("green")
    draft = _draft(profile, original.source, ResolvedBlock("org_chart", "This month", asset_hashes=(reference,)))
    first = library.save_snapshot(draft, expected_revision=0, assets=((reference, raw),))
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    children = [context.Process(target=_competing_writer,
                args=(tmp_path, profile.contract, profile.key, name, ready, start, results))
                for name in ("Synthetic editor A", "Synthetic editor B")]
    try:
        _start_spawned_workers(monkeypatch, children)
        assert {ready.get(timeout=30) for _ in children} == {"Synthetic editor A", "Synthetic editor B"}
        start.set()
        outcomes = [results.get(timeout=30) for _ in children]
        for child in children:
            child.join(timeout=10)
        assert all(child.exitcode == 0 for child in children)
        assert sorted(item[1] for item in outcomes) == ["conflict", "saved"]
        assert all(name == retained_edit for name, _, _, retained_edit in outcomes)
        winner = next(name for name, status, revision, _ in outcomes if status == "saved" and revision == 2)
        args = profile.contract, profile.key, draft.period
        head = library.load_snapshot(*args)
        assert head.revision == 2 and head.draft.prepared_by == winner
        assert library.load_snapshot_version(*args, 1) == first
        assert library.load_snapshot_version(*args, 2) == head
        versions, more = library.snapshot_history(*args)
        assert [item.revision for item in versions] == [2, 1] and not more
        assert sources.source_bytes(profile, head.draft.sources[0]) == original_bytes
    finally:
        _finish(children)
        for queue in (ready, results):
            queue.close()
            queue.join_thread()
