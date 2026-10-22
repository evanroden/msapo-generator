"""Optional shared logo maintenance; everyday managers just see the logos."""

import hashlib

import streamlit as st

from app import monthly_report_branding as branding
from app.monthly_report_editor import _signature


def render_branding(field):
    st.subheader("Shared contract logos")
    st.write("These logos appear on contract cards and fill empty logos in new reports. Existing report logos stay as saved.")
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
        try:
            st.image(assets.get(logo.asset) or branding.read_logo(logo), width=360)
        except branding.LogoArtworkError:
            st.warning("This saved logo could not be read. Replace this shared logo below, upload a reviewed collection, or restore a readable version. History is unchanged.")
        st.text("Contracts: " + (", ".join(logo.contracts) or "ENFRA report branding"))
        from app.monthly_report_branding_replace import OWNER_VARIANT_PREFIX
        owner_provided = logo.source_note.startswith(OWNER_VARIANT_PREFIX)
        st.caption(("Artwork reviewed " if owner_provided else "Source reviewed ") + logo.checked_on)
        if logo.source_note:
            st.text(logo.source_note)
        st.link_button("Official brand reference" if owner_provided else "Official source", logo.source_url)
        if owner_provided:
            st.caption("Owner-provided artwork; the official link is a brand reference.")
        else:
            st.link_button("Artwork source", logo.asset_url)
        with st.expander("All logos and contract mappings"):
            st.dataframe([{"Logo": v.title, "Contracts": ", ".join(v.contracts), "Reviewed": v.checked_on, "Official source": v.source_url} for v in logos], hide_index=True)
    actor = st.text_input("Logo editor name", key=field("report_branding_actor", ""))
    st.caption("Your entered name records this shared change; it is not authenticated identity. Earlier logo collections remain restorable.")
    if current and not upload:
        _replace_selected_logo(current, shown, actor)
    if upload:
        if current:
            removed = {c for v in current.logos for c in v.contracts} - {c for v in logos for c in v.contracts}
            if removed:
                st.warning("These contracts would lose their shared default:")
                st.text(", ".join(sorted(removed)))
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
            st.text(f"Version {old.revision} · {old.actor} · {old.updated_at} · {old.action}")
            st.text(", ".join(v.title for v in old.logos))
            confirm = st.checkbox("Restore this collection as a new shared version", key="report_branding_restore_ok_" + _signature((selected, revision, actor)))
            if st.button("Restore logo collection", disabled=not (confirm and actor.strip()), key="report_branding_restore"):
                try:
                    branding.restore_branding(selected, expected_revision=revision, actor=actor, confirmed=True)
                    st.rerun()
                except (OSError, ValueError) as exc:
                    st.error(str(exc))


def offer_logo(block, contract, prefix, assets, *, scope=None):
    """Explicit replacement in one draft; old/shared assets remain preserved."""
    from uuid import uuid4
    cycle_key = prefix + "_shared_logo_cycle_" + block.key
    try:
        current = branding.load_branding()
        logo = branding.find_logo(contract, brand=block.key == "brand_logo", state=current) if current else None
        if not logo or (block.source != "Omit" and block.asset_hashes == (logo.asset,)):
            st.session_state.pop(cycle_key, None)
            return block
        raw = branding.read_logo(logo)
    except (ValueError, KeyError, TypeError):
        st.session_state.pop(cycle_key, None)
        st.caption("Shared logo unavailable. This report’s artwork stays unchanged.")
        return block
    from dataclasses import replace
    identity = _signature((scope, contract, block.fingerprint, current.revision, logo))
    cycle = st.session_state.get(cycle_key)
    if not isinstance(cycle, dict) or cycle.get("identity") != identity:
        cycle = {"identity": identity, "token": uuid4().hex}
        st.session_state[cycle_key] = cycle
    with st.container(border=True):
        from app.monthly_report_branding_replace import OWNER_VARIANT_PREFIX
        review_label = ("owner-provided artwork reviewed" if logo.source_note.startswith(OWNER_VARIANT_PREFIX)
                        else "official source checked")
        st.caption(f"Available: {logo.title} · {review_label} {logo.checked_on}")
        st.image(raw, width=240)
        st.caption("Optional: changes this draft only. Saved reports and shared defaults stay unchanged.")
        label = "Use this logo in this report" if block.asset_hashes else "Add this logo to this report"
        use = st.button(label, key=prefix + "_official_" + block.key + "_" + cycle["token"])
        if use and st.session_state.get(cycle_key) == cycle:
            try:
                latest = branding.load_branding()
            except (ValueError, KeyError, TypeError):
                latest = None
            if latest != current:
                st.session_state.pop(cycle_key, None)
                st.warning("The shared logos changed. Review the current logo again.")
                return block
            from app.monthly_report_model import picture_replacement_references
            block = replace(block, source="Replace once", pending_library_save=False,
                            asset_hashes=(logo.asset,), asset_captions=(),
                            references=picture_replacement_references(block),
                            client_reviewed_fingerprint="", client_asset_reviews=(), asset_provenance=((logo.asset, ()),))
            # Selecting verified artwork from the reviewed shared collection
            # does not require another pricing/page review in this report.
            from app.monthly_report_asset_review import approve_all_assets
            block = approve_all_assets(block)
            assets[logo.asset] = raw
            st.session_state.pop(cycle_key, None)
            return block
    return block


def _replace_selected_logo(current, key, actor):
    """Optional administration only; ordinary report creation has no new choice."""
    from datetime import date
    from app.monthly_report_branding_replace import (
        prepare_replacement, replace_selected_logo,
    )
    logo = next(logo for logo in current.logos if logo.key == key)
    prefix = "report_single_logo_" + _signature((key, current.revision))
    with st.expander("Replace this shared logo", expanded=False):
        st.caption("Updates this shared logo. New reports use it only for empty logo slots. Contracts, other logos and saved reports stay unchanged.")
        upload = st.file_uploader("Owner-provided approved logo (PNG)", type=["png"],
                                 max_upload_size=4, key=prefix + "_upload")
        if upload is None:
            return
        raw = upload.getvalue()
        left, right = st.columns(2)
        with left:
            st.caption("Current")
            try:
                st.image(branding.read_logo(logo), width=240)
            except branding.LogoArtworkError:
                st.warning("The current artwork is unreadable; its record will remain in history.")
        with right:
            st.caption("Replacement")
            try:
                branding._image(raw, branding.library.asset_reference(raw, "png"))
                st.image(raw, width=240)
            except ValueError as exc:
                # In-memory upload validation only; storage/namespace errors
                # from reading the current logo remain fail-closed above.
                st.error(str(exc))
                return
        checked = st.date_input("Artwork reviewed on", value=date.today(), key=prefix + "_date")
        note = st.text_area("Artwork source and approval", value="", max_chars=900,
                            placeholder="Describe the owner-provided file and approved variant.",
                            key=prefix + "_note")
        st.caption("The official brand link is retained as a reference; this upload is recorded as owner-provided artwork.")
        try:
            review = prepare_replacement(logo, current.revision, raw, actor=actor,
                                         checked_on=checked.isoformat(), source_note=note)
        except ValueError as exc:
            st.caption(str(exc))
            return
        identity = prefix + "_" + review.token
        confirmed = st.checkbox("I reviewed this replacement and approve this shared logo change", key=identity + "_confirm")
        if st.button("Replace selected logo", disabled=not confirmed, key=identity + "_save"):
            try:
                replace_selected_logo(key, raw, expected_revision=current.revision,
                    actor=actor, checked_on=checked.isoformat(), source_note=note,
                    review_token=review.token, confirmed=confirmed)
                st.session_state["report_branding_saved"] = True
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
