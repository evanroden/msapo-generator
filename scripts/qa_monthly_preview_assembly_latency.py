"""Benchmark native section-preview assembly reuse on the existing synthetic DOCX.

Run inside the same 512 MiB / 0.5 CPU container as the resource acceptance job:
  RESOURCE_REQUIRE_512_MB=1 RESOURCE_REQUIRE_HALF_CPU=1 \\
    python scripts/qa_monthly_preview_assembly_latency.py

Reports serial no-reuse versus owner-scoped same-revision previews on the same
build and fixture. Does not modify production data or claim browser paint.
"""
from __future__ import annotations

from hashlib import sha256
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf as fitz

from scripts.qa_monthly_report_resources import _fixture, _memory, _memory_events
from app import monthly_report_native_layout as native
from app.monthly_report_preview import preview_section
from app import monthly_report_section_assembly_cache as cache


def _cpu_quota():
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        return None if quota == "max" else int(quota) / int(period)
    except (OSError, ValueError, ZeroDivisionError):
        return None


def _geometry(preview):
    with fitz.open(stream=preview.pdf, filetype="pdf") as pdf:
        size = tuple((round(page.rect.width, 3), round(page.rect.height, 3))
                     for page in pdf)
        raster = tuple(sha256(pdf[index].get_pixmap(dpi=120, alpha=False).samples).hexdigest()
                       for index in range(min(2, len(pdf))))
        return {"pages": len(pdf), "page_sizes": size, "first_raster_hashes": raster}


def main():
    limit, _ = _memory()
    cpu = _cpu_quota()
    if os.getenv("RESOURCE_REQUIRE_512_MB") == "1" and (limit is None or limit > 512 * 1024 * 1024):
        raise RuntimeError("Run this probe inside the 512 MiB cgroup.")
    if os.getenv("RESOURCE_REQUIRE_HALF_CPU") == "1" and (cpu is None or cpu > 0.5):
        raise RuntimeError("Run this probe inside the 0.5 CPU quota.")
    events_before = _memory_events()
    result = {"memory_limit_bytes": limit, "cpu_quota": cpu, "runs": {}}
    original = native.build_native_docx
    trace = []

    def timed_native(*args, **kwargs):
        started = monotonic()
        raw = original(*args, **kwargs)
        trace.append((round(monotonic() - started, 3), sha256(raw).hexdigest(), len(raw)))
        return raw

    with tempfile.TemporaryDirectory(prefix="synthetic-native-assembly-") as directory:
        directory = Path(directory)
        os.environ["EPC_DATA_DIR"] = str(directory / "runtime")
        draft, assets, size = _fixture(directory)
        result["fixture_docx_bytes"] = size
        result["fixture_sha256"] = sha256((directory / "synthetic-large-photo-report.docx").read_bytes()).hexdigest()
        asset_versions = tuple(sorted((ref, sha256(raw).digest()) for ref, raw in assets.items()))
        native.build_native_docx = timed_native
        try:
            all_outputs = []
            for phase, owner in (("no_reuse", None), ("owner_scoped", "synthetic-visitor")):
                cache.clear()
                trace.clear()
                samples = []
                with cache.owner_scope(owner, asset_versions):
                    for index in range(3):
                        started = monotonic()
                        preview = preview_section(draft, "activity", assets.__getitem__)
                        geometry = _geometry(preview)
                        samples.append({"run": index + 1, "seconds": round(monotonic() - started, 3)})
                        all_outputs.append(geometry)
                        del preview
                        gc.collect()
                result["runs"][phase] = {
                    "samples": samples,
                    "native_assembly_count": len(trace),
                    "native_seconds": [sample[0] for sample in trace],
                    "native_sha256": [sample[1] for sample in trace],
                    "native_bytes": [sample[2] for sample in trace],
                }
            assert result["runs"]["no_reuse"]["native_assembly_count"] == 3
            assert result["runs"]["owner_scoped"]["native_assembly_count"] == 1
            assert len({entry["pages"] for entry in all_outputs}) == 1
            assert all(output == all_outputs[0] for output in all_outputs), (
                "Section preview page geometry or visible raster bytes changed."
            )
            hashes = (result["runs"]["no_reuse"]["native_sha256"]
                      + result["runs"]["owner_scoped"]["native_sha256"])
            assert len(set(hashes)) == 1, "Uncached native assembly bytes are not deterministic."
            baseline = sorted(sample["seconds"] for sample in result["runs"]["no_reuse"]["samples"][1:])[0:2]
            reuse = sorted(sample["seconds"] for sample in result["runs"]["owner_scoped"]["samples"][1:])[0:2]
            result["median_repeat_no_reuse_seconds"] = round(sum(baseline) / 2, 3)
            result["median_repeat_reuse_seconds"] = round(sum(reuse) / 2, 3)
            result["repeat_savings_seconds"] = round(
                result["median_repeat_no_reuse_seconds"] - result["median_repeat_reuse_seconds"], 3
            )
        finally:
            native.build_native_docx = original
            cache.clear()
    events_after = _memory_events()
    result["oom_events_delta"] = events_after.get("oom", 0) - events_before.get("oom", 0)
    assert result["oom_events_delta"] == 0
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
