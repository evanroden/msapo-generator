from copy import deepcopy
import pytest
from lxml import etree as E
from app.monthly_report_cover_metrics import NS,W
from app.monthly_report_divider_metrics import candidates,apply_divider_metrics,validate_records


def fixture():
    namespaces = ' '.join(f'xmlns:{key}="{value}"' for key,value in NS.items())
    root = E.fromstring(f'''<w:document {namespaces}><w:body><w:p><w:r><w:drawing>
      <wp:anchor><wp:extent cx="8000000" cy="8000000"/><a:blip/>
      <a:solidFill><a:srgbClr val="D6EF4B"/></a:solidFill>
      <a:solidFill><a:srgbClr val="547E7E"/></a:solidFill></wp:anchor>
      <wp:anchor wp14:anchorId="1234ABCD"><wp:positionV relativeFrom="page"><wp:posOffset>5000000</wp:posOffset></wp:positionV>
      <wp:extent cx="2500000" cy="3500000"/><a:graphic><a:graphicData><wps:wsp>
      <wps:spPr><a:xfrm><a:ext cx="2500000" cy="3500000"/></a:xfrm><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>
      <wps:txbx><w:txbxContent><w:p><w:r><w:rPr><w:sz w:val="420"/><w:spacing w:val="-400"/><w:color w:val="D6EF4B"/></w:rPr><w:t>10</w:t></w:r></w:p></w:txbxContent></wps:txbx>
      <wps:bodyPr anchor="t"><a:noAutofit/></wps:bodyPr></wps:wsp></a:graphicData></a:graphic></wp:anchor>
      </w:drawing></w:r><w:r><w:t>MONTHLY SCORECARDS</w:t></w:r></w:p></w:body></w:document>''')
    styles = E.fromstring(f'<w:styles {namespaces}><w:style w:styleId="Normal"><w:rPr><w:rFonts w:ascii="Arial"/></w:rPr></w:style></w:styles>')
    return root,styles


def record(item,**changes):
    return {'anchor':item['anchor'],'signature':item['signature'],'line':None,
            'y_delta':8.87,'terminal_tracking':True,**changes}


def test_verified_number_compensates_exact_terminal_tracking_without_changing_glyphs():
    root,styles=fixture();original=deepcopy(root);item=candidates(root,styles)[0]
    text_before=E.tostring(item['element'].find('.//w:txbxContent',NS))
    assert not apply_divider_metrics(root,styles,[])
    assert apply_divider_metrics(root,styles,[record(item)])
    anchor=root.find('.//wp:anchor[@wp14:anchorId]',NS)
    assert anchor.find('wp:extent',NS).get('cx')=='2754000'
    assert anchor.find('wp:extent',NS).get('cy')=='3500000'
    assert anchor.find('wp:positionV/wp:posOffset',NS).text==str(5000000+round(8.87*12700))
    assert E.tostring(anchor.find('.//w:txbxContent',NS))==text_before
    assert not apply_divider_metrics(root,styles,[record(item)])
    assert original.find('.//wp:anchor[@wp14:anchorId]/wp:extent',NS).get('cx')=='2500000'


@pytest.mark.parametrize('change',['font','text','width','tracking','visible_fill','visible_line','nondivider'])
def test_old_measurements_cannot_override_edited_master_or_visible_shapes(change):
    root,styles=fixture();item=candidates(root,styles)[0];anchor=item['element']
    if change=='font':styles.find('.//w:rFonts',NS).set(W+'ascii','Different Font')
    elif change=='text':anchor.find('.//w:t',NS).text='11'
    elif change=='width':anchor.find('wp:extent',NS).set('cx','2600000')
    elif change=='tracking':anchor.find('.//w:spacing',NS).set(W+'val','-200')
    elif change=='visible_fill':anchor.find('.//wps:spPr/a:noFill',NS).tag='{'+NS['a']+'}solidFill'
    elif change=='visible_line':anchor.find('.//a:ln/a:noFill',NS).tag='{'+NS['a']+'}solidFill'
    elif change=='nondivider':root.find('.//w:body/w:p/w:r/w:t',NS).text='Vendor technical data'
    before=E.tostring(root)
    assert not apply_divider_metrics(root,styles,[record(item)])
    assert E.tostring(root)==before


@pytest.mark.parametrize('changes',[{'y_delta':float('nan')},{'y_delta':21},{'terminal_tracking':1},
    {'line':179},{'signature':'guess'},{'anchor':'unknown'}])
def test_records_reject_unbounded_or_unverified_values(changes):
    root,styles=fixture();item=candidates(root,styles)[0]
    with pytest.raises(ValueError):validate_records([record(item,**changes)])
