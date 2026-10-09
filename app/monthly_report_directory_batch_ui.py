"""One reviewed workbook import for the shared contract and site directory."""

from dataclasses import asdict

import streamlit as st

from app import monthly_report_directory_batch as batch
from app.monthly_report_editor import _signature


def _summary_rows(plan):
    rows = []
    for entry in plan.entries:
        scope = "Contract and sites" if entry.contract_contacts and entry.sites else (
            "Contract" if entry.contract_contacts else "Sites")
        rows.append({
            "Contract": entry.contract,
            "Contact scope": scope,
            "Sites": len(entry.sites),
            "Site names": "; ".join(site.title for site in entry.sites),
            "Contract contacts": len(entry.contract_contacts),
            "Site contacts": sum(len(site.contacts) for site in entry.sites),
            "Workbook sheets": "; ".join(entry.source_sheets),
            "Saved revision": entry.expected_revision,
            "Result": "Needs review" if entry.conflicts else (
                "Ready to save" if entry.changed else "Already matches"),
        })
    return rows


def _contact_rows(plan):
    rows = []
    for entry in plan.entries:
        groups = [("Contract-wide", entry.contract_contacts),
                  *((site.title, site.contacts) for site in entry.sites)]
        for scope, contacts in groups:
            for contact in contacts:
                rows.append({
                    "Contract": entry.contract, "Applies to": scope,
                    "Role": contact.role, "Name": contact.name,
                    "Phone": contact.phone, "Email": contact.email,
                    "Source": contact.source,
                })
    return rows


def _show_mappings(plan):
    with st.expander("Check worksheet and column mappings"):
        st.caption("Contract-wide contacts stay separate from site contacts. A contract summary does not create a site or select any report’s sites.")
        mappings = []
        roles = []
        saved_names = {source.split(":", 1)[-1]: site.title
                       for entry in plan.entries for site in entry.sites
                       for source in site.source.split(";") if source}
        for mapping in plan.mappings:
            for column, target in mapping.targets:
                mappings.append({
                    "Worksheet": mapping.worksheet,
                    "Scope": "Contract" if mapping.scope == "contract" else "Site",
                    "Excel cell / column": column,
                    "Workbook site name": target if mapping.scope == "site" else "",
                    "Directory name": saved_names.get(mapping.worksheet + "!" + column, target)
                    if mapping.scope == "site" else target,
                    "Name header row": mapping.header_row,
                    "Field-label column": mapping.label_column,
                    "Address row": str(mapping.address_row) if mapping.address_row else "Absent",
                })
            for group in mapping.groups:
                roles.append({
                    "Worksheet": mapping.worksheet, "Role": group.role,
                    "Name row": str(group.name_row) if group.name_row else "Absent",
                    "Phone row": str(group.phone_row) if group.phone_row else "Absent",
                    "Email row": str(group.email_row) if group.email_row else "Absent",
                })
        if mappings:
            st.dataframe(mappings, hide_index=True, width="stretch")
        if roles:
            st.caption("Rows used for each contact role")
            st.dataframe(roles, hide_index=True, width="stretch")


def _show_result(result):
    if result.saved:
        quantity = f"{len(result.saved)} contract" + ("s" if len(result.saved) != 1 else "")
        st.success(f"Saved contacts for {quantity}. Existing reports and their selected sites were not changed.")
        st.caption("Saved: " + "; ".join(result.saved))
    if result.unchanged:
        quantity = f"{len(result.unchanged)} contract" + ("s already match" if len(result.unchanged) != 1 else " already matches")
        st.info(f"{quantity} the saved directory; no new revisions were created for these records.")
        st.caption("Already current: " + "; ".join(result.unchanged))
    if result.blocked:
        st.warning("These contracts were not saved because they need review.")
        st.dataframe([{"Contract": contract, "Reason": reason} for contract, reason in result.blocked],
                     hide_index=True, width="stretch")
    if result.failed:
        st.error("Some contracts could not be saved. Successful saves above remain available. Refresh the preview before retrying.")
        st.dataframe([{"Contract": contract, "Reason": reason} for contract, reason in result.failed],
                     hide_index=True, width="stretch")


def render_batch(inspection, raw, actor, prefix):
    """Show an immutable reviewed plan; only the explicit save writes data.

    The parent gates directory access. This local check also prevents a caller
    from loading saved directory records without an attributed editor.
    """
    if not actor.strip():
        st.info("Enter your name before viewing or changing saved contact lists.")
        return
    key = prefix + "_batch_" + inspection.sha256[:16]
    cache_key = key + "_preview"
    result_key = key + "_result"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = {"plan": batch.prepare_workbook(inspection), "generation": 0}
    cached = st.session_state[cache_key]
    if st.button("Refresh directory preview", key=key + "_refresh",
                 help="Read the latest saved directory and review the proposed import again."):
        st.session_state[cache_key] = {
            "plan": batch.prepare_workbook(inspection), "generation": cached["generation"] + 1,
        }
        st.session_state.pop(result_key, None)
        st.rerun()
    plan = cached["plan"]
    signature = _signature((asdict(plan), actor.strip(), cached["generation"]))
    st.subheader("Review the full workbook import")
    st.write("Save the usable contract and site contacts together. Missing values are not invented; ambiguous records below are left out.")
    st.caption("The preview includes existing records retained from the saved directory. This import does not change report membership or replace contacts inside existing reports.")
    for notice in plan.notices:
        st.caption(notice)
    if plan.entries:
        st.dataframe(_summary_rows(plan), hide_index=True, width="stretch")
    else:
        st.info("No usable contract contacts or sites were found in this workbook.")
    if plan.exclusions:
        st.warning("These workbook records are excluded from this batch.")
        st.dataframe([{"Worksheet": item.worksheet, "Excel cell / column": item.column,
                       "Reason": item.reason} for item in plan.exclusions],
                     hide_index=True, width="stretch")
    conflicts = [{"Contract": entry.contract, "Reason": reason}
                 for entry in plan.entries for reason in entry.conflicts]
    if conflicts:
        st.warning("These contracts need review and will not be saved. Their current directory records stay unchanged.")
        st.dataframe(conflicts, hide_index=True, width="stretch")
    _show_mappings(plan)
    with st.expander("Review all proposed contact details"):
        rows = _contact_rows(plan)
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.caption("No contact details are included.")
    eligible = tuple(entry for entry in plan.entries if entry.can_save)
    unchanged = tuple(entry for entry in plan.entries if not entry.changed and not entry.conflicts)
    st.caption(f"{len(eligible)} contracts to save · {len(unchanged)} already current · {len({row['Contract'] for row in conflicts})} requiring review")
    outcome = st.session_state.get(result_key)
    current_outcome = outcome[1] if outcome and outcome[0] == signature else None
    if current_outcome is not None:
        _show_result(current_outcome)
    elif plan.entries and not eligible and not conflicts:
        st.success("This workbook already matches the saved directory. No changes are needed.")
    confirmed = st.checkbox("I reviewed the included contracts, sites and contacts and confirm this shared save",
                            key=key + "_confirm_" + signature,
                            disabled=not eligible or current_outcome is not None)
    if st.button("Save all reviewed contacts", key=key + "_save", type="primary",
                 disabled=not (eligible and confirmed) or current_outcome is not None):
        try:
            result = batch.save_workbook_plan(plan, raw, actor=actor.strip(), confirmed=confirmed)
        except (ValueError, OSError) as exc:
            st.error(str(exc))
            st.caption("Refresh the preview and review the current directory before trying again.")
            return
        st.session_state[result_key] = (signature, result)
        st.rerun()
