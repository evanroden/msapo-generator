"""Explicit contract-approved Capital Renewal controls beside Section 9's native editor."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import streamlit as st

from app.monthly_report_asset_review import preserve_asset_reviews
from app.monthly_report_capital_master import (
    CapitalItem, capital_report_block, load_capital_master,
    save_capital_master, select_capital,
)
from app.monthly_report_content_policy import table_has_pricing


MAIN = ("Facility", "Priority", "Recommendation")
DETAILS = ("Facility", "Capital ID", "Field", "Value")
KNOWN = {"Capital ID", "Asset", "Recorded status", "Status recorded month", "Target date"}


def _site(profile, name):
    label = " ".join(str(name).casefold().split())
    found = [site for site in profile.facilities
             if label in {" ".join(s.casefold().split())
                          for s in (site.key, site.title, *site.aliases)}]
    if len(found) != 1:
        raise ValueError("Each approved capital row must identify exactly one selected facility.")
    return found[0]


def _new_key(site, row, position):
    return "report-" + sha256(repr((site, row, position)).encode()).hexdigest()[:24]


def reviewed_capital_items(draft, block, master):
    """Reconcile an explicitly reviewed native table without changing other sites."""
    profile = draft.profile
    if block.key != "capital_renewal" or block.source == "Omit" or not block.rows:
        raise ValueError("Review an included Section 9 capital table before approval.")
    refs = tuple(r for r in block.references if r.startswith("capital-master:"))
    if refs and refs != (master.reference,):
        raise ValueError("This report uses an earlier approved version. Use the current version explicitly before updating it.")
    if any(len(row) != 3 for row in block.rows) or table_has_pricing(MAIN, block.rows):
        raise ValueError("Review all three capital columns and remove monetary content before approval.")

    detail_rows = {}
    for table in block.extra_tables:
        if not table.rows:
            continue
        if table.columns != DETAILS or table.reference != master.reference:
            raise ValueError("Other source columns need explicit review before capital approval; no fields were discarded.")
        if table_has_pricing(table.columns, table.rows):
            raise ValueError("Monetary capital details cannot be approved for client output.")
        for row in table.rows:
            if len(row) != 4 or not row[1] or not row[2]:
                raise ValueError("Each capital detail needs its exact row ID and field.")
            _site(profile, row[0])
            if row[2] == "Capital ID" and row[3] != row[1]:
                raise ValueError("Capital detail identity cannot be edited.")
            entry = detail_rows.setdefault((row[0], row[1]), {})
            if row[2] in entry:
                raise ValueError("Repeated capital detail fields need review.")
            entry[row[2]] = row[3]

    selected = {site.key for site in profile.facilities}
    occurrences = (select_capital(profile, master, draft.period).occurrences
                   if master.revision else ())
    same_order = (refs == (master.reference,)
                  and len(block.rows) == len(occurrences)
                  and tuple(row[0] for row in block.rows) ==
                  tuple(occ.site_title for occ in occurrences))
    unused = list(occurrences)
    matched = set()
    proposed = {}
    for position, row in enumerate(block.rows):
        site = _site(profile, row[0])
        priority, recommendation = row[1].strip(), row[2].strip()
        if not priority or not recommendation:
            raise ValueError("Every approved capital entry needs a priority and recommendation.")
        source = (occurrences[position] if same_order else
                  next((occ for occ in unused
                        if occ.site_key == site.key and
                        (occ.site_title, occ.item.priority, occ.item.recommendation) == tuple(row)), None))
        if source is not None:
            if source in unused:
                unused.remove(source)
            matched.add((site.key, source.item.key))
        old = source.item if source else None
        has_details = old is not None and any(
            table.rows and table.columns == DETAILS for table in block.extra_tables)
        values = detail_rows.get((row[0], old.key), {}) if old else {}
        extra = (tuple((name, value) for name, value in values.items() if name not in KNOWN)
                 if has_details else old.extra_fields if old else ())
        candidate = CapitalItem(
            key=old.key if old else _new_key(site.key, tuple(row), position),
            priority=priority, recommendation=recommendation,
            asset=values.get("Asset", "" if has_details else old.asset if old else ""),
            status=values.get("Recorded status", "" if has_details else old.status if old else ""),
            status_period=values.get("Status recorded month", "" if has_details else old.status_period if old else ""),
            target_date=values.get("Target date", "" if has_details else old.target_date if old else ""),
            site_keys=old.site_keys if old else (site.key,),
            override_of=old.override_of if old else "",
            extra_fields=extra,
            source_reference=old.source_reference if old else "",
        )
        if old and old.site_keys and not set(old.site_keys) <= selected and candidate != old:
            raise ValueError("An approved row covering another site cannot be changed from this report.")
        if old and not old.site_keys and candidate != old:
            # Contract-wide entries stay intact; changed rows become explicit
            # site exceptions, keeping the original asset identity.
            candidate = replace(candidate, key=_new_key(site.key, tuple(row), position),
                                site_keys=(site.key,), override_of=old.key)
        if candidate.key in proposed and proposed[candidate.key] != candidate:
            raise ValueError("A capital row identity conflicts across selected sites.")
        proposed[candidate.key] = candidate

    if any(not occ.item.site_keys and (occ.site_key, occ.item.key) not in matched
           for occ in occurrences):
        raise ValueError("A contract-wide capital entry cannot be removed from one report.")
    removed = tuple(item.key for item in master.items
                    if item.site_keys and set(item.site_keys) <= selected
                    and item.key not in proposed)
    # Rebuild the selected sites only. Old site-specific rows are replaced by
    # their reviewed versions; all other approved scope stays byte-identical.
    retained = {item.key: item for item in master.items
                if not item.site_keys or not set(item.site_keys) <= selected}
    for key, item in proposed.items():
        if key in retained and retained[key] != item:
            raise ValueError("A capital item has conflicting site scope.")
        retained[key] = item
    return tuple(retained.values()), removed


def use_approved_capital(draft, block, master, *, replace_existing=False):
    if block.key != "capital_renewal":
        raise ValueError("Choose the Section 9 capital table.")
    if (block.rows or any(t.rows for t in block.extra_tables)) and not replace_existing:
        raise ValueError("Confirm replacement of this report's existing capital tables.")
    selection = select_capital(draft.profile, master, draft.period)
    approved = capital_report_block(draft.profile, selection)
    # Keep notes, approved images and their references, but not provenance
    # belonging solely to obsolete report-table cells.
    old_refs = (tuple(r for r in block.references if not r.startswith("capital-master:"))
                if block.text.strip() or block.asset_hashes else ())
    changed = replace(block, source="Library", rows=approved.rows,
                      extra_tables=approved.extra_tables,
                      references=tuple(dict.fromkeys((*old_refs, master.reference))),
                      reviewed_fingerprint="", client_reviewed_fingerprint="")
    return preserve_asset_reviews(block, changed)


def render_capital_master(draft, block, prefix):
    """Neither reuse nor shared promotion happens without an author click."""
    scope = sha256(repr((draft.profile.contract, draft.profile.key, draft.period.key)).encode()).hexdigest()[:20]
    key = prefix + "_approved_capital_" + scope
    with st.expander("Approved Capital Renewal (optional)", expanded=False):
        if not draft.prepared_by.strip():
            st.caption("Enter Prepared by above before using or updating approved capital.")
            return block
        try:
            master = load_capital_master(draft.profile.contract)
        except (ValueError, OSError) as exc:
            st.warning("Approved capital is unavailable; report edits were kept: " + str(exc))
            return block
        baseline_key = key + "_expected_revision"
        baseline = st.session_state.setdefault(baseline_key, master.revision)
        if master.revision:
            st.caption(f"Contract-approved version {master.revision} · {len(master.items)} items · approved by {master.actor}.")
        else:
            st.caption("No Capital Renewal list is approved for this contract.")
        st.caption("Report edits are separate from approved contract versions.")
        if baseline != master.revision:
            st.warning("The approved list changed. Reload it before use or approval; this report is unchanged.")
            if st.button("Reload approved capital", key=key + "_reload"):
                st.session_state[baseline_key] = master.revision
                st.rerun()
            return block

        if master.revision and master.items:
            existing = bool(block.rows or any(t.rows for t in block.extra_tables))
            replace_ok = (st.checkbox(
                "Replace this report's existing capital tables (keep notes and pages)",
                key=key + "_replace_" + block.fingerprint) if existing else True)
            if st.button("Use approved Capital Renewal in this report",
                         key=key + "_use_" + master.reference + "_" + block.fingerprint,
                         disabled=not replace_ok):
                try:
                    chosen = use_approved_capital(
                        draft, block, master, replace_existing=bool(replace_ok))
                except (ValueError, OSError) as exc:
                    st.warning("This report is unchanged: " + str(exc))
                else:
                    st.success(f"Copied approved version {master.revision} into this report only.")
                    st.session_state[prefix + "_period_editor_refresh"] = True
                    return chosen

        if block.source == "Omit" or not block.rows:
            st.caption("Add and review capital rows in the Section 9 table above before approval.")
            return block
        st.markdown("**Approve this report's reviewed Section 9 table for future reuse**")
        st.caption("Only selected sites are updated; no vendor prices, private notes or attachments are shared.")
        confirmed = st.checkbox(
            "I reviewed these capital recommendations and approve a new contract version",
            key=key + "_confirm_" + block.fingerprint + "_" + str(baseline))
        if st.button("Save approved Capital Renewal version",
                     key=key + "_save_" + block.fingerprint + "_" + str(baseline),
                     disabled=not confirmed):
            try:
                items, removed = reviewed_capital_items(draft, block, master)
                saved = save_capital_master(
                    draft.profile, items, expected_revision=baseline,
                    actor=draft.prepared_by, confirmed=True, removed_ids=removed)
            except (ValueError, OSError) as exc:
                st.warning("Approved capital list was not changed: " + str(exc))
            else:
                st.session_state[baseline_key] = saved.revision
                st.success(f"Approved contract version {saved.revision}. This report and its pinned revision are unchanged.")
    return block
