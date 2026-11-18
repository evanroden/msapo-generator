"""Export synthetic report artifacts for exact-commit CI and human page review.

No client records, network reader, secrets or live storage are accessed.
The artifacts are evidence of our LibreOffice path, not authored Word fidelity.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter, process_time
import resource

from app.monthly_latency_spans import capture_spans

import pymupdf as fitz

from app.monthly_report_docx import generate_report
from tests.test_monthly_report_full_synthetic_output import approved_synthetic_draft


class _SyntheticEnvironment:
    @staticmethod
    def setenv(name, value):
        os.environ[name] = value


def main() -> None:
    output = Path("test-artifacts/monthly-synthetic")
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="enfra-synthetic-ci-") as tmp:
        draft = approved_synthetic_draft(_SyntheticEnvironment(), Path(tmp))
        wall_start, cpu_start = perf_counter(), process_time()
        with capture_spans() as spans:
            result = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
        export_seconds, export_cpu = perf_counter() - wall_start, process_time() - cpu_start
        if not result.docx or not result.pdf:
            raise RuntimeError("Both actual synthetic report formats are required: " + str(result.pdf_error))
        files = {}
        for name, raw in (("SYNTHETIC-Word-report.docx", result.docx),
                          ("SYNTHETIC-Application-report.pdf", result.pdf)):
            (output / name).write_bytes(raw)
            files[name] = {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}
        with fitz.open(stream=result.pdf, filetype="pdf") as document:
            pages = len(document)
            if pages < 4:
                raise ValueError("Synthetic report lost required pages.")
            files["SYNTHETIC-Application-report.pdf"]["pages"] = pages
        manifest = {
            "synthetic_only": True,
            "authenticated_reference": False,
            "renderer": "LibreOffice in the GitHub Actions runner",
            "scope": "invented work order and price-redacted proposal tables only",
            "expected_work_orders": {"total": 3, "completed": 2, "open": 1, "closure": "66.7%"},
            "files": files,
            "performance": {
                "boundary": "single uncapped CI synthetic final report generation, not browser/production latency",
                "total_wall_seconds": round(export_seconds, 4),
                "python_cpu_seconds": round(export_cpu, 4),
                "peak_python_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                "critical_path_spans": list(spans),
                "exact_build_sha": os.environ.get("MSAPO_SHA") or os.environ.get("GITHUB_SHA") or "unreported",
            },
            "note": "Inspect every page before use. Does not certify Microsoft Word or original-client layout."
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        from scripts.qa_monthly_contact_outputs import export_contact_outputs
        export_contact_outputs(output / "contact-headers")
        from scripts.qa_source_page_outputs import export_source_page_outputs
        export_source_page_outputs(output / "source-pages")

        # A17: separate current-operator all-section control. Both runs use
        # the same immutable 12-section draft and source bytes; warm means a
        # second call in this process, not a served-browser cache claim.
        from tests.test_monthly_report_a17_complete_export import (
            golden_synthetic_draft, audit_golden_package,
        )
        golden, assets = golden_synthetic_draft(_SyntheticEnvironment(), Path(tmp) / "a17")
        asset_hashes = {key: sha256(value).hexdigest() for key, value in assets.items()}
        observed = []
        first_manifest = None
        for phase in ("cold", "warm"):
            start_wall, start_cpu = perf_counter(), process_time()
            produced = generate_report(
                golden, acknowledged_fingerprint=golden.fingerprint,
                asset_loader=assets.__getitem__,
            )
            elapsed_wall = perf_counter() - start_wall
            elapsed_cpu = process_time() - start_cpu
            current_manifest = audit_golden_package(produced, golden)
            if first_manifest is None:
                first_manifest = current_manifest
                (output / "A17-SYNTHETIC-12-section.docx").write_bytes(produced.docx)
                (output / "A17-SYNTHETIC-12-section.pdf").write_bytes(produced.pdf)
            else:
                if (current_manifest["word"]["sha256"] != first_manifest["word"]["sha256"]
                        or current_manifest["pdf"]["page_raster_sha256_20pct"]
                        != first_manifest["pdf"]["page_raster_sha256_20pct"]):
                    raise RuntimeError("A17: cold/warm output parts or page rasters differ.")
            observed.append({
                "phase": phase, "wall_seconds": round(elapsed_wall, 3),
                "process_cpu_seconds": round(elapsed_cpu, 3),
                "docx_sha256": current_manifest["word"]["sha256"],
                "pdf_sha256": current_manifest["pdf"]["sha256"],
                "page_count": current_manifest["pdf"]["pages"],
                "reported_complete": bool(produced.pdf and not produced.pdf_error),
            })
        assert {key: sha256(value).hexdigest() for key, value in assets.items()} == asset_hashes
        try:
            maxrss_mib = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)
        except (ImportError, AttributeError):
            maxrss_mib = None
        first_manifest["runtime"] = {
            "workload": "same synthetic 12-section draft, two sequential in-process exports",
            "conditions": "GitHub Actions runner; not a 512 MiB/0.5 CPU constrained acceptance run",
            "max_process_rss_mib": maxrss_mib,
            "queue_wait_seconds": None,
            "comparisons": observed,
        }
        (output / "A17-SYNTHETIC-12-section-manifest.json").write_text(
            json.dumps(first_manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
