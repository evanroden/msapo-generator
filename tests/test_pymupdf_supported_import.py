"""Prevent legacy PyMuPDF imports from reappearing in served code or QA.

The compatibility namespace `fitz` emits a deprecation warning in newer
PyMuPDF releases. Importing the supported `pymupdf` package, optionally with
a local alias for existing call sites, retains the same APIs.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("app", "scripts", "pages", "runtime")


def test_application_and_qa_use_supported_pymupdf_import_path():
    deprecated = []
    for folder in SOURCE_DIRS:
        for path in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        if name.name == "fitz" or name.name.startswith("fitz."):
                            deprecated.append(f"{path.relative_to(ROOT)}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module == "fitz" or (node.module or "").startswith("fitz."):
                        deprecated.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not deprecated, "Use `import pymupdf` instead of deprecated `fitz`: " + ", ".join(deprecated)


def test_supported_pymupdf_namespace_opens_and_rasterizes_pdf():
    assert pymupdf.mupdf.FzErrorBase
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=180)
        page.insert_text((20, 40), "Supported PyMuPDF import")
        data = document.tobytes()
    with pymupdf.open(stream=data, filetype="pdf") as document:
        assert len(document) == 1
        assert "Supported PyMuPDF import" in document[0].get_text()
        bitmap = document[0].get_pixmap(matrix=pymupdf.Matrix(1, 1),
                                        colorspace=pymupdf.csRGB, alpha=False)
        assert bitmap.width == 240 and bitmap.height == 180
