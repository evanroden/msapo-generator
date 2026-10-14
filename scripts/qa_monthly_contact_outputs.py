"""Retain real synthetic contact outputs, including an actual overflow case.

No owner files, standing-data stores or outward business actions are used.
Native here means the native-layout code path with invented source geometry,
not approval of the installed ENFRA master or Microsoft Word rendering.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from app import pdf_converter
from app.monthly_report_docx import _build_docx
from app.monthly_report_native_layout import build_native_docx
from tests.test_monthly_report_contact_headers import (
    HEADINGS, assert_contact_pdf, assert_contact_table, contact_draft,
    contact_rows, native_contact_source,
)


def export_contact_outputs(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    with TemporaryDirectory(prefix="synthetic-contact-output-") as temporary:
        temporary = Path(temporary)
        native_source = native_contact_source(temporary / "native.docx")
        for native in (False, True):
            for count in (2, 48):
                name = f"SYNTHETIC-{'native' if native else 'generic'}-contacts-{count}"
                rows = contact_rows(count, long=count == 48)
                value = contact_draft(count, long=count == 48, chart=not native)
                raw = (build_native_docx(value, native_source, master=True)
                       if native else _build_docx(value))
                assert_contact_table(raw, rows)
                source = temporary / (name + ".docx")
                source.write_bytes(raw)
                rendered = pdf_converter.convert_to_pdf(source)
                try:
                    pdf = rendered.read_bytes()
                    pages, contact_pages = assert_contact_pdf(pdf, rows)
                finally:
                    rendered.unlink(missing_ok=True)
                for suffix, content in (("docx", raw), ("pdf", pdf)):
                    filename = name + "." + suffix
                    (output / filename).write_bytes(content)
                    files[filename] = {"bytes": len(content), "sha256": sha256(content).hexdigest(),
                                       "contacts": count, "native_writer": native}
                    if suffix == "pdf":
                        files[filename].update(pages=pages, contact_pages=[i + 1 for i in contact_pages])
    checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest = {
        "synthetic_only": True,
        "tested_checkout": checkout,
        "github_head_ref": os.environ.get("GITHUB_HEAD_REF", ""),
        "headings": HEADINGS,
        "renderer": "LibreOffice via app.pdf_converter in the CI runner",
        "files": files,
        "checks": ["actual schema row", "all people intact and unique", "only real header repeats",
                   "multi-page PDF contains all five labels on each contact page"],
        "limits": ["owner native-master geometry not accepted", "not Microsoft Word acceptance",
                   "visual inspection remains separate from structural and PDF text assertions"],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    export_contact_outputs(Path("test-artifacts/monthly-synthetic/contact-headers"))
