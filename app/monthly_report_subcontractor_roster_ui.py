"""Optional, explicit contract-roster actions next to Section 6 contact cards.

The ordinary native contact editor remains the authoritative report editor.
No stand-alone form or passive rerun can promote its contents to a shared
master. A shared version is copied only by an explicit report-scoped action.
"""
from __future__ import annotations

from dataclasses import replace

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_subcontractor_roster import (
    apply_roster, eligible_rosters, load_rosters, save_roster,
)


def render_subcontractor_roster(draft, spec, block, prefix, field):
    if not draft.prepared_by.strip():
        return block
    key = prefix + "_contract_subcontractor_roster"
    try:
        state = load_rosters(draft.profile.contract)
    except (ValueError, OSError) as exc:
        st.warning("Shared subcontractor contacts are unavailable. This report's existing contacts are unchanged: " + str(exc))
        return block

    baseline_key = key + "_expected_revision"
    baseline = st.session_state.setdefault(baseline_key, state.revision)
    fresh = baseline == state.revision
    eligible = eligible_rosters(state, draft.profile)
    with st.expander("Contract subcontractors (optional)", expanded=False):
        st.caption(
            f"{len(eligible)} reusable subcontractor roster"
            f"{'' if len(eligible) == 1 else 's'} for these sites"
            f" · contract revision {state.revision}."
            if eligible else
            "No approved shared subcontractor roster covers these sites. Report-only contacts remain editable above."
        )
        st.caption("Your report-only edits do not change saved contract contacts. Sharing requires an explicit approval.")
        if not fresh:
            st.warning("A shared subcontractor version changed after this form opened. Reload it before saving or using a roster; your report edits remain intact.")
            if st.button("Reload shared subcontractors", key=key + "_reload"):
                st.session_state[baseline_key] = state.revision
                st.rerun()
            return block

        if eligible:
            choices = {entry.id: entry for entry in eligible}
            chosen_key = key + "_selected_roster"
            if st.session_state.get(chosen_key) not in choices:
                st.session_state[chosen_key] = eligible[0].id

            def label(entry_id):
                entry = choices[entry_id]
                scope = "Entire contract" if not entry.sites else (
                    "Selected sites: " + ", ".join(entry.sites))
                count = sum(len(table.rows) for table in entry.tables)
                return f"{scope} · {count} source rows · saved {entry.saved_at}"

            chosen = st.selectbox("Saved subcontractor roster", tuple(choices),
                                  format_func=label, key=chosen_key)
            entry = choices[chosen]
            if st.checkbox("Review saved roster rows", key=key + "_show_" + chosen):
                for table in entry.tables:
                    st.dataframe([dict(zip(table.columns, row)) for row in table.rows[:200]],
                                 hide_index=True)
                    if len(table.rows) > 200:
                        st.caption("Showing the first 200 saved rows; no rows were discarded.")
            existing = bool(block.rows or any(table.rows for table in block.extra_tables))
            replace_key = key + "_replace_" + chosen + "_" + block.fingerprint
            allow_replace = (st.checkbox(
                "Replace this report's existing vendor tables (notes and attached pages are kept)",
                key=replace_key) if existing else True)
            if st.button("Use saved subcontractors in this report",
                         key=key + "_apply_" + chosen + "_" + block.fingerprint,
                         disabled=not allow_replace):
                try:
                    revised = apply_roster(
                        state, entry, draft.profile, block, spec,
                        replace_existing=bool(allow_replace))
                except (ValueError, OSError) as exc:
                    st.warning(str(exc))
                else:
                    st.success("Saved subcontractor rows are now in this report only. Shared contacts were not changed.")
                    st.session_state[prefix + "_period_editor_refresh"] = True
                    return revised

        if not (block.rows or any(table.rows for table in block.extra_tables)):
            st.caption("Add editable vendor contact rows above before publishing a reusable contract roster.")
            return block

        st.markdown("**Save these report rows for future reuse**")
        labels = ("Only the sites in this report", "Entire contract")
        scope_key = key + "_share_scope"
        selected_scope = st.radio("Approved reuse scope", labels, key=scope_key,
                                  help="Only explicitly approved rows are shared. Uploaded pages and report-specific notes stay here.")
        selected_sites = (tuple(facility.key for facility in draft.profile.facilities)
                          if selected_scope == labels[0] else ())
        if not selected_sites:
            st.caption("Contract-wide approval is for genuinely shared vendor rows. Rows explicitly naming a facility must use site-specific approval.")
        confirmation = st.checkbox(
            "I reviewed these vendor contacts and confirm this reuse scope for the contract",
            key=key + "_confirm_" + block.fingerprint + "_" + str(selected_sites) + "_" + str(baseline),
        )
        if st.button("Save shared subcontractors",
                     key=key + "_save_" + block.fingerprint + "_" + str(selected_sites) + "_" + str(baseline),
                     disabled=not confirmation):
            try:
                saved = save_roster(
                    draft.profile, block, spec,
                    site_keys=selected_sites, expected_revision=baseline,
                    actor=draft.prepared_by, confirmed=bool(confirmation),
                )
            except (ValueError, OSError) as exc:
                st.warning("Shared roster was not changed: " + str(exc))
            else:
                st.session_state[baseline_key] = saved.revision
                st.success("Saved a reviewed subcontractor roster for the selected contract scope. This report's contents are unchanged.")
                st.session_state[prefix + "_period_editor_refresh"] = True
    return block
