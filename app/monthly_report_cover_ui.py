"""Current cover content with optional, explicit artwork changes in one place."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_asset_review import preserve_asset_reviews
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_editor import _signature
from app.monthly_report_model import ResolvedBlock, picture_replacement_references


PICTURES = (
    ("client_logo", "Client logo"),
    ("brand_logo", "ENFRA logo"),
    ("cover_photo", "Cover photo"),
)


def replace_cover_picture(block, data, suffix, assets):
    """Replace only the requested slot; identical artwork keeps its review."""
    image = normalize_report_image(data, suffix, line_art=block.key != "cover_photo",
                                   preserve_transparency=block.key in ("brand_logo", "client_logo"))
    reference = library.asset_reference(image.data, image.extension)
    assets[reference] = image.data
    if block.source != "Omit" and block.asset_hashes == (reference,):
        return block
    return preserve_asset_reviews(block, replace(
        block, source="Replace once", asset_hashes=(reference,),
        asset_captions=(), references=picture_replacement_references(block), reviewed_fingerprint="",
        client_reviewed_fingerprint="", asset_provenance=((reference, ()),), client_asset_reviews=(),
    ))


def render_cover_photograph(blocks, prefix, assets, asset_loader, *, scope):
    """The ordinary report's optional photo, without design/logo administration.

    Action identities include the editor incarnation, selected photo and action
    cycle. A delayed native click must not apply to a reset/import or to a later
    return to the same photo. Merely opening this disclosure changes no blocks,
    assets, shared defaults or saved report versions.
    """
    result = dict(blocks)
    block = result.get("cover_photo", ResolvedBlock("cover_photo", "Omit"))
    cycle_key = prefix + "_cover_photograph_cycle"
    cycle = st.session_state.get(cycle_key)
    if not isinstance(cycle, dict) or cycle.get("scope") != scope:
        cycle = {"scope": scope, "token": uuid4().hex}
        st.session_state[cycle_key] = cycle
    identity = _signature((scope, cycle["token"], block.fingerprint))
    st.markdown('<span id="report-cover-photograph"></span>', unsafe_allow_html=True)
    with st.expander("Change cover photograph", expanded=False):
        st.caption("Changes this report’s photograph. Logos and saved report designs stay unchanged.")
        if block.source == "Omit" or not block.asset_hashes:
            st.caption("No cover photograph in this report (optional).")
        else:
            try:
                st.image(asset_loader(block.asset_hashes[0]), width="stretch")
            except (ValueError, OSError, KeyError):
                st.warning("The current photograph could not be displayed. Choose a replacement or leave it out.")
        upload = st.file_uploader(
            "New photograph for this report", type=["png", "jpg", "jpeg", "heic", "heif", "webp"],
            max_upload_size=30, key=prefix + "_cover_photograph_upload_" + identity,
            help="PNG, JPEG, HEIC, HEIF or WebP, up to 30 MB. The current photograph stays until you use the replacement.",
        )
        if upload:
            raw, suffix = upload.getvalue(), Path(upload.name).suffix
            source = _signature((identity, sha256(raw).hexdigest(), suffix))
            use = st.button("Use this photograph", key=prefix + "_cover_photograph_use_" + source)
            if use and st.session_state.get(cycle_key) == cycle:
                try:
                    result["cover_photo"] = replace_cover_picture(block, raw, suffix, assets)
                except (ValueError, OSError):
                    st.error("This photograph could not be read. Choose another image; the current photograph is retained.")
                else:
                    st.session_state[cycle_key] = {"scope": scope, "token": uuid4().hex}
                    # Redraw only after the caller commits every editor field
                    # and attempts recovery; never interrupt a same-click edit.
                    st.session_state[prefix + "_period_editor_refresh"] = True
                    st.success("Cover photograph changed for this report.")
        if block.source != "Omit" and block.asset_hashes:
            omit = st.button("No cover photograph", key=prefix + "_cover_photograph_omit_" + identity)
            if omit and st.session_state.get(cycle_key) == cycle:
                # Retain the original bytes and evidence, including saved versions.
                # Omission is a report choice, not an asset/history deletion.
                result["cover_photo"] = replace(block, source="Omit")
                st.session_state[cycle_key] = {"scope": scope, "token": uuid4().hex}
                st.session_state[prefix + "_period_editor_refresh"] = True
                st.success("Cover photograph left out of this report.")
    return result


def _set_action(key, action):
    st.session_state[key] = action


def _upload_picture(block, title, prefix, assets):
    noun = title if title.startswith("ENFRA") else title.lower()
    upload = st.file_uploader(
        "New " + noun, type=["png", "jpg", "jpeg", "heic", "heif", "webp"],
        key=prefix + "_upload_" + block.key,
    )
    if upload and st.button("Use this " + noun, key=prefix + "_use_" + block.key):
        try:
            block = replace_cover_picture(block, upload.getvalue(), Path(upload.name).suffix, assets)
        except (ValueError, OSError):
            st.error("This picture could not be read. Choose another image; your current artwork is retained.")
        else:
            st.success(title + " updated in this draft. Save progress to keep the change.")
    return block


def _preview_picture(block, title, loader):
    st.markdown("**" + title + "**")
    if block.source == "Omit" or not block.asset_hashes:
        st.caption("No cover photo selected (optional)." if block.key == "cover_photo" else "No logo selected.")
        return
    try:
        st.image(loader(block.asset_hashes[0]), width="stretch")
    except (ValueError, OSError, KeyError):
        st.warning("This picture could not be displayed. Open its change control to choose a replacement.")
    if block.key == "brand_logo":
        st.caption("Used in the report’s page headers.")
    if len(block.asset_hashes) > 1:
        st.caption("The report uses the first picture here. Additional imported artwork is retained in the advanced editor.")


def render_cover(draft, blocks, prefix, assets, field, asset_loader):
    """Return edited cover blocks without changing shared defaults or identity.

    Place this once in the Report step. Title, scope, month and preparer are the
    caller's existing report controls. Saved artwork is reused automatically;
    appearance changes stay inside the optional, collapsed settings.
    """
    result = dict(blocks)
    prefix += "_cover"
    action_key = prefix + "_action"
    st.subheader("Cover and report details")
    st.markdown("**" + draft.profile.title + "**")
    st.write(draft.period.label + " · " + draft.profile.contract)
    st.caption("Sites: " + "; ".join(site.title for site in draft.profile.facilities))
    st.caption("Prepared by: " + (draft.prepared_by.strip() or "Enter your name above"))
    st.caption("Saved artwork is used automatically.")
    with st.expander("Report appearance", expanded=False):
        st.caption("Optional changes to this report’s artwork and footer.")
        preview = st.container()
        actions = st.columns(2)
        for column, label, action in zip(actions, ("Change cover photo", "Edit footer"), ("photo", "footer")):
            column.button(label, key=prefix + "_" + action,
                          on_click=_set_action, args=(action_key, action))
        action = st.session_state.get(action_key, "")
        if action == "photo":
            st.markdown("**Change cover photo**")
            st.caption("The cover photo is optional. Your current photo stays until you use a replacement or remove it.")
            original = block = result.get("cover_photo", ResolvedBlock("cover_photo", "Omit"))
            block = _upload_picture(block, "Cover photo", prefix, assets)
            if block.asset_hashes and block.source != "Omit" and st.button("Remove cover photo", key=prefix + "_remove_photo"):
                block = preserve_asset_reviews(block, replace(
                    block, source="Omit", asset_hashes=(), asset_captions=(),
                    references=(), reviewed_fingerprint="", client_reviewed_fingerprint="",
                ))
                st.success("Cover photo removed from this draft. Save progress to keep the change.")
            if block != original:
                result["cover_photo"] = block
        elif action == "footer":
            block = result.get("footer_text", ResolvedBlock("footer_text", "This month", text=draft.address_line))
            default = "" if block.source == "Omit" else block.text
            value = st.text_area("Report footer (optional)",
                                 key=field(prefix + "_footer_value_" + _signature((block.text, block.source)), default),
                                 help="For example, the facility address. Leave it blank for no footer.")
            if st.button("Use footer text", key=prefix + "_footer_save"):
                if value != default:
                    result["footer_text"] = preserve_asset_reviews(block, replace(
                        block, source="This month", text=value,
                        reviewed_fingerprint="", client_reviewed_fingerprint="",
                    ))
                st.success("Footer updated in this draft. Save progress to keep the change.")
        if action:
            st.button("Done with cover changes", key=prefix + "_done",
                      on_click=_set_action, args=(action_key, ""))
        with preview:
            if action == "photo":
                st.caption("Selected source photo. The report preview shows its placement in the ENFRA cover.")
                _preview_picture(result.get("cover_photo", ResolvedBlock("cover_photo", "Omit")), "Cover photo", asset_loader)
            footer = result.get("footer_text")
            text = (footer.text if footer.source != "Omit" else "") if footer else draft.address_line
            if text.strip():
                st.caption("Footer: " + text)
    return result
