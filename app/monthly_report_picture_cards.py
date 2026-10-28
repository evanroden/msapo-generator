"""Decide what to keep beside its picture, without disconnected image selectors."""

import streamlit as st

from app.monthly_report_content_policy import page_status
from app.monthly_report_import import read_import_image
from app.monthly_report_sections import small_artwork
from app.monthly_report_import_content_types import image_review_caption, image_replacement_guidance


def _turn_page(key, delta, last):
    st.session_state[key] = min(last, max(0, st.session_state.get(key, 0) + delta))


def _choose_role(identity, key, choices, plan, prefix, single):
    """Selecting a single-use role replaces its previous choice in one action."""
    slot = st.session_state[key]
    if slot in single:
        for other, value in list(choices.items()):
            if other != identity and value == slot:
                choices[other] = ""
                other_key = prefix + "_role_" + other
                if other_key in st.session_state:
                    st.session_state[other_key] = ""
    choices[identity] = slot
    plan["picture_roles"] = dict(choices)


def picture_options(section, *, allow_branding=True):
    if section == "cover":
        return {"": "Leave out", "cover_photo": "Use as cover photo",
                **({"client_logo": "Use as client logo", "brand_logo": "Use as ENFRA logo"} if allow_branding else {})}
    choices = {"": "Leave out"}
    if section == "organization":
        choices.update(org_chart="Keep as organization chart",
                       business_hours_workflow="Keep as daytime outage procedure",
                       after_hours_workflow="Keep as after-hours outage procedure",
                       contact_matrix="Keep as contact list")
    else:
        choices["keep"] = "Keep in this section"
    if section != "other":
        choices["divider_" + section] = "Use behind this section’s title"
    return choices


def _cover_choice(key, omitted_key, identity):
    # Native callbacks run before the next render. Updating after the gallery
    # loop left its old Selected/Choose controls visible for one extra event.
    st.session_state[key] = identity
    st.session_state[omitted_key] = not bool(identity)


def review_cover_gallery(images, path, prefix, old, plan):
    """One clickable photo gallery; no per-image radio or mandatory selection.

    A largest, plausible source cover photograph is preselected, but the
    operator can choose any other candidate or leave the cover photograph
    blank. Shared ENFRA/client logos do not belong in this decision.
    """
    from app.monthly_report_start_import import cover_photo_candidates, suggested_cover_photo
    candidates = cover_photo_candidates(images)
    if not candidates:
        return
    from app.monthly_report_content_policy import contains_price
    ids = {item.id for item in candidates}
    key = prefix + "_cover_photo_choice"
    omitted_key = prefix + "_cover_photo_action"
    previous = old.get("cover_picture_id", None)
    prior = next((i for i, slot in old.get("destinations", {}).items()
                  if slot == "cover_photo" and i in ids), None)
    guess = suggested_cover_photo(candidates)
    default = (previous if previous in ids or previous == "" else
               prior if prior else guess.id if guess else "")
    omitted = st.session_state.pop(omitted_key, bool(old.get("cover_photo_omitted")))
    if omitted:
        default = ""
    if key not in st.session_state or st.session_state[key] not in (ids | {""}):
        st.session_state[key] = default
    selected = st.session_state[key]
    if omitted:
        selected = ""
    st.markdown("**Cover photograph**")
    st.caption("The most likely cover photo is selected when its placement and size identify it. Choose another picture or leave it blank.")
    visible = set()
    columns = st.columns(2, gap="medium")
    for index, item in enumerate(candidates, 1):
        with columns[(index - 1) % 2]:
            with st.container(border=True):
                st.caption(f"Picture {index}")
                try:
                    preview = read_import_image(path, item, preview=True)
                    st.image(preview.data, width="stretch",
                             caption=image_review_caption(item, index, "cover"))
                    visible.add(item.id)
                except (ValueError, OSError):
                    st.caption("This picture could not be displayed and will be left out.")
                if contains_price(item.text):
                    st.warning("This picture's caption mentions pricing and cannot be used as a cover photo.")
                    continue
                if item.id not in visible:
                    continue
                if item.id == selected:
                    st.success("Selected cover photo")
                else:
                    st.button(f"Choose picture {index}", key=prefix + "_choose_cover_" + item.id,
                              width="stretch", on_click=_cover_choice,
                              args=(key, omitted_key, item.id))
    st.button("No cover photograph", key=prefix + "_omit_cover",
              type="secondary", width="stretch", on_click=_cover_choice,
              args=(key, omitted_key, ""))
    # Never let an unavailable, priced or stale source picture survive the
    # new selection. Existing logos/footer stay in the same approved plan.
    chosen = next((item for item in candidates if item.id == selected
                   and item.id in visible and not contains_price(item.text)), None)
    destinations = {identity: slot for identity, slot in plan.get("destinations", {}).items()
                    if identity not in ids}
    selected_ids = [identity for identity in plan.get("selected", ()) if identity not in ids]
    if chosen:
        selected_ids.append(chosen.id)
        destinations[chosen.id] = "cover_photo"
    plan["selected"] = selected_ids
    plan["destinations"] = destinations
    plan["cover_picture_id"] = chosen.id if chosen else ""
    plan["cover_photo_omitted"] = bool(omitted and not chosen)
    plan["cover_photo_source_ids"] = tuple(item.id for item in candidates)
    plan["picture_roles"] = {identity: "cover_photo" if chosen and identity == chosen.id else ""
                             for identity in ids}
    plan["picture_choices"] = [chosen.id] if chosen else []


def review_pictures(images, section, path, prefix, scope, field, old, plan, blocking, *, allow_branding=True):
    if not images:
        return
    if section == "cover":
        review_cover_gallery(images, path, prefix, old, plan)
        return
    options = picture_options(section, allow_branding=allow_branding)
    single = {"cover_photo", "client_logo", "brand_logo", "divider_" + section}
    # Choices are copied into the section plan before widgets disappear on a
    # page change. A new widget is restored from this durable session plan.
    choices = {}
    for item in images:
        previous = old.get("destinations", {}).get(item.id)
        if "picture_roles" in old:
            selected = old["picture_roles"].get(item.id, "")
        elif "picture_choices" in old and item.id not in old["picture_choices"]:
            selected = ""
        elif previous:
            selected = previous
        elif small_artwork(item):
            selected = ""
        elif item.suggested_slot in options and (item.suggested_slot not in single or
                sum(i.suggested_slot == item.suggested_slot for i in images) == 1):
            selected = item.suggested_slot
        else:
            selected = "" if section == "cover" else "org_chart" if section == "organization" else "keep"
        choices[item.id] = selected if selected in options else ""
    st.write("Pictures found in your report")
    st.caption(image_replacement_guidance(section))
    if section == "cover":
        st.caption("Choose one cover photo. Choosing another replaces your earlier choice." if not allow_branding else
                   "Choose one cover photo and the logos you want. Choosing another picture for the same role replaces your earlier choice.")
    page_key = prefix + "_picture_page"
    last = (len(images) - 1) // 4
    page = min(st.session_state.get(page_key, 0), last)
    if last:
        left, middle, right = st.columns([1, 2, 1])
        left.button("Previous pictures", key=page_key + "_prev", disabled=page == 0,
                    on_click=_turn_page, args=(page_key, -1, last))
        right.button("Next pictures", key=page_key + "_next", disabled=page == last,
                     on_click=_turn_page, args=(page_key, 1, last))
        middle.caption(f"Pictures {page * 4 + 1}–{min(page * 4 + 4, len(images))} of {len(images)}")
    st.session_state[page_key] = page
    for index, item in enumerate(images[page * 4:page * 4 + 4], page * 4 + 1):
        with st.container(border=True):
            st.caption(f"Picture {index}")
            try:
                preview = read_import_image(path, item, preview=True)
                st.image(preview.data, width=min(preview.width, 650),
                         caption=image_review_caption(item, index, section))
            except (ValueError, OSError):
                st.warning("This picture could not be displayed. Check it in the original report before including it.")
                if choices[item.id]:
                    blocking.append(f"Picture {index} could not be displayed. Leave it out or supply a clear replacement.")
            role_key = field(prefix + "_role_" + item.id, choices[item.id])
            choices[item.id] = st.radio("Use this picture", list(options), format_func=options.get,
                key=role_key, horizontal=True, on_change=_choose_role,
                args=(item.id, role_key, choices, plan, prefix, single))
            with st.expander("Help me check the date or read small text"):
                st.caption("Use this only when you need help reading a scanned page. Compare the result with the picture; automatic reading can miss details.")
                from app.monthly_report_setup_ui import _image_review
                notes = _image_review(path, item, prefix + "_" + item.id, field, scope, compact=True)
                if notes:
                    plan["image_notes"][item.image_part] = notes
    plan["picture_roles"] = choices
    plan["picture_choices"] = [identity for identity, slot in choices.items() if slot]
    for index, item in enumerate(images, 1):
        slot = choices[item.id]
        if not slot:
            continue
        plan["selected"].append(item.id)
        if slot != "keep":
            plan["destinations"][item.id] = slot
        notes = plan["image_notes"].get(item.image_part, "")
        kind, reason = page_status(notes, unreadable=not notes.strip())
        if kind in ("pricing", "legal", "blank", "signature"):
            blocking.append(f"Leave out picture {index}: {reason}")
    for slot in single:
        if list(choices.values()).count(slot) > 1:
            blocking.append("Choose just one picture for: " + options.get(slot, slot) + ".")
