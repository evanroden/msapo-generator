"""A35 standalone synthetic final-conversion benchmark.

Runs inside the production image; no client data, network, saved report or
browser authentication is used. The no-owner control mirrors main's repeated
LibreOffice conversion without asserting byte-level PDF nondeterminism.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
from tempfile import TemporaryDirectory
from time import monotonic, process_time

import pymupdf as fitz

from app import monthly_report_docx as word
from app import monthly_report_final_conversion_cache as cache
from app import monthly_report_render_jobs as jobs
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles


def _cgroup():
    root = Path("/sys/fs/cgroup")
    fields = ("memory.max", "memory.current", "memory.peak", "cpu.max", "cpu.stat", "memory.events")
    result = {}
    for field in fields:
        try:
            result[field] = (root / field).read_text().strip()
        except OSError:
            result[field] = None
    return result


def _cpu_seconds():
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return process_time() + children.ru_utime + children.ru_stime


def _geometry(data):
    with fitz.open(stream=data, filetype="pdf") as document:
        return [tuple(page.rect) for page in document]


def main():
    with TemporaryDirectory(prefix="a35-synthetic-") as directory:
        os.environ["EPC_DATA_DIR"] = directory
        word.pdf_converter.OUTPUT_DIR = Path(directory)
        draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
        original = jobs.convert_to_pdf
        converted = []
        def measured(path, **kwargs):
            converted.append(sha256(path.read_bytes()).hexdigest())
            return original(path, **kwargs)
        jobs.convert_to_pdf = measured
        records = []
        def run(name, current, *, owner=None, assets=()):
            before_wall, before_cpu = monotonic(), _cpu_seconds()
            package = word.generate_report(
                current, acknowledged_fingerprint=current.fingerprint,
                reuse_owner=owner, reuse_asset_versions=assets)
            elapsed = monotonic() - before_wall
            cpu = _cpu_seconds() - before_cpu
            if not package.pdf:
                raise RuntimeError(name + ": PDF failed: " + package.pdf_error)
            records.append({
                "scenario": name, "wall_seconds": elapsed, "cpu_seconds": cpu,
                "rss_peak_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "libreoffice_calls_total": len(converted),
                "docx_sha256": sha256(package.docx).hexdigest(),
                "pdf_sha256": sha256(package.pdf).hexdigest(),
                "pdf_geometry_points": _geometry(package.pdf),
                "memory_current": _cgroup()["memory.current"],
            })
            return package

        uncached_first = run("uncached-control-1", draft)
        uncached_second = run("uncached-control-2", draft)
        assert len(converted) == 2
        assert uncached_first.docx == uncached_second.docx
        assert _geometry(uncached_first.pdf) == _geometry(uncached_second.pdf)
        cache.clear()

        cold = run("scoped-cold", draft, owner="a35-visitor")
        warm = run("scoped-warm", draft, owner="a35-visitor")
        assert len(converted) == 3, "Warm unchanged revision reconverted"
        assert cold.docx == warm.docx and cold.pdf == warm.pdf

        edited = replace(draft, blocks=tuple(
            replace(block, text=block.text + " Confirmed synthetic Activity entry.")
            if block.key == "demo_activity" else block for block in draft.blocks))
        changed = run("changed-activity", edited, owner="a35-visitor")
        assert len(converted) == 4 and changed.docx != cold.docx

        logo = run("changed-unsaved-logo", draft, owner="a35-visitor",
                   assets=(("logo.png", sha256(b"synthetic changed logo bytes").digest()),))
        assert len(converted) == 5 and logo.pdf
        assert _geometry(logo.pdf) == _geometry(cold.pdf)

        result = {
            "synthetic_only": True,
            "authentic_source_acceptance": False,
            "role": "isolated production image, real LibreOffice",
            "scope": "the same draft without owner, with scoped owner, and after Activity/logo edits",
            "limits": _cgroup(),
            "measurements": records,
            "uncached_repeat_wall_seconds": records[1]["wall_seconds"],
            "warm_repeat_wall_seconds": records[3]["wall_seconds"],
        }
        out = Path(os.getenv("A35_BENCHMARK_OUTPUT", "/tmp/a35-final-conversion.json"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
