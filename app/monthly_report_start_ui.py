"""Plain-language contract cards, site checkboxes and first-report choices."""

from dataclasses import replace

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_directory_ui import contract_choices
from app.monthly_report_editor import _key, _signature
from app.monthly_report_model import Facility, ReportProfile
from app.monthly_report_section_ui import _site_options
from app.monthly_report_start import membership_key, matching_profiles, report_key, design_seed, save_design_start


def _logo(contract, state, images):
    from app.monthly_report_branding import find_logo, read_logo, card_image
    logo = find_logo(contract, state=state) if state else None
    if logo:
        if logo.asset not in images:
            images[logo.asset] = card_image(read_logo(logo))
        return images[logo.asset]
    for profile in library.list_profiles(contract):
        state = library.load_profile(contract, profile.key)
        block = state.block("client_logo")
        if block and block.asset_hashes:
            from app.monthly_report_docx import normalize_report_image
            ref = block.asset_hashes[0]
            return card_image(normalize_report_image(library.read_asset(contract, profile.key, ref), "." + ref.rsplit(".", 1)[-1], line_art=True, frame=(2, .75), dpi=96).data)
    return None


def choose_contract(last_contract, field):
    from app.monthly_report_branding import find_logo, load_branding
    state, images = load_branding(), {}
    names = contract_choices()
    current_key = field("report_contract", last_contract if last_contract in names else "")
    current = st.session_state[current_key]
    if current and not st.session_state.get("report_change_contract", False):
        with st.container(border=True):
            st.subheader(current)
            logo = _logo(current, state, images)
            if logo:
                st.image(logo, width=190)
            if st.button("Change contract", key="report_change_contract_button"):
                st.session_state["report_change_contract"] = True
                st.rerun()
        return current
    st.subheader("Choose your contract")
    query = st.text_input("Find a contract", key=field("report_contract_search", ""), placeholder="Type part of the contract name")
    visible = [n for n in names if query.casefold() in n.casefold()]
    if not visible:
        st.info("No matching contract. You can add a contract through the site/contact directory below.")
    for offset in range(0, len(visible), 3):
        for column, name in zip(st.columns(3), visible[offset:offset+3]):
            with column, st.container(border=True):
                logo = _logo(name, state, images)
                if logo:
                    st.image(logo, width=160)
                branding = find_logo(name, state=state) if state else None
                if branding and branding.title.casefold() != name.casefold():
                    st.caption(branding.title)
                if st.button(name, key="report_contract_card_" + _key(name), width="stretch"):
                    st.session_state[current_key] = name
                    st.session_state["report_change_contract"] = False
                    st.rerun()
    return None


def site_choices(contract, profiles):
    # Existing explicit profile identities take priority over catalog spelling.
    # Alias overlap never silently merges membership: require unique matches.
    known = {}
    for profile in profiles:
        for f in profile.facilities:
            known.setdefault(f.key, f)
    for f in _site_options(contract):
        matches = [v for v in known.values() if {n.casefold() for n in (v.title, *v.aliases)} & {n.casefold() for n in (f.title, *f.aliases)}]
        if not matches:
            known.setdefault(f.key, f)
    return tuple(known.values())


def select_sites(contract, profiles, remembered, field, completed=None):
    st.subheader("Which sites go in this one report?")
    st.caption("Check one site for an individual report, or several sites to combine them in one report. For separate reports, complete this process once for each report.")
    options = site_choices(contract, profiles)
    prefix = "report_sites_" + _key(contract)
    if completed:
        st.session_state[prefix + "_new_site"] = ""
    seed = next((p for p in profiles if p.key == (completed or remembered)), None)
    selected = []
    for f in options:
        key = field(prefix + "_" + f.key, bool(seed and f.key in membership_key(seed.facilities)))
        if completed:
            st.session_state[key] = bool(seed and f.key in membership_key(seed.facilities))
        if st.checkbox(f.title, key=key, help="Also known as: " + "; ".join(f.aliases) if f.aliases else None):
            selected.append(f)
    with st.expander("Add a site that is not listed"):
        custom = st.text_input("Site name", key=field(prefix + "_new_site", ""), help="Use a semicolon between names when adding several actual sites.")
        for name in custom.split(";"):
            if name.strip():
                selected.append(Facility(_key(name.strip()), name.strip()))
    facilities = tuple(selected)
    if not facilities:
        st.info("Check at least one site to continue.")
        return None, None
    with st.expander("Other names for these sites (optional)"):
        amended = []
        for f in facilities:
            aliases = st.text_input("Other names for " + f.title, key=field(prefix + "_aliases_" + f.key, "; ".join(f.aliases)))
            amended.append(replace(f, aliases=tuple(v.strip() for v in aliases.split(";") if v.strip())))
        facilities = tuple(amended)
    matches = matching_profiles(profiles, facilities)
    existing = next((p for p in matches if p.key == remembered), matches[0] if matches else None)
    if len(matches) > 1:
        selected_key = st.radio("Saved designs for these same sites", [p.key for p in matches], format_func=lambda key: next(p.title for p in matches if p.key == key), key=prefix + "_matches_" + _signature(membership_key(facilities)))
        existing = next(p for p in matches if p.key == selected_key)
    identity = _signature(membership_key(facilities))
    title = (existing.title if existing else facilities[0].title) if len(facilities) == 1 else " / ".join(f.title for f in facilities)
    scope = "individual"
    if len(facilities) > 1:
        label = st.text_input("Name for this group (optional)", key=field(prefix + "_group_" + identity, existing.title if existing else ""), placeholder="For example: Western Region")
        title = label.strip() or title
        regional = st.checkbox("This is a regional report", key=field(prefix + "_region_" + identity, bool(existing and existing.scope_type == "regional")))
        scope = "regional" if regional else "multi_site"
    try:
        candidate = replace(existing, title=title, facilities=facilities, scope_type=scope) if existing else ReportProfile(contract, report_key(facilities), title, facilities, scope)
    except ValueError:
        st.warning("A site or alternate name was included more than once. Keep one checkbox/name per actual site.")
        return None, None
    return candidate, existing


def starting_choice(profile, profiles, period, prepared, field):
    st.subheader("How would you like to start?")
    available = [p for p in profiles if p.key != profile.key]
    choices = (["Use another report from this contract"] if available else []) + ["Use the general ENFRA monthly report template", "Upload an older or unfinished report from my site"]
    choice_key = field("report_start_choice_" + profile.key, "")
    selected = st.session_state[choice_key]
    from app.monthly_report_branding import find_logo, read_logo, card_image, load_branding
    state = load_branding()
    brand = find_logo(brand=True, state=state) if state else None
    st.caption("Choose one starting point. You can work through the report sections in any order.")
    cards = {
        "Use another report from this contract": ("Another report from this contract", "Reuse an existing layout and logos. You’ll add the people, contacts and work for your selected sites.", _logo(profile.contract, state, {}) if available else None, ":material/library_books:"),
        "Use the general ENFRA monthly report template": ("ENFRA monthly report template", "Start with the standard sections and available client logo. We’ll walk you through your site information.", card_image(read_logo(brand)) if brand else None, ":material/description:"),
        "Upload an older or unfinished report from my site": ("A report you already have", "Upload a Word report from your sites—an older example or a teammate’s unfinished report. Review and update it section by section.", None, ":material/upload_file:"),
    }
    for column, choice in zip(st.columns(len(choices)), choices):
        title, description, logo, icon = cards[choice]
        with column, st.container(border=True):
            if logo:
                st.image(logo, width="stretch")
            else:
                st.markdown("# " + icon)
            st.markdown("**" + title + "**")
            st.caption(description)
            button_label = {choices[-1]: "Upload my report", "Use another report from this contract": "Use a contract report", "Use the general ENFRA monthly report template": "Use ENFRA template"}[choice]
            if st.button("Selected · " + button_label if selected == choice else button_label, icon=icon, type="primary" if selected == choice else "secondary", key="report_start_card_" + _key(choice) + "_" + profile.key, width="stretch"):
                st.session_state[choice_key] = choice
                st.rerun()
    if selected not in choices:
        st.info("Choose a starting point above to continue.")
        return
    st.write("Starting with: **" + cards[selected][0] + "**")
    if selected.startswith("Upload"):
        from app.monthly_report_section_ui import render_section_setup as render_setup
        render_setup(profile.contract, period, prepared, field, identity=profile)
        return
    source = None
    if selected.startswith("Use another"):
        if len(available) == 1:
            st.write("Starting design: " + available[0].title)
            source = library.load_profile(profile.contract, available[0].key)
        else:
            key = st.radio("Report design to reuse", [p.key for p in available], format_func=lambda k: next(p.title for p in available if p.key == k), key="report_start_from_" + profile.key)
            source = library.load_profile(profile.contract, key)
        st.caption("Reuses the section layout, table headings and saved contract logos. You’ll supply this site's org chart, contacts, photos and current work.")
    else:
        st.caption("The available ENFRA and client logos are filled in. Check your org chart, contacts and site information; the tool remembers the design for next time.")
    actor = st.text_input("Your name", key=field("report_start_actor_" + profile.key, prepared))
    confirm = st.checkbox("Save this design for these sites so we can use it next month", key="report_start_confirm_" + _signature((profile, source.revision if source else 0, actor)))
    if st.button("Start this report", key="report_start_save_" + profile.key, disabled=not (actor.strip() and confirm), type="primary"):
        try:
            draft, assets = design_seed(profile, period, actor, source)
            save_design_start(draft, assets, actor=actor, confirmed=True)
            st.session_state["report_setup_done"] = profile.key
            st.session_state["report_start_at_site_information"] = profile.key
            st.session_state["report_resume_import"] = (profile.contract, profile.key, period.key)
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
