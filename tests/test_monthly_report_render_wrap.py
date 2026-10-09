from copy import deepcopy

from lxml import etree
import pytest

from app.monthly_report_render_wrap import normalize_invisible_wraps, _A, _NS, _W, _WP


def composition():
    return etree.fromstring(('''<w:document xmlns:w="{w}" xmlns:wp="{wp}" xmlns:a="{a}" xmlns:wps="{wps}">
      <w:body><w:p><w:r><w:drawing><wp:anchor><wp:positionV relativeFrom="paragraph"><wp:posOffset>-12000</wp:posOffset></wp:positionV>
      <wp:extent cx="400000" cy="600000"/><a:graphic><a:graphicData><a:blip/></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>
      <w:r><w:drawing><wp:anchor distT="365760"><wp:wrapTopAndBottom/>
      <wp:positionV relativeFrom="paragraph"><wp:posOffset>685800</wp:posOffset></wp:positionV><wp:extent cx="6858000" cy="2420620"/>
      <a:graphic><a:graphicData><wps:wsp><wps:spPr><a:xfrm/><a:prstGeom prst="rect"/><a:noFill/>
      <a:ln><a:solidFill><a:prstClr val="black"><a:alpha val="0"/></a:prstClr></a:solidFill></a:ln><a:effectLst/></wps:spPr>
      <wps:txbx><w:txbxContent><w:p/></w:txbxContent></wps:txbx></wps:wsp></a:graphicData></a:graphic>
      </wp:anchor></w:drawing></w:r></w:p></w:body></w:document>''').format(**_NS).encode())


def test_invisible_companion_wrap_only_changes_disposable_wrap_tag():
    native = composition()
    original = etree.tostring(native)
    render = deepcopy(native)
    assert normalize_invisible_wraps(render)
    assert etree.tostring(native) == original
    assert etree.tostring(render) == original.replace(b'wp:wrapTopAndBottom', b'wp:wrapNone')
    assert not normalize_invisible_wraps(render)


@pytest.mark.parametrize('change', ['visible_line', 'visible_fill', 'text', 'image', 'effect', 'no_line', 'not_upward', 'page_position', 'different_paragraph'])
def test_other_shapes_and_spacing_are_preserved(change):
    root = composition()
    shape = root.find('.//wps:wsp', _NS)
    if change == 'visible_line':
        shape.find('.//a:alpha', _NS).set('val', '100000')
    elif change == 'visible_fill':
        shape.find('wps:spPr/a:noFill', _NS).tag = '{' + _NS['a'] + '}solidFill'
    elif change == 'text':
        etree.SubElement(shape.find('.//w:p', _NS), '{' + _NS['w'] + '}t').text = 'Keep this note'
    elif change == 'image':
        etree.SubElement(shape, '{' + _NS['a'] + '}blip')
    elif change == 'effect':
        etree.SubElement(shape.find('.//a:effectLst', _NS), '{' + _NS['a'] + '}outerShdw')
    elif change == 'no_line':
        line = shape.find('.//a:ln', _NS)
        line.getparent().remove(line)
    elif change == 'not_upward':
        root.find('.//wp:positionV/wp:posOffset', _NS).text = '0'
    elif change == 'page_position':
        root.find('.//wp:positionV', _NS).set('relativeFrom', 'page')
    elif change == 'different_paragraph':
        paragraph = root.find('.//w:body/w:p', _NS)
        new_paragraph = etree.SubElement(paragraph.getparent(), '{' + _NS['w'] + '}p')
        new_paragraph.append(paragraph[-1])
    original = etree.tostring(root)
    assert not normalize_invisible_wraps(root)
    assert etree.tostring(root) == original


def divider_shape(*, title="MONTHLY SCORECARDS", relative="page", color="D6EF4B", size="8789670"):
    return etree.fromstring(f'''<w:document xmlns:w="{_W}" xmlns:wp="{_WP}" xmlns:a="{_A}">
      <w:body><w:p><w:r><w:t>{title}</w:t><w:drawing><wp:anchor>
      <wp:positionV relativeFrom="{relative}"><wp:posOffset>19050</wp:posOffset></wp:positionV>
      <wp:extent cx="{size}" cy="7930515"/><wp:wrapTopAndBottom/>
      <a:graphic><a:blip/><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>
      <a:solidFill><a:srgbClr val="547E7E"/></a:solidFill></a:graphic>
      </wp:anchor></w:drawing></w:r></w:p></w:body></w:document>''')


def test_recognized_native_divider_stops_reserving_flow_space_only():
    from app.monthly_report_render_wrap import normalize_divider_wraps
    root = divider_shape()
    expected = etree.fromstring(etree.tostring(root))
    expected.find(".//{" + _WP + "}wrapTopAndBottom").tag = "{" + _WP + "}wrapNone"
    assert normalize_divider_wraps(root)
    assert etree.tostring(root) == etree.tostring(expected)
    assert not normalize_divider_wraps(root)


def test_disposable_divider_fix_requires_independent_verified_profile():
    from io import BytesIO
    from zipfile import ZipFile
    from app.monthly_report_render_compat import rendering_docx
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", etree.tostring(divider_shape()))
    raw = stream.getvalue()
    for profile in (None, {"version": 1, "cover_zero_origin": True},
                    {"version": 2, "cover_zero_origin": True, "divider_wrap_none": False}):
        assert rendering_docx(raw, profile=profile) == raw
    profile = {"version": 2, "cover_zero_origin": False, "divider_wrap_none": True}
    fixed = rendering_docx(raw, profile=profile)
    with ZipFile(BytesIO(fixed)) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    assert root.find(".//{" + _WP + "}wrapNone") is not None
    assert root.find(".//{" + _WP + "}wrapTopAndBottom") is None
    assert rendering_docx(fixed, profile=profile) == fixed


@pytest.mark.parametrize("arguments", [
    {"title": "Vendor service report"}, {"title": "MONTHLY SCORECARDS actual site content"},
    {"relative": "paragraph"}, {"color": "FFFFFF"}, {"size": "4000000"},
])
def test_ordinary_pictures_and_non_page_dividers_keep_original_wrap(arguments):
    from app.monthly_report_render_wrap import normalize_divider_wraps
    root = divider_shape(**arguments)
    before = etree.tostring(root)
    assert not normalize_divider_wraps(root)
    assert etree.tostring(root) == before
