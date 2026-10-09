from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree
from PIL import Image
import fitz
import pytest

from app.monthly_report_render_compat import rendering_docx

V = "urn:schemas-microsoft-com:vml"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def package(*, explicit="", mode="RGBA"):
    image = BytesIO()
    Image.new(mode, (8, 8), (0, 0, 0, 60) if mode == "RGBA" else (0, 0, 0)).save(image, "PNG")
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", f'<root xmlns:v="{V}" xmlns:r="{R}"><v:shape id="shadow" style="width:40pt;height:30pt" {explicit}><v:imagedata r:id="picture"/></v:shape><v:shape id="native" fillcolor="#d4ed49" path="m0,0l10,20xe"/></root>')
        archive.writestr("word/_rels/document.xml.rels", '<Relationships><Relationship Id="picture" Target="media/shadow.png"/></Relationships>')
        archive.writestr("word/media/shadow.png", image.getvalue())
    return out.getvalue()


def shapes(raw):
    with ZipFile(BytesIO(raw)) as archive:
        return etree.fromstring(archive.read("word/document.xml"))


def test_alpha_frame_gets_transparent_defaults_without_changing_image_or_geometry():
    raw = package()
    converted = rendering_docx(raw)
    before, after = shapes(raw), shapes(converted)
    assert after[0].get("filled") == after[0].get("stroked") == "f"
    assert after[0].get("style") == before[0].get("style")
    assert etree.tostring(after[1]) == etree.tostring(before[1])
    assert shapes(raw)[0].get("filled") is None
    with ZipFile(BytesIO(raw)) as source, ZipFile(BytesIO(converted)) as result:
        assert source.read("word/media/shadow.png") == result.read("word/media/shadow.png")
        assert source.read("word/_rels/document.xml.rels") == result.read("word/_rels/document.xml.rels")
    assert rendering_docx(converted) == converted


@pytest.mark.parametrize("explicit", ['filled="t"', 'filled="f"', 'fillcolor="white"'])
def test_explicit_fill_and_opaque_images_remain_byte_identical(explicit):
    raw = package(explicit=explicit)
    assert rendering_docx(raw) == raw
    opaque = package(mode="RGB")
    assert rendering_docx(opaque) == opaque


@pytest.mark.parametrize("operation", ["final", "section", "preview", "word_page"])
def test_monthly_conversion_uses_copy_and_final_download_stays_native(monkeypatch, tmp_path, operation):
    from app import monthly_report_docx as output, monthly_report_preview as preview
    from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    raw = package()
    seen = []

    def convert(path):
        seen.append(path.read_bytes())
        result = tmp_path / (path.stem + ".pdf")
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 72), "Synthetic report")
            pdf.save(result)
        return result

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(output.pdf_converter, "convert_to_pdf", convert)
    monkeypatch.setattr(output, "assemble_docx", lambda *a, **kw: raw)
    monkeypatch.setattr(preview, "section_preview_docx", lambda *a, **kw: raw)
    monkeypatch.setattr(preview, "_build_docx", lambda *a, **kw: raw)
    if operation == "final":
        result = output.generate_report(draft)
        assert result.docx == raw
        assert result.pdf.startswith(b"%PDF-")
    elif operation == "section":
        assert preview.preview_section(draft, "activity").pages == 1
    elif operation == "preview":
        assert preview.preview_report(draft).pages == 1
    else:
        from app import monthly_report_word_pages as pages
        monkeypatch.setattr(pages, "safe_section_docx", lambda *a, **kw: raw)
        monkeypatch.setattr(pages, "_render", lambda path, directory: convert(path))
        assert len(pages.preserve_word_pages(tmp_path / "source.docx", (1,))) == 1
    assert len(seen) == 1
    assert shapes(seen[0])[0].get("filled") == "f"
