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
from time import perf_counter, process_time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document
from docx.shared import Inches
from PIL import Image
import pymupdf as fitz

from app import monthly_report_sources as sources
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


def _image(profile, content, number=None):
    if number is None:
        number = (content.image_items[0][0] if content.image_items else 1)
    image = sources.page_image(profile, content, number, preview=True)
    uri = source_thumbnail_uri(image)
    assert uri.startswith("data:image/") and len(uri) > 50
    assert 0 < image.width <= 1056 and 0 < image.height <= 1056
    return {"hash": sha256(image.data).hexdigest(), "width": image.width,
            "height": image.height, "bytes": len(image.data), "number": number}


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
        for number in range(5):
            profile = _profile(f"qa491-{case}-{number}")
            start = perf_counter()
            content, extras = sources.ingest(profile, "invented" + suffix, raw)
            ingest_at = perf_counter()
            thumb = _image(profile, content)
            finished = perf_counter()
            assert extras == ()
            timings["cold_ingest"].append(ingest_at - start)
            timings["cold_thumbnail"].append(finished - ingest_at)
            timings["cold_total"].append(finished - start)
            warm_start = perf_counter()
            warm, extras = sources.ingest(profile, "invented" + suffix, raw)
            warm_ingest_at = perf_counter()
            warm_thumb = _image(profile, warm)
            warm_finished = perf_counter()
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
        results.append({"workload": case, "source_bytes": len(raw),
                        "fixture_sha256": sha256(raw).hexdigest(),
                        "samples": {key: _summary(values) for key, values in timings.items()},
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
    def counted(*args, **kwargs):
        started = perf_counter()
        raw = native_original(*args, **kwargs)
        calls.append({"seconds": perf_counter() - started, "sha256": sha256(raw).hexdigest()})
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
                        started = perf_counter()
                        preview = preview_section(draft, "activity", assets.__getitem__)
                        converted_at = perf_counter()
                        ticket = store.put(owner or "qa491-control", preview)
                        inserted_at = perf_counter()
                        rasters = store.pages(owner or "qa491-control", ticket, (0, 1))
                        finished = perf_counter()
                        assert rasters and len(rasters) == 2
                        assert all(data.startswith(b"\xff\xd8") for _, data in rasters)
                        geometry = {"pages": ticket.pages,
                                    "sizes": tuple((round(w, 2), round(h, 2)) for w, h in ticket.sizes),
                                    "rasters": tuple(sha256(data).hexdigest() for _, data in rasters)}
                        controls.append(geometry)
                        measures.append({"run": index + 1,
                                         "assembly_conversion_seconds": round(converted_at - started, 4),
                                         "pdf_ticket_seconds": round(inserted_at - converted_at, 4),
                                         "first_two_rasters_seconds": round(finished - inserted_at, 4),
                                         "total_seconds": round(finished - started, 4)})
                        store.discard(owner or "qa491-control", ticket)
                        del preview, rasters
                        gc.collect()
                result["runs"][name] = {"samples": measures, "native_assemblies": len(calls),
                                        "native_assembly_seconds": [round(c["seconds"], 4) for c in calls],
                                        "native_docx_sha256": [c["sha256"] for c in calls]}
            assert result["runs"]["uncached_control"]["native_assemblies"] == 3
            assert result["runs"]["owner_scoped_reuse"]["native_assemblies"] == 1
            assert all(item == controls[0] for item in controls)
            assert len(set(result["runs"]["uncached_control"]["native_docx_sha256"]
                           + result["runs"]["owner_scoped_reuse"]["native_docx_sha256"])) == 1
            result["output_equivalence"] = controls[0]
            result["store_budgets"] = store.stats()
        finally:
            native.build_native_docx = native_original
            assembly_cache.clear()
            store.close()
    return result


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
    with tempfile.TemporaryDirectory(prefix="qa491-synthetic-") as temporary:
        os.environ["EPC_DATA_DIR"] = str(Path(temporary) / "runtime")
        # All source/draft paths are synthetic; no durable or shared client data.
        started = perf_counter()
        cpu_started = process_time()
        child_started = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {"boundary": "server_received_bytes_to_first_raster_delivery",
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
        assert result["memory_events_delta"].get("oom", 0) == 0
        assert result["memory_events_delta"].get("oom_kill", 0) == 0
        output = Path("/tmp/monthly-preview-latency")
        output.mkdir(parents=True, exist_ok=True)
        (output / ("backend-" + part + ".json")).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
