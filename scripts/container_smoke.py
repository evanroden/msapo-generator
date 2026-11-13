"""Synthetic full-image acceptance: three workflows, DOCX, PDF and expense Calc.

Run inside a built image. Uses no customer inputs, credentials or network calls.
Output is safe JSON with structure/version evidence, never document content.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER_DOCX = "SYNTHETIC MSAPO DOCX PROBE"
MARKER_EXPENSE = "SYNTHETIC EXPENSE CONVERSION PROBE"
WORKFLOW_IMPORTS = ("app.web_ui", "app.expense_ui", "app.monthly_report_ui")


def _cmd(args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def _convert(source: Path, output: Path, profile: Path) -> Path:
    # A unique LO profile prevents cross-test locks and leaves the main app alone.
    _cmd(["libreoffice", f"-env:UserInstallation={profile.as_uri()}",
          "--headless", "--convert-to", "pdf", "--outdir", str(output), str(source)])
    target = output / f"{source.stem}.pdf"
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("synthetic LibreOffice conversion did not create a PDF")
    return target


def render_synthetic():
    from docx import Document
    from openpyxl import Workbook
    import pymupdf as fitz

    with tempfile.TemporaryDirectory(prefix="msapo-image-smoke-") as folder:
        root = Path(folder)
        source = root / "synthetic.docx"
        document = Document()
        document.add_paragraph(MARKER_DOCX)
        document.save(source)
        workbook_path = root / "synthetic-expense.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "Synthetic expense"
        sheet["A1"] = MARKER_EXPENSE
        book.save(workbook_path)

        results = {}
        for label, path, marker in (
            ("word", source, MARKER_DOCX),
            ("expense_calc", workbook_path, MARKER_EXPENSE),
        ):
            pdf = _convert(path, root, root / f"profile-{label}")
            with fitz.open(pdf) as reader:
                text = " ".join(page.get_text() for page in reader)
                pages = len(reader)
            if marker not in re.sub(r"\s+", " ", text):
                raise RuntimeError(f"{label}: synthetic marker missing from converted PDF")
            results[label] = {"pages": pages, "extracted_text_matches": True}
        return results


def audit(*, render_only=False):
    report = {
        "synthetic_only": True,
        "architecture": platform.machine(),
        "operating_system": platform.system(),
        "python": platform.python_version(),
        "libreoffice": _cmd(["libreoffice", "--version"]),
        "font_families": {},
    }
    for family in ("Arial", "Calibri", "Cambria"):
        # Basename only: never publish host-private paths.
        report["font_families"][family] = Path(_cmd(
            ["fc-match", "--format=%{file}", family]
        )).name
    if not render_only:
        imported = {}
        for name in WORKFLOW_IMPORTS:
            module = importlib.import_module(name)
            imported[name] = callable(getattr(module, "main", None)) if name == "app.web_ui" else callable(
                getattr(module, "render_expense_workflow" if "expense" in name else "render_monthly_report_workflow", None)
            )
        if not all(imported.values()):
            raise RuntimeError("one or more workflow entrypoints are not callable")
        report["workflows"] = imported
        lock = ROOT / "requirements.lock"
        lines = [line.strip() for line in lock.read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        if not lines or any(not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line) for line in lines):
            raise RuntimeError("requirements.lock has an unpinned dependency")
        report["requirements_lock_sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
        sha = __import__("os").environ.get("APP_GIT_COMMIT", "")
        if sha and not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RuntimeError("APP_GIT_COMMIT is not an exact 40-character commit")
        report["embedded_git_commit"] = sha or "not stamped (Render runtime may supply its SHA)"
    report["synthetic_conversion"] = render_synthetic()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--render-only", action="store_true",
                        help="host-only renderer diagnostic; does not qualify the full image")
    args = parser.parse_args(argv)
    try:
        result = audit(render_only=args.render_only)
        result["status"] = "PASS"
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        # Class and module only: exception messages might contain local paths.
        print(json.dumps({"status": "FAIL", "exception_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

