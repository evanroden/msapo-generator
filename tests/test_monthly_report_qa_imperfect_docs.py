"""Immutable imperfect-source fixtures must use the real importer, with no QA approvals.

The source package is byte-for-byte reproducible. Passing these checks is
synthetic source QA, not final client-output or authentic Word/Adobe parity.
"""
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
import json

import fitz
import pytest
from docx import Document

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_qa_fixture as fixtures
from app import ocr
from app.monthly_report_content_policy import page_status
from app.monthly_report_qa_imperfect_docs import load_pack
from app.monthly_report_testing import isolated


PDF_STATUSES = {
    "QA_Vendor_Service_MixedPages.pdf":
        ("technical", "blank", "legal", "signature", "pricing"),
    "QA_Water_Treatment_MixedPages.pdf":
        ("technical", "technical", "legal", "signature", "blank"),
    "QA_Vendor_AmbiguousDate.pdf":
        ("technical", "technical"),
    "QA_Chemical_DifferentSite.pdf":
        ("technical", "pricing", "blank"),
    "QA_Water_Treatment_ImageOnlyScan.pdf":
        ("review", "blank"),
}


def _contents():
    with isolated("b" * 32):
        packed = load_pack()
    with ZipFile(BytesIO(packed)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("MANIFEST.json"))
        evidence = {
            item["name"]: archive.read(item["name"])
            for item in manifest["files"]
        }
    return packed, names, manifest, evidence


def test_pack_requires_isolated_qa():
    with pytest.raises(ValueError, match="isolated QA"):
        load_pack()


def test_checked_in_pdf_and_docx_pack_is_pinned_complete_and_imperfect():
    package, names, manifest, evidence = _contents()
    assert sha256(package).hexdigest() == (
        "c767124fb922445ced29c07de7755567f3adf6945b2218021584aa8f325c627f")
    assert len(manifest["files"]) == 9
    assert manifest["testing_target"]["contract"] == fixtures.CONTRACT
    assert len([x for x in names if x.endswith(".docx")]) == 4
    assert len([x for x in names if x.endswith(".pdf")]) == 5
    for item in manifest["files"]:
        original = evidence[item["name"]]
        assert sha256(original).hexdigest() == item["sha256"]
        assert len(original) == item["bytes"]
        assert len(original) < 30 * 1024 * 1024
        if item["name"].endswith(".docx"):
            assert Document(BytesIO(original)).paragraphs
            continue
        with fitz.open(stream=original, filetype="pdf") as rendered:
            expected = PDF_STATUSES[item["name"]]
            assert len(rendered) == len(expected)
            for number, (page, wanted) in enumerate(zip(rendered, expected), 1):
                text = page.get_text().strip()
                needs_ocr = ocr._page_needs_ocr(page, native_text=text)
                status, _ = page_status(text, unreadable=needs_ocr)
                assert status == wanted, (item["name"], number, wanted, status)
                if wanted == "blank":
                    assert not text and not page.get_image_info() and not page.get_drawings()
                if wanted == "review":
                    assert not text and page.get_image_info()
    with fitz.open(stream=evidence["QA_Vendor_Service_MixedPages.pdf"], filetype="pdf") as vendor:
        assert "25.1 PSID" in vendor[0].get_text()
        assert "$4,875.00" in vendor[4].get_text()
    with fitz.open(stream=evidence["QA_Water_Treatment_MixedPages.pdf"], filetype="pdf") as water:
        assert "Legionella" in water[0].get_text()
        assert water[1].get_image_info(), "Technical trend image was lost"
    with fitz.open(stream=evidence["QA_Chemical_DifferentSite.pdf"], filetype="pdf") as foreign:
        assert "Demo South" in foreign[0].get_text()
        assert "$1,260.00" in foreign[1].get_text()
    with fitz.open(stream=evidence["QA_Vendor_AmbiguousDate.pdf"], filetype="pdf") as invalid:
        assert "Invalid date" in invalid[0].get_text()
        assert "Planned" in invalid[0].get_text()


@pytest.mark.parametrize("ext, count", [(".pdf", 5), (".docx", 4)])
def test_original_bytes_ingest_in_isolated_namespace_without_report_mutation(
        tmp_path, monkeypatch, ext, count):
    _, _, manifest, evidence = _contents()
    selected = tuple(
        (item["name"], evidence[item["name"]])
        for item in manifest["files"] if item["name"].endswith(ext))
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    assert len(selected) == count
    with isolated(("c" if ext == ".pdf" else "d") * 32):
        fixtures.prepare("prefill")
        before = library.load_snapshot(fixtures.CONTRACT, fixtures.profile().key, fixtures.PERIOD)
        contents, notices = sources.ingest_batch(fixtures.profile(), selected)
        assert len(contents) == count, notices
        assert {c.source.filename for c in contents} == {name for name, _ in selected}
        assert all(c.source.sha256 == sha256(evidence[c.source.filename]).hexdigest()
                   for c in contents)
        assert all(not c.source.client_page_reviews for c in contents)
        assert library.load_snapshot(fixtures.CONTRACT, fixtures.profile().key, fixtures.PERIOD) == before
        if ext == ".pdf":
            vendor = next(c.source for c in contents
                          if c.source.filename == "QA_Vendor_Service_MixedPages.pdf")
            assert vendor.selected_pages == (1,)
            water = next(c.source for c in contents
                         if c.source.filename == "QA_Water_Treatment_MixedPages.pdf")
            assert water.selected_pages == (1, 2)
            scan = next(c.source for c in contents
                        if c.source.filename == "QA_Water_Treatment_ImageOnlyScan.pdf")
            assert scan.needs_vision == (1,)
            foreign = next(c.source for c in contents
                           if c.source.filename == "QA_Chemical_DifferentSite.pdf")
            assert "Demo South" in "\n".join(foreign.page_texts)
    assert library.load_snapshot(fixtures.CONTRACT, fixtures.profile().key, fixtures.PERIOD) is None
