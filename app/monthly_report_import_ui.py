"""Operator-confirmed bootstrap; staging stays separate from shared profiles."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile

import streamlit as st

from app import monthly_report_library as library
from app.config import operator_today
from app.monthly_report_import import (
    MAX_DOCX_BYTES, ImportMapping, imported_draft, inspect_docx, map_items, read_import_image,
)
from app.monthly_report_model import ReportPeriod, default_sections, layout_blocks


def _signature(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _stage(upload):
    # A session-owned TemporaryDirectory is cleaned when discarded. It never
    # becomes a library asset, and live UploadedFile objects are not mirrored.
    if upload.size > MAX_DOCX_BYTES:
        raise ValueError("DOCX exceeds the 128 MB import limit.")
    root = library._root() / "imports"
    root.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="review-", dir=root)
    path = Path(temporary.name) / "source.docx"
    try:
        upload.seek(0)
        size = 0
        with path.open("wb") as output:
            while chunk := upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOCX_BYTES:
                    raise ValueError("DOCX exceeds the 128 MB import limit.")
                output.write(chunk)
        return temporary, path, inspect_docx(path)
    except Exception:
        temporary.cleanup()
        raise
    finally:
        upload.seek(0)


def render_import(state: library.LibraryState, field, browser_timezone: str = "") -> None:
    profile = state.profile
    prefix = "report_import_" + _signature((profile.contract, profile.key))
    stage_key = prefix + "_stage"
    with st.expander("Import an existing DOCX"):
        st.write("Extract content, review each destination, then save confirmed mappings to this profile or a prior report. Facility membership stays explicit in the profile settings.")
        st.caption("Up to 128 MB per DOCX. External links and embedded objects are never opened. Native Word drawings may need an exported PNG/JPEG. Unmapped content remains in this review until you discard it or the session ends.")
        upload = st.file_uploader("Existing monthly report DOCX", type=["docx"], max_upload_size=128, key=prefix + "_upload")
        if st.button("Read DOCX for mapping", key=prefix + "_read", disabled=upload is None):
            try:
                old = st.session_state.pop(stage_key, None)
                if old:
                    old[0].cleanup()
                st.session_state[prefix + "_mappings"] = {}
                st.session_state.pop(prefix + "_saved", None)
                st.session_state.pop(prefix + "_preview", None)
                with st.spinner("Reading document structure and content…"):
                    staged = _stage(upload)
                st.session_state[stage_key] = staged
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        staged = st.session_state.get(stage_key)
        if staged is None:
            return
        _, path, inspection = staged
        document_key = prefix + "_" + inspection.sha256[:16]
        mappings = st.session_state.setdefault(prefix + "_mappings", {})
        st.caption(f"{len(inspection.items)} items · {inspection.word_sections} Word sections. Word section counts do not determine report membership or layout.")
        for notice in inspection.notices:
            st.warning(notice)
        if inspection.title_candidates:
            with st.expander("Cover and title candidates"):
                for title in inspection.title_candidates:
                    st.text(title)
                st.caption("Set the actual display title and facility aliases in Profile library · create or edit.")
        section = st.selectbox("Filter extracted items", ["All", "Unmapped", "Unsupported", *dict.fromkeys(i.section or "Front matter / unplaced" for i in inspection.items)], key=field(document_key + "_filter", "All"))
        items = [i for i in inspection.items if section == "All" or
                 section == "Unmapped" and i.id not in mappings or
                 section == "Unsupported" and i.kind == "unsupported" or
                 section == (i.section or "Front matter / unplaced")]
        if items:
            by_id = {i.id: i for i in items}
            select_key = document_key + "_item_" + _signature(section)
            item_id = st.selectbox("Item to inspect", list(by_id), format_func=lambda key: by_id[key].label, key=select_key)
            item = by_id[item_id]
            st.caption(f"{item.part} · position {item.position} · Word section {item.word_section} · suggested destination: {item.suggested_slot or 'unmatched'}")
            if item.note:
                st.info(item.note)
            if item.text:
                st.text(item.text)
            if item.rows:
                st.dataframe(list(item.rows[:500]), hide_index=True)
                if len(item.rows) > 500:
                    st.caption(f"Showing the first 500 of {len(item.rows)} rows. The mapping includes every row.")
            if item.kind == "image":
                if st.button("Preview extracted image", key=document_key + "_preview_button"):
                    try:
                        image = read_import_image(path, item)
                        st.session_state[prefix + "_preview"] = (item.id, image.data)
                    except (ValueError, OSError) as exc:
                        st.error(str(exc))
                preview = st.session_state.get(prefix + "_preview")
                if preview and preview[0] == item.id:
                    st.image(preview[1], width="stretch")
            specs = {b.key: b for s in default_sections() for b in s.blocks} | {b.key: b for b in layout_blocks()}
            allowed = [b.key for b in specs.values() if (
                item.kind == "image" and b.type in ("image_page", "image_grid", "pdf_pages") or
                item.kind == "text" and b.type in ("rich_text", "stock_text") or
                item.kind == "table" and (b.type in ("table", "work_order_grid") or b.key == "contact_matrix"))]
            if allowed:
                default = item.suggested_slot if item.suggested_slot in allowed else allowed[0]
                destination = st.selectbox("Confirmed destination", allowed, key=field(document_key + "_destination_" + item.id, default))
                columns, header = (), True
                if item.rows:
                    header = st.checkbox("First row contains column headings", key=field(document_key + "_headers_" + item.id, True))
                    columns = tuple(st.multiselect("Columns to keep in this order", list(range(len(item.rows[0]))),
                                                    format_func=lambda i: f"{i+1}: {item.rows[0][i][:70] or 'blank'}",
                                                    key=field(document_key + "_columns_" + item.id, list(range(len(item.rows[0]))))))
                    st.caption("Imported columns remain editable text until you choose a typed monthly-upload mapping. Unselected columns stay in this source review.")
                if st.button("Add confirmed mapping", key=document_key + "_add", disabled=bool(item.rows) and not columns):
                    mappings[item.id] = ImportMapping(item.id, destination, columns, header)
                    st.session_state.pop(prefix + "_saved", None)
                    st.rerun()
        else:
            st.info("No items match this filter.")
        st.write(f"{len(mappings)} mapped · {len(inspection.items)-len(mappings)} retained for review")
        if mappings:
            st.dataframe([{"Item": m.item_id, "Destination": m.slot, "Columns": ", ".join(str(i+1) for i in m.columns)} for m in mappings.values()], hide_index=True)
            remove = st.selectbox("Mapping to remove", ["", *mappings], key=document_key + "_remove_item")
            if st.button("Remove mapping", key=document_key + "_remove", disabled=not remove):
                mappings.pop(remove, None)
                st.rerun()
            target = st.radio("Save confirmed content as", ["Shared library defaults", "Prior report snapshot"], key=field(document_key + "_target", "Shared library defaults"))
            if target == "Shared library defaults":
                with st.expander("Compare library destinations before saving"):
                    destination = st.selectbox("Destination to compare", list(dict.fromkeys(m.slot for m in mappings.values())), key=document_key + "_compare")
                    left, right = st.columns(2)
                    with left:
                        st.caption("Current library content")
                        from app.monthly_report_editor import _preview
                        _preview(state.block(destination), {}, profile)
                    with right:
                        st.caption("Confirmed incoming items")
                        all_items = {i.id: i for i in inspection.items}
                        for mapping in mappings.values():
                            if mapping.slot != destination:
                                continue
                            incoming = all_items[mapping.item_id]
                            if incoming.text:
                                st.text(incoming.text)
                            if incoming.rows:
                                indices = mapping.columns or tuple(range(len(incoming.rows[0])))
                                st.dataframe([[r[i] for i in indices] for r in incoming.rows[:500]], hide_index=True)
                            if incoming.kind == "image":
                                st.caption(incoming.label)
                                preview = st.session_state.get(prefix + "_preview")
                                if preview and preview[0] == incoming.id:
                                    st.image(preview[1], width="stretch")
                                else:
                                    st.caption("Select this item above and press Preview extracted image to show it here.")
            source_month = st.date_input("Original report month", key=field(document_key + "_month", ReportPeriod.previous(operator_today(browser_timezone)).start),
                                         help="Confirm from the original report. The filename or a cover candidate may contain a stale month.")
            period = ReportPeriod(source_month.year, source_month.month)
            snapshot = library.load_snapshot(profile.contract, profile.key, period) if target == "Prior report snapshot" else None
            if snapshot:
                st.warning(f"This will create a new version of the saved {period.label} report.")
                with st.expander("Existing snapshot to compare"):
                    st.json({b.key: {"text": b.text, "rows": b.rows, "images": b.asset_hashes} for b in snapshot.draft.blocks})
            actor = st.text_input("Import editor name", key=field(document_key + "_actor", ""))
            prepared = st.text_input("Original prepared by", key=field(document_key + "_prepared", "")) if target == "Prior report snapshot" else ""
            confirmation = _signature((state.revision, asdict(profile), [asdict(m) for m in mappings.values()], target,
                                       period.key, snapshot.revision if snapshot else 0, actor, prepared))
            st.write("Scope: " + profile.scope_type + " · " + "; ".join(f.title + (" (aliases: " + ", ".join(f.aliases) + ")" if f.aliases else "") for f in profile.facilities))
            members_ok = st.checkbox("I confirm these facility identities, aliases and scope", key=document_key + "_members_" + confirmation)
            confirmed = st.checkbox("I confirm these mappings and this shared save", key=document_key + "_confirm_" + confirmation)
            if st.button("Save confirmed DOCX mappings", key=document_key + "_save", disabled=not (confirmed and members_ok and actor.strip() and (target != "Prior report snapshot" or prepared.strip()))):
                try:
                    with st.spinner("Normalizing selected images and saving confirmed content…"):
                        mapped = map_items(path, inspection, tuple(mappings.values()))
                        if target == "Shared library defaults":
                            library.save_import(profile.contract, profile.key, mapped.blocks, overrides=mapped.overrides, assets=mapped.assets,
                                                expected_revision=state.revision, actor=actor, confirmed=confirmed)
                        else:
                            draft = imported_draft(profile, period, prepared, mapped)
                            library.save_snapshot(draft, expected_revision=snapshot.revision if snapshot else 0, assets=mapped.assets,
                                                  entered_editor=actor)
                        st.session_state[prefix + "_saved"] = f"Saved {len(mapped.mapped_ids)} confirmed items. Unmapped items remain here for review. Choose Library as the source for saved defaults, or start the next month from the imported snapshot."
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
        if st.session_state.get(prefix + "_saved"):
            st.success(st.session_state[prefix + "_saved"])
        discard = st.checkbox("Discard this staged import and unmatched review items", key=document_key + "_discard_ok")
        if st.button("Discard staged DOCX", key=document_key + "_discard", disabled=not discard):
            staged[0].cleanup()
            for suffix in ("_stage", "_mappings", "_preview", "_saved"):
                st.session_state.pop(prefix + suffix, None)
            st.rerun()
