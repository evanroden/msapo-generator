"""Explicit contract-default actions beside the existing report procedure editor."""
from dataclasses import asdict, replace

import streamlit as st

from app import monthly_report_workflow_standards as workflows
from app.monthly_report_editor import _signature
from app.monthly_report_ui_text import literal


def _queue(key, request):
    st.session_state[key] = request


def render_contract_procedure(draft, block, assets, prefix):
    """Return (report block, explicit inclusion); passive rendering never saves."""
    from app.monthly_report_guided import _rich_text_scope
    scope = _signature((asdict(draft.profile), draft.period.key, _rich_text_scope(prefix)))
    root = prefix + "_contract_procedure_" + block.key + "_" + scope
    request_key = prefix + "_contract_procedure_request"
    request = st.session_state.pop(request_key, None)
    explicit = False
    try:
        state = workflows.load_standards(draft.profile.contract)
        if request:
            if (request.get("scope") != scope or request.get("key") != block.key
                    or request.get("fingerprint") != block.fingerprint):
                raise ValueError("This report or procedure changed. Review the current pages before trying again.")
            action = request.get("action")
            if action == "save":
                values = {value.key: value for value in draft.blocks}
                values[block.key] = block
                state = workflows.save_standard(replace(draft, blocks=tuple(values.values())), block, assets,
                    expected_revision=request["revision"], expected_fingerprint=request["fingerprint"], confirmed=True)
                st.success("Contract default saved. Other contracts and saved report versions are unchanged.")
            elif action == "use":
                block = workflows.use_standard(draft, block, assets,
                    expected_revision=request["revision"], expected_fingerprint=request["fingerprint"])
                explicit = True
                st.success("Contract procedure included in this report. Notes and contacts are unchanged.")
            elif action == "adopt":
                state = workflows.adopt_legacy(draft, block.key,
                    expected_revision=request["revision"],
                    expected_legacy_fingerprint=request["legacy_fingerprint"], confirmed=True,
                    expected_legacy_receipt=request.get("legacy_receipt"))
                st.success("Legacy procedure adopted for this contract only. Existing report pages are unchanged.")
            else:
                raise ValueError("Review the current procedure action again.")
    except (ValueError, OSError) as exc:
        st.warning(literal(exc))
        # Show a freshly loaded state after a stale-version action, but do not
        # automatically retry the rejected action or rewrite the report.
        try:
            state = workflows.load_standards(draft.profile.contract)
        except (ValueError, OSError):
            return block, explicit

    item = next((item for item in state.workflows if item.key == block.key), None)
    st.caption("Contract: " + literal(draft.profile.contract))
    if item:
        st.caption(f"Saved default · version {state.revision} · source "
                   + literal(item.origin_profile) + " · " + literal(item.saved_at.split("T")[0]))
    else:
        st.caption("No approved default for this contract. Upload and review its procedure above.")
    st.caption("Edits stay in this report. Saving a contract default is a separate action for future reports.")
    receipt = {"scope": scope, "key": block.key, "fingerprint": block.fingerprint,
               "revision": state.revision}
    identity = _signature(receipt)
    if item:
        st.button("Use contract default in this report", key=root + "_use_" + identity,
                  help="Replace only this procedure's pictures. Keep report notes, contacts and other sections.",
                  on_click=_queue, args=(request_key, dict(receipt, action="use")))
    st.button("Replace contract default" if item else "Save as contract default",
              key=root + "_save_" + identity,
              disabled=draft.synthetic or not workflows._eligible(
                  workflows.refresh_asset_source_context(block, draft.sources))
                  or not workflows.source_pages_allowed(block, draft.sources, draft.profile),
              help="Publish these reviewed procedure pictures only for this contract. Existing reports stay pinned.",
              on_click=_queue, args=(request_key, dict(receipt, action="save")))
    if not item and not draft.synthetic:
        try:
            legacy = workflows.legacy_candidate(draft.profile.contract, block.key)
            if legacy:
                with st.expander("Review legacy procedure for this contract"):
                    st.caption("Recorded source contract: " + literal(legacy.origin_contract)
                               + " · profile: " + literal(legacy.origin_profile))
                    st.caption("Review this saved artifact for this contract before adopting. Historical pinned procedures "
                               "do not retain original source-page links; adoption does not validate that lost history. "
                               "The legacy original and saved reports remain unchanged.")
                    legacy_receipt = workflows.legacy_review_receipt(legacy)
                    review_key = root + "_legacy_" + legacy_receipt
                    if st.button("Preview legacy procedure", key=review_key + "_preview"):
                        st.session_state[review_key] = True
                    if st.session_state.get(review_key):
                        refs = legacy.block.asset_hashes
                        page = (int(st.number_input("Legacy procedure page", min_value=1, max_value=len(refs),
                                                     value=1, key=review_key + "_page")) - 1 if len(refs) > 1 else 0)
                        st.image(workflows.read_asset(refs[page]), width="stretch",
                                 caption=f"Legacy procedure · page {page + 1} of {len(refs)}")
                    st.button("Adopt legacy procedure for this contract", key=review_key + "_adopt_" + identity,
                              disabled=not st.session_state.get(review_key),
                              on_click=_queue, args=(request_key, dict(receipt, action="adopt",
                                  legacy_fingerprint=legacy.block.fingerprint, legacy_receipt=legacy_receipt)))
        except (ValueError, OSError) as exc:
            st.warning("Legacy procedure is unavailable; existing originals were retained. " + literal(exc))
    return block, explicit
