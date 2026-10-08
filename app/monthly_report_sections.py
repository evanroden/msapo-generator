"""Section-level import plans: document internals stay out of the operator UI."""

from dataclasses import dataclass, replace
from collections import defaultdict
import hashlib
import re

from app.monthly_report_content_policy import contains_price, page_status, table_price_columns, table_has_pricing
from app.monthly_report_checks import placeholder_matches
from app.monthly_report_import import MappedImport, ImportMapping, _heading, read_import_image, MAX_NORMALIZED_BYTES
from app.monthly_report_model import ReportTable, ResolvedBlock, default_sections, layout_blocks


@dataclass(frozen=True)
class ImportSection:
    key: str
    title: str
    items: tuple


def is_formatting(item):
    if item.kind != "text":
        return False
    text = item.text.strip()
    if not any(c.isalnum() for c in text):
        return True
    if item.part.startswith(("word/header", "word/footer")) and re.fullmatch(r"(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?", text, re.I):
        return True
    return bool(_heading(text) and _heading(text) != "unmatched")


def section_reviews(inspection):
    titles = {s.key: s.title for s in default_sections()}
    groups, seen_shared = {}, set()
    appearances = defaultdict(set)
    for item in inspection.items:
        if item.kind == "image" and item.position:
            appearances[item.image_digest or item.image_part].add(item.section)
    repeated_design = {part for part, sections in appearances.items() if len(sections) >= 3}
    for item in inspection.items:
        if item.position == 0:
            continue  # Unused package assets are preserved, not visible report pages.
        if is_formatting(item):
            continue
        shared = item.part.startswith(("word/header", "word/footer")) or (item.kind == "image" and (item.image_digest or item.image_part) in repeated_design)
        # Repeated Word headers are one design element, not dozens of tasks.
        if shared:
            signature = (item.kind, item.image_digest or item.image_part, item.text)
            if signature in seen_shared:
                continue
            seen_shared.add(signature)
        key = "cover" if shared or not item.section else item.section
        if key not in titles and key != "cover" or item.position == 0:
            key = "other"
        groups.setdefault(key, []).append(item)
    ordered = ["cover", *[k for k in groups if k not in ("cover", "other")], "other"]
    return tuple(ImportSection(k, "Cover and page design" if k == "cover" else "Other content to check" if k == "other" else titles[k], tuple(groups[k])) for k in ordered if k in groups)


def small_artwork(item):
    return (item.kind == "image" and item.image_width > 0 and item.image_height > 0
            and (max(item.image_width, item.image_height) <= 128 or min(item.image_width, item.image_height) <= 3))


def readable_label(key):
    return {"org_chart": "Organizational chart", "business_hours_workflow": "Business-hours outage process",
            "after_hours_workflow": "After-hours outage process", "contact_matrix": "Facility contacts",
            "activity_summary": "Work completed this month", "work_orders": "Work-order summary",
            "service_calls": "Service calls", "vendor_reports": "Vendor service reports", "water_reports": "Water treatment reports",
            "improvements": "Improvement photos", "mbcx_report": "MBCx report", "subcontractor_matrix": "Vendor contacts",
            "capital_renewal": "Priority capital renewal", "proposals": "Pending and declined proposals"}.get(key, key.replace("_", " ").capitalize())


def default_slot(section):
    spec = next(s for s in default_sections() if s.key == section)
    return next((b.key for b in spec.blocks if b.type in ("rich_text", "stock_text")), spec.blocks[0].key)


def table_without_prices(item):
    rows = item.rows
    if not rows:
        return None, ()
    removed = table_price_columns(rows[0], rows[1:])
    keep = [i for i in range(len(rows[0])) if i not in removed]
    if not keep:
        return None, removed
    columns = tuple(rows[0][i].strip() or f"Column {n+1}" for n, i in enumerate(keep))
    # Repeated/merged titles must not cause data_editor dictionaries to lose cells.
    columns = tuple(title + (f" ({n+1})" if title in columns[:n] else "") for n, title in enumerate(columns))
    values = tuple(tuple(row[i] if i < len(row) else "" for i in keep) for row in rows[1:])
    return ReportTable(columns, values), removed


def build_section_import(path, inspection, plans):
    """Build explicitly approved sections; keep every other item in the original.

    A plan names included images/text/tables and optional edited text. Its saved
    record preserves exclusions and review decisions without exposing item IDs
    in the UI. Multiple tables retain their own schemas instead of being dropped.
    """
    known = {b.key for s in default_sections() for b in s.blocks} | {b.key for b in layout_blocks()}
    grouped, assets, mappings, total = {}, {}, [], 0
    items = {i.id: i for i in inspection.items}
    sections = {s.key: s for s in section_reviews(inspection)}
    for plan in plans:
        if not plan.get("approved"):
            raise ValueError("Review each included section before continuing.")
        if plan.get("omit"):
            continue
        if plan.get("page_layout"):
            preserved = plan.get("preserved_assets", ())
            records = plan.get("word_page_records", ())
            allowed = {"org_chart", "business_hours_workflow", "after_hours_workflow", "contact_matrix"}
            if plan["key"] != "organization" or not preserved or len(preserved) != len(records):
                raise ValueError("Review the complete chart pages before continuing.")
            for (slot, image), record in zip(preserved, records):
                digest = hashlib.sha256(image.data).hexdigest()
                text = record.get("text", "")
                if (slot not in allowed or record.get("slot") != slot or record.get("sha256") != digest
                        or not record.get("reviewed") or record.get("blank") or placeholder_matches(text)
                        or page_status(text, unreadable=not text.strip())[0] in ("pricing", "legal", "signature")):
                    raise ValueError("A complete chart page changed or contains excluded content. Review it again.")
                ref = digest + ".png"
                if ref not in assets:
                    total += len(image.data)
                    if total > MAX_NORMALIZED_BYTES:
                        raise ValueError("Selected images exceed the 60 MB preparation budget.")
                    assets[ref] = image.data
                source = f"docx:{inspection.sha256}:word-sections:{','.join(map(str, record['sections']))}:page:{record['page']}"
                block = grouped.get(slot, ResolvedBlock(slot, "Last month"))
                grouped[slot] = replace(block, asset_hashes=(*block.asset_hashes, ref), references=(*block.references, source))
        if not plan.get("page_layout") and any(i.kind == "unsupported" for i in sections[plan["key"]].items) and not plan.get("unsupported_reviewed"):
            raise ValueError("Choose whether to replace or leave out unread drawings before continuing.")
        selected = () if plan.get("page_layout") else plan.get("selected", ())
        for identity in selected:
            item = items[identity]
            slot = plan.get("destinations", {}).get(identity)
            if not slot:
                slot = item.suggested_slot if plan["target"] == item.section and item.suggested_slot in known else default_slot(plan["target"])
            if slot not in known or item.kind == "unsupported":
                raise ValueError("A section contains content that needs a replacement before it can be included.")
            block = grouped.get(slot, ResolvedBlock(slot, "Last month"))
            reference = f"docx:{inspection.sha256}:{item.id}"
            if item.kind == "image":
                notes = plan.get("image_notes", {}).get(item.image_part, "")
                if page_status(notes, unreadable=not notes.strip())[0] in ("pricing", "legal", "blank", "signature"):
                    raise ValueError("Leave out pages with pricing, legal terms or no report content.")
                image = read_import_image(path, item, line_art=slot not in ("cover_photo", "improvements"))
                digest = hashlib.sha256(image.data).hexdigest() + "." + image.extension
                if digest not in assets:
                    total += len(image.data)
                    if total > MAX_NORMALIZED_BYTES:
                        raise ValueError("Selected images exceed the 60 MB preparation budget. Leave out unneeded pages and try again.")
                    assets[digest] = image.data
                if digest not in block.asset_hashes:
                    block = replace(block, asset_hashes=(*block.asset_hashes, digest))
            elif item.kind == "table":
                table, _ = table_without_prices(item)
                if item.id in plan.get("tables", {}):
                    table = plan["tables"][item.id]
                if table:
                    if table_has_pricing(table.columns, table.rows):
                        raise ValueError("Remove pricing from the section table before continuing.")
                    block = replace(block, extra_tables=(*block.extra_tables, replace(table, reference=reference)))
            else:
                text = plan.get("texts", {}).get(identity, item.text)
                if contains_price(text):
                    raise ValueError("Remove pricing from the section text before continuing.")
                block = replace(block, text="\n\n".join(t for t in (block.text, text.strip()) if t))
                for original_id in plan.get("combined_text_ids", ()):
                    if original_id != identity:
                        block = replace(block, references=(*block.references, f"docx:{inspection.sha256}:{original_id}"))
                        mappings.append(ImportMapping(original_id, slot))
            grouped[slot] = replace(block, references=tuple(dict.fromkeys((*block.references, reference))))
            mappings.append(ImportMapping(identity, slot))
        for slot, image in plan.get("new_assets", ()):
            digest = hashlib.sha256(image.data).hexdigest() + "." + image.extension
            if digest not in assets:
                total += len(image.data)
                if total > MAX_NORMALIZED_BYTES:
                    raise ValueError("Selected images exceed the 60 MB preparation budget.")
                assets[digest] = image.data
            block = grouped.get(slot, ResolvedBlock(slot, "Replace once"))
            # Choosing a new cover photo/logo replaces that picture only; do
            # not discard any native text or other report parts in the block.
            hashes = (digest,) if slot in ("cover_photo", "client_logo", "brand_logo") else tuple(dict.fromkeys((*block.asset_hashes, digest)))
            grouped[slot] = replace(block, asset_hashes=hashes)
    if not grouped:
        raise ValueError("Keep at least one report section before continuing.")
    # Section confirmation covers the actual selected images and current text.
    blocks = tuple(replace(b, client_reviewed_fingerprint=b.fingerprint) for b in grouped.values())
    return MappedImport(blocks, (), tuple(assets.items()), tuple(m.item_id for m in mappings)), tuple(mappings)


def apply_section_omissions(draft, plans):
    """Honor explicit omissions after append-only partial-report preservation."""
    omitted = {p["key"] for p in plans if p.get("approved") and p.get("omit")}
    keys = {b.key for s in draft.sections if s.key in omitted for b in s.blocks}
    if "cover" in omitted:
        keys.update(("cover_photo", "brand_logo", "client_logo", "footer_text"))
    return replace(draft, sections=tuple(replace(s, included=False) if s.key in omitted else s for s in draft.sections),
                   blocks=tuple(replace(b, source="Omit") if b.key in keys else b for b in draft.blocks),
                   address_line="" if "cover" in omitted else draft.address_line)
