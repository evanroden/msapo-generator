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


if __name__ == "__main__":
    main()
