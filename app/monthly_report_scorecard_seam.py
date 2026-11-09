"""Fill a proved native Scorecards divider seam without changing source artwork."""
from io import BytesIO
from PIL import Image
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu
from docx.text.paragraph import Paragraph

MARKER = 'msapo:scorecard-seam:v1'


def fill_scorecard_seam(document, root):
    """Add a bounded teal underlay to one positively identified divider.

    The caller must prove this root is a native Scorecards divider. Ambiguous
    anchors and off-page geometry are left untouched. The photo, number, and
    existing vector artwork remain distinct and are never replaced.
    """
    if root.getparent() is not document.element.body or root.tag != qn('w:p'):
        return False
    anchors=list(root.iter(qn('wp:anchor')))
    if any(node.get('descr') == MARKER for node in root.iter(qn('wp:docPr'))):
        return False
    photos=[]; bands=[]
    for anchor in anchors:
        size=anchor.find(qn('wp:extent')); vertical=anchor.find(qn('wp:positionV'))
        horizontal=anchor.find(qn('wp:positionH'))
        if size is None or vertical is None or horizontal is None:
            continue
        offset=vertical.find(qn('wp:posOffset'))
        if vertical.get('relativeFrom') != 'page' or offset is None:
            continue
        try:
            width=int(size.get('cx','0'));height=int(size.get('cy','0'));y=int(offset.text)
        except (TypeError,ValueError):
            continue
        colors={n.get('val','').upper() for n in anchor.iter(qn('a:srgbClr'))}
        blips=list(anchor.iter(qn('a:blip')))
        if (anchor.get('behindDoc') == '0' and horizontal.get('relativeFrom') in ('page', 'column')
                and len(blips)==1 and 6000000<=width<=15000000
                and 6000000<=height<=15000000 and 0<=y<=100000):
            photos.append(anchor)
        if (anchor.get('behindDoc') == '1' and horizontal.get('relativeFrom') == 'page'
                and not blips and 6000000<=width<=11000000 and 1000000<=height<=5000000
                and 6000000<=y<=10000000 and '547E7E' in colors
                and colors.intersection({'D6EF4B','D5EE4A','D4ED49','D3EC48'})):
            bands.append((anchor,width,y))
    if len(photos)!=1 or len(bands)!=1:
        return False
    _,width,top=bands[0]
    # Keep the underlay bounded to the lower 2 inches above the existing band;
    # a foreground photo covers it. It does not overlap the band's underline.
    gap_height=min(top, 1828800)
    stream=BytesIO();Image.new('RGB',(2,2),(84,126,126)).save(stream,'PNG')
    paragraph=Paragraph(root,document._body)
    inline=paragraph.add_run().add_picture(BytesIO(stream.getvalue()),width=Emu(width),height=Emu(gap_height))._inline
    anchor=OxmlElement('wp:anchor')
    for key,value in {'distT':'0','distB':'0','distL':'0','distR':'0','simplePos':'0',
                      'relativeHeight':'0','behindDoc':'1','locked':'0','layoutInCell':'1','allowOverlap':'1'}.items():
        anchor.set(key,value)
    simple=OxmlElement('wp:simplePos');simple.set('x','0');simple.set('y','0');anchor.append(simple)
    for axis,coordinate in (('H',0),('V',top-gap_height)):
        position=OxmlElement('wp:position'+axis);position.set('relativeFrom','page')
        position_offset=OxmlElement('wp:posOffset');position_offset.text=str(coordinate)
        position.append(position_offset);anchor.append(position)
    anchor.append(inline.extent);anchor.append(OxmlElement('wp:wrapNone'))
    for child in list(inline):anchor.append(child)
    anchor.find(qn('wp:docPr')).set('descr',MARKER)
    inline.getparent().replace(inline,anchor)
    run=root[-1];root.remove(run);root.insert(1 if len(root) and root[0].tag==qn('w:pPr') else 0,run)
    return True
