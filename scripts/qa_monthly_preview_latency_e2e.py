"""Synthetic MR-021 backend latency receipt; no client data or paid services.

Measures the server boundary *after upload bytes arrive*, not network transfer or
browser paint. Pair with qa_monthly_preview_browser_latency.py for first paint.
Run with the production image under 512 MiB / 0.5 CPU; no hosting changes.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import gc
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import tempfile
from threading import Barrier
from zipfile import ZipFile
from time import perf_counter, process_time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document
from openpyxl import Workbook
from app.monthly_latency_spans import capture_spans, measure_span
from docx.shared import Inches
from PIL import Image
import pymupdf as fitz

from app import monthly_report_sources as sources
from app.monthly_report_latency_trace import TimingTrace, span, synthetic_timing
from app.monthly_report_model import Facility, ReportProfile
from app.monthly_report_source_preview import source_thumbnail_uri
from scripts.qa_monthly_report_resources import _fixture, _memory, _memory_events, _current_rss


def _profile(key):
    return ReportProfile("Synthetic Preview Contract", key, "Invented Preview Site",
                         (Facility("synthetic", "Invented Preview Site"),))


def _pdf(pages, variant="A"):
    with fitz.open() as doc:
        for number in range(pages):
            page = doc.new_page(width=612, height=792)
            page.insert_text((55, 70), f"SYNTHETIC PDF {variant} PAGE {number+1:03d}", fontsize=18)
            for mark in range(12):
                page.draw_rect(fitz.Rect(55 + mark * 12, 110 + mark * 4,
                                         390 + mark * 8, 120 + mark * 4),
                               color=(0, 0, 0), width=.5)
        return doc.tobytes(garbage=4, deflate=True)


def _docx(pictures):
    document = Document()
    document.add_heading("SYNTHETIC ONLY - MONTHLY EVIDENCE", 1)
    document.add_paragraph("Invented content. Not an approved report.")
    for number in range(pictures):
        photo = Image.effect_noise((720, 480), 12).convert("RGB")
        photo.paste((40 + number * 15, 80, 120), (20, 20, 160, 125))
        if pictures >= 8:
            resized = photo.resize((1400, 940))
            photo.close()
            photo = resized
        buffer = BytesIO()
        photo.save(buffer, format="JPEG", quality=82)
        document.add_picture(BytesIO(buffer.getvalue()), width=Inches(5.5))
        document.add_paragraph(f"Invented image {number + 1}")
        table = document.add_table(rows=3, cols=3)
        for row in range(3):
            for col in range(3):
                table.cell(row, col).text = f"SYNTHETIC {number + 1} / {row} / {col}"
        photo.close()
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _summary(values):
    ordered = sorted(values)
    result = {"n": len(ordered), "samples_ms": [round(value * 1000, 3) for value in values],
              "min_ms": round(ordered[0] * 1000, 3),
              "median_ms": round(statistics.median(ordered) * 1000, 3),
              "max_ms": round(ordered[-1] * 1000, 3)}
    if len(ordered) >= 20:
        result["p95_ms"] = round(ordered[round(.95 * (len(ordered) - 1))] * 1000, 3)
    return result


def _dominant_stage(receipts, stages):
    """Compare disjoint top-level phases, not nested PDF raster twice."""
    totals = {stage: 0.0 for stage in stages}
    for receipt in receipts:
        for event in receipt["spans"]:
            if not event["point"] and event["stage"] in totals:
                totals[event["stage"]] += event["wall_ms"]
    return {"stage": max(totals, key=totals.get),
            "mean_ms": round(max(totals.values()) / len(receipts), 3),
            "stage_means_ms": {key: round(value / len(receipts), 3)
                               for key, value in totals.items()}}


def _image(profile, content, number=None):
    if number is None:
        number = (content.image_items[0][0] if content.image_items else 1)
    image = sources.page_image(profile, content, number, preview=True)
    uri = source_thumbnail_uri(image)
    assert uri.startswith("data:image/") and len(uri) > 50
    assert 0 < image.width <= 1056 and 0 < image.height <= 1056
    return {"hash": sha256(image.data).hexdigest(), "width": image.width,
            "height": image.height, "bytes": len(image.data), "number": number}


def _work_order_bytes(suffix, rows=256):
    """Invented work-order values only, preserving native table row counts."""
    header = ("Work Order", "Status", "Facility", "Date", "Note")
    data = [(f"QA-WO-{i:04d}", "Open" if i % 2 else "Completed",
             "Invented Preview Site", "2026-09-15", f"synthetic item {i}")
            for i in range(1, rows + 1)]
    if suffix == ".csv":
        return ("\n".join(",".join(row) for row in (header, *data)) + "\n").encode()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Synthetic work orders"
    sheet.append(header)
    for row in data:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _table_cases():
    output = []
    for suffix in (".csv", ".xlsx"):
        raw = _work_order_bytes(suffix)
        cold, warm = [], []
        for attempt in range(5):
            profile = _profile(f"qa491-table-{suffix.lstrip('.')}-{attempt}")
            with capture_spans() as spans:
                with measure_span("source_ingest"):
                    content, extras = sources.ingest(profile, "invented-orders" + suffix, raw)
                started = perf_counter()
                cached, cached_extras = sources.ingest(profile, "invented-orders" + suffix, raw)
                warm.append(perf_counter() - started)
            cold.append(next(event["elapsed_ms"] for event in spans
                             if event["phase"] == "source_ingest") / 1000)
            assert extras == cached_extras == ()
            assert len(content.tables) == len(cached.tables) == 1
            assert len(content.tables[0].rows) == len(cached.tables[0].rows) == 256
            assert content.tables[0].rows == cached.tables[0].rows
            assert content.source.sha256 == cached.source.sha256 == sha256(raw).hexdigest()
        output.append({"workload": "work-orders-" + suffix[1:], "rows": 256,
                       "fixture_sha256": sha256(raw).hexdigest(), "bytes": len(raw),
                       "cold_ingest": _summary(cold), "warm_ingest": _summary(warm),
                       "data_preserved": True, "raster": "not applicable: table/text source"})
    return output


def _mixed_and_negative():
    """Real ingest boundaries, not browser or persisted-report acceptance."""
    profile = _profile("qa491-mixed")
    batch = (("source.pdf", _pdf(2, "MIXED")),
             ("source.docx", _docx(1)),
             ("work-orders.csv", _work_order_bytes(".csv")),
             ("work-orders.xlsx", _work_order_bytes(".xlsx")))
    received = []
    for filename, raw in batch:
        started = perf_counter()
        content, _ = sources.ingest(profile, filename, raw)
        received.append({"suffix": Path(filename).suffix,
                         "sha256": content.source.sha256,
                         "elapsed_ms": round((perf_counter() - started) * 1000, 3)})
    # Same bytes under two labels are one immutable content identity, not two
    # different files. A different revision must never alias the old source.
    duplicate, _ = sources.ingest(profile, "duplicate-label.csv", batch[2][1])
    assert duplicate.source.sha256 == received[2]["sha256"]
    failures = []
    for name, raw in (("empty.csv", b""), ("not-supported.exe", b"bytes"),
                      ("malformed.csv", b'Work Order,Status\n"unclosed,Open')):
        try:
            sources.ingest(profile, name, raw)
        except ValueError:
            failures.append(name.rsplit(".", 1)[-1] + ":rejected")
        else:
            raise AssertionError("Invalid synthetic input unexpectedly accepted")
    return {"ingested": received, "duplicate_content_identity_preserved": True,
            "rejections": failures, "expected_rejections": 3}


def _source_cases():
    cases = (("pdf-small-2", ".pdf", _pdf(2)),
             ("pdf-representative-24", ".pdf", _pdf(24)),
             ("pdf-bounded-large-96", ".pdf", _pdf(96)),
             ("docx-small-1image", ".docx", _docx(1)),
             ("docx-representative-4image", ".docx", _docx(4)),
             ("docx-bounded-large-8image", ".docx", _docx(8)))
    results = []
    for case, suffix, raw in cases:
        timings = {key: [] for key in ("cold_ingest", "cold_thumbnail", "cold_total",
                                      "warm_ingest", "warm_thumbnail", "warm_total")}
        preserved = None
        stage_receipts = {"cold": [], "warm": []}
        cold_spans = []
        for number in range(5):
            profile = _profile(f"qa491-{case}-{number}")
            cold_trace = TimingTrace()
            with synthetic_timing(cold_trace), capture_spans() as spans:
                start = perf_counter()
                with measure_span("source_ingest"):
                    content, extras = sources.ingest(profile, "invented" + suffix, raw)
                ingest_at = perf_counter()
                with measure_span("source_thumbnail"):
                    thumb = _image(profile, content)
                finished = perf_counter()
            stage_receipts["cold"].append(cold_trace.receipt())
            cold_spans.append(list(spans))
            assert extras == ()
            timings["cold_ingest"].append(ingest_at - start)
            timings["cold_thumbnail"].append(finished - ingest_at)
            timings["cold_total"].append(finished - start)
            warm_trace = TimingTrace()
            with synthetic_timing(warm_trace):
                warm_start = perf_counter()
                warm, extras = sources.ingest(profile, "invented" + suffix, raw)
                warm_ingest_at = perf_counter()
                warm_thumb = _image(profile, warm)
                warm_finished = perf_counter()
            stage_receipts["warm"].append(warm_trace.receipt())
            assert extras == () and warm_thumb == thumb and warm.source.sha256 == content.source.sha256
            timings["warm_ingest"].append(warm_ingest_at - warm_start)
            timings["warm_thumbnail"].append(warm_finished - warm_ingest_at)
            timings["warm_total"].append(warm_finished - warm_start)
            preserved = {"source_sha256": content.source.sha256,
                         "source_pages_or_items": len(content.source.page_texts),
                         "first_thumbnail": thumb}
            if suffix == ".pdf" and number == 0:
                midpoint = (len(content.source.page_texts) + 1) // 2
                last = len(content.source.page_texts)
                checks = [_image(profile, content, page) for page in sorted({1, midpoint, last})]
                assert len({entry["hash"] for entry in checks}) == len(checks)
                preserved["first_middle_last_thumbnail_geometry_and_hash"] = checks
            del content, warm
            gc.collect()
        results.append({"workload": case, "source_kind": suffix[1:],
                        "source_bytes": len(raw),
                        "fixture_sha256": sha256(raw).hexdigest(),
                        "samples": {key: _summary(values) for key, values in timings.items()},
                        "cold_critical_path_spans": cold_spans,
                        "stage_receipts": stage_receipts,
                        "dominant_cold_stage": _dominant_stage(stage_receipts["cold"],
                            ("hash_cache_lookup", "parse", "optional_visual_read")),
                        "dominant_warm_stage": _dominant_stage(stage_receipts["warm"],
                            ("hash_cache_lookup", "parse", "optional_visual_read")),
                        "preservation": preserved})
    return results


def _concurrent():
    raw = _pdf(24, "two-concurrent-visitors")
    barrier = Barrier(2)
    def visitor(index):
        profile = _profile(f"qa491-concurrent-{index}")
        barrier.wait(timeout=20)
        start = perf_counter()
        content, _ = sources.ingest(profile, "shared-name.pdf", raw)
        image = _image(profile, content)
        return {"owner": profile.key, "elapsed_seconds": round(perf_counter() - start, 4),
                "source_sha256": content.source.sha256, "thumbnail": image}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(visitor, index) for index in (1, 2)]
        values = [future.result(timeout=90) for future in futures]
    assert values[0]["thumbnail"] == values[1]["thumbnail"]
    assert values[0]["owner"] != values[1]["owner"]
    return values


def _replacement():
    profile = _profile("qa491-replacement")
    first, _ = sources.ingest(profile, "same-name.pdf", _pdf(3, "OLD"))
    first_page = _image(profile, first)
    replacement, _ = sources.ingest(profile, "same-name.pdf", _pdf(3, "NEW"))
    latest = _image(profile, replacement)
    assert first.source.sha256 != replacement.source.sha256
    assert first_page["hash"] != latest["hash"]
    assert _image(profile, first) == first_page  # Immutable original retained.
    return {"old_source_sha256": first.source.sha256,
            "new_source_sha256": replacement.source.sha256,
            "old_thumbnail_sha256": first_page["hash"], "new_thumbnail_sha256": latest["hash"],
            "both_source_occurrences_preserved": True}


def _section_preview():
    from app.monthly_report_preview import preview_section
    from app.monthly_report_preview_store import PreviewStore
    from app import monthly_report_section_assembly_cache as assembly_cache
    from app import monthly_report_native_layout as native

    native_original = native.build_native_docx
    calls = []
    def package_members_sha256(raw):
        # Compare every actual DOCX XML, relationship and embedded media part.
        # ZIP container timestamps/order can differ without changing content.
        with ZipFile(BytesIO(raw)) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names)), "Duplicate DOCX package names."
            members = sorted((name, sha256(archive.read(name)).hexdigest()) for name in names)
        return sha256(json.dumps(members, separators=(",", ":")).encode()).hexdigest()

    def counted(*args, **kwargs):
        started = perf_counter()
        with span("native_assembly"), measure_span("native_assembly"):
            raw = native_original(*args, **kwargs)
        calls.append({"seconds": perf_counter() - started, "sha256": sha256(raw).hexdigest(),
                      "package_sha256": package_members_sha256(raw)})
        return raw
    result = {"runs": {}}
    with tempfile.TemporaryDirectory(prefix="qa491-native-") as directory:
        root = Path(directory)
        # _fixture's installed source and images remain in this isolated namespace.
        draft, assets, source_bytes = _fixture(root)
        result["source_docx_bytes"] = source_bytes
        result["source_sha256"] = sha256((root / "synthetic-large-photo-report.docx").read_bytes()).hexdigest()
        versions = tuple(sorted((ref, sha256(raw).digest()) for ref, raw in assets.items()))
        store = PreviewStore()
        native.build_native_docx = counted
        try:
            controls = []
            for name, owner in (("uncached_control", None), ("owner_scoped_reuse", "qa491-owner")):
                assembly_cache.clear()
                calls.clear()
                measures = []
                from app.monthly_report_section_assembly_cache import owner_scope
                with owner_scope(owner, versions):
                    for index in range(3):
                        trace = TimingTrace()
                        with synthetic_timing(trace), capture_spans() as spans:
                            started = perf_counter()
                            preview = preview_section(draft, "activity", assets.__getitem__)
                            converted_at = perf_counter()
                            ticket = store.put(owner or "qa491-control", preview)
                            inserted_at = perf_counter()
                            with span("raster"), measure_span("first_raster"):
                                rasters = store.pages(owner or "qa491-control", ticket, (0, 1))
                            finished = perf_counter()
                        assert rasters and len(rasters) == 2
                        assert all(data.startswith(b"\xff\xd8") for _, data in rasters)
                        geometry = {"pages": ticket.pages,
                                    "sizes": tuple((round(w, 2), round(h, 2)) for w, h in ticket.sizes),
                                    "rasters": tuple(sha256(data).hexdigest() for _, data in rasters)}
                        controls.append(geometry)
                        measures.append({"run": index + 1,
                                         "stage_receipt": trace.receipt(),
                                         "assembly_conversion_seconds": round(converted_at - started, 4),
                                         "pdf_ticket_seconds": round(inserted_at - converted_at, 4),
                                         "first_two_rasters_seconds": round(finished - inserted_at, 4),
                                         "total_seconds": round(finished - started, 4),
                                         "critical_path_spans": list(spans)})
                        store.discard(owner or "qa491-control", ticket)
                        del preview, rasters
                        gc.collect()
                result["runs"][name] = {"samples": measures, "native_assemblies": len(calls),
                                        "dominant_stage": _dominant_stage(
                                            [sample["stage_receipt"] for sample in measures],
                                            ("job_queue", "native_assembly", "conversion", "raster")),
                                        "native_assembly_seconds": [round(c["seconds"], 4) for c in calls],
                                        "native_docx_sha256": [c["sha256"] for c in calls],
                                         "native_docx_package_sha256": [c["package_sha256"] for c in calls]}
            assert result["runs"]["uncached_control"]["native_assemblies"] == 3
            assert result["runs"]["owner_scoped_reuse"]["native_assemblies"] == 1
            assert all(item == controls[0] for item in controls)
            # Raw ZIP hashes are still reported; require exact equality of
            # all package member bytes for meaningful native DOCX equivalence.
            assert len(set(result["runs"]["uncached_control"]["native_docx_package_sha256"]
                           + result["runs"]["owner_scoped_reuse"]["native_docx_package_sha256"])) == 1, (
                "Uncached and reused native DOCX package contents differ."
            )
            result["output_equivalence"] = controls[0]
            result["store_budgets"] = store.stats()
        finally:
            native.build_native_docx = native_original
            assembly_cache.clear()
            store.close()
    return result


def _cpu_stat():
    try:
        stats = {}
        for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines():
            parts = line.split()
            if len(parts) == 2:
                stats[parts[0]] = int(parts[1])
        return stats
    except (OSError, ValueError):
        return {}


def _human_summary(result):
    env = result["environment"]
    lines = [
        "A01 SYNTHETIC ONLY — not production latency or live-report acceptance",
        "Exact commit: " + str(env["commit"]),
        f"Part: {result['part']}; CPU quota: {env['cpu_quota']}; memory cap bytes: {env['memory_limit_bytes']}",
        f"Total wall: {result['elapsed_seconds']}s; Python CPU: {result['python_process_cpu_seconds']}s; Office CPU: {result['child_office_cpu_seconds']}s",
        f"Peak Python RSS: {result['peak_process_rss_bytes']}; cgroup memory peak: {result['cgroup_peak_bytes']}",
        f"Cgroup CPU stat delta: {result['cpu_stat_delta']}; OOM delta: {result['memory_events_delta']}",
    ]
    if result["part"] == "sources":
        for case in result["sources"]:
            cold, warm = case["samples"]["cold_total"], case["samples"]["warm_total"]
            lines.append(f"{case['workload']}: cold median {cold['median_ms']}ms, warm median {warm['median_ms']}ms; n={cold['n']}")
        for case in result["work_order_tables"]:
            lines.append(f"{case['workload']}: cold median {case['cold_ingest']['median_ms']}ms; warm median {case['warm_ingest']['median_ms']}ms; rows={case['rows']}")
    else:
        for name, data in result["native_section"]["runs"].items():
            elapsed = [row["total_seconds"] for row in data["samples"]]
            lines.append(f"{name}: median total {statistics.median(elapsed):.4f}s; native assemblies={data['native_assemblies']}; raw={elapsed}")
    lines.append("Five samples per source and three native runs are not enough for credible p95.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Independent capped synthetic source/native phases")
    parser.add_argument("--part", required=True, choices=("sources", "native"))
    part = parser.parse_args().part
    memory_limit, _ = _memory()
    cpu = None
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        cpu = None if quota == "max" else int(quota) / int(period)
    except (OSError, ValueError, ZeroDivisionError):
        pass
    if os.environ.get("RESOURCE_REQUIRE_512_MB") == "1" and (
            memory_limit is None or memory_limit > 512 * 1024 * 1024):
        raise RuntimeError("Requires 512 MiB cgroup.")
    if os.environ.get("RESOURCE_REQUIRE_HALF_CPU") == "1" and (cpu is None or cpu > .5):
        raise RuntimeError("Requires 0.5 CPU quota.")
    before_events = _memory_events()
    before_cpu_stats = _cpu_stat()
    with tempfile.TemporaryDirectory(prefix="qa491-synthetic-") as temporary:
        os.environ["EPC_DATA_DIR"] = str(Path(temporary) / "runtime")
        # All source/draft paths are synthetic; no durable or shared client data.
        started = perf_counter()
        cpu_started = process_time()
        child_started = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {"schema": 2,
                  "boundary": "server_received_bytes_to_first_raster_delivery",
                  "part": part,
                  "environment": {"python": sys.version.split()[0],
                                  "platform": platform.platform(), "memory_limit_bytes": memory_limit,
                                  "cpu_quota": cpu,
                                  "dependencies": {
                                      name: importlib.metadata.version(name)
                                      for name in ("PyMuPDF", "Pillow", "python-docx")
                                  }, "commit": os.environ.get("APP_GIT_COMMIT")
                                  or os.environ.get("MSAPO_SHA") or "unreported"}}
        # Run each phase in a *fresh* 512-MiB process. The production render
        # guard correctly refuses native work if an unrelated large extraction
        # has already consumed its headroom. Never suppress RenderBusy here.
        if part == "sources":
            result["sources"] = _source_cases()
            result["work_order_tables"] = _table_cases()
            result["mixed_source_and_negative"] = _mixed_and_negative()
            result["concurrent_visitor_sources"] = _concurrent()
            result["replacement"] = _replacement()
        else:
            result["native_section"] = _section_preview()
        result["elapsed_seconds"] = round(perf_counter() - started, 3)
        result["python_process_cpu_seconds"] = round(process_time() - cpu_started, 3)
        child_ended = resource.getrusage(resource.RUSAGE_CHILDREN)
        result["child_office_cpu_seconds"] = round(
            child_ended.ru_utime + child_ended.ru_stime
            - child_started.ru_utime - child_started.ru_stime, 3)
        result["rss_bytes_at_end"] = _current_rss()
        try:
            result["cgroup_peak_bytes"] = int(Path("/sys/fs/cgroup/memory.peak").read_text())
        except (OSError, ValueError):
            result["cgroup_peak_bytes"] = None
        result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        result["memory_events_delta"] = {key: value - before_events.get(key, 0)
                                          for key, value in _memory_events().items()}
        result["cpu_stat_delta"] = {key: value - before_cpu_stats.get(key, 0)
                                    for key, value in _cpu_stat().items()}
        assert result["memory_events_delta"].get("oom", 0) == 0
        assert result["memory_events_delta"].get("oom_kill", 0) == 0
        output = Path("/tmp/monthly-preview-latency")
        output.mkdir(parents=True, exist_ok=True)
        (output / ("backend-" + part + ".json")).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        summary = _human_summary(result)
        (output / ("backend-" + part + ".txt")).write_text(summary)
        print(summary, flush=True)
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
