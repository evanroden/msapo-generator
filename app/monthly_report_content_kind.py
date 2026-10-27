"""Display-only descriptions of inspected Word content; never infer OCR."""

from collections import Counter


def content_kind_description(item):
    return {
        "text": "Extracted Word text · review wording before including it.",
        "table": "Native Word table · extracted cells can be reviewed and mapped.",
        "image": "Picture · its text and cells are not directly editable. Image reading is a separate, optional step.",
        "unsupported": "Word layout requiring review · drawings or embedded content are not an editable table here.",
        "native_layout": "Native Word layout · design content, not an editable table here.",
    }.get(item.kind, "Content type not recognized · review the original.")


def section_content_description(items):
    counts = Counter(item.kind for item in items)
    labels = (("text", "text item", "text items"),
              ("table", "native table", "native tables"),
              ("image", "picture", "pictures"),
              ("native_layout", "native layout", "native layouts"),
              ("unsupported", "layout needing review", "layouts needing review"))
    parts = [f"{counts[kind]} {singular if counts[kind] == 1 else plural}"
             for kind, singular, plural in labels if counts[kind]]
    return "Imported content: " + " · ".join(parts) if parts else ""
