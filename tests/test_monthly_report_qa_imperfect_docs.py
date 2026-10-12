"""The synthetic QA pack must remain difficult without publishing any client data."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from shutil import which
from zipfile import ZipFile
import json

import fitz
import pytest
from docx import Document

from app import ocr
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_qa_fixture as fixtures
from app.monthly_report_content_policy import page_status
from app.monthly_report_qa_imperfect_docs import build_pack, RECORDS
from app.monthly_report_testing import isolated


def test_qa_documents_cannot_be_built_in_live_context():
    with pytest.raises(ValueError, match="isolated QA"):
        build_pack()


@pytest.mark.skipif(which("libreoffice") is None, reason="PDF converter not installed in this runtime")
def test_synthetic_docs_pdf_pages_are_real_and_policy_review_is_required(tmp_path, monkeypatch):
    with isolated("b" * 32):
        packed = build_pack()
    with ZipFile(BytesIO(packed)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("MANIFEST.json"))
        assert manifest["synthetic"] is True
        assert manifest["contract"] == "QA Demonstration - Synthetic Only"
        assert len(manifest["files"]) == 9
        assert "README.txt" in names
        assert all(f["filename"] in names for f in manifest["files"])
        for meta in manifest["files"]:
            source = archive.read(meta["filename"])
            assert sha256(source).hexdigest() == meta["sha256"]
            assert len(source) < 30 * 1024 * 1024
            if meta["filename"].endswith(".docx"):
                doc = Document(BytesIO(source))
                assert doc.paragraphs
                continue
            with fitz.open(stream=source, filetype="pdf") as pdf:
                assert len(pdf) == len(meta["page_kinds_in_pdf"])
                for page, kind in zip(pdf, meta["page_kinds_in_pdf"]):
                    text = page.get_text().strip()
                    status, _ = page_status(
                        text, unreadable=ocr._page_needs_ocr(page, native_text=text))
                    expected = "technical" if kind in {"technical", "chart"} else (
                        "review" if kind == "image-needs-review" else kind)
                    assert status == expected, (meta["filename"], kind, status)
                    if kind == "blank":
                        assert not text and not page.get_drawings() and not page.get_image_info()
                    if kind == "image-needs-review":
                        assert not text and page.get_image_info()
        vendor_pdf = archive.read("QA_Vendor_MixedPages.pdf")
        with fitz.open(stream=vendor_pdf, filetype="pdf") as pdf:
            assert "25.1 PSID" in pdf[0].get_text()
            assert "SYNTHETIC" in pdf[0].get_text()
            assert "$4,875.00" in pdf[4].get_text()
        water_pdf = archive.read("QA_WaterTreatment_MixedPages.pdf")
        with fitz.open(stream=water_pdf, filetype="pdf") as pdf:
            assert "Legionella culture: PENDING" in pdf[0].get_text()
            assert pdf[1].get_image_info(), "Relevant technical trend image was lost"
        other_pdf = archive.read("QA_Chemical_DifferentSite.pdf")
        with fitz.open(stream=other_pdf, filetype="pdf") as pdf:
            assert "Facility: Demo South" in pdf[0].get_text()
            assert "$1,260.00" in pdf[1].get_text()
        invalid_pdf = archive.read("QA_Vendor_InvalidCompletionDate.pdf")
        with fitz.open(stream=invalid_pdf, filetype="pdf") as pdf:
            assert "Invalid date" in pdf[0].get_text()
            assert "not completed" in pdf[0].get_text().lower()
        candidate_pdf_files = tuple(
            (name, archive.read(name)) for name in sorted(names)
            if name.startswith("QA_") and name.endswith(".pdf")
        )

    # Reuse the application's real importer in a disposable server namespace.
    # Reading a source is not an approval to include its content in a report.
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    live_root = library._root()
    with isolated("c" * 32):
        fixtures.prepare("prefill")
        before = library.load_snapshot(fixtures.CONTRACT, fixtures.profile().key, fixtures.PERIOD)
        contents, notices = sources.ingest_batch(
            fixtures.profile(), candidate_pdf_files)
        assert len(contents) == 5
        assert {c.source.filename for c in contents} == {
            name for name, _payload in candidate_pdf_files
        }
        scans = [c for c in contents if "ImageOnlyScan" in c.source.filename]
        assert len(scans) == 1 and scans[0].source.needs_vision == (1,)
        main_vendor = next(c.source for c in contents if c.source.filename == "QA_Vendor_MixedPages.pdf")
        assert main_vendor.selected_pages == (1,)
        main_water = next(c.source for c in contents if c.source.filename == "QA_WaterTreatment_MixedPages.pdf")
        assert main_water.selected_pages == (1, 2)
        assert library.load_snapshot(fixtures.CONTRACT, fixtures.profile().key, fixtures.PERIOD) == before
    assert library._root() == live_root
    assert library.load_snapshot(fixtures.CONTRACT, fixtures.profile().key, fixtures.PERIOD) is None
