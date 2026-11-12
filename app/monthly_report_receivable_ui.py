"""One native Accounts Receivable intake from the shared Manage source files owner.

The original CSV/XLSX is ingested and retained by that existing owner.
Selecting rows here never imports another file, approves a financial output,
or writes client monetary columns. All choices remain report-scoped.
"""
import hashlib
import json
import streamlit as st

from app.monthly_report_correction_targets import report_identity
from app.monthly_report_receivable_intake import (
    EDITABLE, _RECEIPT_LINK, _digest, check_review_binding, decoded,
    editable_rows, inspect_content, prepare_review,
)


def saved_review_for_editor(draft, current, content, number, review):
    """Hydrate only the exact current, still-valid source/period receipt.

    Internal corrections are defaults, never new source evidence or client
    financial permission. If the block/source is stale, do not replay edits.
    """
    originals = [block for block in draft.blocks if block.key == "accounts_receivable"]
    if (len(originals) != 1 or originals[0] != current or current.source == "Omit"):
        return None
    refs = [ref for ref in current.references if ref.startswith(_RECEIPT_LINK)]
    if len(refs) != 1:
        return None
    candidates = []
    for raw in draft.source_row_reviews:
        try:
            receipt = decoded(raw)
        except ValueError:
            continue
        if (_RECEIPT_LINK + _digest(receipt) == refs[0]
                and receipt["report"] == report_identity(draft)
                and receipt["period"] == draft.period.key
                and receipt["source_id"] == content.source.id
                and receipt["source_sha256"] == content.source.sha256
                and receipt["table_number"] == number
                and receipt["table_reference"] == review.table_reference
                and receipt["table_fingerprint"] == review.fingerprint):
            candidates.append(receipt)
    if len(candidates) != 1 or check_review_binding(draft) is not None:
        return None
    if [row["reference"] for row in candidates[0]["rows"]] != [
            row.reference for row in review.rows]:
        return None
    return candidates[0]


def reviewed_editor_defaults(review, receipt):
    rows = editable_rows(review)
    if receipt is not None:
        for row, saved in zip(rows, receipt["rows"]):
            row.update(saved["corrections"])
    return rows


def render_receivable_intake(draft, blocks, prefix):
    key = prefix + "_receivables"
    st.caption(
        "Open invoices and AR Aging · internal review. Amounts, payments, credits "
        "and balances are visible here only. The client report contains an "
        "invoice-status view without monetary figures; it is not a complete "
        "AR Aging statement."
    )
    current = blocks.get("accounts_receivable")
    if current is not None and current.rows:
        st.caption("Current Section 10 invoice status rows: " + str(len(current.rows)))
    contents = tuple(content for content in st.session_state.get(prefix + "_evidence", ())
                     if content.source.suffix in (".csv", ".xlsx") and
                     len([source for source in draft.sources
                          if source.id == content.source.id and source == content.source]) == 1)
    if not contents:
        st.info("Read a CSV/XLSX invoice export in Manage source files, then return here. "
                "Missing saved originals are never replaced by a filename match.")
        return draft, blocks
    candidates = [(content, n) for content in contents
                  for n in range(1, len(content.tables) + 1)]
    options = tuple((content.source.id, number) for content, number in candidates)
    if len(options) != len(set(options)):
        st.warning("An invoice source occurs more than once. Correct the source identity.")
        return draft, blocks
    by_key = {(content.source.id, number): content for content, number in candidates}
    def label(value):
        content = by_key[value]
        return (content.source.filename + " · " + content.source.sha256[:12] +
                " · sheet/table " + str(value[1]) +
                " (" + content.tables[value[1] - 1].name + ")")
    with st.expander("Review an existing invoice source", expanded=not bool(current and current.rows)):
        choice = st.selectbox("Source invoice sheet", options, format_func=label,
                              key=key + "_source")
        content, number = by_key[choice], choice[1]
        try:
            review = inspect_content(draft, content, number)
        except (ValueError, OSError) as exc:
            st.warning(str(exc))
            return draft, blocks
        if not review.rows:
            st.caption("This source sheet contains no invoice rows.")
            return draft, blocks
        labels = {column.candidate_role for column in review.columns}
        if review.duplicate_roles or not {"invoice_id", "site", "status"} <= labels:
            st.warning("This table needs one Invoice, Site and Status column without competing headings. "
                       "Use a corrected source export; its original is unchanged.")
            st.table([{"Source header": column.heading,
                       "Candidate role": column.candidate_role or "Unmapped"}
                      for column in review.columns])
            return draft, blocks
        if review.unknown_columns:
            st.caption("Unmapped source columns remain in the original and internal receipt; "
                       "they do not become client-report fields.")
        st.caption("Source rows " + str(len(review.rows)) +
                   " · exact table fingerprint " + review.fingerprint[:12] +
                   ". Dates must use YYYY-MM-DD; unknown/ambiguous source dates stay explicit.")
        st.table([{"Source heading": col.heading, "Candidate field": col.candidate_role or "Unmapped",
                   "Internal monetary": "Yes" if col.policy_controlled else "No"}
                  for col in review.columns])
        st.caption("Original invoice cells (internal review only, including unapproved amounts):")
        unique_headers = [str(column.index + 1) + ". " + column.heading
                          for column in review.columns]
        st.dataframe([dict(zip(unique_headers, row.cells)) for row in review.rows],
                     hide_index=True, width="stretch")
        st.caption("Edit the review fields below when the original is ambiguous. "
                   "Raw source values remain unchanged. No outstanding balance is inferred.")
        saved = saved_review_for_editor(draft, current, content, number, review)
        # Source metadata, report owner, original table and prior receipt are
        # all part of the editor identity. A previous month cannot replay a
        # native data-editor delta even when invoice IDs and bytes match.
        stamp = hashlib.sha256(json.dumps((
            report_identity(draft), content.source.fingerprint, review.fingerprint,
            _RECEIPT_LINK + _digest(saved) if saved else "new-review"),
            ensure_ascii=False).encode()).hexdigest()[:24]
        if saved:
            st.caption("Saved review: as of " + saved["as_of"] +
                       " · corrections remain editable. Original cells above are unchanged.")
        elif current is not None and any(ref.startswith(_RECEIPT_LINK) for ref in current.references):
            st.warning("The previous invoice review does not match this report, source or table. "
                       "Recheck the original rows and enter a new as-of date; no approval was reused.")
        with st.form(key + "_review_" + stamp):
            as_of = st.text_input("Aging as of date (YYYY-MM-DD)",
                                  value=saved["as_of"] if saved else "",
                                  help="Required explicit review date; not inferred from the report month.")
            roles = {
                "customer_invoice": "Customer-billable / CCJ invoice (internal amounts)",
                "vendor_invoice": "Vendor invoice (internal only; no client totals)",
                "contract": "Contract source (internal review; no automatic output grant)",
                "enfra_client_report": "ENFRA report intended for client (no automatic output grant)",
                "unverified": "Source audience not established (no financial output)",
            }
            source_kind = st.selectbox(
                "Exact source category", list(roles),
                index=list(roles).index(saved["source_kind"]) if saved else 0,
                format_func=roles.get)
            editor = st.data_editor(reviewed_editor_defaults(review, saved),
                                    num_rows="fixed", key=key + "_rows_" + stamp,
                                    hide_index=True, width="stretch")
            if current is not None and current.rows:
                overwrite = st.checkbox("Replace the existing Section 10 status rows with this reviewed source")
            else:
                overwrite = True
            confirmed = st.checkbox(
                "I checked every invoice row and the as-of date against the original source; "
                "amounts are internal only and no client monetary output is approved"
            )
            submitted = st.form_submit_button("Apply reviewed invoice statuses")
        if not submitted:
            return draft, blocks
        if not confirmed or not overwrite:
            st.warning("Confirm each source row and the replacement choice before applying.")
            return draft, blocks
        if not isinstance(editor, list) or len(editor) != len(review.rows):
            st.error("The native row editor changed shape; nothing was applied.")
            return draft, blocks
        corrections = {}
        for row, presented in zip(review.rows, editor):
            if (not isinstance(presented, dict) or
                    presented.get("Source row") != row.position):
                st.error("A source row identity changed; no invoice statuses were applied.")
                return draft, blocks
            fields = {column.candidate_role: row.cells[column.index]
                      for column in review.columns
                      if column.candidate_role and column.candidate_role != "aging_bucket"}
            corrections[row.reference] = {
                role: value for role in EDITABLE
                if (value := presented.get(role, "")) != fields.get(role, "")}
        try:
            revised, new_block = prepare_review(
                draft, content, number, as_of=as_of,
                edited=corrections, source_kind=source_kind, confirmed=True)
        except (ValueError, OSError) as exc:
            st.error(str(exc))
            st.caption("No source, financial amount, or prior Section 10 row was changed.")
            return draft, blocks
        blocks["accounts_receivable"] = new_block
        st.session_state[prefix + "_period_editor_refresh"] = True
        st.success("Reviewed invoice statuses applied to Section 10. "
                   "Monetary amounts remain internal and are not authorized for client export.")
        return revised, blocks
