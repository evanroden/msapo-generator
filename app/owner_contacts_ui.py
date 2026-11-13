"""Owner screen for saved contacts and PO history (#21).

Rendered inside the purchase page's About section, and only when
``app.owner_access.owner_access_configured()`` is true. Everything below the
unlock box is shown only after the server-side passcode was entered in this
browser session.
"""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from app.memory import (
    contracts_with_saved_contacts,
    correct_vendor_contact,
    delete_vendor_contact,
    po_history,
    saved_vendor_contacts,
)
from app.owner_access import check_owner_passcode, locked_out, owner_access_configured

UNLOCKED_KEY = "owner_contacts_unlocked"


def _when(ts: float) -> str:
    if not ts:
        return "unknown"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def render_owner_contacts() -> None:
    if not owner_access_configured():
        return
    st.markdown("**Owner: saved contacts and PO history**")
    if not st.session_state.get(UNLOCKED_KEY):
        if locked_out():
            st.caption("Too many wrong tries. Try again later.")
            return
        passcode = st.text_input("Owner passcode", type="password", key="owner_passcode_input")
        if st.button("Unlock", key="owner_unlock"):
            if check_owner_passcode(passcode):
                st.session_state[UNLOCKED_KEY] = True
                st.session_state.pop("owner_passcode_input", None)
                st.rerun()
            else:
                st.error("That passcode is not right.")
        return

    if st.button("Lock", key="owner_lock"):
        st.session_state.pop(UNLOCKED_KEY, None)
        st.rerun()

    contracts = contracts_with_saved_contacts()
    if not contracts:
        st.caption("Nothing saved yet.")
        return
    contract = st.selectbox("Account", contracts, key="owner_contract")

    st.markdown("Saved vendor contacts (removed two years after last use)")
    contacts = saved_vendor_contacts(contract)
    if not contacts:
        st.caption("No saved vendor contacts for this account.")
    for index, row in enumerate(contacts):
        st.write(
            f"{row['vendor']}: {row['name']} <{row['email']}> "
            f"(used {row['count']}x, last {_when(row['last_used'])})"
        )
        cols = st.columns(3)
        new_name = cols[0].text_input("Name", value=row["name"], key=f"owner_name_{index}")
        new_email = cols[1].text_input("Email", value=row["email"], key=f"owner_email_{index}")
        if cols[2].button("Save", key=f"owner_save_{index}"):
            if correct_vendor_contact(contract, row["vendor"], row["name"], row["email"],
                                      new_name=new_name, new_email=new_email):
                st.rerun()
            else:
                st.error("Could not save that change. Check the name and email.")
        if cols[2].button("Delete", key=f"owner_delete_{index}"):
            delete_vendor_contact(contract, row["vendor"], row["name"], row["email"])
            st.rerun()

    st.markdown("PO history")
    history = po_history(contract)
    if not history:
        st.caption("No PO history for this account yet.")
    else:
        st.table([
            {"Date": _when(h["recorded_at"]), "Vendor": h["vendor"],
             "Total": h["total"], "Quote file": h["quote_filename"]}
            for h in history
        ])
