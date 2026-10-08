"""Upload-first setup with explicit item decisions for mixed-month documents."""

from dataclasses import asdict, replace

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_editor import _grid, _key, _signature
from app.monthly_report_import import ImportMapping, imported_draft, map_items, read_import_image
from app.monthly_report_import_ui import _stage
from app.monthly_report_model import Facility, ReportProfile, default_sections, layout_blocks
from app.monthly_report_setup import (
    DECISIONS, design_profile, initial_decision, item_findings, merge_drafts, suggested_mappings,
)


def _image_review(path, item, prefix, field, scope, *, compact=False):
    from app.monthly_report_image_review import MAX_IMAGE_REVIEWS, prepare_review, read_image, remaining_reviews, complete_review
    from app.receipt_jobs import start_receipt
    image_key = prefix + "_image_" + item.image_part
    if not compact and st.button("Show this image", key=image_key + "_show"):
        st.session_state[prefix + "_preview"] = (item.id, read_import_image(path, item).data)
    preview = st.session_state.get(prefix + "_preview")
    if not compact and preview and preview[0] == item.id:
        st.image(preview[1], width="stretch")
    readings = st.session_state.setdefault(prefix + "_readings", {})
    job_key = prefix + "_image_job"
    job = st.session_state.get(job_key)
    if job and job[1].done():
        try:
            readings[job[0]] = job[1].result()
            complete_review(scope, job[2], readings[job[0]])
        except Exception:
            st.warning("Automatic image reading did not finish. Your report is unchanged; inspect the image or try again.")
        st.session_state.pop(job_key, None)
        job = None
    if job:
        st.info("Reading one image. Other content is unchanged.")
        st.button("Check image reading", key=prefix + "_check_image")
    remaining = remaining_reviews(scope)
    st.caption(f"{remaining} automatic page checks remaining for this report/month. Check the result against the picture before relying on it." if compact else f"Optional visual/OCR reading: {remaining} of {MAX_IMAGE_REVIEWS} new image checks left for this report/month. New-profile setup shares the contract/month allowance until saved. Repeated images reuse cached readings. Unchecked images still require your review. OCR may miss small or handwritten details.")
    if st.button("Help read this page" if compact else "Read dates and text in this image", key=image_key + "_read", disabled=job is not None):
        if item.image_part not in readings:
            prepared = []
            def prepare():
                digest, cached, content = prepare_review(scope, path, item)
                prepared.append(digest)
                return cached, content
            future = start_receipt(prepare, lambda value: value[0] or read_image(value[1]))
            if future is None:
                st.warning("The document reader is busy. Try again shortly; no image was processed.")
            else:
                st.session_state[job_key] = (item.image_part, future, prepared[0])
                st.rerun()
    read_text = readings.get(item.image_part, "")
    if read_text:
        st.text(read_text)
        st.caption("Machine transcription—not verified evidence. Compare it with the image before deciding.")
    return st.text_area("What this page says (check and correct if needed)" if compact else "Corrected image text / review notes", key=field(image_key + "_text_" + _signature(read_text), read_text), height=120)


def render_legacy_setup(contract, period, prepared, field, *, state=None):
    prefix = "report_setup_" + _signature((contract, state.profile.key if state else "new", period.key))
    image_scope = (library.imported_review_scope(contract, state.profile.key, period) if state else "") or prefix
    st.subheader("Use a report you already have")
    st.write("Upload a preferred DOCX. We’ll suggest its sections and reusable site information, then ask what belongs in this month’s report.")
    st.caption("A report can contain several months. Cover titles and filenames never decide which pages to remove. The original and unmatched items are retained after you confirm a save. Up to 128 MB.")
    upload = st.file_uploader("Older or partially completed report", type=["docx"], max_upload_size=128, key=prefix + "_upload")
    if st.button("Analyze report", key=prefix + "_analyze", disabled=upload is None):
        staged = _stage(upload)
        old = st.session_state.get(prefix + "_stage")
        st.session_state[prefix + "_stage"] = staged
        if old and old[0]:
            old[0].cleanup()
        st.rerun()
    if state:
        original = library.imported_original(contract, state.profile.key)
        if original and st.button("Review the saved original and unmatched content", key=prefix + "_original"):
            from app.monthly_report_import import inspect_docx
            old = st.session_state.get(prefix + "_stage")
            st.session_state[prefix + "_stage"] = (None, original, inspect_docx(original))
            if old and old[0]:
                old[0].cleanup()
            st.rerun()
    staged = st.session_state.get(prefix + "_stage")
    if not staged:
        return
    _, path, inspection = staged
    p = prefix + "_" + inspection.sha256[:16]
    intent = "Content-based review"
    st.info(f"Output month: {period.label}. Each section is reviewed against that month. Nothing is removed merely because the title looks old.")
    for notice in inspection.notices:
        st.warning(notice)
    suggestions = {m.item_id: m for m in suggested_mappings(inspection)}
    mappings = st.session_state.setdefault(p + "_mappings", suggestions)
    decisions = st.session_state.setdefault(p + "_decisions", {
        item.id: initial_decision(item, item.id in suggestions, period) for item in inspection.items})
    notes = st.session_state.setdefault(p + "_notes", {})
    titles = {s.key: s.title for s in default_sections()}
    st.write(f"Found {len(inspection.items)} content items across {len({i.section for i in inspection.items if i.section})} logical sections.")
    with st.expander("Detected sections and suggested destinations"):
        st.dataframe([{"Section": titles.get(i.section, "Cover / unplaced"), "Item": i.label,
                       "Destination": mappings[i.id].slot.replace("_", " ") if i.id in mappings else "Needs placement",
                       "Decision": decisions[i.id]} for i in inspection.items], hide_index=True)
    pending = [i for i in inspection.items if decisions[i.id] == "Needs review"]
    st.subheader(f"Review mixed-month content · {len(pending)} left")
    st.caption("Keep = include in the output. Reference = retain for later, not in the output. Exclude = leave out of this draft, while preserving the original. Review service dates, not just printed template dates.")
    filter_value = st.selectbox("Show items", ["Needs review", "All items", "Kept items", "Reference / excluded"], key=field(p + "_filter", "Needs review"))
    items = [i for i in inspection.items if filter_value == "All items" or
             filter_value == "Needs review" and decisions[i.id] == "Needs review" or
             filter_value == "Kept items" and decisions[i.id] == "Keep in report" or
             filter_value == "Reference / excluded" and decisions[i.id] in DECISIONS[2:]]
    if items:
        by_id = {i.id: i for i in items}
        select_key = field(p + "_item_" + filter_value, items[0].id)
        if st.session_state[select_key] not in by_id:
            st.session_state[select_key] = items[0].id
        item = by_id[st.selectbox("Content to review", list(by_id), format_func=lambda k: by_id[k].label, key=select_key)]
        st.write(titles.get(item.section, "Cover / unplaced"))
        if item.text:
            st.text(item.text)
        if item.rows:
            st.dataframe(list(item.rows[:500]), hide_index=True)
        if item.kind == "image":
            before = notes.get(item.id, "")
            notes[item.id] = _image_review(path, item, p, field, image_scope)
            if before != notes[item.id]:
                decisions[item.id] = "Needs review"
        for finding in item_findings(item, period, notes.get(item.id, "")):
            st.warning(finding)
        if item.note:
            st.caption(item.note)
        specs = {b.key: b for s in default_sections() for b in s.blocks} | {b.key: b for b in layout_blocks()}
        allowed = [b.key for b in specs.values() if
                   item.kind == "image" and b.type in ("image_page", "image_grid", "pdf_pages") or
                   item.kind == "text" and b.type in ("rich_text", "stock_text") or
                   item.kind == "table" and (b.type in ("table", "work_order_grid") or b.key == "contact_matrix")]
        destination = st.selectbox("Where it belongs", ["", *allowed], format_func=lambda v: v.replace("_", " ").capitalize() if v else "Not placed",
                                   key=field(p + "_destination_" + item.id, mappings[item.id].slot if item.id in mappings else ""))
        decision = st.selectbox("Use this item", DECISIONS, key=field(p + "_decision_" + item.id, decisions[item.id]))
        if st.button("Confirm item and continue", key=p + "_confirm_item", disabled=decision == "Needs review" or (decision == "Keep in report" and not destination)):
            decisions[item.id] = decision
            if destination:
                mappings[item.id] = ImportMapping(item.id, destination)
            else:
                mappings.pop(item.id, None)
            st.rerun()
    else:
        st.success("No items in this view.")
    st.caption("Unmatched headings, text, images and unsupported objects remain in the saved original. This importer rebuilds an editable report from confirmed destinations; it does not promise a pixel-identical Word layout.")

    st.subheader("Confirm the report’s sites and name")
    existing = state.profile if state else None
    title = st.text_input("Report name", key=field(p + "_title", existing.title if existing else ""), help="A stable display name, without the month or year.")
    scope = st.selectbox("Report scope", ["individual", "multi_site", "regional"],
                         format_func=lambda v: {"individual": "Single site", "multi_site": "Multiple sites", "regional": "Regional"}[v],
                         key=field(p + "_scope", existing.scope_type if existing else "individual"), disabled=existing is not None)
    if existing:
        facilities = existing.facilities
        st.write("; ".join(f.title + (" (also: " + ", ".join(f.aliases) + ")" if f.aliases else "") for f in facilities))
    else:
        from app.monthly_report_directory_ui import choose_facilities
        selected_sites = choose_facilities(contract, p, field)
        seed = [{"Identity": f.key, "Facility": f.title, "Alternate names": "; ".join(f.aliases)} for f in selected_sites]
        rows = _grid(p + "_facilities" + ("_" + _signature(seed) if seed else ""), seed or [{"Identity": "", "Facility": "", "Alternate names": ""}],
                     num_rows="dynamic", hide_index=True, disabled=["Identity"], column_config={"Identity": None})
        facilities = tuple(Facility(r.get("Identity") or _key(str(r.get("Facility") or "")), str(r["Facility"]).strip(),
                                    tuple(a.strip() for a in str(r.get("Alternate names") or "").split(";") if a.strip()))
                           for r in rows if str(r.get("Facility") or "").strip())
    st.caption("One row per actual site. Separate alternate names with semicolons; aliases are not additional sites. Membership and scope are never inferred from the title.")
    actor = st.text_input("Your name", key=field(p + "_actor", prepared))
    st.caption("Saved content is shared in this internal-testing app. Your entered name records who made the change; it is not authenticated identity.")
    candidate = None
    try:
        candidate = replace(existing, title=title.strip()) if existing else ReportProfile(contract, _key(title), title.strip(), facilities, scope)
    except ValueError as exc:
        st.caption(str(exc))
    pending = [i for i in inspection.items if decisions[i.id] == "Needs review"]
    kept = tuple(m for identity, m in mappings.items() if decisions[identity] == "Keep in report")
    signature = _signature((asdict(candidate) if candidate else None, period.key, intent, decisions, notes, [asdict(m) for m in kept], actor, state.revision if state else 0))
    confirmed = st.checkbox("I checked the content decisions and confirm these sites, aliases and shared save", key=p + "_confirm_" + signature)
    if st.button("Save design and continue this report", key=p + "_save", type="primary",
                 disabled=bool(pending) or not (candidate and title.strip() and kept and actor.strip() and confirmed)):
        try:
            with st.spinner("Saving the original, confirmed content and reusable design…"):
                mapped = map_items(path, inspection, kept)
                profile = candidate if existing else design_profile(candidate, inspection, kept, mapped.overrides)
                draft = imported_draft(profile, period, actor, mapped)
                current = library.load_snapshot(contract, profile.key, period) if existing else None
                prior_import = library.load_imported_draft(contract, profile.key) if existing else None
                base = current.draft if current else None
                if prior_import and prior_import.period == period and (not current or library.imported_snapshot_revision(contract, profile.key) == current.revision):
                    base = merge_drafts(base, prior_import)
                draft = merge_drafts(base, draft)
                review = {"sha256": inspection.sha256, "intent": intent, "period": period.key,
                          "image_review_scope": image_scope,
                          "items": [asdict(i) for i in inspection.items], "decisions": decisions,
                          "image_notes": notes, "mappings": [asdict(m) for m in kept]}
                library.save_report_setup(profile, draft, path, review, assets=mapped.assets,
                                          expected_revision=state.revision if state else 0, actor=actor, confirmed=True,
                                          snapshot_revision=current.revision if current else 0)
                st.session_state["report_resume_import"] = (contract, profile.key, period.key)
                st.session_state["report_setup_done"] = profile.key
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))


def render_setup(contract, period, prepared, field, *, state=None, **working):
    from app.monthly_report_section_ui import render_section_setup
    return render_section_setup(contract, period, prepared, field, state=state, **working)
