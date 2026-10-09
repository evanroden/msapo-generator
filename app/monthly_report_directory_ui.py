"""Optional, reviewed directory administration and report-scoped contact updates."""

from dataclasses import asdict, replace
import re

import streamlit as st

from app import contracts, monthly_report_directory as directory
from app.monthly_report_editor import _grid, _preview, _signature


def contract_choices():
    # The catalog's display spelling wins; case/spacing variants are one choice.
    # A legacy saved name must not create duplicate landing-page button IDs.
    choices = {}
    for name in (*contracts.contract_names(), *directory.directory_contracts()):
        identity = " ".join(name.casefold().split())
        choices.setdefault(identity, name)
    return list(choices.values())


def _known_sites(contract, state):
    from app.monthly_report_section_ui import _site_options

    saved = {s.key: s for s in state.sites} if state else {}
    for facility in _site_options(contract):
        saved.setdefault(facility.key, directory.DirectorySite(facility.key, facility.title, facility.aliases))
    return tuple(saved.values())


def _edit_contacts(site, prefix):
    rows = _grid(prefix + "_contacts_" + site.key, [
        {"Role": c.role, "Name": c.name, "Phone": c.phone, "Email": c.email, "Source": c.source}
        for c in site.contacts] or [{"Role": "", "Name": "", "Phone": "", "Email": "", "Source": ""}],
        num_rows="dynamic", hide_index=True, disabled=["Source"], column_config={"Source": None})
    return tuple(directory.DirectoryContact(*(str(r.get(k) or "").strip() for k in ("Role", "Name", "Phone", "Email", "Source")))
                 for r in rows if any(str(r.get(k) or "").strip() for k in ("Role", "Name", "Phone", "Email")))


def _site_editor(sites, existing, prefix, *, importing=False):
    by_id = {s.key: s for s in sites}
    existing_by_title = {s.title: s for s in existing}
    records = []
    for site in sites:
        matches = [s.title for s in existing if directory.facility_names(site) & directory.facility_names(s)]
        matched = existing_by_title[matches[0]] if len(matches) == 1 else None
        aliases = tuple(dict.fromkeys((*site.aliases, *((matched.title, *matched.aliases) if matched else ()))))
        aliases = tuple(n for n in aliases if n.casefold() != site.title.casefold())
        records.append({"Include": True, "Identity": site.key, "Site": site.title,
                        "Aliases": "; ".join(aliases),
                        "Address": site.address or (matched.address if matched else ""), "Active": matched.active if matched else site.active,
                        "Existing site": matches[0] if len(matches) == 1 else "New site",
                        "Source": site.source.split(":", 1)[-1]})
    edited = _grid(prefix + "_sites", records, hide_index=True,
                   disabled=["Identity", "Source"], column_config={"Identity": None,
                    "Existing site": st.column_config.SelectboxColumn("Match to a listed site", options=["New site", *existing_by_title], help="Choose a listed site when the worksheet uses a different name for the same place. This keeps its saved identity.") if importing else None,
                    "Include": st.column_config.CheckboxColumn() if importing else None,
                    "Aliases": st.column_config.TextColumn(help="Alternate names for this one site, separated by semicolons."),
                    "Active": st.column_config.CheckboxColumn(help="Inactive sites stay in history and existing reports but are not offered for new setup.")})
    st.caption("Match a different spelling to the same listed site. Keep alternate names in Aliases, not separate rows. Unselected existing sites are retained.")
    chosen = [r for r in edited if r.get("Include", True)]
    if not chosen:
        return ()
    contact_store = st.session_state.setdefault(prefix + "_reviewed_contacts", {})
    def contact_key(row):
        return row["Identity"] + "_" + _signature(row.get("Existing site", ""))
    def proposed(row):
        site = by_id[row["Identity"]]
        old = existing_by_title.get(row.get("Existing site")) if importing else None
        return replace(site, contacts=directory.proposed_contacts(old.contacts, site.contacts)) if old else site
    with st.expander("Review and edit leadership / contact details", expanded=True):
        selection_key = prefix + "_contact_site"
        valid = [r["Identity"] for r in chosen]
        if st.session_state.get(selection_key) not in valid:
            st.session_state[selection_key] = valid[0]
        selected = st.selectbox("Site contacts to edit", [r["Identity"] for r in chosen],
                                format_func=lambda key: next(r["Site"] for r in chosen if r["Identity"] == key), key=selection_key)
        selected_row = next(r for r in chosen if r["Identity"] == selected)
        old = existing_by_title.get(selected_row.get("Existing site")) if importing else None
        if old:
            st.caption("Currently saved contacts (unchanged until confirmation)")
            st.dataframe([{"Role": c.role, "Name": c.name, "Phone": c.phone, "Email": c.email} for c in old.contacts], hide_index=True)
            st.caption("Proposed contacts below retain missing fields only for the same person and retain roles absent from this worksheet. Review or edit every proposed value.")
        contact_store[contact_key(selected_row)] = _edit_contacts(proposed(selected_row), prefix + "_" + _signature(selected_row.get("Existing site", "")))
    result = []
    for row in chosen:
        source = by_id[row["Identity"]]
        matched = existing_by_title.get(row.get("Existing site")) if importing else None
        aliases = tuple(v.strip() for v in str(row.get("Aliases") or "").split(";") if v.strip())
        # Every alias, including a matched record's prior name, was visible and
        # editable in the grid before this confirmed save.
        result.append(replace(source, key=matched.key if matched else source.key,
                              title=str(row.get("Site") or "").strip(), aliases=aliases,
                              address=str(row.get("Address") or "").strip(), active=bool(row.get("Active", True)),
                              contacts=contact_store.get(contact_key(row), proposed(row).contacts)))
    with st.expander("All included contacts before saving"):
        st.dataframe([{"Site": s.title, "Role": c.role, "Name": c.name, "Phone": c.phone, "Email": c.email}
                      for s in result for c in s.contacts], hide_index=True)
    return tuple(result)


def render_directory(field):
    try:
        _render_directory(field)
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        st.caption("Nothing was replaced. Correct the selection or reload the current version before trying again.")


def _render_directory(field):
    if st.button("Back to monthly reports", key="report_directory_back"):
        st.session_state["report_directory_manage"] = False
        st.rerun()
    st.subheader("Contract and site directory")
    st.write("Save suggested sites and contacts once. Each report still confirms its own single-site, multi-site or regional membership.")
    st.caption("This directory does not authenticate a returning manager, send messages, change purchase-order/expense routing, or update existing reports automatically.")
    flash = st.session_state.pop("report_directory_message", "")
    if flash:
        st.success(flash)
    # Do this before listing, loading, or rendering any saved contact record.
    # This remains an attribution gate for the owner's no-login testing mode,
    # never a claim that the entered name authenticates a visitor.
    actor = st.text_input("Directory editor name", key=field("report_directory_actor", ""), max_chars=160)
    st.caption("Your name records directory changes. It is not a login or verified identity; this testing app has no sign-in protection.")
    if not actor.strip():
        st.info("Enter your name before viewing or changing saved contact lists.")
        return
    mode = st.radio("Directory task", ["Import a workbook", "Review saved directory"], key=field("report_directory_mode", "Import a workbook"), horizontal=True)
    if mode == "Review saved directory":
        names = directory.directory_contracts(include_archived=True)
        if not names:
            st.info("No directory has been saved yet. Import a workbook to begin.")
            return
        contract = st.selectbox("Saved contract directory", names, key="report_directory_existing")
        state = directory.load_directory(contract, include_archived=True)
        prefix = "report_directory_saved_" + _signature((contract, state.revision))
        st.caption(f"Revision {state.revision} · entered editor: {state.actor} · {state.updated_at}")
        if state.archived:
            st.info("This contact list is archived. It is no longer offered for new reports. Restore a saved version below to use it again.")
            _directory_history(contract, state, prefix, actor)
            return
        sites = _site_editor(state.sites, (), prefix)
        raw, source_sha, sheet_name = None, state.source_sha256, state.source_sheet
    else:
        upload = st.file_uploader("Contract / site directory workbook", type=["xlsx"], max_upload_size=30, key="report_directory_upload")
        if st.button("Read workbook", disabled=upload is None, key="report_directory_read"):
            raw = upload.getvalue()
            inspection = directory.inspect_workbook(raw)
            st.session_state["report_directory_workbook"] = (raw, inspection)
            st.rerun()
        staged = st.session_state.get("report_directory_workbook")
        if not staged:
            return
        raw, inspection = staged
        for notice in inspection.notices:
            st.caption(notice)
        sheets = {s.name: s for s in inspection.sheets}
        recommended = next((s.name for s in inspection.sheets if not s.summary and not s.hidden), next(iter(sheets)))
        p = "report_directory_import_" + inspection.sha256[:16]
        chosen_sheet = st.selectbox("Contract worksheet", list(sheets), key=field(p + "_sheet", recommended),
                                    format_func=lambda name: name + (" · summary/index" if sheets[name].summary else "") + (" · hidden" if sheets[name].hidden else ""))
        sheet = sheets[chosen_sheet]
        if sheet.summary:
            st.warning("This looks like an index or cross-contract summary. Select a site-detail tab; importing a summary as one contract could assign the wrong sites.")
            return
        for notice in directory.sheet_findings(inspection, sheet):
            st.warning(notice)
        contract_names = contract_choices()
        clean_title = re.sub(r"\s+Sites$", "", re.sub(r"^\d+\s*[-.]\s*", "", sheet.name), flags=re.I).strip()
        default = next((n for n in contract_names if n.casefold() == clean_title.casefold()), "Add another contract")
        selected_contract = st.selectbox("Save under contract", [*contract_names, "Add another contract"], key=field(p + "_contract_" + sheet.name, default))
        contract = st.text_input("Contract name", key=field(p + "_name_" + sheet.name, clean_title)) if selected_contract == "Add another contract" else selected_contract
        if not contract.strip():
            return
        state = directory.load_directory(contract, include_archived=True)
        if state and state.archived:
            st.info("This contract’s contact list is archived. Open Review saved directory and restore it before importing changes.")
            return
        prefix = p + "_" + _signature((contract, sheet.name, state.revision if state else 0))
        header, label, address, groups = directory.suggest_matrix(sheet)
        with st.expander("Check how the worksheet is read"):
            st.caption("Sites run across columns; contact roles run down rows. These are suggestions, not confirmed identities. Zero means that a field is absent.")
            header = int(st.number_input("Row containing site names", 1, 1048576, value=header, key=prefix + "_header"))
            label = int(st.number_input("Field-label column number", 1, 16384, value=label, key=prefix + "_labels"))
            address = int(st.number_input("Address row (0 if absent)", 0, 1048576, value=address, key=prefix + "_address"))
            groups = _grid(prefix + "_mapping", groups or [{"Use": True, "Role": "", "Name row": 0, "Phone row": 0, "Email row": 0}],
                           num_rows="dynamic", hide_index=True,
                           column_config={k: st.column_config.NumberColumn(min_value=0, max_value=1048576, step=1) for k in ("Name row", "Phone row", "Email row")})
        proposed = directory.matrix_sites(inspection, sheet, header, label, address, groups)
        edit_prefix = prefix + "_" + _signature([asdict(s) for s in proposed])
        st.subheader("Confirm sites, aliases and contacts")
        incoming = _site_editor(proposed, _known_sites(contract, state), edit_prefix, importing=True)
        if not incoming:
            st.info("Select at least one site to save.")
            return
        sites = directory.merge_sites(state.sites if state else (), incoming)
        source_sha, sheet_name = inspection.sha256, sheet.name
        st.caption(f"Saving {len(incoming)} reviewed site records; {len(sites) - len(incoming)} other saved records remain unchanged. Other workbook tabs are not imported into this contract.")
    revision = state.revision if state else 0
    signature = _signature((contract, revision, [asdict(s) for s in sites], actor, source_sha, sheet_name))
    confirmed = st.checkbox("I reviewed all included sites and contacts and confirm this shared save", key=prefix + "_confirm_" + signature)
    if st.button("Save contract directory", key=prefix + "_save", type="primary", disabled=not (sites and actor.strip() and confirmed)):
        directory.save_directory(contract, sites, expected_revision=revision, actor=actor, confirmed=confirmed,
                                 raw=raw, source_sha256=source_sha, source_sheet=sheet_name)
        st.session_state["report_directory_message"] = "Directory saved. Existing reports and their selected sites were not changed. You can review another tab or return to report setup."
        st.rerun()
    if state:
        _directory_history(contract, state, prefix, actor)
        with st.expander("Remove this contact list from use"):
            st.write(f"Archive the shared contact list for **{contract}**. It will stop supplying site and contact suggestions. Saved reports, source workbooks and directory history stay available.")
            confirmed_archive = st.checkbox("Archive this contract’s contact list", key=prefix + "_archive_ok_" + _signature(actor))
            if st.button("Archive contact list", key=prefix + "_archive", disabled=not confirmed_archive):
                directory.archive_directory(contract, expected_revision=state.revision, actor=actor, confirmed=confirmed_archive)
                st.session_state["report_directory_message"] = "Contact list archived. You can restore it from Review saved directory. Saved reports were not changed."
                st.rerun()


def _directory_history(contract, state, prefix, actor):
    with st.expander("History and restoration", expanded=state.archived):
        number = int(st.number_input("Directory version to inspect", 1, state.revision, value=state.revision, key=prefix + "_history"))
        prior = directory.load_directory(contract, number)
        st.caption(f"Version {number} · {prior.actor} · {prior.updated_at} · {prior.action}")
        st.dataframe([{"Site": s.title, "Aliases": "; ".join(s.aliases), "Active": s.active, "Contacts": len(s.contacts)} for s in prior.sites], hide_index=True)
        restore = st.checkbox("Restore this directory version as a new revision", key=prefix + f"_restore_ok_{number}_" + _signature(actor))
        if st.button("Restore directory", key=prefix + "_restore", disabled=not (restore and actor.strip() and (state.archived or number != state.revision))):
            directory.restore_directory(contract, number, expected_revision=state.revision, actor=actor, confirmed=restore)
            st.session_state["report_directory_message"] = "Directory restored as a new revision. Report snapshots were not changed."
            st.rerun()


def choose_facilities(contract, prefix, field):
    state = directory.load_directory(contract)
    if not state:
        return ()
    active = {s.key: s for s in state.sites if s.active}
    key = field(prefix + "_directory_sites", [])
    if any(k not in active for k in st.session_state[key]):
        st.warning("The directory changed. Reconfirm the report’s site selection.")
        st.session_state[key] = [k for k in st.session_state[key] if k in active]
    selected = st.multiselect("Choose this report’s sites from the saved directory", list(active),
                              format_func=lambda key: active[key].title, key=key)
    st.caption(f"Directory revision {state.revision}. No sites are selected automatically; regional membership must be confirmed below.")
    return tuple(active[k].facility for k in selected)


def review_contacts(draft, prefix, field, assets):
    if not draft.prepared_by.strip():
        st.caption("Enter your name in Report before comparing contacts with the saved site directory.")
        return draft
    state = directory.load_directory(draft.profile.contract)
    if not state:
        return draft
    with st.expander("Compare contacts with the saved site directory"):
        current = next((b for b in draft.blocks if b.key == "contact_matrix"), None)
        links = {r.split(":")[1]: r.split(":")[2] for r in current.references if r.startswith("directory-site:") and len(r.split(":")) == 3} if current else {}
        active = {s.key: s for s in state.sites if s.active}
        suggestions = directory.suggest_contact_bindings(state, draft.profile.facilities, links)
        st.caption("Matching site names are suggested below. Check the sites and people before using these contacts in your report.")
        bindings = {}
        for facility in draft.profile.facilities:
            default = suggestions.get(facility.key, "")
            key = field(prefix + "_directory_link_" + facility.key, default if default in active else "")
            if st.session_state[key] not in ("", *active):
                st.session_state[key] = ""
            bindings[facility.key] = st.selectbox("Directory site for " + facility.title, ["", *active],
                                                format_func=lambda k: active[k].title if k else "Choose the matching site", key=key)
        try:
            candidate, missing = directory.contact_block(state, draft.profile.facilities, bindings)
        except ValueError as exc:
            st.error(str(exc))
            return draft
        if missing:
            st.warning("Choose a directory match for: " + "; ".join(missing) + ". Report membership will not be changed.")
        left, right = st.columns(2)
        with left:
            st.write("Contacts currently in this report")
            _preview(current, assets, draft.profile)
        with right:
            st.write(f"Directory contacts · revision {state.revision}")
            st.dataframe([dict(zip((c.title for c in directory.CONTACT_SPEC.columns), row)) for row in candidate.rows], hide_index=True)
        signature = _signature((asdict(current) if current else None, asdict(candidate), missing))
        confirmed = st.checkbox("Replace this report’s contact matrix with this reviewed directory table", key=prefix + "_contacts_ok_" + signature)
        st.caption("This is an explicit replacement in this report only. It does not change shared report defaults, org charts, membership or the source workbook. Save progress to pin it for next month.")
        if st.button("Use reviewed contact table", key=prefix + "_use_contacts", disabled=not (confirmed and candidate.rows and not missing)):
            st.session_state[prefix + "_contacts_undo"] = (current, draft.sections)
            draft = directory.apply_contacts(draft, candidate)
            _resume_contacts(draft, prefix)
        undo = st.session_state.get(prefix + "_contacts_undo")
        if undo and st.button("Undo contact table update", key=prefix + "_undo_contacts"):
            blocks = {b.key: b for b in draft.blocks}
            if undo[0]:
                blocks["contact_matrix"] = undo[0]
            else:
                blocks.pop("contact_matrix", None)
            draft = replace(draft, blocks=tuple(blocks.values()), sections=undo[1])
            st.session_state.pop(prefix + "_contacts_undo", None)
            _resume_contacts(draft, prefix)
    return draft


def _resume_contacts(draft, prefix):
    # An explicit replacement/undo resets only that contact editor's ephemeral
    # delta; otherwise an old data_editor value could overwrite the new table.
    changed = (prefix + "_edit_contact_matrix_", prefix + "_contacts_contact_matrix_")
    st.session_state["report_draft_mirror"] = {k:v for k,v in st.session_state.get("report_draft_mirror", {}).items() if not k.startswith(changed)}
    for key in list(st.session_state):
        if key.startswith(changed):
            del st.session_state[key]
    st.session_state[prefix + "_draft"] = draft
    st.rerun()
