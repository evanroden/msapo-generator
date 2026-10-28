"""Explicit correction of source membership, separate from target report sites."""
from dataclasses import asdict
import hashlib
import json

import streamlit as st

from app.monthly_report_model import Facility


def correction_scope(inspection, target, period, source_view=None):
    return (inspection.sha256, getattr(source_view, "receipt_sha256", ""),
            target.contract, target.key, tuple(sorted(f.key for f in target.facilities)),
            period.key)


def correction_receipt(scope, sites):
    return hashlib.sha256(json.dumps((scope, [asdict(s) for s in sites]),
                                    sort_keys=True).encode()).hexdigest()


def correct_detected_sites(inspection, target, period, detected, known_sites, prefix, field, *, source_view=None):
    """Return only a current explicitly confirmed source membership.

    Editing a selection retires its previous approval. The target profile and
    source bytes are never changed, and no source/date/artwork review is granted.
    """
    scope = (*correction_scope(inspection, target, period, source_view),
             tuple(sorted((f.key, f.title, tuple(f.aliases)) for f in known_sites)),
             tuple(sorted(f.key for f in detected)))
    active_scope_key = "monthly_source_membership_scope"
    if st.session_state.get(active_scope_key) != scope:
        st.session_state.pop("monthly_source_membership_confirmation", None)
        st.session_state.pop("monthly_source_membership_render_scope", None)
        st.session_state[active_scope_key] = scope
    if not detected:
        return None  # Unknown-source UI still owns its ordinary confirmation.
    scope_key = hashlib.sha256(repr(scope).encode()).hexdigest()[:20]
    p = prefix + "_source_membership_" + scope_key
    options = {f.key: f for f in (*known_sites, *detected)}
    with st.expander("Correct source sites"):
        st.caption("This report: " + "; ".join(f.title for f in target.facilities))
        st.caption("Detected in upload: " + "; ".join(f.title for f in detected))
        st.caption("Changing source sites resets unsaved import-review choices; saved reports stay unchanged.")
        selected = st.multiselect("Actual sites covered by the uploaded report", list(options),
                                  format_func=lambda k: options[k].title,
                                  key=field(p + "_selected", [f.key for f in detected]))
        custom = st.text_input("Source site not listed (optional)", key=field(p + "_custom", ""),
                               help="Separate multiple source sites with semicolons.")
        sites = [options[k] for k in selected]
        from app.monthly_report_editor import _key
        invalid = False
        for name in (s.strip() for s in custom.split(";")):
            if not name:
                continue
            key = _key(name)
            if not key:
                invalid = True
                continue
            matches = [f for f in options.values() if name.casefold() in
                       {n.casefold() for n in (f.title, *f.aliases)}]
            if len(matches) > 1 or (not matches and key in options):
                invalid = True
                continue
            site = matches[0] if matches else Facility(key, name)
            if any(prior.key == site.key and prior != site for prior in sites):
                invalid = True
                continue
            sites.append(site)
        sites = tuple(sorted({f.key: f for f in sites}.values(), key=lambda f: f.key))
        receipt = correction_receipt(scope, sites)
        # One active import receipt, not a cache that resurrects approvals
        # after the operator switches away and then back to an earlier source.
        receipt_key = "monthly_source_membership_confirmation"
        if invalid or st.session_state.get(receipt_key) not in (None, receipt):
            st.session_state.pop(receipt_key, None)
        if invalid:
            st.warning("Enter an unambiguous source site name using letters or numbers.")
        if st.button("Confirm source sites", key=p + "_confirm", disabled=invalid or not sites):
            st.session_state[receipt_key] = receipt
        confirmed = not invalid and bool(sites) and st.session_state.get(receipt_key) == receipt
        if st.button("Use detected source sites", key=p + "_detected"):
            st.session_state.pop(receipt_key, None)
            confirmed = False
        if confirmed:
            st.caption("Confirmed source sites: " + "; ".join(f.title for f in sites))
        else:
            st.caption("Detected sites remain in use until you confirm. This does not change the report’s selected sites.")
    return sites if confirmed else None


def source_review_epoch(inspection, target, period, sites, relation, source_view=None):
    """Never resurrect section widgets/approval after switching source scope."""
    from uuid import uuid4
    scope = (*correction_scope(inspection, target, period, source_view),
             tuple(sorted((f.key, f.title, tuple(f.aliases)) for f in sites)), relation)
    key = "monthly_source_membership_render_scope"
    previous = st.session_state.get(key)
    if not previous or previous[0] != scope:
        previous = (scope, uuid4().hex)
        st.session_state[key] = previous
    return previous[1]
