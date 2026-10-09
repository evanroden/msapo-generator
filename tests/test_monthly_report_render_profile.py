from dataclasses import replace
from io import BytesIO
import json

from docx import Document
from docx.oxml import OxmlElement
from docx.shared import Pt
import pymupdf as fitz
from PIL import Image
import pytest

from app import monthly_report_designs as designs
from app import monthly_report_library as library
from app.monthly_report_model import default_sections, synthetic_profiles
from app.monthly_report_render_profile import DEFAULT, calibrate, validate_profile


def pair(tmp_path, origin=0, producer='Unrelated producer', title='Synthetic North September 2026'):
    image=Image.new('RGB',(300,180))
    image.putdata([(x%256,y%256,(x+y)%256)for y in range(180)for x in range(300)])
    buffer=BytesIO();image.save(buffer,format='PNG');raw=buffer.getvalue()
    doc=Document();doc.add_paragraph(title)
    doc.add_paragraph('Operations and Maintenance Monthly Review Prepared by Synthetic Team')
    inline=doc.add_paragraph().add_run().add_picture(BytesIO(raw),width=Pt(300),height=Pt(180))._inline
    inline.tag='{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}anchor'
    position=OxmlElement('wp:positionV');position.set('relativeFrom','paragraph')
    offset=OxmlElement('wp:posOffset');offset.text=str(200*12700);position.append(offset);inline.insert(0,position)
    doc.add_section()
    for section in default_sections():
        doc.add_heading(section.title,1)
    source=tmp_path/'source.docx';doc.save(source)
    pdf=fitz.open();page=pdf.new_page()
    page.insert_textbox(fitz.Rect(40,20,570,140),title+'\nOperations and Maintenance Monthly Review Prepared by Synthetic Team',fontsize=12)
    page.insert_image(fitz.Rect(72,200+origin,372,380+origin),stream=raw)
    pdf.set_metadata({'producer':producer})
    path=tmp_path/f'companion-{origin}.pdf';pdf.save(path);pdf.close()
    return source,path


def test_pair_calibrates_geometry_not_producer(tmp_path):
    source,pdf=pair(tmp_path,producer='LibreOffice pretend')
    zero=calibrate(source,pdf)
    assert zero['render_profile']['cover_zero_origin']
    assert zero['cover_measurements'][0]['origin_points']==0
    source,pdf=pair(tmp_path,origin=49,producer='Adobe PDF Library pretend')
    assert calibrate(source,pdf)['render_profile']==DEFAULT


def test_pair_rejects_wrong_identity_and_unknown_image_stays_native(tmp_path):
    source,pdf=pair(tmp_path)
    with fitz.open(pdf)as doc:
        page=doc[0];page.add_redact_annot(fitz.Rect(0,0,600,150));page.apply_redactions()
        altered=tmp_path/'other.pdf';doc.save(altered)
    with pytest.raises(ValueError,match='identity'):
        calibrate(source,altered)
    with fitz.open(pdf)as doc:
        page=doc[0];page.add_redact_annot(fitz.Rect(72,200,372,380));page.apply_redactions()
        altered=tmp_path/'no-photo.pdf';doc.save(altered)
    assert calibrate(source,altered)['render_profile']==DEFAULT


def test_paired_pin_immutable_legacy_default_and_integrity(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'data'))
    source,pdf=pair(tmp_path)
    profile=synthetic_profiles()[0]
    legacy=designs.install(source,profile,actor='Editor',expected_revision=0)
    paired=designs.install(source,profile,actor='Editor',expected_revision=1,companion_pdf=pdf)
    assert legacy.template!=paired.template
    assert designs.render_profile_for(legacy)==DEFAULT
    assert designs.render_profile_for(paired)['cover_zero_origin']
    assert designs.source_for(paired).read_bytes()==source.read_bytes()
    assert designs.source_for(legacy).read_bytes()==source.read_bytes()
    assert designs.pin(legacy)==legacy
    meta=designs._directory(profile.contract)/'metadata'/(designs.fingerprint(paired)+'.json')
    original_metadata=meta.read_bytes()
    meta.unlink()
    with pytest.raises(ValueError,match='unavailable'):
        designs.source_for(paired)
    meta.write_bytes(original_metadata)
    value=json.loads(meta.read_text());value['render_profile']['cover_zero_origin']=False
    meta.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='integrity'):
        designs.render_profile_for(paired)


def test_paired_master_versions_do_not_change_pinned_report(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'data'))
    source,pdf=pair(tmp_path)
    old=designs.install_master(source,actor='Editor',expected_revision=0)
    profile=designs.pin(replace(synthetic_profiles()[0],template=designs.MASTER_PREFIX+old))
    new=designs.install_master(source,actor='Editor',expected_revision=1,companion_pdf=pdf)
    assert new!=old and designs.pin(profile)==profile
    latest=designs.pin(profile,latest_master=True)
    assert designs.render_profile_for(latest)['cover_zero_origin']
    assert designs.render_profile_for(profile)==DEFAULT
    assert designs.master_section_order(latest)
    metadata=library._read(library._root()/'designs/master/metadata'/(new+'.json'))
    companion=library._root()/'designs/master'/(metadata['companion_sha256']+'.pdf');companion.unlink();companion.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='integrity'):
        designs.source_for(latest)


def test_profile_flags_are_finite_typed_and_versioned():
    assert validate_profile()==DEFAULT
    for invalid in ({'version':1,'cover_zero_origin':1},{'version':True,'cover_zero_origin':False},
                    {'version':2,'cover_zero_origin':True},{**DEFAULT,'font':'Arial'}):
        with pytest.raises(ValueError):validate_profile(invalid)


@pytest.mark.parametrize("profile", [{"version":1,"cover_zero_origin":True},
                                     {"version":2,"cover_zero_origin":True,"divider_wrap_none":True},
                                     {**DEFAULT,"cover_zero_origin":True,"cover_metrics":[{"anchor":"A1234567","signature":"a"*64,"line":296,"y_delta":-4.34}]}])
def test_final_and_section_pdf_boundaries_resolve_profile_and_limit_cover_scope(tmp_path,monkeypatch,profile):
    from app import monthly_report_docx as output, monthly_report_preview as preview
    from app.monthly_report_model import ReportPeriod, synthetic_draft
    draft=synthetic_draft(synthetic_profiles()[0],ReportPeriod(2026,9))
    monkeypatch.setattr(designs,'render_profile_for',lambda p:dict(profile))
    monkeypatch.setattr(output,'assemble_docx',lambda *a,**kw:b'native-download')
    monkeypatch.setattr(preview,'section_preview_docx',lambda *a,**kw:b'native-preview')
    calls=[]
    converted_document=Document()
    converted_document.add_paragraph('conversion-only')
    conversion=BytesIO(); converted_document.save(conversion)
    def render(raw,*,profile):
        calls.append((raw,profile));return conversion.getvalue()
    monkeypatch.setattr(output,'rendering_docx',render)
    monkeypatch.setattr(preview,'rendering_docx',render)
    def convert(path):
        assert Document(path).paragraphs[0].text=='conversion-only'
        result=tmp_path/'converted.pdf'
        pdf=fitz.open();pdf.new_page();pdf.save(result);pdf.close()
        return result
    monkeypatch.setattr(output.pdf_converter,'convert_to_pdf',convert)
    package=output.generate_report(draft)
    assert package.docx==b'native-download' and package.pdf
    preview.preview_section(draft,'cover')
    preview.preview_section(draft,'training')
    section_profile={**profile,'cover_zero_origin':False}
    if 'cover_metrics' in section_profile:
        section_profile['cover_metrics']=[]
    assert calls==[(b'native-download',profile),(b'native-preview',profile),(b'native-preview',section_profile)]


def test_oversized_cover_images_are_checked_before_any_pixel_decoding(monkeypatch):
    from app.monthly_report_render_profile import _pdf_evidence
    class Page:
        def get_text(self):return 'Synthetic report cover text'
        def get_images(self,full):return [(1,0,100_000,100_000)]
        def get_image_info(self,**kwargs):raise AssertionError('Oversized image decoded')
    class Pdf:
        is_encrypted=False
        metadata={'producer':'Synthetic'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def __len__(self):return 1
        def __getitem__(self,index):return Page()
    monkeypatch.setattr(fitz,'open',lambda path:Pdf())
    assert _pdf_evidence('synthetic.pdf')['images']==[]


def divider_pair(tmp_path, *, full_pixels=False, duplicate=False, origin=49):
    from docx.oxml.ns import qn
    source, pdf = pair(tmp_path, origin=origin)
    image = Image.new('RGB', (900, 650))
    image.putdata([(x % 251, y % 239, (x + 2 * y) % 241) for y in range(650) for x in range(900)])
    raw = BytesIO(); image.save(raw, format='PNG')
    document = Document(source)
    paragraph = document.add_paragraph('MONTHLY SCORECARDS')
    anchor = paragraph.add_run().add_picture(BytesIO(raw.getvalue()), width=Pt(692.1), height=Pt(624.45))._inline
    anchor.tag = qn('wp:anchor')
    position = OxmlElement('wp:positionV'); position.set('relativeFrom', 'page')
    offset = OxmlElement('wp:posOffset'); offset.text = '19050'; position.append(offset); anchor.insert(0, position)
    anchor.append(OxmlElement('wp:wrapTopAndBottom'))
    crop = OxmlElement('a:srcRect'); crop.set('l', '20000')
    anchor.find('.//' + qn('pic:blipFill')).append(crop)
    for color in ('D6EF4B', '547E7E'):
        fill = OxmlElement('a:solidFill'); node = OxmlElement('a:srgbClr'); node.set('val', color); fill.append(node); anchor.append(fill)
    document.save(source)
    supplied = image if full_pixels else image.crop((180, 0, 900, 650))
    buffer = BytesIO(); supplied.save(buffer, format='PNG')
    with fitz.open(pdf) as document:
        for _ in range(2 if duplicate else 1):
            page = document.new_page(width=612, height=792)
            box = fitz.Rect(-170.25, 1.5, 612, 553.65) if full_pixels else fitz.Rect(-81.4, 1.5, 610.7, 625.95)
            page.insert_image(box, stream=buffer.getvalue(), keep_proportion=False)
        target = tmp_path / 'with-divider.pdf'; document.save(target)
    return source, target


@pytest.mark.parametrize('full_pixels,duplicate,origin,expected', [
    (False, False, 49, True), (True, False, 0, False), (False, True, 0, False)])
def test_divider_crop_geometry_proof_is_independent_and_unambiguous(tmp_path, full_pixels, duplicate, origin, expected):
    source, pdf = divider_pair(tmp_path, full_pixels=full_pixels, duplicate=duplicate, origin=origin)
    result = calibrate(source, pdf)
    assert result['render_profile']['divider_wrap_none'] is expected
    assert result['render_profile']['cover_zero_origin'] is (origin == 0)
    assert bool(result['divider_measurements']) is expected


def test_version_one_profile_identity_is_not_silently_upgraded():
    import hashlib
    from app.monthly_report_render_profile import identity, LEGACY_DEFAULT
    profile = {'version': 1, 'cover_zero_origin': True}
    assert validate_profile(profile) == profile
    assert validate_profile(LEGACY_DEFAULT) == LEGACY_DEFAULT
    original_payload = {'source_sha256': 'a' * 64, 'companion_sha256': 'b' * 64, 'render_profile': profile}
    expected = hashlib.sha256(json.dumps(original_payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert identity('a' * 64, 'b' * 64, profile) == expected
    assert identity('a' * 64, 'b' * 64, {**profile, 'version': 2, 'divider_wrap_none': False}) != expected


def test_divider_worker_rejects_large_metadata_before_any_pixel_decode():
    from app.monthly_report_render_profile import _pdf_divider_images
    class Page:
        def get_images(self, full): return [(1, 0, 100_000, 100_000, 8, '', '', '', '', 0)]
        def get_image_info(self, **kwargs): raise AssertionError('Unexpected pixel/placement request')
    class Pdf:
        def __len__(self): return 1
        def __getitem__(self, index): return Page()
        def extract_image(self, xref): raise AssertionError('Oversized image decoded')
    assert _pdf_divider_images(Pdf(), [{'aspect': 1, 'width': 600, 'height': 600, 'y': 0}]) == []


@pytest.mark.parametrize("legacy_flags", [{"version": 1, "cover_zero_origin": True},
                                          {"version": 2, "cover_zero_origin": True, "divider_wrap_none": True}])
def test_existing_version_one_paired_metadata_resolves_without_repinning(tmp_path, monkeypatch, legacy_flags):
    import hashlib
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'data'))
    source, companion = pair(tmp_path)
    profile = synthetic_profiles()[0]
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    pdf_hash = hashlib.sha256(companion.read_bytes()).hexdigest()
    metadata = {'source_sha256': source_hash, 'companion_sha256': pdf_hash, 'render_profile': legacy_flags}
    original_digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    directory = designs._directory(profile.contract)
    (directory / 'metadata').mkdir(parents=True)
    (directory / (source_hash + '.docx')).write_bytes(source.read_bytes())
    (directory / (pdf_hash + '.pdf')).write_bytes(companion.read_bytes())
    metadata_path = directory / 'metadata' / (original_digest + '.json')
    metadata_path.write_text(json.dumps({'schema': 1, 'hash': original_digest, **metadata}))
    before = metadata_path.read_bytes()
    pinned = replace(profile, template=designs.PREFIX + original_digest)
    assert designs.render_profile_for(pinned) == legacy_flags
    assert designs.source_for(pinned).read_bytes() == source.read_bytes()
    assert designs.pin(pinned) == pinned
    assert metadata_path.read_bytes() == before


def color_pair(tmp_path, *, color_mode='white', source_mode='eligible'):
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn
    from lxml import etree
    source, pdf = pair(tmp_path, origin=49)
    document = Document(source)
    style = document.styles.add_style('Divider', WD_STYLE_TYPE.PARAGRAPH)
    properties = style.element.get_or_add_rPr()
    fill = OxmlElement('w14:textFill'); solid = OxmlElement('w14:solidFill'); rgb = OxmlElement('w14:srgbClr')
    rgb.set(qn('w14:val'), 'FFFFFF'); solid.append(rgb); fill.append(solid); properties.append(fill)
    color = OxmlElement('w:color'); color.set(qn('w:val'), '000000' if source_mode == 'explicit' else 'auto'); properties.append(color)
    if source_mode == 'transparent':
        alpha = OxmlElement('w14:alpha'); alpha.set(qn('w14:val'), '50000'); rgb.append(alpha)
    if source_mode in {'ordinary', 'inheritedordinary'}:
        selected = 'Divider'
        if source_mode == 'inheritedordinary':
            derived = document.styles.add_style('InheritedDivider', WD_STYLE_TYPE.PARAGRAPH)
            derived.base_style = style
            selected = 'InheritedDivider'
        document.add_paragraph('MONTHLY SCORECARDS', style=selected)
    else:
        drawing = OxmlElement('w:pict'); shape = etree.SubElement(drawing, '{urn:schemas-microsoft-com:vml}shape')
        textbox = etree.SubElement(shape, qn('w:txbxContent')); paragraph = etree.SubElement(textbox, qn('w:p'))
        props = etree.SubElement(paragraph, qn('w:pPr')); selected_style = etree.SubElement(props, qn('w:pStyle')); selected_style.set(qn('w:val'), 'Divider')
        run = etree.SubElement(paragraph, qn('w:r')); etree.SubElement(run, qn('w:t')).text = 'MONTHLY SCORECARDS'
        document.add_paragraph().add_run()._r.append(drawing)
    document.save(source)
    with fitz.open(pdf) as output:
        for _ in range(2 if color_mode == 'duplicate' else 1):
            page = output.new_page(width=612, height=792)
            page.draw_rect(fitz.Rect(0, 580, 612, 760), color=None, fill=(.3, .5, .5))
            color = (0, 0, 0) if color_mode == 'black' else (1, 1, 1)
            if color_mode == 'mixed':
                page.insert_text((50, 650), 'MONTHLY', fontsize=32, color=(1, 1, 1))
                page.insert_text((240, 650), 'SCORECARDS', fontsize=32, color=(0, 0, 0))
            elif color_mode != 'missing':
                page.insert_text((50, 650), 'MONTHLY SCORECARDS', fontsize=32, color=color,
                                 render_mode=3 if color_mode == 'invisible' else 0)
            if color_mode == 'occluded':
                page.draw_rect(fitz.Rect(0, 580, 612, 760), color=None, fill=(.3, .5, .5), overlay=True)
        target = tmp_path / 'title-color.pdf'; output.save(target)
    return source, target


@pytest.mark.parametrize('color_mode,expected', [('white', True), ('black', False), ('mixed', False),
                                                ('duplicate', False), ('missing', False), ('invisible', False), ('occluded', False)])
def test_divider_white_title_requires_visible_unambiguous_companion_text(tmp_path, color_mode, expected):
    source, pdf = color_pair(tmp_path, color_mode=color_mode)
    result = calibrate(source, pdf)
    assert result['render_profile']['divider_white_text'] is expected
    assert result['render_profile']['cover_zero_origin'] is False
    assert result['render_profile']['divider_wrap_none'] is False
    assert bool(result['divider_title_measurements']) is expected


@pytest.mark.parametrize('source_mode', ['explicit', 'transparent', 'ordinary', 'inheritedordinary'])
def test_divider_color_calibration_never_overrides_explicit_or_unrecognized_source(tmp_path, source_mode):
    source, pdf = color_pair(tmp_path, source_mode=source_mode)
    assert not calibrate(source, pdf)['render_profile']['divider_white_text']


def test_version_two_profile_identity_is_not_upgraded_by_color_feature():
    import hashlib
    from app.monthly_report_render_profile import identity
    value = {'version': 2, 'cover_zero_origin': False, 'divider_wrap_none': True}
    assert validate_profile(value) == value
    payload = {'source_sha256': 'a' * 64, 'companion_sha256': 'b' * 64, 'render_profile': value}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert identity('a' * 64, 'b' * 64, value) == expected
