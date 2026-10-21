from dataclasses import replace
from io import BytesIO
from hashlib import sha256

import pytest
from docx import Document
from docx.shared import Inches
from docx.oxml.ns import qn
from PIL import Image

from app.monthly_report_asset_layout import document_page_indexes, picture_runs
from app.monthly_report_model import ReportSource, ResolvedBlock


def image(size, color):
    out = BytesIO(); Image.new('RGB', size, color).save(out, 'PNG')
    raw = out.getvalue()
    return sha256(raw).hexdigest()+'.png', raw


def payload():
    assets = dict((image((600,180),'navy'), image((850,1100),'white'), image((400,200),'green')))
    refs = tuple(assets)
    source = ReportSource('pdf-source', 'report.pdf', 'a'*64, '.pdf',
                          page_texts=('Synthetic service evidence',), selected_pages=(1,))
    reference = f'{source.id}:1:{source.fingerprint}'
    block = ResolvedBlock('improvements','This month',asset_hashes=refs,
                          asset_captions=('Photo A','Service page','Photo B'),
                          references=(reference,),asset_provenance=((refs[1],(reference,)),),photos_per_page=3)
    return block, source, assets


def test_exact_mapping_only_and_ordered_mixed_runs():
    block, source, _ = payload()
    assert document_page_indexes(block,(source,)) == {1}
    assert tuple(picture_runs(block,(source,))) == ((False,(0,)),(True,(1,)),(False,(2,)))
    assert document_page_indexes(replace(block, asset_hashes=tuple(reversed(block.asset_hashes))),(source,)) == {1}


@pytest.mark.parametrize('change', ['missing','other_asset','duplicate_map','duplicate_reference','outside_block','stale_source','jpeg','unselected','out_of_range','marker_only','asset_changed','duplicate_source'])
def test_untrusted_or_missing_mapping_does_not_expand(change):
    block, source, _ = payload(); sources=(source,)
    ref=block.references[0]; asset=block.asset_hashes[1]
    if change=='missing': block=replace(block,asset_provenance=())
    elif change=='other_asset': block=replace(block,asset_provenance=(('0'*64+'.png',(ref,)),))
    elif change=='duplicate_map': block=replace(block,asset_provenance=block.asset_provenance*2)
    elif change=='duplicate_reference': block=replace(block,asset_provenance=((asset,(ref,ref)),))
    elif change=='outside_block': block=replace(block,references=())
    elif change=='stale_source': sources=(replace(source,service_date='2026-10-02'),)
    elif change=='jpeg': sources=(replace(source,suffix='.jpg'),)
    elif change=='unselected': sources=(replace(source,selected_pages=()),)
    elif change=='out_of_range':
        ref=f'{source.id}:2:{source.fingerprint}';block=replace(block,references=(ref,),asset_provenance=((asset,(ref,)),))
    elif change=='marker_only': block=replace(block,asset_provenance=((asset,('asset-source-context:v1:pdf-source:1:'+'a'*64,)),))
    elif change=='asset_changed': block=replace(block,asset_hashes=(block.asset_hashes[0],'b'*64+'.png',block.asset_hashes[2]))
    elif change=='duplicate_source': sources=(source,source)
    assert document_page_indexes(block,sources)==set()


def test_native_mixed_pages_keep_photo_frames_order_captions_and_input(tmp_path):
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_native_layout import build_native_docx
    block, source, assets=payload()
    document=Document();document.add_heading('MONTHLY ACTIVITY SUMMARY',1)
    document.add_paragraph('Improvement Highlights and Pics')
    document.add_picture(BytesIO(next(iter(assets.values()))),width=Inches(6),height=Inches(1.8))
    document.add_picture(BytesIO(next(iter(assets.values()))),width=Inches(4),height=Inches(2))
    path=tmp_path/'source.docx';document.save(path)
    current=replace(draft(block),sources=(source,));before=current.fingerprint
    for section in (None,'activity',None):
        raw=build_native_docx(current,path,asset_loader=assets.__getitem__,section_key=section)
        output=Document(BytesIO(raw)); shapes=list(output.inline_shapes)
        assert len(shapes)==3
        assert shapes[0].width==Inches(6) and shapes[0].height==Inches(1.8)
        assert shapes[1].width>Inches(5) and shapes[1].height>Inches(6)
        assert shapes[2].width==Inches(4) and shapes[2].height==Inches(2)
        pictures=[p for p in output.paragraphs if p._p.find('.//'+qn('wp:inline')) is not None]
        assert pictures[1].paragraph_format.page_break_before
        assert pictures[2].paragraph_format.page_break_before
        assert [p.text for p in output.paragraphs if p.text in block.asset_captions]==list(block.asset_captions)
        assert current.fingerprint==before
        assert [sha256(output.part.related_parts[s._inline.graphic.graphicData.pic.blipFill.blip.embed].blob).hexdigest()+'.png' for s in shapes]==list(block.asset_hashes)


def test_generic_mixed_run_emits_original_document_not_grid_and_keeps_receipts():
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_docx import _build_docx, outline
    block, source, assets=payload()
    current=replace(draft(block),sources=(source,));before=current.fingerprint
    raw=_build_docx(current,asset_loader=assets.__getitem__)
    output=Document(BytesIO(raw))
    matches=[s for s in output.inline_shapes if output.part.related_parts[s._inline.graphic.graphicData.pic.blipFill.blip.embed].blob==assets[block.asset_hashes[1]]]
    assert len(matches)==1 and matches[0].width>Inches(5) and matches[0].height>Inches(6)
    assert current.fingerprint==before
    assert outline(current)[0][2]==4  # divider estimate + photo / document / photo
    assert 'Service page' in [p.text for p in output.paragraphs]


def test_pending_document_still_blocks_generation():
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_checks import preflight
    block, source, assets=payload()
    assert document_page_indexes(block,(source,))=={1}
    checks=preflight(replace(draft(block),sources=(source,)))
    assert any(c.code=='client_pages' and c.blocking for c in checks)


def test_identical_portrait_photo_without_exact_page_mapping_stays_photo():
    block, source, _=payload()
    unmapped=replace(block,asset_provenance=(),references=(),photos_per_page=3)
    assert tuple(picture_runs(unmapped,(source,)))==((False,(0,1,2)),)


def test_document_only_accepts_native_section_without_photo_frame(tmp_path):
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_native_layout import build_native_docx
    block, source, assets=payload()
    block=replace(block,asset_hashes=(block.asset_hashes[1],),asset_captions=('Service page',))
    document=Document(); document.add_heading('MONTHLY ACTIVITY SUMMARY',1)
    document.add_paragraph('Old narrative')
    path=tmp_path/'no-photo.docx';document.save(path)
    output=Document(BytesIO(build_native_docx(replace(draft(block),sources=(source,)),path,asset_loader=assets.__getitem__)))
    assert len(output.inline_shapes)==1 and output.inline_shapes[0].width>Inches(5)
    picture=next(p for p in output.paragraphs if p._p.find('.//'+qn('wp:inline')) is not None)
    assert not picture.paragraph_format.page_break_before


def test_retained_original_native_art_is_not_reflowed(tmp_path):
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_native_layout import build_native_docx
    from app.monthly_report_import import inspect_docx, map_items, ImportMapping
    block, source, assets=payload();raw=assets[block.asset_hashes[1]]
    document=Document();document.add_heading('MONTHLY ACTIVITY SUMMARY',1)
    document.add_paragraph('Improvement Highlights and Pics')
    document.add_picture(BytesIO(raw),width=Inches(1.4),height=Inches(1.8))
    path=tmp_path/'retained.docx';document.save(path)
    inspection=inspect_docx(path);item=next(i for i in inspection.items if i.kind=='image')
    mapped=map_items(path,inspection,(ImportMapping(item.id,'improvements'),))
    original=mapped.blocks[0];reference=f'{source.id}:1:{source.fingerprint}'
    original=replace(original,references=(*original.references,reference),asset_provenance=((original.asset_hashes[0],(reference,)),))
    assert document_page_indexes(original,(source,))=={0}
    output=Document(BytesIO(build_native_docx(replace(draft(original),sources=(source,)),path,asset_loader=dict(mapped.assets).__getitem__)))
    assert len(output.inline_shapes)==1
    assert output.inline_shapes[0].width==Inches(1.4) and output.inline_shapes[0].height==Inches(1.8)


def test_multiple_document_pages_landscape_section_keep_order(tmp_path):
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_native_layout import build_native_docx
    block, source, assets=payload();source=replace(source,page_texts=('One','Two'),selected_pages=(1,2))
    another,raw=image((1100,850),'purple');assets[another]=raw
    refs=(f'{source.id}:1:{source.fingerprint}',f'{source.id}:2:{source.fingerprint}')
    block=replace(block,asset_hashes=(block.asset_hashes[1],another),asset_captions=('Page one','Page two'),references=refs,
                  asset_provenance=((block.asset_hashes[1],(refs[0],)),(another,(refs[1],))))
    document=Document();document.sections[0].page_width=Inches(11);document.sections[0].page_height=Inches(8.5)
    document.add_heading('MONTHLY ACTIVITY SUMMARY',1);document.add_paragraph('Old narrative')
    path=tmp_path/'landscape.docx';document.save(path)
    output=Document(BytesIO(build_native_docx(replace(draft(block),sources=(source,)),path,asset_loader=assets.__getitem__)))
    assert len(output.inline_shapes)==2
    assert output.inline_shapes[1].width>Inches(6)
    assert all(s.height<Inches(7) for s in output.inline_shapes)
    assert [p.text for p in output.paragraphs if p.text in block.asset_captions]==list(block.asset_captions)


@pytest.mark.parametrize('sequence', [(0,1),(1,2),(0,2,1),(1,)])
def test_native_edge_order_and_single_available_frame(tmp_path,sequence):
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_native_layout import build_native_docx
    block,source,assets=payload()
    block=replace(block,asset_hashes=tuple(block.asset_hashes[i] for i in sequence),
                  asset_captions=tuple(block.asset_captions[i] for i in sequence))
    document=Document();document.add_heading('MONTHLY ACTIVITY SUMMARY',1)
    document.add_paragraph('Improvement Highlights and Pics')
    document.add_picture(BytesIO(next(iter(assets.values()))),width=Inches(6),height=Inches(1.8))
    path=tmp_path/'single.docx';document.save(path)
    raw=build_native_docx(replace(draft(block),sources=(source,)),path,asset_loader=assets.__getitem__)
    output=Document(BytesIO(raw));shapes=list(output.inline_shapes)
    assert len(shapes)==len(sequence)
    assert [sha256(output.part.related_parts[s._inline.graphic.graphicData.pic.blipFill.blip.embed].blob).hexdigest()+'.png' for s in shapes]==list(block.asset_hashes)
    assert [p.text for p in output.paragraphs if p.text in block.asset_captions]==list(block.asset_captions)
    assert shapes[sequence.index(1)].height>Inches(6)


def test_duplicate_asset_occurrences_do_not_infer_document_intent():
    block,source,_=payload()
    block=replace(block,asset_hashes=(block.asset_hashes[1],block.asset_hashes[1]),asset_captions=('One','Other'))
    assert not document_page_indexes(block,(source,))


def test_shared_photo_and_document_bytes_keep_document_preview_fidelity():
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_asset_layout import photo_preview_references
    block,source,_=payload()
    cover=ResolvedBlock('cover_photo','This month',asset_hashes=(block.asset_hashes[1],))
    current=replace(draft(block,cover),sources=(source,))
    assert photo_preview_references(current)=={block.asset_hashes[0],block.asset_hashes[2]}
    assert document_page_indexes(cover,(source,))==set()


def test_trailing_empty_native_paragraph_budget_preserves_boundary_and_stops_at_content():
    from app.monthly_report_native_pages import NativePages
    from docx.shared import Pt
    from docx.enum.text import WD_BREAK
    document=Document();origin=document.add_paragraph('Current picture')
    empty=document.add_paragraph();empty.paragraph_format.space_after=Pt(9)
    empty.add_run().font.size=Pt(12)
    boundary=document.add_paragraph();boundary.add_run().add_break(WD_BREAK.PAGE)
    document.add_paragraph('Next section content')
    before=document._element.xml
    # No page owner mutation is involved in this read-only sizing operation.
    budget=NativePages.trailing_picture_space(None,document,origin._p)
    assert budget >= (12*1.2+9)*20
    assert document._element.xml==before
    assert NativePages.trailing_picture_space(None,document,boundary._p)==0


from tests.conftest import requires_libreoffice


@requires_libreoffice
def test_rendered_document_tail_has_no_new_blank_page(tmp_path):
    import fitz
    from docx.enum.text import WD_BREAK
    from tests.test_monthly_report_native_layout import draft
    from app.monthly_report_native_layout import build_native_docx
    from app.pdf_converter import convert_to_pdf
    block,source,assets=payload()
    block=replace(block,asset_hashes=block.asset_hashes[:2],asset_captions=block.asset_captions[:2])
    document=Document()
    from docx.shared import Pt
    section=document.sections[0]
    section.page_width=Inches(8.5);section.page_height=Inches(11)
    section.top_margin=section.bottom_margin=Inches(.7)
    section.left_margin=section.right_margin=Inches(.8)
    document.styles['Normal'].font.name='Arial'
    document.styles['Normal'].font.size=Pt(11)
    document.styles['Normal'].paragraph_format.space_after=Pt(7)
    document.add_heading('MONTHLY ACTIVITY SUMMARY',1)
    document.add_paragraph('Retained activity narrative')
    document.add_paragraph('Improvement Highlights and Pics')
    document.add_picture(BytesIO(next(iter(assets.values()))),width=Inches(6),height=Inches(1.8))
    document.add_paragraph();document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    document.add_heading('TRAINING SUMMARY',1);document.add_paragraph('Old training')
    path=tmp_path/'tail-source.docx';document.save(path)
    from app.monthly_report_import import inspect_docx,map_items,ImportMapping
    inspection=inspect_docx(path)
    text=next(item for item in inspection.items if item.kind=='text' and item.text=='Retained activity narrative')
    retained=map_items(path,inspection,(ImportMapping(text.id,'activity_summary'),)).blocks[0]
    current=replace(draft(retained,block,ResolvedBlock('training_summary','This month',text='Current training')),sources=(source,))
    for scope,expected in (('activity',2),(None,3)):
        raw=build_native_docx(current,path,asset_loader=assets.__getitem__,section_key=scope)
        out=tmp_path/f'tail-{scope}.docx';out.write_bytes(raw)
        output=convert_to_pdf(out)
        try:
            with fitz.open(output) as pdf:
                assert len(pdf)==expected, f"{scope}: expected {expected} pages, got {len(pdf)}"
                assert 'Service page' in pdf[1].get_text()
                if scope is None: assert 'Current training' in pdf[2].get_text()
        finally:
            output.unlink(missing_ok=True)


@pytest.mark.parametrize('inherited',[False,True])
def test_tail_budget_stops_before_effective_next_page_paragraph(inherited):
    from app.monthly_report_native_pages import NativePages
    from docx.shared import Pt
    from docx.enum.style import WD_STYLE_TYPE
    document=Document();origin=document.add_paragraph('Current picture')
    boundary=document.add_paragraph()
    if inherited:
        style=document.styles.add_style('Synthetic next page',WD_STYLE_TYPE.PARAGRAPH)
        style.paragraph_format.page_break_before=True
        style.paragraph_format.space_before=Pt(600)
        boundary.style=style
    else:
        boundary.paragraph_format.page_break_before=True
        boundary.paragraph_format.space_before=Pt(600)
    document.add_paragraph().paragraph_format.space_after=Pt(600)
    before=document._element.xml
    assert NativePages.trailing_picture_space(None,document,origin._p)==0
    assert document._element.xml==before
