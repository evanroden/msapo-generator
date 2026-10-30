"""Upload a report, confirm its sites, then review recognizable report sections."""

import hashlib
from contextlib import nullcontext
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_content_policy import contains_price, table_has_pricing
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_cover_images import image_byte_limit, read_picture_upload, normalize_cover_photo
from app.monthly_report_upload_limits import uploader_limit_mib, byte_limit_label
from app.monthly_report_editor import _grid, _key, _signature
from app.monthly_report_import import imported_draft
from app.monthly_report_import_ui import _stage
from app.monthly_report_model import (
    Facility,
    ReportProfile,
    ReportTable,
    known_sections,
)
from app.monthly_report_section_help import section_help
from app.monthly_report_sections import (
    default_slot,
    section_reviews,
    table_without_prices,
)
from app.monthly_report_setup import design_profile, item_findings


def _cover_action_key(prefix):
    """Retire only the cover radio when an explicit template action replaces it."""
    epoch = st.session_state.get(prefix + "_cover_action_epoch", "")
    return prefix + ("_cover_choice_" + epoch if epoch else "") + "_section_cover_action"


def _replace_cover_action(prefix, action):
    # A browser can submit the old radio alongside the next button click.
    # A new identity isolates that payload without overriding fresh choices.
    st.session_state[prefix + "_cover_action_epoch"] = uuid4().hex
    st.session_state[_cover_action_key(prefix)] = action


def plan_signature(plan):
    value = {k: v for k, v in plan.items() if k not in ("new_assets", "preserved_assets", "approved", "approval_stamp")}
    value["new_assets"] = [(slot, hashlib.sha256(image.data).hexdigest()) for slot, image in plan.get("new_assets", ())]
    value["preserved_assets"] = [(slot, hashlib.sha256(image.data).hexdigest()) for slot, image in plan.get("preserved_assets", ())]
    return _signature(value)


def _site_options(contract):
    from app.monthly_report_site_catalog import site_options
    return site_options(contract)


def _identity(contract, prepared, prefix, field, state, inspection=None):
    if state:
        # The current report header already states these sites. Repeating
        # "Hospital · Hospital" above an import adds no useful decision.
        return state.profile, prepared, [] if prepared.strip() else ["Enter Prepared by above."]
    from app.monthly_report_start_import import source_sites
    options = {f.key: f for f in _site_options(contract)}
    inferred = {f.key for f in source_sites(inspection, options.values())} if inspection else set()
    st.subheader("Report sites")
    st.caption("The sites identified on the uploaded cover are selected. Change only incorrect sites.")
    selected = []
    for site in options.values():
        label = site.title
        if st.checkbox(label, key=field(prefix + "_site_" + site.key, site.key in inferred),
                       help="Include this site in the current report."):
            selected.append(site)
    custom = st.text_input("Add a site not listed (optional)",
                           key=field(prefix + "_custom_site", ""),
                           help="Separate multiple names with semicolons.")
    try:
        facilities = tuple(selected) + tuple(Facility(_key(v.strip()), v.strip())
                                             for v in custom.split(";") if v.strip())
        if facilities:
            ReportProfile(contract, "selection", "Selected sites", facilities,
                          "individual" if len(facilities) == 1 else "multi_site")
    except ValueError:
        message = "A site was entered more than once or overlaps another site's name. Correct the selected sites."
        st.warning(message)
        return None, prepared, [message]
    actor = prepared.strip() or st.text_input("Your name", key=field(prefix + "_actor", ""),
                                              help="Used only when a name has not already been provided.")
    seed_title = facilities[0].title if len(facilities) == 1 else " / ".join(f.title for f in facilities)[:160]
    scope = "individual" if len(facilities) == 1 else "multi_site"
    with st.expander("Report name and alternate site names (optional)"):
        title = st.text_input("Report name",
                              key=field(prefix + "_title_" + _signature(seed_title), seed_title),
                              help="The month and year are added automatically.")
        if len(facilities) > 1 and st.checkbox(
                "This group is a regional report", key=field(prefix + "_regional", False)):
            scope = "regional"
        amended = []
        for facility in facilities:
            aliases = st.text_input("Other names for " + facility.title,
                                    key=field(prefix + "_aliases_" + facility.key, "; ".join(facility.aliases)))
            amended.append(replace(facility, aliases=tuple(v.strip() for v in aliases.split(";") if v.strip())))
        facilities = tuple(amended)
    missing = []
    if not facilities:
        missing.append("Choose the site or sites identified in the starting report.")
    if not title.strip():
        missing.append("Give the report a name.")
    if not actor.strip():
        missing.append("Enter your name.")
    candidate = None
    if not missing:
        try:
            candidate = ReportProfile(contract, _key(title), title.strip(), facilities, scope)
        except ValueError:
            missing.append("A site or alternate name belongs to multiple sites. Correct that overlap.")
    return candidate, actor, missing


def _use_new_cover_photo(key, digest):
    st.session_state[key] = digest


def _replacement_pictures(section, p, plan):
    """Keep each replacement tied to a named report part across reruns."""
    if section.key == "cover":
        labels = {"cover_photo": "New cover photograph"}
        st.caption("Add only what you want to change. Each new picture replaces the selected picture for that purpose; other cover details stay as they are.")
    elif section.key == "organization":
        labels = {"org_chart": "New organization chart", "business_hours_workflow": "New daytime outage procedure", "after_hours_workflow": "New after-hours outage procedure", "contact_matrix": "New facility contact page"}
        st.caption("Add only the parts that changed. A new picture replaces all previous pictures for that part; the other organization pages stay in the report.")
    else:
        labels = {{"activity": "improvements", "training": "training_summary", "maintenance": "vendor_reports", "water": "water_reports"}.get(section.key, default_slot(section.key)): section_help(section.key).upload_label}
        st.caption("Choose “Leave out” on the old picture when replacing it. Complete vendor, chemical and MBCx files can be added in This month’s work after setup.")
    replacements = {slot: image for slot, image in plan.get("new_assets", ())
                    if slot not in {"client_logo", "brand_logo"}}
    use_key = p + "_new_cover_photo_use"
    pending_use = st.session_state.pop(use_key, "") if section.key == "cover" else ""
    for slot, label in labels.items():
        is_cover_photo = slot == "cover_photo"
        upload = st.file_uploader(label, type=["png", "jpg", "jpeg", "heic", "heif", "webp"],
                                  key=p + "_replacement_" + slot,
                                  max_upload_size=uploader_limit_mib(image_byte_limit(cover_photo=is_cover_photo)),
                                  help=f"Up to {byte_limit_label(image_byte_limit(cover_photo=True))} and 40 million pixels; large photos may need resizing when the service is busy."
                                       if is_cover_photo else None)
        if upload:
            try:
                if is_cover_photo:
                    raw = read_picture_upload(upload, cover_photo=True)
                    replacements[slot] = normalize_cover_photo(raw, Path(upload.name).suffix)
                else:
                    replacements[slot] = normalize_report_image(upload.getvalue(), Path(upload.name).suffix, line_art=section.key == "organization" or slot.endswith("logo"))
            except (ValueError, OSError) as exc:
                if is_cover_photo:
                    from app.monthly_report_cover_ui import _picture_error
                    st.error(_picture_error(exc))
                else:
                    st.error("This picture could not be read. Choose another image; your previous selection is retained.")
        if slot in replacements:
            if slot == "cover_photo" and pending_use:
                if hashlib.sha256(replacements[slot].data).hexdigest() == pending_use:
                    plan["cover_photo_omitted"] = False
                else:
                    st.error("The new cover photograph changed before that choice was applied. Your No cover photograph choice remains; review the current image before using it.")
            omitted = section.key == "cover" and plan.get("cover_photo_omitted")
            st.image(replacements[slot].data, width="stretch", caption=label + (
                " — retained here; No cover photograph is selected" if omitted else " — included in this report"))
    plan["new_assets"] = list(replacements.items())
    if section.key == "cover" and plan.get("cover_photo_omitted") and "cover_photo" in replacements:
        image = replacements["cover_photo"]
        digest = hashlib.sha256(image.data).hexdigest()
        st.button("Use this new cover photograph", key=p + "_use_new_cover_" + digest[:20],
                  on_click=_use_new_cover_photo, args=(use_key, digest))


def _explicit_quote_price_risk(section, inspection):
    """Only a named uploaded vendor quote may need a price acknowledgment."""
    import re
    if inspection is None or section.key != "proposals":
        return False
    labels = " ".join(inspection.title_candidates)
    if not re.search(r"\b(?:vendor|supplier)\b.{0,60}\b(?:quote|quotation|estimate)\b"
                     r"|\b(?:quote|quotation|estimate)\b.{0,60}\b(?:vendor|supplier)\b",
                     labels, re.I):
        return False
    return any(contains_price(item.text + "\n" +
                              "\n".join(" ".join(row) for row in item.rows))
               for item in section.items)


def _section_card(section, path, inspection, period, prefix, field, plans, first, *, cover_photo_ids=(),
                  cover_design_available=False, source_name="Uploaded Word report", source_view=None, profile=None,
                  independent_template=False, native_art_size_limited=False):
    p = prefix + "_section_" + section.key
    old = plans.get(section.key, {})
    # Streamlit includes an expander's label in its identity, even with a key.
    # A changing "Ready" suffix would close it and discard its active widgets.
    text_only_period_review = (bool(old.get("period_review_items"))
                               and not old.get("new_assets")
                               and not old.get("preserved_assets")
                               and not old.get("word_page_records")
                               and not old.get("native_art_review")
                               and all(item.kind == "text" for item in section.items))
    # A quick close/reopen must not let an older toggle rerun remove an
    # active text editor. Keep this lightweight review mounted client-side.
    # Media, tables and native artwork retain their deliberate lazy boundary.
    box = st.expander(section.title, expanded=first, key=p + "_open",
                      on_change="ignore" if text_only_period_review else "rerun")
    if not text_only_period_review and not box.open:
        return
    with box:
        # Reserve the same position, but do not display stale approval from
        # the previous render. The current decision may have changed below.
        status_slot = st.empty()
        guide = section_help(section.key)
        st.write(guide.guidance)
        from app.monthly_report_content_kind import section_content_description
        content_description = section_content_description(section.items)
        if content_description:
            st.caption(content_description)
        actions = ["Keep and review", "Edit text or change pictures", "Leave this section out"]
        labels = dict(zip(actions, (guide.keep, guide.edit, "Start this section blank")))
        if section.key == "cover":
            labels[actions[2]] = ("Use selected ENFRA template" if independent_template else
                                 "Use this report’s cover design" if cover_design_available
                                  else "Leave imported cover artwork out")
        if section.key != "other" and any(item.kind == "image" for item in section.items):
            st.caption("Picture text and cells are not directly editable. Choose “" +
                       labels[actions[1]] + "” to reach replacement uploads.")
        action_key = field(_cover_action_key(prefix) if section.key == "cover" else p + "_action",
                           old.get("action", actions[0]))
        current_action = st.session_state.get(action_key)
        # Keep the cover's native remount default consistent with its staged
        # action. Unknown values still fall back to review, never approval.
        action_index = (actions.index(current_action)
                        if section.key == "cover" and current_action in actions else 0)
        action = st.radio("What would you like to do?", actions, index=action_index,
                          format_func=labels.get, key=action_key, horizontal=True)
        plan = {"key": section.key, "action": action, "target": section.key,
                "omit": action == actions[2], "selected": [], "texts": {},
                "tables": {}, "destinations": {},
                "new_assets": [(slot, image) for slot, image in old.get("new_assets", [])
                               if slot not in {"brand_logo", "client_logo"}],
                "image_notes": dict(old.get("image_notes", {})), "automatic": old.get("automatic", False),
                "period_review_items": tuple(old.get("period_review_items", ())),
                "period_review_label": period.label,
                "source_sha256": old.get("source_sha256", ""),
                "source_site_relation": old.get("source_site_relation", ""),
                "automatic_logo_skips": {role:list(ids) for role,ids in old.get("automatic_logo_skips", {}).items()},
                "automatic_divider_skips": {role:list(ids) for role,ids in old.get("automatic_divider_skips", {}).items()},
                "cover_photo_omitted": old.get("cover_photo_omitted", False),
                "cover_photo_source_ids": tuple(old.get("cover_photo_source_ids", ())),
                # A separate price/text question cannot erase an already
                # preserved native source diagram when this card reopens.
                "auto_native_diagrams": old.get("auto_native_diagrams", False),
                "captured_word_sections": old.get("captured_word_sections", ()),
                "preserved_assets": list(old.get("preserved_assets", ())),
                "word_page_records": list(old.get("word_page_records", ()))}
        from app.monthly_report_native_art_review import native_cover_furniture_ids
        furniture_ids = native_cover_furniture_ids(inspection.items) if source_view is not None else ()
        kept_native = set()
        if old.get("native_art_review") is not None:
            from app.monthly_report_native_art_review import verify_native_art_review
            context = verify_native_art_review(path, source_view, profile, period, old["native_art_review"])
            kept_native = {item.original_id for item in context.inventory.occurrences}
            plan["native_art_review"] = context.receipt
        blocking = []
        cover_recovery = ("Choose ‘Use selected ENFRA template’ above to leave the uploaded cover out."
                          if independent_template else
                          "Choose ‘Use this report’s cover design’ above to keep its current artwork."
                          if cover_design_available else
                          "Open an existing report if you want to use its saved cover design.")
        if plan["omit"]:
            if section.key == "cover":
                from app.monthly_report_start_import import unresolved_cover_artwork
                unread = any(i.kind == "unsupported" for i in section.items)
                if not cover_design_available and (unread or unresolved_cover_artwork(section.items, native_furniture_ids=furniture_ids)):
                    blocking.append(
                        "This starting report would also supply the new report’s page design. "
                        "Repair the unread or unassigned cover artwork in the original Word file "
                        "and upload it again, or open an existing report with a saved cover design. "
                        "Leaving its cover contribution out cannot make that source artwork safe."
                    )
                else:
                    st.caption(
                        "Uses the selected ENFRA whole-report template. Uploaded cover artwork and footer stay only in the retained original."
                        if independent_template else
                        "Keeps this report’s current cover design, logos, photograph and footer. "
                        "No cover artwork or address from this upload is added; the unchanged "
                        "original is retained."
                        if cover_design_available else
                        "The uploaded cover content stays in the saved original for reference."
                    )
            else:
                st.caption("This section stays in the report. The uploaded content remains in the saved original for reference.")
        else:
            from app.monthly_report_word_pages_ui import chart_page_review
            if chart_page_review(section, path, period, p, field, old, plan, blocking):
                # A deliberate complete-page selection replaces automatic
                # diagram capture; never combine two full-page copies.
                plan["auto_native_diagrams"] = False
                plan["captured_word_sections"] = ()
                if action == actions[1]:
                    _replacement_pictures(section, p, plan)
                elif plan["new_assets"]:
                    from app.monthly_report_sections import readable_label
                    for slot, image in plan["new_assets"]:
                        st.image(image.data, width="stretch", caption="Your updated " + readable_label(slot).lower() + " is retained")
                _approve_plan(plan, p, field, old, plans, blocking,
                              quote_price_risk=_explicit_quote_price_risk(section, inspection),
                              status_slot=status_slot)
                return
            items = list(section.items)
            if section.key == "cover":
                st.info(f"The cover will use the confirmed sites and {period.label}. Old cover dates and the old contents list are not reused.")
                # Logo/cover choices are visual; old cover prose cannot masquerade
                # as this month's activity. It remains in the retained original.
                items = [i for i in items if i.kind == "image" or i.suggested_slot == "footer_text"]
            elif section.key == "other":
                target = st.selectbox("Where should this content appear?", ["", *[s.key for s in known_sections()]],
                                      format_func=lambda k: next((s.title for s in known_sections() if s.key == k), "Choose a report section"), key=field(p + "_target", old.get("target", "")))
                plan["target"] = target
                if not target:
                    blocking.append("Choose a section above, or leave this additional content out of the draft.")
            texts = [i for i in items if i.kind == "text"]
            if old.get("period_review_items"):
                # Period review may not bring explicitly old prose back merely
                # because it shares a section with unfinished, undated work.
                # A pending period item may be unselected because its price
                # needs editing. Keep it visible; contains_price still blocks
                # approval until the user removes that price explicitly.
                retained_ids = old.get("combined_text_ids") or (
                    *old.get("selected", ()), *old.get("period_review_items", ()))
                texts = [i for i in texts if i.id in retained_ids]
            if texts:
                prior_texts = old.get("texts", {})
                if old.get("combined_text_ids"):
                    # An existing section edit is already an aggregate. Never
                    # append the original paragraphs again on its next rerun.
                    combined = prior_texts.get(texts[0].id, "\n\n".join(i.text for i in texts))
                else:
                    # Automatic plans store one value per paragraph, not one
                    # combined section under the first paragraph's identity.
                    combined = "\n\n".join(prior_texts.get(i.id, i.text) for i in texts)
                text = combined
                if action == actions[1]:
                    text_key = field(p + "_text", combined)
                    # A native remount needs the exact delivered value in its
                    # protobuf default too, including an intentional clear.
                    # Seeding Python session state alone can render blank.
                    text = st.text_area(guide.text_label,
                                        value=st.session_state.get(text_key, combined),
                                        key=text_key, height=200)
                if action != actions[1]:
                    st.text(text[:14000])
                    if len(text) > 14000:
                        st.caption(f"Long text: choose ‘{guide.edit}’ above to review the full section.")
                if contains_price(text):
                    blocking.append(f"This text includes pricing. Choose ‘{guide.edit}’ above and remove the pricing before including it.")
                plan["selected"].append(texts[0].id)
                plan["texts"][texts[0].id] = text
                if section.key == "cover":
                    plan["destinations"][texts[0].id] = "footer_text"
                # All original paragraphs remain identifiable in the review record.
                plan["combined_text_ids"] = [i.id for i in texts]
                findings = tuple(dict.fromkeys(f for i in texts for f in item_findings(i, period) if f.startswith("Other-month")))
                if findings:
                    st.warning("Check older dates in this section. Keep valid ongoing history; update only the parts that refer to this month’s work.")
            for n, item in enumerate((i for i in items if i.kind == "table"), 1):
                table, removed = table_without_prices(item)
                table = old.get("tables", {}).get(item.id, table)
                if table:
                    from app.monthly_report_table_review_ui import review_table_headings
                    table = review_table_headings(table, p + "_table_" + item.id, field)
                if removed:
                    st.caption("Pricing columns were removed from this client-facing table. The original table is retained in the uploaded report.")
                if table:
                    st.write(f"Table {n}")
                    rows = [dict(zip(table.columns, r)) for r in table.rows]
                    if action == actions[1]:
                        rows = _grid(p + "_table_" + item.id + "_" + _signature(table.columns), rows, num_rows="dynamic", hide_index=True)
                        table = ReportTable(table.columns, tuple(tuple("" if r.get(c) is None else str(r[c]) for c in table.columns) for r in rows))
                    else:
                        st.dataframe(rows[:300], hide_index=True)
                        if len(rows) > 300:
                            st.caption(f"Showing the first 300 rows. Choose ‘{guide.edit}’ above to inspect all rows.")
                    if table_has_pricing(table.columns, table.rows):
                        blocking.append(f"A table cell still contains pricing. Choose ‘{guide.edit}’ above and remove it.")
                    plan["tables"][item.id] = table
                    plan["selected"].append(item.id)
            from app.monthly_report_picture_cards import review_pictures
            pictures = [i for i in items if i.kind == "image" and i.id not in kept_native]
            if (old.get("automatic") and old.get("source_sha256") == inspection.sha256
                    and old.get("source_site_relation") == "same"):
                divider_roles = {"divider_" + section.key for section in known_sections()}
                # Reopening an unrelated card must not reselect native-owned source dividers.
                pictures = [item for item in pictures if not (
                    item.suggested_slot in divider_roles
                    and item.id in old.get("automatic_divider_skips", {}).get(item.suggested_slot, ())
                    and item.id not in old.get("selected", ()))]
            if section.key == "cover":
                fixed_logos = [i for i in pictures if old.get("destinations", {}).get(i.id, i.suggested_slot)
                               in {"brand_logo", "client_logo"}]
                for item in fixed_logos:
                    role = old.get("destinations", {}).get(item.id, item.suggested_slot)
                    if (old.get("automatic") and inspection is not None
                            and old.get("source_sha256") == inspection.sha256
                            and item.id in old.get("automatic_logo_skips", {}).get(role, ())
                            and item.id not in old.get("selected", ())):
                        # An unrelated review card cannot silently select a
                        # source logo already replaced by preferred artwork.
                        continue
                    plan["selected"].append(item.id)
                    plan["destinations"][item.id] = old.get("destinations", {}).get(item.id, item.suggested_slot)
                pictures = [i for i in pictures if i not in fixed_logos]
                if cover_photo_ids:
                    # The dedicated gallery already owns this same source's
                    # photo choice. A second gallery here used an independent
                    # native key and could reverse No cover photograph or a
                    # new selection while reviewing unrelated cover artwork.
                    chosen = old.get("cover_picture_id", "")
                    if (chosen in cover_photo_ids and chosen in old.get("selected", ())
                            and old.get("destinations", {}).get(chosen) == "cover_photo"):
                        plan["selected"].append(chosen)
                        plan["destinations"][chosen] = "cover_photo"
                    plan["cover_picture_id"] = chosen if chosen in cover_photo_ids else ""
                    plan["picture_choices"] = [chosen] if chosen in plan["selected"] else []
                    plan["picture_roles"] = {identity: "cover_photo" if identity in plan["picture_choices"] else ""
                                             for identity in cover_photo_ids}
            if not (section.key == "cover" and cover_photo_ids):
                review_pictures(pictures, section.key,
                                path, p, prefix, field, old, plan, blocking, allow_branding=False)
            if section.key == "cover":
                from app.monthly_report_start_import import unresolved_cover_artwork
                from app.monthly_report_import import read_import_image
                unknown = tuple(item for item in unresolved_cover_artwork(section.items, native_furniture_ids=furniture_ids) if item.id not in kept_native)
                if unknown:
                    st.markdown("**Other imported cover artwork**")
                    for number, item in enumerate(unknown[:4], 1):
                        st.caption(f"Cover artwork {number} · {source_name}")
                        try:
                            preview = read_import_image(path, item, preview=True, source_view=source_view)
                            st.image(preview.data, width=min(preview.width, 650))
                        except (ValueError, OSError):
                            st.warning(f"Cover artwork {number} could not be displayed; it remains in the original Word file.")
                    if len(unknown) > 4:
                        st.caption(f"{len(unknown) - 4} more unassigned cover images remain in this original.")
                    blocking.append(
                        "Cover artwork 1" + (f" and {len(unknown) - 1} more images have" if len(unknown) > 1 else " has") +
                        " no confirmed photograph or logo role. Repair it in the original Word "
                        "file and upload it again. " + cover_recovery +
                        " These images will not be silently dropped or assigned a guessed role."
                    )
            if action == actions[1] and section.key != "other":
                _replacement_pictures(section, p, plan)
            elif plan["new_assets"]:
                from app.monthly_report_sections import readable_label
                for slot, image in plan["new_assets"]:
                    caption = "Your updated " + readable_label(slot).lower() + " is retained"
                    if section.key == "cover" and plan.get("cover_photo_omitted") and slot == "cover_photo":
                        caption += "; No cover photograph is selected, so it is not included"
                    st.image(image.data, width="stretch", caption=caption)
            if any(i.kind == "unsupported" for i in section.items):
                # Do not silently exclude a difficult SmartArt/VML/OLE frame
                # after removing the old generic "continue without" radio.
                # It must be rendered into the original section or have an
                # explicit clear replacement before this section is accepted.
                preserved = section.key != "cover" and bool(plan.get("page_layout") and plan.get("preserved_assets")
                                 or plan.get("auto_native_diagrams") and plan.get("preserved_assets")
                                 or plan.get("new_assets"))
                plan["unsupported_reviewed"] = preserved
                if not preserved:
                    if section.key == "cover":
                        count = sum(i.kind == "unsupported" for i in section.items)
                        st.caption(f"{count} unread cover drawing{'s' if count != 1 else ''} · {source_name}")
                    blocking.append(
                        "A Word diagram in " + section.title + " could not be preserved. " +
                        ("The file exceeds the native-artwork processing limit. Use an available ENFRA template "
                         "or keep the original and upload a smaller test copy; replacing the upload starts a new review."
                         if section.key == "cover" and native_art_size_limited else
                         "A new cover photograph changes only the photograph; it cannot replace "
                         "this unread drawing. Repair that artwork in the original Word file and "
                         "upload it again. " + cover_recovery
                         if section.key == "cover" else
                         "Use its original-page preview or the clear replacement upload; "
                         "it will not be silently left out.")
                    )
                else:
                    st.caption("Source drawings are retained in this section, "
                               "either as safe original-page images or named replacements.")
        _approve_plan(plan, p, field, old, plans, blocking,
                      quote_price_risk=_explicit_quote_price_risk(section, inspection),
                      status_slot=status_slot)


def _approve_plan(plan, p, field, old, plans, blocking, *, quote_price_risk=False, status_slot=None):
    for message in blocking:
        st.error(message)
    stamp = plan_signature(plan)
    # The ordinary starting-report importer already strips known prices,
    # excludes unsafe text/pages and rejects a remaining price in its final
    # package gate. A blanket "this section is ready" checkbox adds no
    # protection. Reserve a specific acknowledgment for an explicitly named
    # vendor quotation whose content signals financial amounts; that checkbox
    # NEVER overrides an actual blocking content-safety error.
    reviewed = True
    if quote_price_risk:
        reviewed = st.checkbox(
            "I reviewed this vendor quotation and excluded all pricing",
            key=field(p + "_price_quote_review_" + stamp,
                      old.get("approval_stamp") == stamp))
    if plan.get("period_review_items") and not plan.get("omit"):
        period_reviewed = st.checkbox(
            "This work belongs in " + plan.get("period_review_label", "this month"),
            key=field(p + "_undated_period_review_" + stamp,
                      old.get("approval_stamp") == stamp))
        reviewed = reviewed and period_reviewed
    plan["approved"] = bool(reviewed and not blocking)
    plan["approval_stamp"] = stamp if plan["approved"] else ""
    plans[plan["key"]] = plan
    if status_slot is not None:
        # This is the same current decision used by Continue, not last run's
        # approved flag. Keep the expander title and all native controls stable.
        status_slot.caption("Ready" if plan["approved"] else "Review")
    if blocking:
        st.caption("Resolve the message above before including this content.")


def render_pending_cover_selection(draft, assets, contract, period, state):
    """Preview the selected imported cover photograph before committing it.

    Images are read from this session's original staging file and carried
    only in the transient preview payload. Neither current report history nor
    approved standing artwork changes until Continue is explicitly saved.
    """
    from app.monthly_report_import import read_import_image
    from app.monthly_report_model import ResolvedBlock
    prefix = "report_setup_" + _signature((contract, state.profile.key if state else draft.profile.key,
                                          period.key))
    staged = st.session_state.get(prefix + "_stage")
    if not staged:
        return draft, assets
    _, path, inspection = staged
    active = st.session_state.get(prefix + "_active_section_review")
    # Only this render's exact source/view/membership scope may contribute a
    # pending photo. Never guess a legacy key or reuse a superseded review.
    if not active or active[0] != inspection.sha256:
        return draft, assets
    plans = st.session_state.get(active[1] + "_section_plans", {})
    plan = plans.get("cover", {})
    if plan.get("omit"):
        return draft, assets
    if plan.get("cover_photo_omitted"):
        current = next((block for block in draft.blocks if block.key == "cover_photo"), None)
        if current and current.source != "Omit" and current.asset_hashes:
            st.caption("The imported cover photo is left out. Your current report photo is unchanged; remove it in this report first if you want no cover photograph.")
            return draft, assets
        omitted = replace(current, source="Omit") if current else ResolvedBlock("cover_photo", "Omit")
        return replace(draft, blocks=tuple(block for block in draft.blocks if block.key != "cover_photo") + (omitted,)), assets
    identity = next((item_id for item_id, slot in plan.get("destinations", {}).items()
                     if slot == "cover_photo" and item_id in plan.get("selected", ())), "")
    if not identity:
        return draft, assets
    item = next((candidate for candidate in inspection.items if candidate.id == identity
                 and candidate.kind == "image" and candidate.section in ("", "cover")), None)
    if item is None:
        return draft, assets
    try:
        photo = read_import_image(path, item, line_art=False)
        reference = library.asset_reference(photo.data, photo.extension)
    except (ValueError, OSError):
        st.caption("The selected cover photo is unavailable; the original report remains unchanged.")
        return draft, assets
    updated = dict(assets)
    updated[reference] = photo.data
    blocks = tuple(block for block in draft.blocks if block.key != "cover_photo") + (
        ResolvedBlock("cover_photo", "Replace once", asset_hashes=(reference,)),
    )
    st.caption("Cover preview includes the selected photo. It is not saved until you continue.")
    return replace(draft, blocks=blocks), updated


def _starting_review_sections(sections, plans, diagram_failures):
    """Keep unresolved cards reachable unless a dedicated recovery is shown.

    Cover/proposal drawings deliberately skip automatic preservation. Filtering
    every drawing question hid their only review controls. A card can also stay
    blocked after rebuilding its plan without the original seed questions.
    """
    pending = []
    for section in sections:
        plan = plans.get(section.key, {})
        questions = plan.get("questions", ())
        if (plan.get("approved") and not questions
                and not (section.key == "cover" and plan.get("omit"))
                and not plan.get("period_review_items")):
            continue
        if (section.key in diagram_failures and questions
                and all(q.startswith("A Word diagram or image") for q in questions)):
            continue
        pending.append(section)
    return tuple(pending)


def _native_art_preservation_review(path, source_view, profile, period, actor, prefix, field, *, saved=None, inventory=None):
    """One source-art preservation review, never a logo or Word-branch choice."""
    from app.monthly_report_native_art_review import (
        _native_art_inventory, make_native_art_review, _verify_native_art_review,
    )
    from app.monthly_report_import import _read_import_image
    from app.monthly_report_operational_source import _operation_from_verified_view
    if inventory is None:
        inventory = _native_art_inventory(path, source_view, profile, period)
    if not inventory.occurrences:
        return None
    if saved is not None:
        return _verify_native_art_review(path, source_view, profile, period, saved).receipt
    groups = {}
    for occurrence in inventory.occurrences:
        if any(values for representation in occurrence.rendition_representations
               for tag, values in representation.crop_orientation
               if tag not in ("{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent",
                              "{http://schemas.openxmlformats.org/drawingml/2006/main}ext")):
            st.error("This source artwork uses crop or orientation settings that require a rendered-location review. "
                     "The current preservation inspector cannot approve it from a full-image thumbnail.")
            return None
        groups.setdefault(occurrence.preview_group_key, []).append(occurrence)
    kept, reviewed = set(), set()
    with st.expander("Preserve native page artwork", expanded=True):
        st.caption("Keep this artwork in its original position. Check that it belongs in this report; "
                   "the original file stays unchanged.")
        with _operation_from_verified_view(path, source_view) as operation:
            items = {item.id: item for item in operation.view.original_inspection.items}
            for number, (group, occurrences) in enumerate(groups.items(), 1):
                key = prefix + "_native_art_" + inventory.sha256[:20] + "_" + group[:16]
                st.markdown(f"**Native page artwork {number}**")
                locations = tuple(dict.fromkeys(
                    "Cover" if item.original_part == "word/document.xml" else
                    "Page header" if "/header" in item.original_part else "Page footer"
                    for item in occurrences))
                st.caption(" / ".join(locations) + f" · {len(occurrences)} location(s)")
                with st.popover("Source details"):
                    st.caption("Exact source targets: " + "; ".join(
                        f"{item.original_part} · {item.original_id}" for item in occurrences))
                    st.caption("Preservation does not assign logo ownership or certify hidden file contents.")
                try:
                    from io import BytesIO
                    from zipfile import ZipFile
                    from PIL import Image
                    from app.monthly_report_operational_source import lookup_original
                    _, rendered = lookup_original(operation.view, occurrences[0].original_id)
                    with ZipFile(operation.rendition_path) as package:
                        with Image.open(BytesIO(package.read(rendered.image_part))) as source_image:
                            if (source_image.format != "PNG" or source_image.mode not in ("RGB", "RGBA")
                                    or source_image.info or source_image.getexif()):
                                raise ValueError("Rendered-location review is required for encoded display metadata.")
                    picture = _read_import_image(path, items[occurrences[0].original_id], preview=True,
                                                 source_view=operation.view, _operation=operation,
                                                 preserve_transparency=True)
                    st.image(picture.data, width=min(picture.width, 650))
                except (ValueError, OSError):
                    st.error("This verified artwork could not be displayed; preservation remains blocked.")
                    continue
                # One explicit action covers preservation AND the same visible
                # suitability review. Old separate/partial choices cannot seed it.
                st.caption("Confirm it belongs in this report, with no visible pricing or inappropriate private information.")
                if st.checkbox("I reviewed this artwork and want to keep it unchanged",
                               key=field(key + "_preserve_review_v1", False)):
                    kept.update(item.original_id for item in occurrences)
                    reviewed.update(item.original_id for item in occurrences)
        ids = tuple(item.original_id for item in inventory.occurrences)
        if kept != set(ids) or reviewed != set(ids) or not actor.strip():
            st.info("Inspect and preserve every listed artwork group before this source design can be used.")
            return None
        return make_native_art_review(inventory, actor=actor, keep_native_ids=ids,
                                      visually_reviewed_ids=ids, suitable_ids=ids)


def _source_view_admission(function):
    """Finite automatic source preparation shares the existing monthly slot."""
    from functools import wraps
    from inspect import signature
    parameters = signature(function)
    @wraps(function)
    def admitted(*args, **kwargs):
        values = parameters.bind_partial(*args, **kwargs).arguments
        state, identity = values.get('state'), values.get('identity')
        prefix = ("report_setup_" + _signature((values['contract'], state.profile.key if state else identity.key if identity else "new", values['period'].key))
                  if 'contract' in values and 'period' in values else None)
        if prefix:
            st.session_state.pop(prefix + '_active_section_review', None)
        staged = st.session_state.get(prefix + '_stage') if prefix else None
        from app.monthly_report_source_view_runtime import import_candidate
        needs_view = staged is not None and import_candidate(staged[2])
        from app import monthly_report_render_jobs as jobs
        try:
            if kwargs.get("source_view") is None and not needs_view:
                return function(*args, **kwargs)
            with jobs.work_slot(preview=True):
                return function(*args, **kwargs)
        except jobs.RenderBusy:
            from app.monthly_report_busy_ui import show_busy_retry
            show_busy_retry()
            return True
    return admitted


@_source_view_admission
def render_section_setup(contract, period, prepared, field, *, state=None, identity=None,
                         working_draft=None, working_assets=(), working_revision=None, source_view=None):
    prefix = "report_setup_" + _signature((contract, state.profile.key if state else identity.key if identity else "new", period.key))
    # An existing report is already editable. Keep its replacement uploader
    # optional, but always render the uploader in the same widget container
    # across staged/review reruns so Streamlit cannot discard its bytes.
    optional_import = working_draft is not None
    original_token_key = prefix + "_original_review_token"

    def _open_saved_original():
        if not state:
            return
        original = library.imported_original(contract, state.profile.key)
        if original and st.button("Open the saved original for section review",
                                  key=prefix + "_original", disabled=not prepared.strip()):
            from app.monthly_report_import import inspect_docx
            st.session_state[prefix + "_stage"] = (None, original, inspect_docx(original))
            st.session_state[original_token_key] = uuid4().hex
            st.session_state[prefix + "_image_conflict_incarnation"] = uuid4().hex
            st.session_state.pop(prefix + "_image_replacements", None)
            st.rerun()

    if optional_import:
        with st.expander("Use a different starting report",
                         expanded=bool(st.session_state.get(prefix + "_stage")
                                       or st.session_state.get(prefix + "_failed_digest"))):
            st.caption("Upload an earlier or unfinished Word report.")
            upload = st.file_uploader("Starting report", type=["docx"], max_upload_size=128,
                                      key=prefix + "_upload")
            _open_saved_original()
    else:
        st.subheader("Start with a report")
        st.caption("Upload an earlier or unfinished Word report.")
        upload = st.file_uploader("Starting report", type=["docx"], max_upload_size=128,
                                  key=prefix + "_upload")
    # File selection is the Analyze action. The exact content hash, never
    # its reusable filename or a widget rerun, determines whether a new
    # source must be inspected. An error leaves the existing staged draft
    # intact and presents one explicit Retry, not repeated heavy parsing.
    if upload is not None:
        digest = hashlib.sha256(upload.getvalue()).hexdigest()
        staged = st.session_state.get(prefix + "_stage")
        loaded_hash = staged[2].sha256 if staged else ""
        committed_hash = st.session_state.get(prefix + "_committed_upload_digest", "")
        failed_hash = st.session_state.get(prefix + "_failed_digest")
        retry = False
        if failed_hash == digest:
            retry = st.button("Retry report analysis", key=prefix + "_retry_analysis")
        # A committed upload still mounted after saving must not reopen itself.
        # Once another source is staged, however, reselecting that committed
        # file is a new choice and must replace the superseded review.
        unchanged_committed_upload = not staged and digest == committed_hash
        if digest != loaded_hash and not unchanged_committed_upload and (digest != failed_hash or retry):
            try:
                with st.spinner("Reading sections and cover pictures…"):
                    incoming = _stage(upload)
                previous = st.session_state.get(prefix + "_stage")
                st.session_state[prefix + "_stage"] = incoming
                st.session_state[prefix + "_image_conflict_incarnation"] = uuid4().hex
                st.session_state.pop(prefix + "_image_replacements", None)
                st.session_state.pop(original_token_key, None)
                st.session_state.pop(prefix + "_failed_digest", None)
                st.session_state.pop(prefix + "_failed_notice", None)
                if previous and previous[0]:
                    previous[0].cleanup()
                st.rerun()
            except (ValueError, OSError) as exc:
                # Retain only a vetted, operator-safe failure reason. An XML
                # parser exception can contain filenames or source fragments.
                # A neutral rerun must not erase the actual rejected budget.
                from app.monthly_report_starting_errors import starting_docx_failure_notice
                st.session_state[prefix + "_failed_digest"] = digest
                st.session_state[prefix + "_failed_notice"] = starting_docx_failure_notice(exc)
    else:
        st.session_state.pop(prefix + "_failed_digest", None)
        st.session_state.pop(prefix + "_failed_notice", None)
        # Removing then selecting the same file is an explicit new import.
        # An unchanged native uploader after a successful save is not.
        st.session_state.pop(prefix + "_committed_upload_digest", None)
        previous = st.session_state.get(prefix + "_stage")
        if previous and previous[0]:
            # Removing the uploader's file cancels its unsaved review too.
            # An explicitly opened saved original has no temporary handle and
            # remains available through its independent action below.
            previous[0].cleanup()
            st.session_state.pop(prefix + "_stage", None)
    if upload is not None and st.session_state.get(prefix + "_failed_digest") == digest:
        st.warning(st.session_state.get(prefix + "_failed_notice",
                  "This report could not be analyzed. Choose a valid DOCX or retry; your existing work was preserved."))
        if failed_hash != digest:
            # On the first rejected upload, the earlier Retry control did not
            # exist when the digest was checked. Show it *now* rather than
            # requiring a neutral second click/rerun to reveal recovery.
            # On later renders the same keyed button was already mounted above.
            st.button("Retry report analysis", key=prefix + "_retry_analysis")
        st.info("The newly selected file has not been analyzed. Retry or choose another file before continuing.")
        return True
    if not optional_import:
        _open_saved_original()
    staged = st.session_state.get(prefix + "_stage")
    if not staged:
        st.session_state.pop(original_token_key, None)
        return False
    _, path, inspection = staged
    automatic_view = source_view is None
    native_art_size_limited = False
    if source_view is None:
        from app.monthly_report_source_view_runtime import derive_import_view
        try:
            source_view = derive_import_view(path, inspection)
        except (ValueError, OSError) as exc:
            # Original audit and existing blocking questions remain truthful.
            from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES
            if path.stat().st_size > MAX_VIEW_SOURCE_BYTES and "source byte budget" in str(exc):
                native_art_size_limited = True
                st.warning(
                    f"This file is within the 128 MiB upload limit, but automatic native-artwork "
                    f"interpretation is limited to {MAX_VIEW_SOURCE_BYTES // (1024 * 1024)} MiB. "
                    "This is a processing limit, not evidence that the artwork is damaged. "
                    "Your original and current review are unchanged. Use an available independent "
                    "template below, or keep the original and upload a smaller test copy. "
                    "Replacing the upload starts a new review.")
            else:
                st.warning("Automatic native artwork interpretation is blocked: " + str(exc))
    if source_view is not None and not automatic_view:
        from app.monthly_report_operational_source import verify_inspection
        try:
            source_view = verify_inspection(path, inspection, source_view)
        except (ValueError, OSError) as exc:
            st.error(str(exc))
            return True
    p = prefix + "_" + inspection.sha256[:16]
    if source_view is not None:
        p += "_view_" + source_view.receipt_sha256[:16]
    cancel_original = False
    if staged[0] is None:
        # A later review of identical source bytes is a new action target.
        token = st.session_state.setdefault(original_token_key, uuid4().hex)
        cancel_original = st.button("Cancel saved-original review", key=p + "_cancel_original_" + token)
    if cancel_original:
        # This stage has no uploader to clear. Retire only its unsaved review
        # choices, never the saved original or the current report's work.
        st.session_state.pop(prefix + "_stage", None)
        st.session_state.pop(original_token_key, None)
        for key in list(st.session_state):
            if key.startswith(p + "_"):
                st.session_state.pop(key, None)
        st.rerun()
    if state and staged[0] is None and not prepared.strip():
        st.info("Enter Prepared by above to review the saved original.")
        return True
    if identity:
        candidate = identity
        actor = prepared.strip() or st.text_input(
            "Your name", key=field(p + "_actor", ""))
        missing = [] if actor.strip() else ["Enter your name."]
    else:
        candidate, actor, missing = _identity(contract, prepared, p, field, state, inspection)
    if not candidate:
        for message in missing:
            st.info(message)
        return True
    from app.monthly_report_start_import import (
        analyze_starting_report,
        automatic_section_plans,
        build_starting_import,
    )
    profiles = library.list_profiles(contract)
    known_sites = {f.key: f for f in (*_site_options(contract), *(f for profile in profiles for f in profile.facilities), *candidate.facilities)}
    analysis = analyze_starting_report(inspection, candidate, period, known_sites.values(), known_profiles=profiles)
    from app.monthly_report_source_sites_ui import correct_detected_sites
    confirmed_source = correct_detected_sites(
        inspection, candidate, period, analysis.source_sites, tuple(known_sites.values()),
        p, field, source_view=source_view)
    if confirmed_source is not None:
        analysis = analyze_starting_report(
            inspection, candidate, period, known_sites.values(),
            confirmed_sites=confirmed_source, known_profiles=profiles)
    if analysis.site_relation == "unknown":
        st.info("The starting report does not clearly name its sites. Confirm them once so another site's contacts and work are not copied into this report.")
        from app.monthly_report_start_import import source_sites
        inferred_source = {site.key for site in source_sites(inspection, known_sites.values())}
        source_keys = [
            site.key for site in known_sites.values()
            if st.checkbox(site.title, key=field(p + "_source_site_" + site.key,
                                                site.key in inferred_source))
        ]
        with st.expander("A source site is not listed"):
            source_names = st.text_input("Source site name", key=field(p + "_source_site_name", ""),
                                         help="For several source sites, separate the names with semicolons.")
        confirmed_sites = [known_sites[key] for key in source_keys]
        for name in (n.strip() for n in source_names.split(";")):
            if name:
                if not _key(name):
                    st.error("Enter the source site's name using letters or numbers.")
                    return True
                confirmed_sites.append(next((f for f in known_sites.values() if name.casefold() in
                                              {n.casefold() for n in (f.title, *f.aliases)}), Facility(_key(name), name)))
        if not confirmed_sites:
            return True
        analysis = analyze_starting_report(inspection, candidate, period, known_sites.values(),
                                          confirmed_sites=tuple({f.key: f for f in confirmed_sites}.values()))
    from app.monthly_report_source_sites_ui import source_review_epoch
    p += "_source_scope_" + source_review_epoch(
        inspection, candidate, period, analysis.source_sites, analysis.site_relation, source_view)
    source_names = "; ".join(site.title for site in analysis.source_sites)
    st.caption("Starting report: " + source_names + (f" · {analysis.source_period[0]}-{analysis.source_period[1]:02d}" if analysis.source_period else " · source month not stated"))
    if analysis.site_relation == "other":
        st.info("This report covers different sites. Its layout and table headings will be reused; your selected sites keep their own contacts, photos and work.")
    elif analysis.older_items:
        st.info(f"Preparing {period.label}. Earlier monthly work stays in the original. Standing information and any work already updated for this month are carried across.")
    else:
        st.info(f"Preparing {period.label}. Existing work is carried across so you can finish the remaining sections.")
    from app.monthly_report_branding import find_logo, load_branding
    branding = load_branding()
    preferred_logos = tuple(key for key in ("brand_logo", "client_logo")
                            if (state and state.block(key) and state.block(key).asset_hashes)
                            or (branding and find_logo(contract, brand=key == "brand_logo", state=branding)))
    from app.monthly_report_designs import source_for
    native_design = source_for(candidate) is not None
    native_art_review = None
    native_art_pending = False
    if (source_view is not None and state is not None
            and state.profile.imported_from not in ("", inspection.sha256)):
        # An incoming contribution is not permission to replace the saved
        # native design or rebind its source-view authority to different bytes.
        st.info("This is a different starting-report file. Its native artwork cannot yet be combined with this saved report. Your saved report is unchanged. "
                "Add the updated pages in their report sections, or start a separate report to use this design.")
        return True
    if source_view is not None:
        try:
            saved_art = (library.imported_native_art_review(contract, candidate.key, period, source_view=source_view)
                         if state and state.profile.imported_from == inspection.sha256
                         and library.source_view_replay_recorded(contract, candidate.key, period, inspection.sha256) else None)
            from app.monthly_report_native_art_review import _native_art_inventory
            art_inventory = _native_art_inventory(path, source_view, candidate, period)
            native_art_review = _native_art_preservation_review(
                path, source_view, candidate, period, actor, p, field, saved=saved_art,
                inventory=art_inventory)
            native_art_pending = bool(art_inventory.occurrences) and native_art_review is None
        except (ValueError, OSError) as exc:
            st.error(str(exc))
            return True
    seed = automatic_section_plans(inspection, analysis, preferred_logos=preferred_logos,
                                   native_design=native_design, source_view=source_view,
                                   native_art_review=native_art_review, source_path=path,
                                   profile=candidate, period=period)
    seed_signature = _signature((analysis, preferred_logos, native_design) if source_view is None else
                                (analysis, preferred_logos, native_design, native_art_review,
                                 source_view.receipt_sha256))
    if st.session_state.get(p + "_analysis_signature") != seed_signature:
        st.session_state[p + "_section_plans"] = seed
        st.session_state[p + "_analysis_signature"] = seed_signature
    intent = "Automatic starting report"
    sections = section_reviews(inspection, source_view=source_view)
    plans = st.session_state.setdefault(p + "_section_plans", {})
    st.session_state[prefix + "_active_section_review"] = (inspection.sha256, p)
    # Preserve native diagrams at their evidenced Word/ENFRA section before
    # asking the operator about anything. Ordinary image parts already follow
    # suggested_slot; this path is only for complex native Word drawings.
    # Rendering uses the existing bounded, passive Word-page converter and is
    # cached per content hash/section. Failure does not equate to Leave out:
    # the section remains blocked, with its source retained for exact repair.
    from app.monthly_report_visual_preservation import (
        DiagramPreservationError, diagram_source_sections, preserve_section_diagrams,
    )
    diagram_failures = {}
    if analysis.site_relation == "same":
        from app.monthly_report_content_policy import contains_price
        for section in sections:
            if section.key in ("cover", "other", "proposals", "accounts_receivable"):
                # Cover art can contain another site's logo and proposals can
                # show money only in image pixels; neither is auto-certified.
                continue
            if not any(i.kind == "unsupported" for i in section.items):
                continue
            plan = plans.get(section.key, {})
            if plan.get("auto_native_diagrams") or plan.get("new_assets"):
                continue
            if any(i.id in analysis.older_items for i in section.items
                   if i.kind == "unsupported"):
                diagram_failures[section.key] = (
                    "This drawing appears to belong to an earlier reporting "
                    "period. Its destination is retained, but it must be checked "
                    "before being carried into the current month."
                )
                continue
            cache_key = p + "_diagram_render_" + section.key
            result = st.session_state.get(cache_key)
            if result is None:
                try:
                    diagram_source_sections(inspection, section)
                    with st.spinner("Keeping the original diagrams in " + section.title + "…"):
                        result = preserve_section_diagrams(path, inspection, section)
                except DiagramPreservationError as exc:
                    result = str(exc)
                st.session_state[cache_key] = result
            if isinstance(result, str):
                diagram_failures[section.key] = result
                continue
            if result:
                plan.update(result)
                plan["unsupported_reviewed"] = True
                plan["questions"] = tuple(q for q in plan.get("questions", ())
                                         if not q.startswith("A Word diagram or image"))
                plan["approved"] = not plan["questions"]
                plans[section.key] = plan

    # A single optional cover photo belongs in a small thumbnail gallery, not
    # a repeated radio under every large photo/logo. The automatic suggestion
    # is already in the plan; clicking a replacement changes only this unsaved
    # draft and leaves the retained original/approved logos untouched.
    # A whole-template choice is explicit and remains staged until the normal
    # atomic Continue save. It never approves the uploaded cover artwork.
    template_choice_key = p + "_independent_template"
    template_choice = st.session_state.get(template_choice_key, {})
    template_scope = (inspection.sha256, candidate.contract, candidate.key, period.key)
    if template_choice and template_choice.get("scope") != template_scope:
        # A namespace key alone is not proof of the full source identity.
        # Retire only this stale opt-in, never another section's review.
        st.session_state.pop(template_choice_key, None)
        template_choice = {}
    fallback_template, fallback_error = "", ""
    cover_review = next((section for section in sections if section.key == "cover"), None)
    if state is None and source_view is None and cover_review is not None:
        from app.monthly_report_start_import import unresolved_cover_artwork
        from app.monthly_report_template_fallback import verified_master_template
        if (any(item.kind == "unsupported" for item in cover_review.items)
                or unresolved_cover_artwork(cover_review.items)):
            try:
                available_template = verified_master_template(candidate, template_choice.get("template", ""))
                if template_choice:
                    fallback_template = available_template
            except (ValueError, OSError) as exc:
                available_template, fallback_error = "", str(exc)
                st.error(fallback_error)
            if available_template:
                st.caption("Use the ENFRA template for the whole report, not just its cover. "
                           "The uploaded report’s original formatting will not be reproduced. "
                           "Your body review, edits and original file stay; imported cover artwork is left out. "
                           "Nothing is saved until Continue.")
                if not fallback_template:
                    if st.button("Use ENFRA template and keep this review", key=p + "_choose_template"):
                        from copy import deepcopy
                        st.session_state[template_choice_key] = {
                            "template": available_template, "scope": template_scope, "cover_plan": deepcopy(plans["cover"])}
                        plans["cover"] = dict(plans["cover"], action="Leave this section out", omit=True,
                                               approved=True, questions=[])
                        _replace_cover_action(p, "Leave this section out")
                        st.rerun()
                elif st.button("Keep uploaded report design instead", key=p + "_cancel_template"):
                    plans["cover"] = template_choice["cover_plan"]
                    _replace_cover_action(p, plans["cover"].get("action", "Keep and review"))
                    st.session_state.pop(template_choice_key, None)
                    st.rerun()
    cover_photo_ids = ()
    cover_section = next((section for section in sections if section.key == "cover"), None)
    if cover_section and analysis.site_relation == "same":
        from app.monthly_report_start_import import cover_photo_candidates
        from app.monthly_report_picture_cards import review_cover_gallery
        from app.monthly_report_native_art_review import native_cover_furniture_ids
        furniture_ids = native_cover_furniture_ids(inspection.items) if source_view is not None else ()
        candidates = cover_photo_candidates(cover_section.items, native_furniture_ids=furniture_ids)
        if candidates:
            cover_photo_ids = tuple(item.id for item in candidates)
            with st.expander("Cover photograph", expanded=True,
                             key=p + "_cover_gallery_expander", on_change="rerun") as gallery:
                if gallery.open:
                    existing = plans["cover"]
                    if existing.get("omit"):
                        st.caption("Imported cover photos are not selected while this upload’s cover content is left out. Change that choice in Cover and page design below.")
                    else:
                        updated = dict(existing)
                        updated["selected"] = list(existing.get("selected", ()))
                        updated["destinations"] = dict(existing.get("destinations", {}))
                        review_cover_gallery(candidates, path, p + "_cover_gallery",
                                             existing, updated)
                        # No blanket approval button: the selected source photo
                        # still flows through the image/package safety checks.
                        # A photograph selection cannot resolve unread Word art
                        # or a previous blocking review in this same cover.
                        updated["approved"] = bool(existing.get("approved")
                                                   and not updated.get("questions"))
                        plans["cover"] = updated
    questions = [section for section in sections if plans.get(section.key, {}).get("questions")]
    if diagram_failures:
        st.subheader("Diagrams needing a specific recovery")
        for section in sections:
            if section.key not in diagram_failures:
                continue
            with st.container(border=True):
                st.markdown("**" + section.title + "**")
                st.warning(diagram_failures[section.key])
                key = p + "_diagram_render_" + section.key
                if st.button("Retry safe diagram preservation for " + section.title,
                             key=key + "_retry"):
                    st.session_state.pop(key, None)
                    st.rerun()
                from app.monthly_report_visual_preservation import VISUAL_SLOTS
                slot = VISUAL_SLOTS.get(section.key)
                if slot:
                    upload = st.file_uploader(
                        "Clear replacement diagram for " + section.title,
                        type=["png", "jpg", "jpeg", "heic", "heif", "webp"],
                        key=p + "_diagram_replacement_" + section.key,
                        max_upload_size=30,
                    )
                    if upload:
                        try:
                            picture = normalize_report_image(
                                upload.getvalue(), Path(upload.name).suffix,
                                line_art=section.key in ("organization", "subcontractors", "capital", "rfi"),
                            )
                        except (ValueError, OSError):
                            st.error("The replacement image could not be safely read. The original is unchanged.")
                        else:
                            plan = plans[section.key]
                            plan["new_assets"] = [(slot, picture)]
                            plan["unsupported_reviewed"] = True
                            plan["questions"] = tuple(q for q in plan.get("questions", ())
                                                      if not q.startswith("A Word diagram or image"))
                            plan["approved"] = not plan["questions"]
                            plans[section.key] = plan
                            st.caption("The replacement is selected for this section and "
                                       "will be saved only when you continue.")
    # A recoverable diagram has its own exact-section retry/upload directly
    # above. Do not show a second generic Keep/Edit/Leave-out radio for that
    # same unresolved object.
    questions = _starting_review_sections(sections, plans, diagram_failures)
    if questions:
        pending_review = any(not plans[s.key].get("approved") or plans[s.key].get("questions")
                             for s in questions)
        st.subheader("A few details need a check" if pending_review else "Imported content is ready")
        for index, section in enumerate(questions):
            # Keep month-confirmed content reachable for corrections. Reuse its
            # stable, collapsible card rather than removing its widgets (and
            # losing the only edit path) after acknowledgment.
            if not plans[section.key].get("approved") or plans[section.key].get("questions"):
                for message in seed[section.key]["questions"]:
                    st.caption(section.title + ": " + message)
            _section_card(section, path, inspection, period, p, field, plans, index == 0,
                          cover_photo_ids=cover_photo_ids if section.key == "cover" else (),
                          cover_design_available=state is not None or bool(fallback_template),
                          independent_template=bool(fallback_template),
                          native_art_size_limited=native_art_size_limited,
                          source_name=upload.name if upload is not None else "Saved original Word report",
                          source_view=source_view, profile=candidate)
    with st.expander("Review what will be carried across (optional)", key=p + "_check_import", on_change="rerun") as details:
        if details.open:
            for section in sections:
                if section not in questions:
                    plan = plans[section.key]
                    has_content = any(plan.get(key) for key in ("selected", "new_assets", "preserved_assets"))
                    status = "ready" if has_content else "starts blank"
                    if not plan.get("approved") or plan.get("questions"):
                        status = "needs review"
                    st.caption(section.title + " · " + status)
    remaining = [s.title for s in sections if not plans.get(s.key, {}).get("approved")]
    todo = [*missing, *(["Review these sections: " + "; ".join(remaining) + "."] if remaining else [])]
    if fallback_error:
        todo.append("The selected ENFRA template could not be verified; your review is unchanged.")
    if fallback_template and not plans.get("cover", {}).get("omit"):
        todo.append("Leave this upload’s cover contribution out to use the independent ENFRA template.")
    if native_art_pending:
        todo.append("Review the native page artwork above before continuing.")
    if state is None and not fallback_template and cover_section and plans["cover"].get("approved"):
        from app.monthly_report_start_import import unresolved_cover_artwork
        from app.monthly_report_native_art_review import native_cover_furniture_ids
        furniture_ids = native_cover_furniture_ids(inspection.items) if source_view is not None else ()
        kept_native = set()
        if native_art_review is not None:
            from app.monthly_report_native_art_review import verify_native_art_review
            context = verify_native_art_review(path, source_view, candidate, period, native_art_review)
            kept_native = {item.original_id for item in context.inventory.occurrences}
        if (any(item.kind == "unsupported" for item in cover_section.items)
                or any(item.id not in kept_native for item in unresolved_cover_artwork(cover_section.items, native_furniture_ids=furniture_ids))):
            # Even deliberately excluded foreign content would remain inside a
            # new profile's uploaded native design. A contribution omission or
            # an older staged approval cannot certify that design's artwork.
            message = ("The cover artwork in " + (upload.name if upload is not None else "the saved original") +
                       " is unread or has no confirmed role. Repair it in the original Word file and upload it again, "
                       "or open an existing report with a saved cover design. This upload would also supply a new report’s page design.")
            if native_art_size_limited:
                message = ("This upload exceeds the native-artwork processing limit, so its page design cannot yet be used. "
                           "Choose an available ENFRA template above, or keep the original and upload a smaller test copy. "
                           "Replacing the upload starts a new review; the original is not damaged by this error.")
            st.error(message)
            todo.append("Choose an independent template or a smaller test copy to continue."
                        if native_art_size_limited else
                        "Repair the source cover artwork before using it as a new report design.")
    prepared_import = None
    def _prepare_merge():
        nonlocal prepared_import
        if prepared_import is None:
            # New eager preflight work shares the existing admission gate with
            # previews/exports. Keep one normalized import only in this rerun,
            # never a second decoded copy or a cross-rerun/session asset cache.
            from app.monthly_report_render_jobs import work_slot
            with work_slot(preview=True) if recovery_preflight else nullcontext():
                prepared_import = build_starting_import(
                    path, inspection, tuple(plans[s.key] for s in sections),
                    source_view=source_view, profile=candidate, period=period)
        else:
            # Continue may reuse immutable normalized bytes from this exact
            # render, but source identity and mutable saved state are checked
            # again, then profile/snapshot CAS protects final publication.
            if path.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("Original DOCX exceeds the import limit.")
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != inspection.sha256:
                    raise ValueError("Original DOCX changed during review. Analyze it again.")
        mapped, mappings = prepared_import
        profile = candidate if state else design_profile(candidate, inspection, mappings, mapped.overrides)
        profile = replace(profile, excluded_sections=())
        if fallback_template:
            from app.monthly_report_template_fallback import fallback_profile
            profile = fallback_profile(profile, fallback_template)
        draft = imported_draft(profile, period, actor, mapped)
        draft = replace(draft, sections=tuple(replace(s, included=True) for s in draft.sections))
        if fallback_template:
            from app.monthly_report_template_fallback import validate_fallback_sections
            validate_fallback_sections(draft)
        replay_existing = state and (source_view is None or library.source_view_replay_recorded(
            contract, profile.key, period, inspection.sha256))
        previous, verified = library.starting_contribution(
            contract, profile.key, period, inspection.sha256, source_view=source_view) if replay_existing else (None, False)
        from app.monthly_report_start_replay import (
            retain_automatic_divider_contributions, retain_automatic_logo_contributions,
        )
        incoming_keys = {block.key for block in draft.blocks}
        draft = retain_automatic_logo_contributions(
            draft, previous, verified=verified, inspection=inspection,
            plans=plans.values(), preferred_logos=preferred_logos)
        draft = retain_automatic_divider_contributions(
            draft, previous, verified=verified, inspection=inspection,
            plans=plans.values(), native_design=native_design)
        consumed_logo_slots = {block.key for block in draft.blocks
                               if block.key in ("brand_logo", "client_logo") and block.key not in incoming_keys}
        current = library.load_snapshot(contract, profile.key, period) if state else None
        prior_import = library.load_imported_draft(contract, profile.key) if state else None
        base = current.draft if current else None
        if working_draft is not None:
            if (working_draft.profile.contract, working_draft.profile.key, working_draft.period) != (contract, profile.key, period):
                raise ValueError("The open draft belongs to different sites or a different month. Reopen the intended report before importing.")
            if working_revision != (current.revision if current else 0):
                raise ValueError("Another version was saved while you were working. Compare and accept that version using Save progress before adding this report. Your open draft and upload are preserved.")
            base = working_draft
        elif prior_import and prior_import.period == period and (not current or library.imported_snapshot_revision(contract, profile.key) == current.revision):
            # Bootstrap already includes this exact snapshot plus the
            # last acknowledged import. Appending the snapshot again
            # can resurrect its older text or duplicate edited tables.
            base = prior_import
        return mapped, profile, draft, previous, verified, consumed_logo_slots, current, base

    from app.monthly_report_start_conflicts import LABELS, image_conflicts, apply_replacements, snapshot_guard
    replacement_key = prefix + "_image_replacements"
    incarnation_key = prefix + "_image_conflict_incarnation"
    incarnation = st.session_state.setdefault(incarnation_key, uuid4().hex)
    decisions = st.session_state.setdefault(replacement_key, {})
    review_scope = _signature((inspection.sha256, tuple(plan_signature(plan) for plan in plans.values()),
                               candidate, actor, working_draft, working_revision,
                               state.revision if state else 0))
    if st.session_state.get(prefix + "_image_review_scope") != review_scope:
        decisions.clear()
        incarnation = uuid4().hex
        st.session_state[incarnation_key] = incarnation
        st.session_state[prefix + "_image_review_scope"] = review_scope
    def _conflict_context(current):
        return dict(verified=verified, source_sha256=inspection.sha256,
                    profile_revision=state.revision if state else 0,
                    snapshot_revision=current.revision if current else 0,
                    incarnation=incarnation)

    has_page = any(slot in LABELS for plan in plans.values()
                   for slot in (*plan.get("destinations", {}).values(),
                                *(slot for slot, _ in plan.get("new_assets", ())),
                                *(slot for slot, _ in plan.get("preserved_assets", ()))))
    recovery_preflight = bool(state and not todo and has_page)
    if recovery_preflight:
        from app.monthly_report_render_jobs import RenderBusy
        try:
            mapped, profile, incoming_draft, previous, verified, _, current, base = _prepare_merge()
            scope = _signature((base, incoming_draft, previous, verified, state.revision,
                                current.revision if current else 0))
            scope_key = prefix + "_image_conflict_scope"
            if st.session_state.get(scope_key) != scope:
                decisions.clear()
                incarnation = uuid4().hex
                st.session_state[incarnation_key] = incarnation
                st.session_state[scope_key] = scope
            conflicts = image_conflicts(base, incoming_draft, previous, **_conflict_context(current))
            valid = {conflict.slot: conflict.binding for conflict in conflicts}
            if any(valid.get(slot) != binding for slot, binding in decisions.items()):
                decisions.clear()
                st.warning("The report or incoming picture changed. Review both pictures again before replacing anything.")
            if conflicts:
                st.subheader("A report page already has a different picture")
                st.caption("Your current report is unchanged. Compare the two pages before explicitly replacing one. This does not approve the incoming picture’s contents.")
                assets = dict((*working_assets, *mapped.assets))
                for conflict in conflicts:
                    with st.container(border=True):
                        st.markdown("**" + conflict.label + "**")
                        for label, block in (("Current report", conflict.current), ("Incoming report", conflict.incoming)):
                            reference = block.asset_hashes[0]
                            raw = assets.get(reference) or library.read_asset(contract, profile.key, reference)
                            if library.asset_reference(raw, reference.rsplit(".", 1)[-1]) != reference:
                                raise ValueError("A preview picture changed. Review the source again; your report is unchanged.")
                            st.image(raw, width="stretch", caption=label + " — " + conflict.label)
                            st.caption("Picture caption: " + (block.asset_captions[0] if block.asset_captions else "(none)"))
                        if decisions.get(conflict.slot) == conflict.binding:
                            st.caption("Incoming page selected. Nothing changes until you continue and the import saves successfully.")
                        if st.button("Use incoming " + conflict.label.lower(), key=p + "_replace_" + conflict.binding):
                            decisions[conflict.slot] = conflict.binding
                            st.rerun()
                        if st.button("Keep current " + conflict.label.lower() + " and return to review", key=p + "_keep_" + conflict.binding):
                            decisions.clear()
                            st.session_state[incarnation_key] = uuid4().hex
                            st.rerun()
                if any(decisions.get(conflict.slot) != conflict.binding for conflict in conflicts):
                    todo.append("Compare the different report pages above. Keeping the current page leaves this incoming report unimported.")
        except (ValueError, OSError, RenderBusy) as exc:
            decisions.clear()
            st.session_state[incarnation_key] = uuid4().hex
            st.error(str(exc))
            if isinstance(exc, RenderBusy):
                if st.button("Retry report page comparison", key=p + "_retry_page_comparison"):
                    st.rerun()
                todo.append("Report page comparison is waiting for capacity. Your report and upload are unchanged.")
            else:
                todo.append("Resolve the existing report conflict before continuing; your report and upload are unchanged.")
    for message in todo:
        st.info(message)
    if not todo:
        st.success("Your sites and sections are ready. Continue to add this month’s files and finish the report.")
    st.caption("Saving remembers this design and its site information for next month. Saved content is shared in this public internal-testing app. Your entered name records the change; it is not a login.")
    if st.button("Continue to this month’s updates", key=p + "_save", type="primary", disabled=bool(todo) or not candidate):
        try:
            if todo:
                raise ValueError("Resolve the remaining starting-report messages before continuing. Your draft and upload are unchanged.")
            with st.spinner("Saving your report and its reusable design…"):
                mapped, profile, draft, previous, verified, consumed_logo_slots, current, base = _prepare_merge()
                source_draft = draft
                from app.monthly_report_start_replay import merge_starting_drafts
                if decisions:
                    base = apply_replacements(base, draft, previous, decisions, **_conflict_context(current))
                draft = merge_starting_drafts(base, draft, previous, verified=verified)
                # Existing reviewed logos belong to the selected sites/contract.
                # A starting report must not replace them with older artwork.
                assets = dict((*working_assets, *mapped.assets))
                blocks = {b.key: b for b in draft.blocks}
                # Three-way replay has already preserved report-only Clear or
                # removal of consumed source logos. Standing/default art cannot
                # silently refill those slots after that decision.
                for key in preferred_logos:
                    saved = state.block(key) if state else None
                    if saved and saved.asset_hashes and key not in blocks and key not in consumed_logo_slots:
                        blocks[key] = saved
                        for reference in saved.asset_hashes:
                            assets[reference] = library.read_asset(contract, profile.key, reference)
                from app.monthly_report_branding import apply_defaults
                draft = apply_defaults(replace(draft, blocks=tuple(blocks.values()),
                                               sections=tuple(replace(s, included=True) for s in draft.sections)),
                                       assets, skip_slots=consumed_logo_slots)
                review = {"sha256": inspection.sha256, "intent": intent, "period": period.key, "image_review_scope": p,
                          "inferred_source": asdict(analysis),
                          "items": [asdict(i) for i in inspection.items],
                          "section_plans": [{k: v for k, v in plan.items() if k not in ("new_assets", "preserved_assets")} for plan in plans.values()]}
                if fallback_template:
                    review["independent_template_choice"] = {"template": fallback_template, "scope": "whole-report", "source_cover": "left-out"}
                if native_art_review is not None:
                    review["native_art_review"] = native_art_review
                # Normalize dataclass table values for the JSON audit record.
                review["section_plans"] = [dict(plan, tables={k: asdict(v) for k, v in plan.get("tables", {}).items()}) for plan in review["section_plans"]]
                if decisions:
                    review["single_image_replacements"] = dict(decisions)
                guard = snapshot_guard(profile, period, current.revision if current else 0,
                                       current.draft.fingerprint if current else "") if decisions else nullcontext()
                with guard:
                    library.save_report_setup(profile, draft, path, review, assets=tuple(assets.items()),
                                              expected_revision=state.revision if state else 0, actor=actor, confirmed=True,
                                              snapshot_revision=current.revision if current else 0, source_draft=source_draft, source_view=source_view)
                decisions.clear()
                st.session_state[incarnation_key] = uuid4().hex
                st.session_state["report_resume_import"] = (contract, profile.key, period.key)
                st.session_state["report_setup_done"] = profile.key
                # Only durable success retires this exact source-review task.
                # Keep the receipt scoped to report/sites/month so its still
                # mounted uploader cannot immediately recreate unsaved review.
                # Failures retain the original staged source and every choice.
                if st.session_state.get(prefix + "_stage") is staged:
                    st.session_state.pop(prefix + "_stage", None)
                    st.session_state.pop(original_token_key, None)
                    if staged[0]:
                        st.session_state[prefix + "_committed_upload_digest"] = inspection.sha256
                        staged[0].cleanup()
            st.rerun()
        except (ValueError, OSError) as exc:
            decisions.clear()
            st.session_state[incarnation_key] = uuid4().hex
            st.error(str(exc))
    return True
