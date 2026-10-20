"""Another contract's design names do not travel into a new report (Refs #296, CR-render-5).

The master's theme name and its unused custom style names were copied into
every generated Word file, visible in Word's Design and Styles panes. Used
styles stay so the report renders the same. Synthetic values only.
"""
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from lxml import etree

from app import monthly_report_designs as designs
from app.monthly_report_docx import _build_docx
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_native_package import W, _neutral_design_names
from test_monthly_report_designs import master_reference

CANARY = "OTHER CLIENT ZX918"


def _master(tmp_path):
    path = master_reference(tmp_path)
    document = Document(path)
    document.styles.add_style(CANARY + " Style", WD_STYLE_TYPE.PARAGRAPH)
    document.save(path)
    source, output = ZipFile(path), BytesIO()
    with ZipFile(output, "w") as target:
        for info in source.infolist():
            raw = source.read(info)
            if info.filename == "word/theme/theme1.xml":
                raw = raw.replace(b'name="Office Theme"', ('name="' + CANARY + ' Theme"').encode())
            target.writestr(info, raw)
    path.write_bytes(output.getvalue())
    return path


def test_generated_report_drops_the_master_theme_name_and_unused_custom_styles(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "isolated"))
    designs.install_master(_master(tmp_path), actor="Synthetic Editor", expected_revision=0)
    profile = replace(synthetic_profiles()[0], contract="Synthetic Second Client")
    package = _build_docx(synthetic_draft(designs.pin(profile), ReportPeriod(2026, 9)))
    with ZipFile(BytesIO(package)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    assert not [name for name, raw in parts.items() if CANARY.encode() in raw]
    assert b'name="Office Theme"' in parts["word/theme/theme1.xml"]
    assert b'w:styleId="Heading1"' in parts["word/styles.xml"]


def _styles(*styles):
    body = "".join(styles)
    return f'<w:styles xmlns:w="{W}">{body}</w:styles>'.encode()


def _style(identity, *children, custom=True, default=False, kind="paragraph"):
    flags = (' w:customStyle="1"' if custom else "") + (' w:default="1"' if default else "")
    return f'<w:style w:type="{kind}" w:styleId="{identity}"{flags}><w:name w:val="{identity} name"/>{"".join(children)}</w:style>'


def test_only_unreferenced_custom_styles_are_removed():
    output = {
        "word/document.xml": f'<w:document xmlns:w="{W}"><w:body><w:p><w:pPr><w:pStyle w:val="Used"/></w:pPr></w:p></w:body></w:document>'.encode(),
        "word/numbering.xml": f'<w:numbering xmlns:w="{W}"><w:abstractNum><w:numStyleLink w:val="ListLink"/></w:abstractNum></w:numbering>'.encode(),
        "word/styles.xml": _styles(
            _style("Normal", custom=False, default=True), _style("Heading9", custom=False),
            _style("Used", '<w:basedOn w:val="Base"/><w:link w:val="UsedChar"/><w:next w:val="After"/>',
                   '<w:rPr><w:rStyle w:val="Nested"/></w:rPr>'),
            _style("Base"), _style("UsedChar"), _style("After"), _style("Nested"), _style("ListLink"),
            _style("CustomDefault", default=True), _style("Unused"), _style("UnusedChild", '<w:basedOn w:val="Base"/>')),
    }
    _neutral_design_names(output)
    kept = [node.get(f"{{{W}}}styleId") for node in etree.fromstring(output["word/styles.xml"])]
    assert kept == ["Normal", "Heading9", "Used", "Base", "UsedChar", "After", "Nested", "ListLink", "CustomDefault"]


def test_unchanged_parts_keep_their_bytes():
    styles = _styles(_style("Normal", custom=False, default=True))
    theme = b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office Theme"/>'
    output = {"word/styles.xml": styles, "word/theme/theme1.xml": theme}
    _neutral_design_names(output)
    assert output == {"word/styles.xml": styles, "word/theme/theme1.xml": theme}


def test_document_defaults_keep_referenced_custom_styles_and_their_dependencies():
    """Implicit document defaults are live references, even without body uses."""
    defaults = ('<w:docDefaults><w:rPrDefault><w:rPr>'
                '<w:rStyle w:val="DefaultRun"/>'
                '</w:rPr></w:rPrDefault></w:docDefaults>')
    output = {
        "word/document.xml": f'<w:document xmlns:w="{W}"><w:body/></w:document>'.encode(),
        "word/settings.xml": (f'<w:settings xmlns:w="{W}">'
                              '<w:defaultTableStyle w:val="DefaultTable"/></w:settings>').encode(),
        "word/styles.xml": _styles(
            defaults,
            _style("DefaultRun", '<w:basedOn w:val="RunBase"/>', kind="character"),
            _style("RunBase", kind="character"),
            _style("DefaultTable", '<w:basedOn w:val="TableBase"/>', kind="table"),
            _style("TableBase", kind="table"),
            _style("Unused")),
    }
    original_settings = output["word/settings.xml"]
    _neutral_design_names(output)
    root = etree.fromstring(output["word/styles.xml"])
    kept = {node.get(f"{{{W}}}styleId") for node in root.iter(f"{{{W}}}style")}
    assert kept == {"DefaultRun", "RunBase", "DefaultTable", "TableBase"}
    assert etree.tostring(root.find(f"{{{W}}}docDefaults")) == etree.tostring(
        etree.fromstring(f'<w:styles xmlns:w="{W}">{defaults}</w:styles>'.encode())[0])
    assert output["word/settings.xml"] == original_settings
