"""Decide what to keep beside its picture, without disconnected image selectors."""

import streamlit as st

from app.monthly_report_content_policy import page_status
from app.monthly_report_import import read_import_image
from app.monthly_report_sections import small_artwork


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


def picture_options(section):
    if section == "cover":
        return {"": "Leave out", "cover_photo": "Use as cover photo",
                "client_logo": "Use as client logo", "brand_logo": "Use as ENFRA logo"}
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


def review_pictures(images, section, path, prefix, scope, field, old, plan, blocking):
    if not images:
        return
    options = picture_options(section)
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
    st.caption("Look at each picture, then choose what to do directly underneath it. “Leave out” keeps it in the saved original only.")
    if section == "cover":
        st.caption("Choose one cover photo and the logos you want. Choosing another picture for the same role replaces your earlier choice.")
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
                st.image(preview.data, width=min(preview.width, 650))
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
