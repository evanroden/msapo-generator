"""Reproducible 1/2/120-page Review raster control vs private-ticket shortcut.

This isolates post-conversion PDF processing. It does NOT measure Word
conversion or an authentic/served browser first paint. Synthetic pages only.
"""
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import resource
import sys
from time import perf_counter, process_time

import pymupdf as fitz
from PIL import Image

# Direct script invocation starts sys.path at scripts/, not the repository root.
# Match the existing monthly benchmark's standalone import contract.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.image_open import open_image
from app.monthly_report_preview import ReportPreview
from app.monthly_report_preview_store import PreviewStore
from app.monthly_report_preview_ticket import private_ticket_pdf

LIMIT = 25 * 1024 * 1024


def source(count):
    with fitz.open() as pdf:
        for index in range(count):
            page = pdf.new_page(width=612, height=792)
            page.insert_text((64, 72), f"SYNTHETIC PAGE {index + 1:03d}")
            for j in range(18):
                page.insert_text((64, 100 + j * 26), f"Synthetic report row {index}:{j}", fontsize=11)
        return pdf.tobytes(garbage=3, deflate=True)


def flatten_original(raw):
    """Same eager raster/JPEG/watermark loop as the current-main control."""
    output = fitz.open()
    try:
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            for source_page in pdf:
                pix = source_page.get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                buffer = BytesIO()
                image.save(buffer, "JPEG", quality=65, optimize=True)
                page = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
                page.insert_image(page.rect, stream=buffer.getvalue())
                point = fitz.Point(page.rect.width * .18, page.rect.height * .63)
                page.insert_text(point, "DRAFT - REVIEW ONLY", fontsize=32,
                                 color=(.7, .08, .08), fill_opacity=.4,
                                 morph=(point, fitz.Matrix(35)))
                page.insert_text((25, 22), "DRAFT PREVIEW - NOT A FINISHED CLIENT REPORT",
                                 fontsize=9, color=(.65, .05, .05))
        return output.tobytes(garbage=3, deflate=True)
    finally:
        output.close()


def ticket_only(raw):
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        return private_ticket_pdf(pdf, source_bytes=len(raw), max_pages=150, max_bytes=LIMIT)


def sample(raw, count, route, repetition):
    started = perf_counter()
    cpu = process_time()
    result = flatten_original(raw) if route == "eager_baseline" else ticket_only(raw)
    processed_ms = (perf_counter() - started) * 1000
    cpu_ms = (process_time() - cpu) * 1000
    assert result is not None and len(result) <= LIMIT
    with fitz.open(stream=result, filetype="pdf") as pdf:
        assert len(pdf) == count
        geometry = [tuple(round(x, 4) for x in p.rect) for p in pdf]
        assert all(rect == (0.0, 0.0, 612.0, 792.0) for rect in geometry)
        geometry_hash = sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest()
    store = PreviewStore()
    try:
        started = perf_counter()
        ticket = store.put("synthetic-owner", ReportPreview(result, count, str(count), "Synthetic"))
        put_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        visible = store.pages("synthetic-owner", ticket, tuple(range(min(count, 2))), dpi=120)
        first_two_ms = (perf_counter() - started) * 1000
        assert len(visible) == min(count, 2)
        started = perf_counter()
        image = open_image(BytesIO(visible[0][1]), formats=("JPEG",))
        image.load()
        first_decode_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        assert store.pages("synthetic-owner", ticket, (0,), dpi=120)
        warm_pixel_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        if count > 2:
            assert store.pages("synthetic-owner", ticket, (count - 1,), dpi=120)
        later_ms = (perf_counter() - started) * 1000
        retained = store.stats()
    finally:
        store.close()
    return {
        "route": route, "repetition": repetition, "pages": count,
        "processing_wall_ms": round(processed_ms, 2),
        "processing_cpu_ms": round(cpu_ms, 2),
        "store_put_ms": round(put_ms, 2),
        "first_two_page_raster_ms": round(first_two_ms, 2),
        "first_jpeg_pillow_decode_ms_not_browser": round(first_decode_ms, 2),
        "warm_first_page_store_ms": round(warm_pixel_ms, 2),
        "later_page_raster_ms": round(later_ms, 2),
        "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "ticket_entries": retained["pdf_entries"],
        "raster_entries": retained["raster_entries"],
        "pdf_sha256": sha256(result).hexdigest(),
        "geometry_sha256": geometry_hash,
        "pending_jobs": 0,
        "pending_jobs_scope": "standalone algorithm benchmark, not live scheduler",
    }


def main():
    rows = []
    for count in (1, 2, 120):
        raw = source(count)
        for repetition in (1, 2):
            for route in ("eager_baseline", "private_ticket"):
                rows.append(sample(raw, count, route, repetition))
    record = {
        "mode": "synthetic post-conversion comparison, not a full build/browser acceptance",
        "python": sys.version.split()[0],
        "commit": os.environ.get("MSAPO_SHA", "local-standalone"),
        "limits": {"cpu_fraction": os.environ.get("QA_CPU_FRACTION", "not enforced"),
                   "memory_mib": os.environ.get("QA_MEMORY_MIB", "not enforced")},
        "rows": rows,
    }
    folder = Path(os.environ.get("QA_A04_OUTPUT", "/tmp/monthly-review-ticket"))
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "benchmark.json"
    dest.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(dest), "records": len(rows),
                      "pages": [1, 2, 120], "max_rss_kib": max(row["peak_process_rss_kib"] for row in rows)}))


if __name__ == "__main__":
    main()
