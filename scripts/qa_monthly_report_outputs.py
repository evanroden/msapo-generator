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

import fitz

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
        result = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
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
            "note": "Inspect every page before use. Does not certify Microsoft Word or original-client layout."
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        from scripts.qa_monthly_contact_outputs import export_contact_outputs
        export_contact_outputs(output / "contact-headers")


if __name__ == "__main__":
    main()
