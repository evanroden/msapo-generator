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


def floating_cover(*, first_header=False, footer=False, flowing=False, top="0", cover_only=False,
                   identity="Operations and Maintenance Monthly Review"):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    wp = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    first = '<w:headerReference w:type="first" r:id="first"/>' if first_header else ""
    foot = '<w:footerReference w:type="first" r:id="footer"/>' if footer else ""
    text = "Actual flowing content" if flowing else "="
    xml = f'''<w:document xmlns:w="{w}" xmlns:r="{R}" xmlns:wp="{wp}"><w:body>
      <w:p><w:r><w:t>{text}</w:t><w:drawing><wp:anchor><wp:positionV relativeFrom="paragraph"><wp:posOffset>5523001</wp:posOffset></wp:positionV></wp:anchor></w:drawing></w:r></w:p>
      <w:p><w:r><w:pict><w:txbxContent><w:p><w:r><w:t>{identity}</w:t></w:r></w:p></w:txbxContent></w:pict></w:r><w:pPr><w:sectPr><w:headerReference w:type="default" r:id="default"/>{first}{foot}
      <w:pgMar w:top="{top}" w:bottom="0" w:header="720"/><w:titlePg/></w:sectPr></w:pPr></w:p>
      <w:sectPr><w:pgMar w:top="720" w:bottom="720"/></w:sectPr>
      </w:body></w:document>'''
    if cover_only:
        root = etree.fromstring(xml)
        body = root.find("{" + w + "}body")
        section = body[1].find(".//{" + w + "}sectPr")
        section.getparent().remove(section)
        body.remove(body[-1])
        body.append(section)
        xml = etree.tostring(root)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def test_reference_calibrated_cover_fix_is_opt_in_and_preserves_inherited_header():
    raw = floating_cover()
    assert rendering_docx(raw) == raw
    assert rendering_docx(raw, profile={"version": 1, "cover_zero_origin": False}) == raw
    fixed = rendering_docx(raw, profile={"version": 1, "cover_zero_origin": True})
    root = shapes(fixed)
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    sections = list(root.iter(w + "sectPr"))
    assert sections[0].find(w + "headerReference") is None
    assert sections[0].find(w + "titlePg") is None
    assert sections[0].find(w + "pgMar").get(w + "header") == "0"
    assert sections[1].find(w + "headerReference").get("{" + R + "}id") == "default"
    assert rendering_docx(fixed, profile={"version": 1, "cover_zero_origin": True}) == fixed


def test_cover_only_preview_receives_same_header_fix_without_matching_other_sections():
    profile = {"version": 1, "cover_zero_origin": True}
    raw = floating_cover(cover_only=True)
    result = shapes(rendering_docx(raw, profile=profile))
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    sections = list(result.iter(w + "sectPr"))
    assert len(sections) == 1
    assert sections[0].find(w + "headerReference") is None
    assert sections[0].find(w + "titlePg") is None
    divider = floating_cover(cover_only=True, identity="MONTHLY SCORECARDS")
    assert rendering_docx(divider, profile=profile) == divider


@pytest.mark.parametrize("arguments", [
    {"first_header": True}, {"footer": True}, {"flowing": True}, {"top": "720"},
])
def test_calibration_does_not_override_explicit_design_or_flowing_covers(arguments):
    raw = floating_cover(**arguments)
    assert rendering_docx(raw, profile={"version": 1, "cover_zero_origin": True}) == raw


@pytest.mark.parametrize("profile", [
    {"version": 1, "cover_zero_origin": "true"}, {"version": 2, "cover_zero_origin": True},
    {"version": 1, "cover_zero_origin": True, "guess": True},
])
def test_render_profile_rejects_unvalidated_flags(profile):
    with pytest.raises(ValueError):
        rendering_docx(floating_cover(), profile=profile)


@pytest.mark.parametrize("style_id,color,fill,extra,expected", [
    ("Divider", "", "FFFFFF", "", True),
    ("DividerChar", '<w:color w:val="auto"/>', "FFFFFF", "", True),
    ("BodyText", "", "FFFFFF", "", False),
    ("Divider", '<w:color w:val="000000"/>', "FFFFFF", "", False),
    ("Divider", '<w:color w:val="auto" w:themeColor="accent1"/>', "FFFFFF", "", False),
    ("Divider", "", "123456", "", False),
    ("Divider", "", "FFFFFF", '<w14:alpha w14:val="50000"/>', False),
])
def test_divider_fill_bridge_preserves_explicit_color_transparency_and_other_styles(
        style_id, color, fill, extra, expected):
    from app.monthly_report_render_compat import _divider_text_fill, _W, _W14
    root = etree.fromstring(f'''<w:styles xmlns:w="{_W[1:-1]}" xmlns:w14="{_W14[1:-1]}">
      <w:style w:styleId="{style_id}"><w:rPr>{color}
      <w14:textFill><w14:solidFill><w14:srgbClr w14:val="{fill}">{extra}</w14:srgbClr>
      </w14:solidFill></w14:textFill><w14:shadow w14:dist="38100"/>
      </w:rPr></w:style></w:styles>''')
    before = etree.tostring(root)
    assert _divider_text_fill(root) is expected
    if expected:
        assert root.find('.//' + _W + 'color').get(_W + 'val') == 'FFFFFF'
        assert root.find('.//' + _W14 + 'shadow').get(_W14 + 'dist') == '38100'
        assert not _divider_text_fill(root)
    else:
        assert etree.tostring(root) == before


def test_disposable_white_text_requires_independent_measured_flag():
    from app.monthly_report_render_compat import _W, _W14
    styles = f'''<w:styles xmlns:w="{_W[1:-1]}" xmlns:w14="{_W14[1:-1]}">
      <w:style w:styleId="Divider"><w:rPr><w14:textFill><w14:solidFill>
      <w14:srgbClr w14:val="FFFFFF"/></w14:solidFill></w14:textFill>
      </w:rPr></w:style></w:styles>'''.encode()
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("word/styles.xml", styles)
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{_W[1:-1]}"><w:body/></w:document>')
    raw = output.getvalue()
    for profile in (None, {"version": 1, "cover_zero_origin": True},
                    {"version": 2, "cover_zero_origin": True, "divider_wrap_none": True},
                    {"version": 3, "cover_zero_origin": True, "divider_wrap_none": True,
                     "divider_white_text": False}):
        assert rendering_docx(raw, profile=profile) == raw
    profile = {"version": 3, "cover_zero_origin": False, "divider_wrap_none": False,
               "divider_white_text": True}
    fixed = rendering_docx(raw, profile=profile)
    with ZipFile(BytesIO(fixed)) as archive:
        root = etree.fromstring(archive.read("word/styles.xml"))
        assert root.find('.//' + _W + 'color').get(_W + 'val') == 'FFFFFF'
    assert rendering_docx(fixed, profile=profile) == fixed
    with ZipFile(BytesIO(raw)) as archive:
        assert archive.read("word/styles.xml") == styles
