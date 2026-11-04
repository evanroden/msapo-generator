"""Make proven native divider background photographs monochrome in derivatives.

Only standalone, full-page JPEG DrawingML pictures in a previously recognized
native divider are eligible. Other artwork, alternate representations, and
original source assets are deliberately left alone.
"""
from io import BytesIO

from docx.oxml.ns import qn
from PIL import Image, ImageOps, UnidentifiedImageError

from app.ocr import _MAX_PIXELS_PER_FRAME

WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def monochrome_divider_photos(document, roots):
    """Update eligible live occurrences, never the shared source image part."""
    for root in roots:
        if root.getparent() is not document.element.body:
            continue
        for anchor in root.iter(WP + 'anchor'):
            # Paired choice/fallback drawings must be handled together. Until
            # equivalent fallbacks are proven, leave both untouched.
            parent = anchor.getparent()
            alternate = False
            while parent is not None and parent is not root:
                alternate |= parent.tag == MC + 'AlternateContent'
                parent = parent.getparent()
            if alternate or any(n.tag == MC + 'AlternateContent' for n in anchor.iter()):
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
