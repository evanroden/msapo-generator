"""Focused A10 synthetic controls: no real customer documents or network traffic."""
from io import BytesIO
import json
from pathlib import Path

from docx import Document
import pymupdf as fitz
import pytest

from scripts.azure_acceptance_parity import (
    compare_bundle, compare_pdf, compare_word, load_identity, main,
)

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def docx(text: str, *, table=False, altered_core=False) -> bytes:
    doc = Document()
    doc.add_heading("Synthetic Example", 1)
    doc.add_paragraph(text)
    if table:
        tab = doc.add_table(rows=2, cols=2)
        tab.cell(0, 0).text = "Equipment"
        tab.cell(0, 1).text = "Status"
        tab.cell(1, 0).text = "DEMO-001"
        tab.cell(1, 1).text = "OK"
    if altered_core:
        doc.core_properties.author = "other synthetic writer"
        doc.core_properties.comments = "Other metadata"
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def pdf(lines=("Synthetic Example", "No real records"), *, pages=1, rgb=(0, 0, 0), offset=0,
        changed_metadata=False) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((70 + offset, 90), lines[i % len(lines)], fontsize=12,
                         color=tuple(c / 255 for c in rgb))
    if changed_metadata:
        doc.set_metadata({"title": "Different PDF metadata", "author": "Other synthetic writer"})
    out = doc.tobytes()
    doc.close()
    return out


def meta(folder: Path, *, environment: str, digest=DIGEST, fixture="test_fixture_123", sha=SHA):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "metadata.json"
    path.write_text(json.dumps({"environment": environment, "image_digest": digest,
                               "dataset_classification": "synthetic", "fixture_id": fixture,
                               "source_sha": sha}))
    return path


def test_docx_metadata_ignored_and_content_geometry_artwork_compared():
    a, b = docx("A complete invented work order", table=True), docx("A complete invented work order", table=True, altered_core=True)
    assert all(v == "PASS" for k, v in compare_word(a, b).items() if k not in {"counts"})
    assert compare_word(a, docx("A changed work order", table=True))["content"] == "FAIL"
    assert compare_word(a, docx("A complete invented work order", table=False))["tables"] == "FAIL"


def test_pdf_metadata_ignored_and_page_order_and_geometry_compared():
    original = pdf(("Page Alpha", "Page Beta"), pages=2)
    metadata_change = pdf(("Page Alpha", "Page Beta"), pages=2, changed_metadata=True)
    result = compare_pdf(original, metadata_change)
    assert all(v == "PASS" for v in result.values() if isinstance(v, str) and v in ("PASS", "FAIL"))
    assert compare_pdf(original, pdf(("Page Beta", "Page Alpha"), pages=2))["page_order"] == "FAIL"
    assert compare_pdf(original, pdf(("Page Alpha", "Page Beta"), pages=2, offset=20))["geometry"] == "FAIL"
    assert compare_pdf(original, pdf(("Page Alpha", "Page Beta"), pages=2, rgb=(255, 0, 0)))["grayscale"] == "FAIL"


def test_same_artifacts_at_same_digest_pass_without_exposing_text(tmp_path):
    a, b = tmp_path / "container", tmp_path / "azure"
    a.mkdir(); b.mkdir()
    (a / "monthly.docx").write_bytes(docx("Site: invented only", table=True))
    (b / "monthly.docx").write_bytes(docx("Site: invented only", table=True, altered_core=True))
    (a / "monthly.pdf").write_bytes(pdf())
    (b / "monthly.pdf").write_bytes(pdf(changed_metadata=True))
    result = compare_bundle(a, b, sha=SHA, baseline_identity=meta(a, environment="container"),
                            azure_identity=meta(b, environment="azure-staging"),
                            required=["monthly.docx", "monthly.pdf"])
    serialized = json.dumps(result)
    assert result["status"] == "PASS"
    assert "Site: invented" not in serialized
    assert "monthly.docx" not in serialized
    assert len(result["artifacts"]) == 2


def test_missing_output_is_not_a_pass(tmp_path):
    a, b = tmp_path / "container", tmp_path / "azure"
    a.mkdir(); b.mkdir()
    result = compare_bundle(a, b, sha=SHA, baseline_identity=meta(a, environment="container"),
                            azure_identity=meta(b, environment="azure-staging"), required=["monthly.docx"])
    assert result["status"] == "NOT_RUN"


def test_mismatched_digest_fixture_and_wrong_environment_block(tmp_path):
    a, b = tmp_path / "container", tmp_path / "azure"
    meta_a = meta(a, environment="container")
    meta_b = meta(b, environment="azure-staging", digest="sha256:" + "c" * 64)
    with pytest.raises(ValueError, match="mismatch"):
        compare_bundle(a, b, sha=SHA, baseline_identity=meta_a,
                       azure_identity=meta_b, required=["x.pdf"])
    meta_b = meta(b, environment="production", digest=DIGEST)
    with pytest.raises(ValueError, match="environment"):
        load_identity(meta_b, SHA, "azure-staging")
    meta_b = meta(b, environment="azure-staging", fixture="different_fixture_123")
    with pytest.raises(ValueError, match="mismatch"):
        compare_bundle(a, b, sha=SHA, baseline_identity=meta_a,
                       azure_identity=meta_b, required=["x.pdf"])


def test_path_escape_and_empty_evidence_block(tmp_path):
    a, b = tmp_path / "container", tmp_path / "azure"
    ma = meta(a, environment="container"); mb = meta(b, environment="azure-staging")
    for required in ([], ["../private.pdf"], ["note.txt"], ["/tmp/data.pdf"]):
        with pytest.raises(ValueError):
            compare_bundle(a, b, sha=SHA, baseline_identity=ma, azure_identity=mb, required=required)


def test_cli_writes_blocked_status_not_false_success(tmp_path):
    out = tmp_path / "evidence.json"
    rc = main(["--baseline", str(tmp_path / "missing1"), "--azure", str(tmp_path / "missing2"),
               "--baseline-identity", str(tmp_path / "missing1"),
               "--azure-identity", str(tmp_path / "missing2"),
               "--sha", SHA, "--require", "monthly.pdf", "--output", str(out)])
    assert rc == 4
    assert json.loads(out.read_text())["status"] == "BLOCKED"


def test_embedded_attachment_omission_detected_in_pdf_and_docx():
    from zipfile import ZipFile
    original_pdf = fitz.open()
    original_pdf.new_page()
    original_pdf.embfile_add("invented.txt", b"invented attachment only")
    with_attachment = original_pdf.tobytes()
    original_pdf.close()
    assert compare_pdf(with_attachment, pdf(("",), pages=1))["attachments"] == "FAIL"

    original_docx = docx("Invented attached memo")
    buf = BytesIO()
    with ZipFile(BytesIO(original_docx)) as source, ZipFile(buf, "w") as output:
        for item in source.infolist():
            output.writestr(item, source.read(item.filename))
        output.writestr("word/embeddings/synthetic.bin", b"mock bundled source")
    assert compare_word(buf.getvalue(), original_docx)["attachments"] == "FAIL"


def test_corrupt_document_and_bad_identity_fail_closed(tmp_path):
    a, b = tmp_path / "container", tmp_path / "azure"
    ma = meta(a, environment="container")
    mb = meta(b, environment="azure-staging")
    (a / "monthly.docx").write_bytes(b"not a Word ZIP")
    (b / "monthly.docx").write_bytes(docx("Synthetic"))
    res = compare_bundle(a, b, sha=SHA, baseline_identity=ma, azure_identity=mb,
                         required=["monthly.docx"])
    assert res["status"] == "FAIL"
    bad = json.loads(mb.read_text()); bad["image_digest"] = None
    mb.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="digest"):
        load_identity(mb, SHA, "azure-staging")


def test_word_style_change_detected_without_text_change():
    original = docx("Synthetic style check")
    changed = Document(BytesIO(original))
    changed.styles["Heading 1"].font.name = "Synthetic Different Serif"
    buffer = BytesIO()
    changed.save(buffer)
    result = compare_word(original, buffer.getvalue())
    assert result["content"] == "PASS"
    assert result["styles_fonts"] == "FAIL"


def test_word_artwork_order_detected_when_media_bytes_same():
    from PIL import Image
    original = Document()
    for rgb in ((25, 60, 90), (165, 35, 20)):
        picture = BytesIO()
        Image.new("RGB", (48, 48), rgb).save(picture, format="PNG")
        picture.seek(0)
        original.add_picture(picture)
    baseline = BytesIO()
    original.save(baseline)
    reordered = Document(BytesIO(baseline.getvalue()))
    body = reordered.element.body
    pictures = [el for el in body if el.xpath('.//a:blip')]
    assert len(pictures) == 2
    body.remove(pictures[1])
    body.insert(body.index(pictures[0]), pictures[1])
    updated = BytesIO()
    reordered.save(updated)
    result = compare_word(baseline.getvalue(), updated.getvalue())
    assert result["artwork"] == "PASS"
    assert result["artwork_order"] == "FAIL"
