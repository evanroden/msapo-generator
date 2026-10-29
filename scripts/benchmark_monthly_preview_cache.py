"""Synthetic PreviewStore cold-raster/warm-read measurements; no live data or SLA.

Run the same script on each candidate and compare fixture/raster hashes and
module identity. 'Cold' means the requested raster is absent, NOT cold disk,
upload, queue, Word conversion or end-to-end browser latency. Timings are
observations, never a flaky CI gate. Memory is process-wide peak RSS on Linux.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import statistics
import sys
from time import perf_counter, process_time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf as fitz
from app import monthly_report_preview_store as module


def fixture(pages, marks):
    """Mixed-orientation pages with separate vector streams and unique text."""
    with fitz.open() as pdf:
        for index in range(pages):
            page = pdf.new_page(width=612, height=792)
            page.insert_text((30, 30), f"Synthetic preview benchmark - page {index + 1}")
            for mark in range(marks):
                x, y = 30 + (mark % 12) * 45, 55 + (mark // 12) * 30
                page.draw_rect(fitz.Rect(x, y, x + 30, y + 18),
                               color=(0.1, 0.3, 0.5), fill=(0.7, 0.8, 0.9))
            if index % 3 == 1:
                page.set_rotation(90)
        # Stable fixture bytes let separate baseline/candidate runs be compared.
        return pdf.tobytes(no_new_id=True)


def distribution(values):
    ordered = sorted(values)
    return {"samples": len(values), "median_ms": statistics.median(ordered),
            "p95_ms": ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)],
            "min_ms": ordered[0], "max_ms": ordered[-1]}


def measure(pages, marks, *, repeats=7, warm_reads=60):
    if not 2 <= pages <= 120 or not 1 <= marks <= 120:
        raise ValueError("Synthetic workload must stay within its page/mark limits.")
    if not 1 <= repeats <= 20 or not 1 <= warm_reads <= 200:
        raise ValueError("Choose bounded repeat and warm-read counts.")
    raw = fixture(pages, marks)
    cold_wall, warm_wall, cold_cpu, warm_cpu = [], [], [], []
    cold_opens = warm_opens = 0
    raster_hashes = None
    cache_stats = None
    for _ in range(repeats):
        store = module.PreviewStore()
        try:
            ticket = store.put("synthetic-benchmark", SimpleNamespace(pdf=raw))
            calls = 0
            real_open = module.fitz.open
            def opened(*args, **kwargs):
                nonlocal calls
                calls += 1
                return real_open(*args, **kwargs)
            with patch.object(module.fitz, "open", side_effect=opened):
                before_cpu, before_wall = process_time(), perf_counter()
                expected = store.pages("synthetic-benchmark", ticket, (0, pages - 1), dpi=120)
                cold_wall.append((perf_counter() - before_wall) * 1000)
                cold_cpu.append((process_time() - before_cpu) * 1000)
                cold_opens += calls
                calls = 0
                for _ in range(warm_reads):
                    before_cpu, before_wall = process_time(), perf_counter()
                    actual = store.pages("synthetic-benchmark", ticket, (0, pages - 1), dpi=120)
                    warm_wall.append((perf_counter() - before_wall) * 1000)
                    warm_cpu.append((process_time() - before_cpu) * 1000)
                    if actual != expected:
                        raise AssertionError("Warm preview changed the requested raster bytes/order.")
                warm_opens += calls
            hashes = [hashlib.sha256(image).hexdigest() for _, image in expected]
            if raster_hashes is not None and hashes != raster_hashes:
                raise AssertionError("Repeated cold rendering changed the synthetic raster bytes.")
            raster_hashes = hashes
            cache_stats = store.stats()
            if (cache_stats['pdf_bytes'] > store.disk_limit
                    or cache_stats['raster_bytes'] > store.raster_limit):
                raise AssertionError("Preview exceeded its existing cache budget.")
        finally:
            store.close()
    return {"pages": pages, "vector_marks_per_page": marks, "pdf_bytes": len(raw),
            "pdf_sha256": hashlib.sha256(raw).hexdigest(), "dpi": 120,
            "indexes": [0, pages - 1], "cold_wall": distribution(cold_wall),
            "warm_wall": distribution(warm_wall), "cold_cpu": distribution(cold_cpu),
            "warm_cpu": distribution(warm_cpu), "cold_pdf_opens": cold_opens,
            "warm_pdf_opens": warm_opens, "raster_sha256": raster_hashes,
            "cache_stats": cache_stats,
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if sys.platform.startswith('linux') else 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warm-reads", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20 or not 1 <= args.warm_reads <= 200:
        parser.error("repeats must be 1..20; warm-reads must be 1..200")
    implementation = Path(module.__file__).read_bytes()
    result = {"schema": 1, "scope": "Synthetic local raster cache only; not end-to-end latency",
              "python": platform.python_version(), "pymupdf": fitz.VersionBind,
              "platform": platform.system() + ' ' + platform.machine(),
              "store_sha256": hashlib.sha256(implementation).hexdigest(),
              "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "repeats": args.repeats, "warm_reads_per_repeat": args.warm_reads,
              "workloads": [measure(pages, marks, repeats=args.repeats, warm_reads=args.warm_reads)
                            for pages, marks in ((2, 8), (24, 80), (120, 120))]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
