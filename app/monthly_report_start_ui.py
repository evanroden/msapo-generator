"""Plain-language contract cards, site checkboxes and first-report choices."""

from dataclasses import replace
import re

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_directory_ui import contract_choices
from app.monthly_report_editor import _key, _signature
from app.monthly_report_model import Facility, ReportProfile
from app.monthly_report_section_ui import _site_options
from app.monthly_report_start import membership_key, matching_profiles, report_key, design_seed, save_design_start, recommended_designs


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


def _contract_label(code, branding):
    """Use only the contract title from an approved, exact contract logo map."""
    title = (branding.title.strip() if branding else "") or code
    return title


def _fallback_initials(title):
    letters = [word[0].upper() for word in re.findall(r"[A-Za-z0-9]+", title)]
    return "".join(letters[:3]) or "—"


def _contract_tile(title):
    # UI-only placeholder. It never substitutes a fabricated image in DOCX.
    label = _fallback_initials(title)
    st.markdown(
        '<div aria-label="No logo configured" style="width:8.5rem;height:3.5rem;'
        'background:#e9efed;border:1px solid #c3d1cc;border-radius:.35rem;'
        'display:flex;align-items:center;justify-content:center;'
        'font-weight:700;letter-spacing:.08em;color:#174237">' + label + '</div>',
        unsafe_allow_html=True,
    )


def choose_contract(last_contract, field):
    from app.monthly_report_branding import find_logo, load_branding
    state, images = load_branding(), {}
    names = contract_choices()
    current_key = field("report_contract", last_contract if last_contract in names else "")
    current = st.session_state[current_key]
    if current and not st.session_state.get("report_change_contract", False):
        selected_logo = find_logo(current, state=state) if state else None
        selected_title = _contract_label(current, selected_logo)
        logo = _logo(current, state, images)
        if logo:
            picture, identity, action = st.columns((1, 5, 2), vertical_alignment="center")
            picture.image(logo, width=80)
        else:
            identity, action = st.columns((6, 2), vertical_alignment="center")
        with identity:
            st.subheader(selected_title, anchor=False)
            if selected_title.casefold() != current.casefold():
                st.caption("Account code: " + current)
        if action.button("Change contract", key="report_change_contract_button", width="stretch"):
            st.session_state["report_change_contract"] = True
            st.rerun()
        return current
    st.subheader("Choose your contract")
    query = st.text_input("Find a contract", key=field("report_contract_search", ""), placeholder="Type part of the contract name")
    cards = [(name, _contract_label(name, find_logo(name, state=state) if state else None))
             for name in names]
    visible = [(code, title) for code, title in cards
               if query.casefold() in (code + " " + title).casefold()]
    if not visible:
        st.info("No matching contract. Try another name or add one through the contract directory.")
        from app.monthly_report_admin_ui import admin_url
        st.link_button("Open contract directory", admin_url("directory"))
    for offset in range(0, len(visible), 3):
        for column, (name, title) in zip(st.columns(3), visible[offset:offset+3]):
            with column, st.container(border=True):
                logo = _logo(name, state, images)
                if logo:
                    st.image(logo, width=160)
                else:
                    _contract_tile(title)
                if title.casefold() != name.casefold():
                    st.caption("Account code: " + name)
                # Exact source code is the selection identity. The approved
                # full client title is the primary visual label and searchable.
                if st.button(title, key="report_contract_card_" + _signature(name), width="stretch"):
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


def identity_summary(profile):
    """One exact site/scope summary for the stable contract/month strip."""
    facilities = profile.facilities
    label = "Site: " if len(facilities) == 1 else "Sites: "
    sites = label + "; ".join(site.title for site in facilities)
    ordinary_title = facilities[0].title if len(facilities) == 1 else " / ".join(site.title for site in facilities)
    name = profile.title + " · " if profile.title != ordinary_title else ""
    scope = {"individual": "", "multi_site": "Combined report · ", "regional": "Regional report · "}[profile.scope_type]
    return name + scope + sites


def select_sites(contract, profiles, remembered, field, completed=None, *, render_details_action=None):
    options = site_choices(contract, profiles)
    prefix = "report_sites_" + _key(contract)
    if completed:
        st.session_state[prefix + "_new_site"] = ""
    seed = next((p for p in profiles if p.key == (completed or remembered)), None)
    selected = []
    # Native width="stretch" expands the Streamlit row, but NOT its associated
    # clickable <label> (observed 968px row vs 236px label in both engines).
    # Extend that SAME semantic label, not a second click handler or duplicated
    # checkbox. All pointer, touch, label and keyboard paths retain one input.
    # Scope styling to this specific container; no other report/PO toggles.
    with st.container(key="monthly_native_site_choices"):
        st.html("""
        <style>
        .st-key-monthly_native_site_choices [data-testid="stCheckbox"] label:has(input[type="checkbox"]) {
            box-sizing: border-box;
            width: 100% !important;
            min-height: 44px;
            display: flex;
            align-items: center;
            cursor: pointer;
        }
        .st-key-monthly_native_site_choices [data-testid="stCheckbox"] label:has(input[type="checkbox"]):focus-within {
            outline: 2px solid currentColor;
            outline-offset: 2px;
        }
        </style>
        """)
        for f in options:
            key = field(prefix + "_" + f.key, bool(seed and f.key in membership_key(seed.facilities)))
            if completed:
                st.session_state[key] = bool(seed and f.key in membership_key(seed.facilities))
            detail = "Include this site in the report." + (" Also known as: " + "; ".join(f.aliases) if f.aliases else "")
            if st.checkbox(f.title, key=key, help=detail, width="stretch"):
                selected.append(f)
    selection_notice = st.empty()
    with st.expander("More report details"):
        custom = st.text_input("Site name", key=field(prefix + "_new_site", ""), help="Use a semicolon between names when adding several actual sites.")
        for name in custom.split(";"):
            if name.strip():
                try:
                    selected.append(Facility(_key(name.strip()), name.strip()))
                except ValueError:
                    selection_notice.warning("Give each new site a name containing letters or numbers.")
                    return None, None
        facilities = tuple(selected)
        if not facilities:
            selection_notice.info("Select at least one site to continue.")
            return None, None
        # Reject duplicate actual sites before per-site alias widgets exist.
        try:
            ReportProfile(contract, "selection", "Selected sites", facilities,
                          "individual" if len(facilities) == 1 else "multi_site")
        except ValueError:
            selection_notice.warning("A site or alternate name was included more than once. Keep one checkbox/name per actual site. Remove any duplicate from Site name above to continue.")
            return None, None
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
            selection_notice.warning("A site or alternate name was included more than once. Keep one checkbox/name per actual site.")
            return None, None
        if render_details_action is not None:
            render_details_action(candidate, existing)
    return candidate, existing


def starting_choice(profile, profiles, period, prepared, field):
    from app.monthly_report_section_ui import render_section_setup
    if render_section_setup(profile.contract, period, prepared, field, identity=profile):
        return
    available = recommended_designs(profile, profiles, period)
    choices = (["Use another report from this contract"] if available else []) + ["Use the general ENFRA monthly report template"]
    from app.monthly_report_designs import master_state
    master = master_state()
    if master.get("default"):
        selected = "Use the general ENFRA monthly report template"
        st.caption("No starting report is needed. ENFRA master design version " + str(master["revision"]) + " is applied automatically.")
    else:
        choice_key = field("report_start_choice_" + profile.key, "")
        selected = st.session_state[choice_key]
        st.caption("No report file? Start from a saved contract design or the standard template.")
        for column, choice in zip(st.columns(len(choices)), choices):
            label = "Use a contract report" if choice.startswith("Use another") else "Use ENFRA template"
            if column.button(label, key="report_start_card_" + _key(choice) + "_" + profile.key,
                             type="primary" if selected == choice else "secondary", width="stretch"):
                st.session_state[choice_key] = choice
                st.rerun()
    if selected not in choices:
        return
    source = None
    if selected.startswith("Use another"):
        st.caption("Suggested order: shared sites first, then the same report scope, then the most recent saved month. This copies the design; it does not add sites to your report.")
        if len(available) == 1:
            st.write("Starting design: " + available[0].title)
            source = library.load_profile(profile.contract, available[0].key)
        else:
            key = st.radio("Report design to reuse", [p.key for p in available], format_func=lambda k: next(p.title for p in available if p.key == k), key="report_start_from_" + profile.key)
            source = library.load_profile(profile.contract, key)
        st.caption("Reuses the section layout, table headings and saved contract logos. You’ll supply this site's org chart, contacts, photos and current work.")
    else:
        st.caption("The available ENFRA and client logos are filled in. Check your org chart, contacts and site information; the tool remembers the design for next time.")
    st.caption("All report sections are included. Add the information available now and continue unfinished sections later.")
    actor = st.text_input("Your name", key=field("report_start_actor_" + profile.key, prepared))
    pending_key = "report_start_pending_" + profile.key
    if st.button("Start this report", key="report_start_save_" + profile.key,
                 disabled=not actor.strip() or st.session_state.get(pending_key, False),
                 type="primary"):
        st.session_state[pending_key] = True
        try:
            with st.spinner("Preparing this report for your selected sites…"):
                draft, assets = design_seed(profile, period, actor, source)
                save_design_start(draft, assets, actor=actor, confirmed=True)
            st.session_state["report_setup_done"] = profile.key
            st.session_state["report_start_at_site_information"] = profile.key
            st.session_state["report_resume_import"] = (profile.contract, profile.key, period.key)
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
        finally:
            st.session_state.pop(pending_key, None)
