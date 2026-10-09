"""Optional shared logo maintenance; everyday managers just see the logos."""

import hashlib

import streamlit as st

from app import monthly_report_branding as branding
from app.monthly_report_editor import _signature


def render_branding(field):
    if st.button("Back to monthly reports", key="report_branding_back"):
        st.session_state["report_branding_manage"] = False
        st.rerun()
    st.subheader("Shared contract logos")
    st.write("These logos appear on contract cards and fill empty logos in new reports. Existing report logos stay as saved; managers can choose a replacement in Site information.")
    current = branding.load_branding()
    revision = current.revision if current else 0
    upload = st.file_uploader("Reviewed logo collection", type=["zip"], max_upload_size=32, key="report_branding_bundle")
    logos, assets = (current.logos, {}) if current else ((), {})
    digest = ""
    if upload:
        raw = upload.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        try:
            logos, assets = branding.inspect_bundle(raw)
        except ValueError as exc:
            st.error(str(exc))
            return
    if logos:
        st.caption(f"{len(logos)} logos · {sum(len(v.contracts) for v in logos)} contract mappings")
        shown = st.selectbox("Logo to inspect", [v.key for v in logos], format_func=lambda key: next(v.title for v in logos if v.key == key), key="report_branding_preview_" + digest)
        logo = next(v for v in logos if v.key == shown)
        st.image(assets.get(logo.asset) or branding.read_logo(logo), width=360)
        st.write("Contracts: " + (", ".join(logo.contracts) or "ENFRA report branding"))
        st.caption("Source reviewed " + logo.checked_on)
        if logo.source_note:
            st.caption(logo.source_note)
        st.link_button("Official source", logo.source_url)
        st.link_button("Artwork source", logo.asset_url)
        with st.expander("All logos and contract mappings"):
            st.dataframe([{"Logo": v.title, "Contracts": ", ".join(v.contracts), "Reviewed": v.checked_on, "Official source": v.source_url} for v in logos], hide_index=True)
    actor = st.text_input("Logo editor name", key=field("report_branding_actor", ""))
    st.caption("Your entered name records this shared change; it is not authenticated identity. Earlier logo collections remain restorable.")
    if upload:
        if current:
            removed = {c for v in current.logos for c in v.contracts} - {c for v in logos for c in v.contracts}
            if removed:
                st.warning("These contracts would lose their shared default: " + ", ".join(sorted(removed)))
        confirmed = st.checkbox("I reviewed the logos, official sources and contract mappings and confirm this shared update", key="report_branding_confirm_" + _signature((digest, revision, actor)))
        if st.button("Save shared logos", disabled=not (actor.strip() and confirmed), type="primary", key="report_branding_save"):
            try:
                branding.save_branding(logos, assets, expected_revision=revision, actor=actor, confirmed=True)
                st.session_state["report_branding_saved"] = True
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
    if st.session_state.pop("report_branding_saved", False):
        st.success("Shared logos saved. New report designs can use them now.")
    if current:
        with st.expander("Logo history and restore"):
            selected = st.selectbox("Saved collection", list(range(current.revision, 0, -1)), key="report_branding_history")
            old = branding.load_branding(selected)
            st.caption(f"Version {old.revision} · {old.actor} · {old.updated_at} · {old.action}")
            st.write(", ".join(v.title for v in old.logos))
            confirm = st.checkbox("Restore this collection as a new shared version", key="report_branding_restore_ok_" + _signature((selected, revision, actor)))
            if st.button("Restore logo collection", disabled=not (confirm and actor.strip()), key="report_branding_restore"):
                try:
                    branding.restore_branding(selected, expected_revision=revision, actor=actor, confirmed=True)
                    st.rerun()
                except (OSError, ValueError) as exc:
                    st.error(str(exc))


def offer_logo(block, contract, prefix, assets):
    """Explicit replacement in one draft; old/shared assets remain preserved."""
    logo = branding.find_logo(contract, brand=block.key == "brand_logo")
    if not logo or block.asset_hashes == (logo.asset,):
        return block
    from dataclasses import replace
    with st.container(border=True):
        st.caption(f"Available: {logo.title} · official source checked {logo.checked_on}")
        st.image(branding.read_logo(logo), width=240)
        label = "Use this logo in this report" if block.asset_hashes else "Add this logo to this report"
        if st.button(label, key=prefix + "_official_" + block.key + "_" + logo.asset):
            assets[logo.asset] = branding.read_logo(logo)
            block = replace(block, source="Replace once", asset_hashes=(logo.asset,), asset_captions=(), references=(), client_reviewed_fingerprint="")
            # Selecting verified artwork from the reviewed shared collection
            # does not require another pricing/page review in this report.
            return replace(block, client_reviewed_fingerprint=block.fingerprint)
    return block
