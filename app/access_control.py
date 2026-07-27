"""Minimal access gate for the internal Streamlit application.

This is an interim control for a small internal user group. It is intentionally
fail-closed: the application does not render unless EPC_ACCESS_PASSWORD is set
and the current browser session supplies the matching value.

A shared password is not a substitute for ENFRA SSO, per-user authorization,
or an audit trail. Replace this module when an approved identity provider is
available.
"""

from __future__ import annotations

import hmac
import os

import streamlit as st

_PASSWORD_ENV = "EPC_ACCESS_PASSWORD"
_SESSION_KEY = "epc_authenticated"
_FAILURE_KEY = "epc_failed_logins"


def configured_password() -> str | None:
    """Return the configured shared password, or None when it is absent."""
    password = os.getenv(_PASSWORD_ENV)
    return password if password else None


def password_matches(submitted: str, expected: str) -> bool:
    """Compare credentials without a normal short-circuiting string comparison."""
    return hmac.compare_digest(
        submitted.encode("utf-8"),
        expected.encode("utf-8"),
    )


def require_access() -> None:
    """Stop the Streamlit page until the browser session is authenticated."""
    expected = configured_password()
    if expected is None:
        st.error(
            "Access control is not configured. Set EPC_ACCESS_PASSWORD in the "
            "Render service before using this deployment."
        )
        st.stop()

    if st.session_state.get(_SESSION_KEY):
        with st.sidebar:
            if st.button("Sign out", key="epc_sign_out"):
                st.session_state.pop(_SESSION_KEY, None)
                st.session_state.pop(_FAILURE_KEY, None)
                st.rerun()
        return

    st.markdown("## Email Process Control")
    st.caption("Enter the internal access password to continue.")
    submitted = st.text_input(
        "Access password",
        type="password",
        key="epc_access_password_input",
    )

    if st.button("Continue", type="primary", key="epc_access_submit"):
        if password_matches(submitted, expected):
            st.session_state[_SESSION_KEY] = True
            st.session_state.pop(_FAILURE_KEY, None)
            st.rerun()

        failures = int(st.session_state.get(_FAILURE_KEY, 0)) + 1
        st.session_state[_FAILURE_KEY] = failures
        st.error("That password was not accepted.")
        if failures >= 5:
            st.caption(
                "Several unsuccessful attempts were recorded in this browser "
                "session. Close the tab and contact the application owner if needed."
            )

    st.stop()
