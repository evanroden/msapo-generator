"""Review valid history before recovering an unreadable shared directory."""
import streamlit as st

from app import monthly_report_directory_recovery as recovery
from app.monthly_report_editor import _signature
from app.monthly_report_ui_text import literal


def render_recovery(unavailable, actor):
    if not unavailable:
        return
    with st.expander("Recover an unreadable directory", expanded=True):
        st.caption("Inspect saved history, then choose the version to recover. The damaged record and all earlier versions are retained.")
        keys = [problem.storage_key for problem in unavailable]
        chosen = st.selectbox("Unreadable directory record", keys, key="report_directory_recovery_record")
        cache_key = "report_directory_recovery_review_" + chosen
        if st.button("Inspect recovery history", key="report_directory_recovery_inspect"):
            st.session_state.pop(cache_key, None)
            try:
                st.session_state[cache_key] = recovery.inspect_recovery(chosen)
            except (ValueError, OSError) as exc:
                st.error(literal(exc))
        review = st.session_state.get(cache_key)
        if review is not None and review.context != recovery.review_context():
            st.session_state.pop(cache_key, None)
            review = None
        if review is None:
            return
        st.text(review.versions[0].contract)
        versions = {state.revision: state for state in review.versions}
        prefix = "report_directory_recovery_" + _signature((review.fingerprint, actor))
        selected = st.selectbox("Saved version to recover", sorted(versions, reverse=True), key=prefix + "_version")
        prior = versions[selected]
        st.caption(literal(f"Version {prior.revision} · {prior.actor} · {prior.updated_at}"))
        st.caption(f"Recovery will create revision {review.next_revision}. " +
                   ("This version is archived and will stay archived." if prior.archived else "This version is active."))
        if review.unavailable_versions:
            st.warning("Unreadable history versions are retained and cannot be selected: " +
                       ", ".join(map(str, review.unavailable_versions)))
        st.dataframe([{"Site": site.title, "Aliases": "; ".join(site.aliases), "Address": site.address,
                       "Active": site.active} for site in prior.sites], hide_index=True)
        rows = [{"Scope": "Contract-wide", "Role": c.role, "Name": c.name, "Phone": c.phone, "Email": c.email}
                for c in prior.contract_contacts]
        rows.extend({"Scope": site.title, "Role": c.role, "Name": c.name, "Phone": c.phone, "Email": c.email}
                    for site in prior.sites for c in site.contacts)
        st.dataframe(rows, hide_index=True)
        confirmed = st.checkbox("Recover this reviewed version as a new directory revision",
                                key=prefix + f"_confirm_{selected}")
        if st.button("Recover directory", key=prefix + "_save", disabled=not confirmed):
            try:
                restored = recovery.recover_directory(review, selected, actor=actor, confirmed=confirmed)
            except (ValueError, OSError) as exc:
                st.error(literal(exc))
                return
            st.session_state.pop(cache_key, None)
            st.session_state["report_directory_message"] = (
                f"Recovered directory as revision {restored.revision}. The damaged record and earlier history were retained. Existing reports were not changed.")
            st.rerun()
