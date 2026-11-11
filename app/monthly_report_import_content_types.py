"""Concise, source-grounded editability labels for starting-report review.

These labels describe what the current editor can actually change. An image
may contain visible words, but a raster image is not editable Word text and
no automatic OCR result is implied. Classification never changes routing,
asset approval, source identity or generated report content.
"""
from collections import Counter


def content_type_summary(items):
    """One optional line differentiating imported source capabilities."""
    counts = Counter(item.kind for item in items)
    if not any(counts[kind] for kind in ("table", "image", "unsupported", "native_layout")):
        return ""

    def quantity(number, singular, plural):
        return f"{number} {singular if number == 1 else plural}"

    parts = []
    if counts["text"]:
        parts.append(quantity(counts["text"], "editable text item", "editable text items"))
    if counts["table"]:
        parts.append(quantity(counts["table"], "editable Word table", "editable Word tables"))
    if counts["image"]:
        parts.append(quantity(counts["image"], "image-only picture", "image-only pictures"))
    # Native-layout inventory may include drawings rather than row-based
    # tables. It is never evidence that Word shapes are individually editable.
    drawings = sum(
        item.kind == "native_layout" and bool(item.text.strip())
        for item in items
    )
    uncertain = counts["unsupported"] + drawings
    if uncertain:
        parts.append(quantity(uncertain, "drawing/embedded item to review",
                              "drawing/embedded items to review"))
    return "Source content: " + " · ".join(parts) + "."


def picture_review_caption(item):
    """A readable image purpose without inventing its identity or OCR text."""
    role = getattr(item, "image_role", "")
    description = {
        "brand_logo": "ENFRA logo image",
        "client_logo": "Client logo image",
        "logo": "Logo image (owner unconfirmed)",
        "header_artwork": "Header artwork image",
    }.get(role, "Imported picture")
    return description + " · Image only; text inside is not editable. Replace the picture to update it."


def unsupported_content_guidance(items):
    """Explain the actual fallback, never promise a table or extracted OCR."""
    if not any(item.kind == "unsupported" for item in items):
        return ""
    return (
        "Unsupported drawing or embedded content is not an editable table. "
        "Check its original-page preview or use a clear replacement."
    )
