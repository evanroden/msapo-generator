from io import BytesIO
from zipfile import ZipFile

from lxml import etree
import pytest

from app.monthly_report_render_headers import header_fingerprint, hidden_divider_header_overrides

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def package(*, later="other", image=b"reviewed pixels", header_text="", content=False):
    paragraph = '<w:p><w:r><w:t>Real section text</w:t></w:r></w:p>' if content else ""
    following = ('<w:headerReference w:type="default" r:id="other"/>' if later == "other"
                 else '<w:headerReference w:type="default" r:id="hidden"/>' if later == "shared" else "")
    document = f'''<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}"><w:body>
    <w:p><w:r><w:t>TRAINING SUMMARY</w:t><w:drawing><wp:anchor>
    <wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>
    <wp:extent cx="8789670" cy="7930515"/><a:graphic><a:blip/>
    <a:solidFill><a:srgbClr val="D6EF4B"/></a:solidFill><a:solidFill><a:srgbClr val="547E7E"/></a:solidFill>
    </a:graphic></wp:anchor></w:drawing></w:r></w:p>{paragraph}
    <w:p><w:pPr><w:sectPr><w:headerReference w:type="default" r:id="hidden"/></w:sectPr></w:pPr></w:p>
    <w:p><w:r><w:t>Following content</w:t></w:r></w:p><w:sectPr>{following}</w:sectPr></w:body></w:document>'''.encode()
    header = f'''<w:hdr xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}"><w:p><w:r>{header_text}<w:drawing>
    <wp:anchor><wp:docPr id="1" name="Logo"/><a:graphic><a:blip r:embed="picture"/></a:graphic></wp:anchor>
    </w:drawing></w:r></w:p></w:hdr>'''.encode()
    relation_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", f'<Relationships xmlns="{relation_ns}"><Relationship Id="hidden" Target="header1.xml"/><Relationship Id="other" Target="header2.xml"/></Relationships>')
        archive.writestr("word/header1.xml", header)
        archive.writestr("word/_rels/header1.xml.rels", f'<Relationships xmlns="{relation_ns}"><Relationship Id="picture" Type="{R}/image" Target="media/logo.png"/></Relationships>')
        archive.writestr("word/media/logo.png", image)
    return output.getvalue()


def test_measured_header_override_is_header_only_and_native_bytes_unchanged():
    raw = package()
    with ZipFile(BytesIO(raw)) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        original = etree.tostring(document)
        proof = {"part": "word/header1.xml", "fingerprint": header_fingerprint(archive, "word/header1.xml")}
        assert not hidden_divider_header_overrides(archive, document)
        changes = hidden_divider_header_overrides(archive, document, [proof])
        assert set(changes) == {"word/header1.xml"}
        assert b"anchor" not in changes["word/header1.xml"]
        assert etree.tostring(document) == original
        assert archive.read("word/media/logo.png") == b"reviewed pixels"


@pytest.mark.parametrize("mode", ["shared", "inherited", "content", "changed_image", "text_header", "wrong_hash"])
def test_unproven_or_content_headers_are_never_suppressed(mode):
    with ZipFile(BytesIO(package())) as original:
        proof = {"part": "word/header1.xml", "fingerprint": header_fingerprint(original, "word/header1.xml")}
    raw = package(later=mode if mode in {"shared", "inherited"} else "other",
                  content=mode == "content", image=b"changed" if mode == "changed_image" else b"reviewed pixels",
                  header_text="<w:t>Keep this name</w:t>" if mode == "text_header" else "")
    if mode == "wrong_hash":
        proof["fingerprint"] = "a" * 64
    with ZipFile(BytesIO(raw)) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
        assert not hidden_divider_header_overrides(archive, root, [proof])
