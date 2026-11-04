"""Make proven native divider background photographs monochrome in derivatives.

Only standalone, full-page JPEG DrawingML pictures in a previously recognized
native divider are eligible. Other artwork, alternate representations, and
original source assets are deliberately left alone.
"""
from io import BytesIO

from docx.oxml.ns import qn
from PIL import Image, ImageOps, ImageChops, UnidentifiedImageError

from app.ocr import _MAX_PIXELS_PER_FRAME

WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _may_include_flattened_brand(image):
    """Leave obvious two-color branded composites untouched.

    This is a conservative screen, not proof an image has no branding.
    """
    sample = image.convert('RGB').resize((128, 128))
    palette = ((214, 239, 75), (84, 126, 126))
    counts = [0, 0]
    for pixel in sample.getdata():
        for index, color in enumerate(palette):
            if max(abs(channel - target) for channel, target in zip(pixel, color)) <= 20:
                counts[index] += 1
    return all(count >= 164 for count in counts)



def _has_already_gray_fallback(document, anchor, wrapper):
    """Leave the fallback untouched; act only when its sole image is gray."""
    choice=next((x for x in wrapper if x.tag==MC+'Choice'),None)
    fallback=next((x for x in wrapper if x.tag==MC+'Fallback'),None)
    if choice is None or fallback is None or anchor not in choice.iter():
        return False
    if len(list(choice.iter(A+'blip'))) != 1:
        return False
    vml='{urn:schemas-microsoft-com:vml}imagedata'
    images=list(fallback.iter(vml))
    if len(images)!=1 or list(fallback.iter(A+'blip')):
        return False
    rel=document.part.rels.get(images[0].get(R+'id'))
    if rel is None or rel.is_external:
        return False
    try:
        with Image.open(BytesIO(rel.target_part.blob)) as image:
            if image.width*image.height>_MAX_PIXELS_PER_FRAME:
                return False
            red, green, blue = image.convert('RGB').split()
            return (ImageChops.difference(red, green).getextrema()[1] <= 3
                    and ImageChops.difference(green, blue).getextrema()[1] <= 3)
    except (OSError,ValueError,Image.DecompressionBombError,UnidentifiedImageError):
        return False


def monochrome_divider_photos(document, roots):
    """Update eligible live occurrences, never the shared source image part."""
    for root in roots:
        if root.getparent() is not document.element.body:
            continue
        for anchor in root.iter(WP + 'anchor'):
            # Paired choice/fallback drawings must be handled together. Until
            # equivalent fallbacks are proven, leave both untouched.
            parent = anchor.getparent()
            wrappers = []
            while parent is not None and parent is not root:
                if parent.tag == MC + 'AlternateContent':
                    wrappers.append(parent)
                parent = parent.getparent()
            if any(n.tag == MC + 'AlternateContent' for n in anchor.iter()) or len(wrappers)>1:
                continue
            if wrappers and not _has_already_gray_fallback(document, anchor, wrappers[0]):
                continue
            extent = anchor.find(WP + 'extent')
            try:
                if extent is None or min(int(extent.get('cx', '0')), int(extent.get('cy', '0'))) <= 6000000:
                    continue
            except ValueError:
                continue
            blips = list(anchor.iter(A + 'blip'))
            if len(blips) != 1:
                continue
            blip = blips[0]
            rid = blip.get(R + 'embed')
            rel = document.part.rels.get(rid)
            if rel is None or rel.is_external or rel.target_part.content_type != 'image/jpeg':
                continue
            try:
                with Image.open(BytesIO(rel.target_part.blob)) as source:
                    if (source.format != 'JPEG' or source.width * source.height > _MAX_PIXELS_PER_FRAME
                            or min(source.size) < 800 or source.getexif().get(274, 1) != 1):
                        continue
                    if _may_include_flattened_brand(source):
                        continue
                    image = ImageOps.grayscale(source).convert('RGB')
                    output = BytesIO()
                    image.save(output, 'PNG')
            except (OSError, ValueError, Image.DecompressionBombError, UnidentifiedImageError):
                continue
            # Bind only this drawing and its matching Word editing layer. Never
            # replace bytes on the shared part (which may be used elsewhere).
            layer_nodes = [n for n in blip.iter() if n is not blip and n.get(R + 'embed')]
            if any(document.part.rels.get(n.get(R + 'embed')) is None or
                   document.part.rels[n.get(R + 'embed')].is_external or
                   document.part.rels[n.get(R + 'embed')].target_part.blob != rel.target_part.blob
                   for n in layer_nodes):
                continue
            new_rid, _ = document.part.get_or_add_image(BytesIO(output.getvalue()))
            blip.set(R + 'embed', new_rid)
            for node in layer_nodes:
                node.set(R + 'embed', new_rid)
