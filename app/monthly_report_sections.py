"""Section-level import plans: document internals stay out of the operator UI."""

from dataclasses import dataclass, replace
from collections import defaultdict
import hashlib
import re

from app.monthly_report_content_policy import contains_price, page_status, table_price_columns, table_has_pricing, logical_table_columns
from app.monthly_report_checks import placeholder_matches
from app.monthly_report_import import MappedImport, ImportMapping, _heading, read_import_image, _read_import_image, MAX_NORMALIZED_BYTES, is_logo_artwork, is_header_artwork
from app.monthly_report_model import ReportTable, ResolvedBlock, known_sections, layout_blocks
from app.monthly_report_asset_review import approve_all_assets


@dataclass(frozen=True)
class ImportSection:
    key: str
    title: str
    items: tuple


def is_formatting(item):
    if item.kind == "native_layout":
        return True  # Retained native geometry; extracted text/images stay separate.
    if item.note in ("Native divider artwork", "Native section heading") and item.kind in ("text", "unsupported"):
        return True
    if item.kind != "text":
        return False
    text = item.text.strip()
    if not any(c.isalnum() for c in text):
        return True
    if item.part.startswith(("word/header", "word/footer")) and re.fullmatch(r"(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?", text, re.I):
        return True
    return bool(_heading(text) and _heading(text) != "unmatched")


def section_reviews(inspection, *, source_view=None):
    from app.monthly_report_operational_source import operational_items
    source_items = operational_items(inspection, source_view)
    titles = {s.key: s.title for s in known_sections()}
    groups, seen_shared = {}, set()
    appearances = defaultdict(set)
    for item in source_items:
        if item.kind == "image" and item.position:
            appearances[item.image_digest or item.image_part].add(item.section)
    repeated_design = {part for part, sections in appearances.items() if len(sections) >= 3}
    for item in source_items:
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
    return {"org_chart": "Organizational chart", "business_hours_workflow": "Business-hours outage procedure",
            "after_hours_workflow": "After-hours outage procedure", "contact_matrix": "Facility contacts",
            "activity_summary": "Work completed this month", "work_orders": "Work-order summary",
            "service_calls": "Service calls", "vendor_reports": "Vendor service reports", "water_reports": "Water treatment reports",
            "improvements": "Progress photos", "mbcx_report": "MBCx report", "subcontractor_matrix": "Vendor contacts",
            "mbcx_status": "Commissioning update", "capital_renewal": "Priority capital renewal", "proposals": "Proposals",
            "rfi_matrix": "Information requests"}.get(key, key.replace("_", " ").capitalize())


def default_slot(section):
    spec = next(s for s in known_sections() if s.key == section)
    return next((b.key for b in spec.blocks if b.type in ("rich_text", "stock_text")), spec.blocks[0].key)


def table_without_prices(item):
    rows = item.rows
    if not rows:
        return None, ()
    headings = logical_table_columns(rows[0])
    removed = table_price_columns(headings, rows[1:])
    keep = [i for i in range(len(rows[0])) if i not in removed]
    if not keep:
        return None, removed
    columns = tuple(headings[i].strip() or f"Column {n+1}" for n, i in enumerate(keep))
    # Repeated/merged titles must not cause data_editor dictionaries to lose cells.
    columns = tuple(title + (f" ({n+1})" if title in columns[:n] else "") for n, title in enumerate(columns))
    values = tuple(tuple(row[i] if i < len(row) else "" for i in keep) for row in rows[1:])
    return ReportTable(columns, values), removed


def build_section_import(path, inspection, plans, *, source_view=None, profile=None, period=None):
    """Build explicitly approved sections after independent view verification."""
    if source_view is not None:
        from app.monthly_report_operational_source import verified_operation
        with verified_operation(path, source_view, inspection) as operation:
            return _build_section_import(path, inspection, plans, source_view=operation.view, _operation=operation,
                                         profile=profile, period=period)
    return _build_section_import(path, inspection, plans, profile=profile, period=period)


def _build_section_import(path, inspection, plans, *, source_view=None, _operation=None, profile=None, period=None):
    known = {b.key for s in known_sections() for b in s.blocks} | {b.key for b in layout_blocks()}
    from app.monthly_report_operational_source import checked_operation, operational_items
    if source_view is not None:
        checked_operation(path, source_view, _operation)
    def read_image(item, **options):
        if source_view is None:
            return read_import_image(path, item, **options)
        return _read_import_image(path, item, source_view=source_view, _operation=_operation, **options)
    source_items = operational_items(inspection, source_view)
    grouped, assets, mappings, total = {}, {}, [], 0
    items = {i.id: i for i in source_items}
    image_references = {f"docx:{inspection.sha256}:{i.id}" for i in source_items if i.kind == "image"}
    preserved_page_prefix = f"docx:{inspection.sha256}:word-sections:"
    sections = {s.key: s for s in section_reviews(inspection, source_view=source_view)}
    plans = tuple(plans)
    from app.monthly_report_native_art_review import native_cover_furniture_ids
    furniture_ids = native_cover_furniture_ids(inspection.items) if source_view is not None else ()
    kept_native = set()
    reviews = [plan for plan in plans if plan.get("native_art_review") is not None]
    if reviews:
        if (len(reviews) != 1 or source_view is None or reviews[0].get("key") != "cover"
                or profile is None or period is None):
            raise ValueError("Native artwork preservation requires its verified source view and report scope.")
        from app.monthly_report_native_art_review import _verify_native_art_review
        preserved = _verify_native_art_review(path, source_view, profile, period, reviews[0]["native_art_review"])
        if preserved is not None:
            kept_native = {item.original_id for item in preserved.inventory.occurrences}
        if reviews[0].get("omit") or any(kept_native.intersection(plan.get("selected", ())) for plan in plans):
            raise ValueError("Native artwork preservation conflicts with this exact occurrence's omission or mapping.")
    for plan in plans:
        if not plan.get("approved"):
            raise ValueError("Review each included section before continuing.")
        if plan.get("omit"):
            continue
        if any(items[identity].kind == "image" and is_header_artwork(items[identity])
               and plan.get("destinations", {}).get(identity) == "cover_photo"
               for identity in plan.get("selected", ())):
            raise ValueError("Header artwork has no confirmed photograph role. Keep it out of the cover photo and confirm its identity first.")
        if plan["key"] == "cover":
            from app.monthly_report_start_import import unresolved_cover_artwork
            cover = sections["cover"]
            # A different-site source deliberately contributes only recognized
            # branding, never its foreign photos/drawings. Keep that existing
            # exclusion semantics distinct from certifying unread same-site art.
            foreign_excluded = bool(
                plan.get("automatic") and plan.get("source_sha256") == inspection.sha256
                and plan.get("source_site_relation") == "other"
                and not any(plan.get(key) for key in ("new_assets", "preserved_assets", "page_layout", "auto_native_diagrams"))
                and all(items[identity].kind == "image"
                        and items[identity].suggested_slot in ("brand_logo", "client_logo")
                        and plan.get("destinations", {}).get(identity) == items[identity].suggested_slot
                        for identity in plan.get("selected", ()))
            )
            if not foreign_excluded and any(item.kind == "unsupported" for item in cover.items):
                # A photograph upload is not a replacement for a different
                # unread Word drawing. No supported Cover whole-page recovery
                # exists here; only explicit omission can keep an existing
                # report's design without certifying that source artwork.
                raise ValueError("Unread cover artwork must be repaired in the original Word file, or left out using the existing report’s saved cover design. A new cover photograph cannot replace it.")
            if not foreign_excluded and any(item.id not in kept_native for item in unresolved_cover_artwork(cover.items, native_furniture_ids=furniture_ids)):
                raise ValueError("Cover artwork has no confirmed photograph or logo role. Repair the original Word file or use the existing report’s saved cover design.")
            if plan.get("cover_photo_omitted"):
                from app.monthly_report_start_import import cover_photo_candidates
                candidates = tuple(item.id for item in cover_photo_candidates(cover.items, native_furniture_ids=furniture_ids))
                if (not candidates or plan.get("source_sha256") != inspection.sha256
                        or tuple(plan.get("cover_photo_source_ids", ())) != candidates
                        or any(plan.get("destinations", {}).get(identity) == "cover_photo"
                               for identity in plan.get("selected", ()))):
                    raise ValueError("The No cover photograph choice belongs to another source or selection. Review this cover again; nothing was changed.")
                grouped["cover_photo"] = ResolvedBlock(
                    "cover_photo", "Omit", references=tuple(f"docx:{inspection.sha256}:{identity}" for identity in candidates))
        if plan.get("page_layout") or plan.get("auto_native_diagrams"):
            preserved = plan.get("preserved_assets", ())
            records = plan.get("word_page_records", ())
            from app.monthly_report_visual_preservation import VISUAL_SLOTS
            auto = bool(plan.get("auto_native_diagrams"))
            allowed = ({VISUAL_SLOTS[plan["key"]]} if auto and plan["key"] in VISUAL_SLOTS
                       else {"org_chart", "business_hours_workflow", "after_hours_workflow", "contact_matrix"})
            if (not preserved or len(preserved) != len(records)
                    or (auto and (not plan.get("automatic") or plan.get("page_layout")
                                  or plan["key"] not in VISUAL_SLOTS))
                    or (not auto and plan["key"] != "organization")):
                raise ValueError("The original diagram pages need their section and source proof.")
            for (slot, image), record in zip(preserved, records):
                digest = hashlib.sha256(image.data).hexdigest()
                text = record.get("text", "")
                kind, _ = page_status(text, unreadable=not text.strip())
                source_proved = (
                    auto and record.get("source_verified") is True
                    and record.get("source_sha256") == inspection.sha256
                    and tuple(record.get("sections", ())) == tuple(plan.get("captured_word_sections", ()))
                    and all(number > 0 for number in record.get("sections", ()))
                )
                if (slot not in allowed or record.get("slot") != slot or record.get("sha256") != digest
                        or not (record.get("reviewed") or source_proved)
                        or record.get("blank") or placeholder_matches(text)
                        or kind in ("pricing", "legal", "signature", "blank")
                        or (auto and record.get("visual_review_required") is not (kind == "review"))
                        or (kind == "review" and not (
                            auto and source_proved and record.get("visual_review_required") is True))):
                    raise ValueError("A diagram page was not safely preserved. Review it again in its original report section.")
                ref = digest + ".png"
                if ref not in assets:
                    total += len(image.data)
                    if total > MAX_NORMALIZED_BYTES:
                        raise ValueError("Selected images exceed the 60 MB preparation budget.")
                    assets[ref] = image.data
                source = f"docx:{inspection.sha256}:word-sections:{','.join(map(str, record['sections']))}:page:{record['page']}"
                block = grouped.get(slot, ResolvedBlock(slot, "Last month"))
                contexts = dict(block.asset_provenance)
                contexts[ref] = tuple(dict.fromkeys((*contexts.get(ref, ()), source)))
                grouped[slot] = replace(block, asset_hashes=(*block.asset_hashes, ref), references=(*block.references, source),
                                        asset_provenance=tuple(contexts.items()))
        if (not plan.get("page_layout") and not plan.get("auto_native_diagrams")
                and any(i.kind == "unsupported" for i in sections[plan["key"]].items)
                and not plan.get("unsupported_reviewed")):
            # No generic Continue-without-art choice. A diagram stays unresolved
            # until source-bound pages or clear replacements are retained.
            raise ValueError("A Word diagram contains unread drawings that were not preserved. Prepare its source page or add a replacement in this section.")
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
                if slot == "cover_photo" and is_header_artwork(item):
                    raise ValueError("Header artwork has no confirmed photograph role. Keep it out of the cover photo and confirm its identity first.")
                if slot == "cover_photo" and is_logo_artwork(item):
                    raise ValueError("This image is identified as a logo. Keep it in a branding slot and choose a photograph for the cover.")
                notes = plan.get("image_notes", {}).get(item.image_part, "")
                if page_status(notes, unreadable=not notes.strip())[0] in ("pricing", "legal", "blank", "signature"):
                    raise ValueError("Leave out pages with pricing, legal terms or no report content.")
                image = read_image(item, line_art=slot not in ("cover_photo", "improvements"),
                                          preserve_transparency=slot in ("brand_logo", "client_logo"))
                digest = hashlib.sha256(image.data).hexdigest() + "." + image.extension
                if digest not in assets:
                    total += len(image.data)
                    if total > MAX_NORMALIZED_BYTES:
                        raise ValueError("Selected images exceed the 60 MB preparation budget. Leave out unneeded pages and try again.")
                    assets[digest] = image.data
                if digest not in block.asset_hashes:
                    caption = item.text.strip()
                    if contains_price(caption):
                        raise ValueError("Remove pricing from the picture caption before continuing.")
                    captions = block.asset_captions + ("",) * (len(block.asset_hashes) - len(block.asset_captions))
                    block = replace(block, asset_hashes=(*block.asset_hashes, digest),
                                    asset_captions=(*captions, caption))
                contexts = dict(block.asset_provenance)
                contexts[digest] = tuple(dict.fromkeys((*contexts.get(digest, ()), reference)))
                block = replace(block, asset_provenance=tuple(contexts.items()))
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
            if slot == "cover_photo" and plan.get("cover_photo_omitted"):
                continue  # The explicit No-photo action wins over a retained staged upload.
            digest = hashlib.sha256(image.data).hexdigest() + "." + image.extension
            if digest not in assets:
                total += len(image.data)
                if total > MAX_NORMALIZED_BYTES:
                    raise ValueError("Selected images exceed the 60 MB preparation budget.")
                assets[digest] = image.data
            block = grouped.get(slot, ResolvedBlock(slot, "Replace once"))
            # Choosing a new cover photo/logo replaces that picture only; do
            # not discard any native text or other report parts in the block.
            if slot in ("org_chart", "business_hours_workflow", "after_hours_workflow", "contact_matrix"):
                # A named replacement changes that entire pictured part. Keep
                # native text/tables and their provenance, not references to the
                # superseded pictures or preserved Word pages.
                references = tuple(ref for ref in block.references
                                   if ref not in image_references and not ref.startswith(preserved_page_prefix))
                grouped[slot] = replace(block, source="Replace once", asset_hashes=(digest,),
                                        asset_captions=(), references=references, asset_provenance=((digest, ()),))
            else:
                hashes = (digest,) if slot in ("cover_photo", "client_logo", "brand_logo") else tuple(dict.fromkeys((*block.asset_hashes, digest)))
                contexts = dict(block.asset_provenance)
                contexts[digest] = ()
                grouped[slot] = replace(block, asset_hashes=hashes,
                                        asset_provenance=tuple((ref, contexts[ref]) for ref in hashes))
    if not grouped:
        raise ValueError("Keep at least one report section before continuing.")
    # Section confirmation covers the actual selected images and current text.
    blocks = tuple(approve_all_assets(b) for b in grouped.values())
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
