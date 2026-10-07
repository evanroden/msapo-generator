"""Bounded, deterministic chart and photo pages shared by preview and DOCX."""

from io import BytesIO
from pathlib import Path
import hashlib
import json

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.ocr import _MAX_PIXELS_PER_FRAME
from app.monthly_report_model import OrgChartNode, ReportTable

PAGE = (1400, 1540)  # 7 by 7.7 inches at print resolution; leaves room for headings.
INK = "#092b24"
MUTED = "#49635d"
LIME = "#dcf36b"
FONT_ROOT = Path("/usr/share/fonts/truetype/dejavu")


def contact_positions(draft):
    """Offer positions from this report's contact fields, never infer managers.

    Only recognizable name/role/site columns are read. Images, prose, vendor
    tables and other sites' directories are not a source of chart identities.
    A person with two roles/sites remains two separately selectable positions.
    """
    block = next((b for b in draft.blocks if b.key == "contact_matrix"), None)
    spec = next((b for s in draft.sections if s.included for b in s.blocks if b.key == "contact_matrix"), None)
    if block is None or spec is None or block.source == "Omit":
        return ()
    tables = (ReportTable(tuple(c.title for c in spec.columns), block.rows), *block.extra_tables)
    fields = {
        "name": {"name", "contact name", "full name"},
        "role": {"role", "position", "title", "role / position"},
        "team": {"facility", "site", "team", "site or team", "site / team"},
    }
    result = {}
    for table in tables:
        columns = [" ".join(c.casefold().split()) for c in table.columns]
        indices = {field: [i for i, c in enumerate(columns) if c in labels] for field, labels in fields.items()}
        if any(len(v) > 1 for v in indices.values()) or not (indices["name"] or indices["role"]):
            continue  # Ambiguous schemas stay in the contact editor for review.
        for row in table.rows:
            values = {field: row[ids[0]].strip() if ids and ids[0] < len(row) else "" for field, ids in indices.items()}
            if not (values["name"] or values["role"]):
                continue
            identity = tuple(" ".join(values[k].casefold().split()) for k in ("name", "role", "team"))
            key = "contact-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
            result.setdefault(key, OrgChartNode(key, **values))
    return tuple(result.values())


def font(size, bold=False):
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(str(FONT_ROOT / filename), size)
    except OSError:
        return ImageFont.load_default(size=size)


def wrapped(text, face, width, draw):
    lines, line = [], ""
    for word in str(text).split():
        # Split long unbroken words instead of painting outside the card.
        pieces, piece = [], ""
        for char in word:
            if piece and draw.textlength(piece + char, font=face) > width:
                pieces.append(piece)
                piece = ""
            piece += char
        pieces.append(piece)
        for piece in pieces:
            candidate = (line + " " + piece).strip()
            if line and draw.textlength(candidate, font=face) > width:
                lines.append(line)
                line = piece
            else:
                line = candidate
    return (*lines, line) if line else tuple(lines)


def png(image):
    output = BytesIO()
    image.save(output, "PNG", optimize=True)
    return output.getvalue()


def validate_org(nodes):
    if not nodes or len(nodes) > 60:
        raise ValueError("Add between 1 and 60 people or positions to this chart.")
    identities = {n.key for n in nodes}
    if len(identities) != len(nodes) or any(not n.key for n in nodes):
        raise ValueError("Each chart position needs its own identity.")
    by_key = {n.key: n for n in nodes}
    for node in nodes:
        if not (node.name.strip() or node.role.strip()):
            raise ValueError("Enter a name or role for each chart position.")
        if any(len(v) > 100 for v in (node.name, node.role, node.team)):
            raise ValueError(
                "Keep each chart name, role and team under 100 characters."
            )
        if node.reports_to and node.reports_to not in identities:
            raise ValueError(
                "Choose an existing manager or No manager for every position."
            )
        visited, cursor = set(), node
        while cursor:
            if cursor.key in visited:
                raise ValueError(
                    "The reporting lines form a loop. A person cannot report back to themselves."
                )
            visited.add(cursor.key)
            cursor = by_key.get(cursor.reports_to)


def org_groups(nodes):
    """Keep small hierarchies together; split larger teams into readable pages."""
    validate_org(nodes)
    children = {n.key: [c for c in nodes if c.reports_to == n.key] for n in nodes}

    def subtree(node):
        return (node, *(v for c in children[node.key] for v in subtree(c)))

    def depth(node):
        return 1 + max((depth(c) for c in children[node.key]), default=0)

    def leaves(node):
        return sum(leaves(c) for c in children[node.key]) or 1

    groups = []

    def split(node):
        if leaves(node) <= 4 and depth(node) <= 4:
            groups.append(subtree(node))
            return
        direct = children[node.key]
        for start in range(0, len(direct), 4):
            groups.append((node, *direct[start : start + 4]))
        for child in direct:
            if children[child.key]:
                split(child)

    for root in nodes:
        if not root.reports_to:
            split(root)
    return tuple(groups)


def org_page(nodes, index=0):
    groups = org_groups(nodes)
    group = groups[index]
    children = {n.key: [c for c in group if c.reports_to == n.key] for n in group}
    widths = {}

    def measure(node):
        widths[node.key] = sum(measure(c) for c in children[node.key]) or 1
        return widths[node.key]

    root = group[0]
    total = measure(root)
    positions = {}

    def place(node, left, level):
        positions[node.key] = (left + widths[node.key] / 2, level)
        for child in children[node.key]:
            place(child, left, level + 1)
            left += widths[child.key]

    place(root, 0, 0)
    page = Image.new("RGB", PAGE, "white")
    draw = ImageDraw.Draw(page)
    draw.text((40, 25), "Organization & reporting lines", font=font(36, True), fill=INK)
    draw.rectangle((40, 88, PAGE[0] - 40, 95), fill=LIME)
    draw.text(
        (40, PAGE[1] - 48),
        f"Team chart · {index + 1} of {len(groups)}",
        font=font(22),
        fill=MUTED,
    )
    width = min(520, (PAGE[0] - 100) / total - 28)
    boxes = {}
    # Every field wraps in full. Card height uses the actual text, no truncation.
    texts = {}
    heights = {}
    for node in group:
        lines = []
        for value, bold in ((node.name, True), (node.role, False), (node.team, False)):
            lines.extend(
                (line, bold)
                for line in wrapped(value, font(25, bold), width - 32, draw)
            )
        texts[node.key] = lines
        level = positions[node.key][1]
        heights[level] = max(heights.get(level, 0), 35 + 33 * len(lines))
    y = 160
    tops = {}
    for level in sorted(heights):
        tops[level] = y
        y += heights[level] + 80
    if y > PAGE[1] - 40:
        raise ValueError(
            "This chart has too much text for readable pages. Shorten roles/team labels."
        )
    for node in group:
        unit, level = positions[node.key]
        center = 50 + unit * (PAGE[0] - 100) / total
        boxes[node.key] = (
            center - width / 2,
            tops[level],
            center + width / 2,
            tops[level] + heights[level],
        )
    for node in group:
        if node.reports_to in boxes:
            parent, child = boxes[node.reports_to], boxes[node.key]
            x1, x2 = (parent[0] + parent[2]) / 2, (child[0] + child[2]) / 2
            mid = (parent[3] + child[1]) / 2
            draw.line(
                ((x1, parent[3]), (x1, mid), (x2, mid), (x2, child[1])),
                fill=MUTED,
                width=4,
            )
    for node in group:
        box = boxes[node.key]
        draw.rounded_rectangle(box, radius=14, fill="#edf3f0", outline=INK, width=3)
        draw.rounded_rectangle(
            (box[0], box[1], box[2], box[1] + 9), radius=4, fill=LIME
        )
        for n, (line, bold) in enumerate(texts[node.key]):
            draw.text(
                ((box[0] + box[2]) / 2, box[1] + 20 + n * 33),
                line,
                font=font(25, bold),
                fill=INK,
                anchor="mt",
            )
    return png(page)


def photo_count(block):
    if type(block.photos_per_page) is not int or not 1 <= block.photos_per_page <= 6:
        raise ValueError("Choose between 1 and 6 photos per page.")
    return (
        len(block.asset_hashes) + block.photos_per_page - 1
    ) // block.photos_per_page


def photo_page(block, loader, index=0):
    count = photo_count(block)
    if not 0 <= index < count:
        raise ValueError("That photo page does not exist.")
    page = Image.new("RGB", PAGE, "white")
    draw = ImageDraw.Draw(page)
    columns = 1 if block.photos_per_page <= 2 else 2
    rows = (block.photos_per_page + columns - 1) // columns
    cell_w, cell_h = (PAGE[0] - 40) // columns, (PAGE[1] - 40) // rows
    start = index * block.photos_per_page
    for offset, ref in enumerate(
        block.asset_hashes[start : start + block.photos_per_page]
    ):
        x, y = 20 + (offset % columns) * cell_w, 20 + (offset // columns) * cell_h
        caption = (
            block.asset_captions[start + offset]
            if start + offset < len(block.asset_captions)
            else ""
        )
        lines = wrapped(caption, font(24), cell_w - 44, draw)
        if len(lines) > 4:
            raise ValueError(
                "Shorten a photo caption or choose fewer photos per page (maximum four caption lines)."
            )
        caption_h = 32 * len(lines) + 20 if lines else 12
        frame = (cell_w - 32, cell_h - caption_h - 24)
        raw = loader(ref)
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > _MAX_PIXELS_PER_FRAME:
                raise ValueError("Photo exceeds the image pixel limit.")
            image = ImageOps.exif_transpose(source)
            image.thumbnail(frame, Image.Resampling.LANCZOS)
            rgba = image.convert("RGBA")
            page.paste(
                rgba,
                (
                    int(x + (cell_w - image.width) / 2),
                    int(y + (frame[1] - image.height) / 2),
                ),
                rgba,
            )
        draw.rounded_rectangle(
            (x + 4, y + 2, x + cell_w - 12, y + cell_h - 12),
            radius=10,
            outline="#d4e0dc",
            width=2,
        )
        for n, line in enumerate(lines):
            draw.text(
                (x + 20, y + frame[1] + 12 + n * 32), line, font=font(24), fill=INK
            )
    return png(page)
