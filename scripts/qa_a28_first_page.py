"""A28 synthetic PDF first-request benchmark; does not invoke Word or browser.

Compare the prior section UI's default page-zero read, the corrected selected
page, and the hypothetical eager whole-document thumbnail inventory. All modes
use the production PreviewStore, the same PDFs/DPI, and isolated cold stores.
"""
import hashlib
import json
import os
from pathlib import Path
import resource
from statistics import median
from time import perf_counter, process_time
from types import SimpleNamespace

import pymupdf as fitz

from app.monthly_report_preview_store import PreviewStore


def fixture(count):
    with fitz.open() as doc:
        for index in range(count):
            page = doc.new_page(width=612, height=792)
            page.insert_text((48, 64), f"A28 PUBLIC SYNTHETIC {count} PAGE {index+1}")
            page.draw_rect(fitz.Rect(40, 100, 72+index % 17, 130), color=(0, 0, 0))
        return doc.tobytes()


def benchmark(raw, count, mode):
    selected = count - 1
    store = PreviewStore()
    original_sha = hashlib.sha256(raw).hexdigest()
    wall, cpu = perf_counter(), process_time()
    try:
        ticket = store.put("a28-synthetic-owner", SimpleNamespace(pdf=raw, initial_page=selected))
        if mode == "prior_default":
            store.pages("a28-synthetic-owner", ticket, (0,), dpi=96)
            assert selected != 0
        elif mode == "eager_inventory":
            for index in range(count):
                store.pages("a28-synthetic-owner", ticket, (index,), dpi=96)
        elif mode != "selected_first":
            raise ValueError("Unknown benchmark route")
        selected_image = store.pages("a28-synthetic-owner", ticket, (selected,), dpi=96)[0][1]
        first_ms = (perf_counter() - wall) * 1000
        first_cpu_ms = (process_time() - cpu) * 1000
        warm_start = perf_counter()
        assert store.pages("a28-synthetic-owner", ticket, (selected,), dpi=96)[0][1] == selected_image
        warm_ms = (perf_counter() - warm_start) * 1000
        for index in range(count):
            pages = store.pages("a28-synthetic-owner", ticket, (index,), dpi=96)
            assert pages and pages[0][0] == index
        full_ms = (perf_counter() - wall) * 1000
        full_cpu_ms = (process_time() - cpu) * 1000
        assert hashlib.sha256(raw).hexdigest() == original_sha
        return {
            "pages": count, "mode": mode,
            "first_selected_raster_wall_ms": round(first_ms, 3),
            "first_selected_raster_cpu_ms": round(first_cpu_ms, 3),
            "full_raster_wall_ms": round(full_ms, 3),
            "full_raster_cpu_ms": round(full_cpu_ms, 3),
            "warm_selected_wall_ms": round(warm_ms, 3),
            "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "queue_ms": None,  # Direct store-only workload, no queue admission.
            "original_pdf_sha256": hashlib.sha256(raw).hexdigest(),
            "selected_jpeg_sha256": hashlib.sha256(selected_image).hexdigest(),
            "selected_index": selected,
            "ticket_pages": ticket.pages,
            "ticket_initial_page": ticket.initial_page,
            "raster_cache_entries": store.stats()["raster_entries"],
        }
    finally:
        store.close()


def main():
    rows = []
    for count in (2, 24, 120):
        raw = fixture(count)
        for repeat in range(2):
            for mode in ("prior_default", "selected_first", "eager_inventory"):
                row = benchmark(raw, count, mode)
                row["repeat"] = repeat
                rows.append(row)
        group = [r for r in rows if r["pages"] == count]
        assert len({r["selected_jpeg_sha256"] for r in group}) == 1
        assert len({r["original_pdf_sha256"] for r in group}) == 1
        assert all(r["ticket_pages"] == count and r["selected_index"] == count-1 for r in group)
        figures = {mode: median(r["first_selected_raster_wall_ms"] for r in group
                                if r["mode"] == mode)
                   for mode in ("prior_default", "selected_first", "eager_inventory")}
        print(f"{count} pages, median first selected JPEG (includes private ticket put) ms: "
              + ", ".join(f"{mode}={value:.1f}" for mode, value in figures.items()), flush=True)
    evidence = {
        "sha": os.getenv("A28_HEAD_SHA", "unprovided"),
        "environment": {
            "memory_mib": os.getenv("A28_MEMORY_MIB", "not-cgroup-verified"),
            "cpu_fraction": os.getenv("A28_CPU_FRACTION", "not-cgroup-verified"),
            "pymupdf": fitz.VersionBind,
        },
        "method": "synchronous synthetic PreviewStore put plus JPEG decode, no browser first paint or LibreOffice",
        "samples": rows,
    }
    output = Path(os.getenv("A28_EVIDENCE_OUT", "/tmp/a28-first-page.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"saved {output}", flush=True)


if __name__ == "__main__":
    main()
