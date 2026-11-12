#!/usr/bin/env python3
"""Reproducible, synthetic preview-cache cold/warm benchmark (MR-021/#491).

Run: python scripts/qa_monthly_preview_warm_latency.py
The benchmark deliberately measures *raster retrieval*, not source upload,
initial LibreOffice conversion, served latency or device/browser performance.
Every run prints the workload, per-run timings, PDF opens, cache resource use
and two-byte/source revisions; time thresholds are NOT asserted across hosts.
"""
from __future__ import annotations

from argparse import ArgumentParser
from io import BytesIO
import json
from statistics import median
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image

from app import monthly_report_preview_store as store


def synthetic_pdf(pages, label):
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=612, height=792)
            page.insert_text((72, 72), f"SYNTHETIC {label} source page {index + 1}")
            page.insert_text((72, 96), "Verified preview cache benchmark. " * 4)
        return document.tobytes()


def benchmark(pages, repeats):
    raw = synthetic_pdf(pages, "baseline")
    changed = synthetic_pdf(pages, "changed-source")
    cache = store.PreviewStore()
    try:
        owner = "synthetic-preview-benchmark"
        ticket = cache.put(owner, SimpleNamespace(pdf=raw, initial_page=0))
        with patch.object(store.fitz, "open", wraps=store.fitz.open) as opened:
            begin = perf_counter()
            cold = cache.pages(owner, ticket, (0, 1), dpi=120)
            cold_ms = (perf_counter() - begin) * 1000
            cold_opens = opened.call_count
            opened.reset_mock()
            warm_ms = []
            for _ in range(repeats):
                begin = perf_counter()
                again = cache.pages(owner, ticket, (0, 1), dpi=120)
                warm_ms.append((perf_counter() - begin) * 1000)
                assert cold == again
            warm_opens = opened.call_count
            # Register the replacement under its own ticket; put() validates
            # the PDF and is not a raster page request. Count page opens only.
            new_ticket = cache.put(owner, SimpleNamespace(pdf=changed, initial_page=0))
            opened.reset_mock()
            begin = perf_counter()
            new = cache.pages(owner, new_ticket, (0, 1), dpi=120)
            invalidated_ms = (perf_counter() - begin) * 1000
            replacement_opens = opened.call_count
        assert ticket.key != new_ticket.key and cold != new
        assert cold_opens == replacement_opens == 1 and warm_opens == 0
        dimensions = []
        for index, image in cold:
            with Image.open(BytesIO(image)) as decoded:
                assert decoded.format == "JPEG"
                assert decoded.width == 1020 and decoded.height == 1320
                dimensions.append((index, decoded.width, decoded.height))
        cache_stats = cache.stats()
        return {
            "pages": pages, "pdf_input_bytes": len(raw),
            "cold_raster_ms": round(cold_ms, 3),
            "warm_raster_median_ms": round(median(warm_ms), 3),
            "warm_raster_max_ms": round(max(warm_ms), 3),
            "warm_requests": repeats,
            "cold_pdf_opens": cold_opens, "warm_pdf_opens": warm_opens,
            "source_replacement_pdf_opens": replacement_opens,
            "source_replacement_ms": round(invalidated_ms, 3),
            "page_images": dimensions,
            "cache": cache_stats,
        }
    finally:
        cache.close()


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, nargs="*", default=[6, 32, 96])
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if args.repeats < 2 or not args.pages or any(
            type(pages) is not int or pages < 2 or pages > 150 for pages in args.pages):
        parser.error("Choose 2–150 pages and at least two warm repeats.")
    import platform
    result = {
        "workload": "Synthetic text PDFs, two viewport pages, 120 DPI, cold/warm and changed source",
        "environment": {"python": platform.python_version(),
                        "platform": platform.platform(),
                        "pymupdf": getattr(fitz, "VersionBind", "unknown")},
        "target": "0 redundant PDF opens for fully cached viewport JPEGs; cold/miss remains 1",
        "results": [benchmark(n, args.repeats) for n in args.pages],
        "limitations": "No served initial-preview, browser, upload or LibreOffice conversion latency measured.",
    }
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
