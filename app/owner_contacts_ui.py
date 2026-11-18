"""Owner screen for saved contacts and PO history (#21).

Rendered inside the purchase page's About section. The owner decided on
13 November 2026 to use this screen without a passcode: the app has no sign-in
and the owner is its only user, so anyone who opens the About section can see
and edit these contacts.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from app import config

from app.memory import (
    contracts_with_saved_contacts,
    correct_vendor_contact,
    delete_vendor_contact,
    po_history,
    saved_vendor_contacts,
)


def _when(ts: float, browser_timezone: str | None = None) -> str:
    if not ts:
        return "unknown"
    # Follow config.operator_today: prefer the browser's zone, then EPC_TIMEZONE.
    for zone in (str(browser_timezone or "").strip(), config.EPC_TIMEZONE):
        if not zone:
            continue
        try:
            return datetime.fromtimestamp(ts, ZoneInfo(zone)).strftime("%Y-%m-%d")
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _contact_key(contract: str, row: dict) -> str:
    """Opaque, account-scoped widget identity; no contact details in widget keys."""
    identity = json.dumps(
        [contract, row["vendor"], row["name"], row["email"]], ensure_ascii=False
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def render_owner_contacts() -> None:
    # This screen is already inside About; do not demand a second disclosure
    # click before showing saved contact identities and their native editors.
    st.markdown("**Saved contacts and PO history**")

    contracts = contracts_with_saved_contacts()
    if not contracts:
        st.caption("Nothing saved yet.")
        return
    contract = st.selectbox("Account", contracts, key="owner_contract")
    browser_timezone = st.context.timezone

    st.markdown("Saved vendor contacts (removed two years after last use)")
    contacts = saved_vendor_contacts(contract)
    if not contacts:
        st.caption("No saved vendor contacts for this account.")
    for row in contacts:
        key = _contact_key(contract, row)
        st.text(
            f"{row['vendor']}: {row['name']} <{row['email']}> "
            f"(used {row['count']}x, last {_when(row['last_used'], browser_timezone)})"
        )
        cols = st.columns(3)
        new_name = cols[0].text_input("Name", value=row["name"], key=f"owner_name_{key}")
        new_email = cols[1].text_input("Email", value=row["email"], key=f"owner_email_{key}")
        if cols[2].button("Save", key=f"owner_save_{key}"):
            if correct_vendor_contact(contract, row["vendor"], row["name"], row["email"],
                                      new_name=new_name, new_email=new_email):
                st.rerun()
            else:
                st.error("Could not save that change. Check the name and email.")
        if cols[2].button("Delete", key=f"owner_delete_{key}"):
            delete_vendor_contact(contract, row["vendor"], row["name"], row["email"])
            st.rerun()

    st.markdown("PO history")
    history = po_history(contract)
    if not history:
        st.caption("No PO history for this account yet.")
    else:
        st.table([
            {"Date": _when(h["recorded_at"], browser_timezone), "Vendor": h["vendor"],
             "Total": h["total"], "Quote file": h["quote_filename"]}
            for h in history
        ])
