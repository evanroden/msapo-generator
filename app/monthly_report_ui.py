"""Real-report entry point. Synthetic report builders are test fixtures only."""

from datetime import date

import streamlit as st

from app.monthly_report_recovery import load_active_draft, save_active_draft

MONTHLY_REPORT_WORKFLOW = "Monthly report"


def preserve_report_draft_state() -> None:
    """Mirror registered operator fields and persist active work when possible."""
    mirror = dict(st.session_state.get("report_draft_mirror", {}))
    for key in st.session_state.get("report_widget_keys", ()):
        if key in st.session_state:
            value = st.session_state[key]
            if isinstance(value, (str, bool, int, float, date, tuple, list)):
                mirror[key] = value
    st.session_state["report_draft_mirror"] = mirror

    context = st.session_state.get("monthly_recovery_context")
    if isinstance(context, dict):
        save_active_draft(
            context.get("browser_token", ""),
            context.get("account_key", ""),
            context.get("report_key", ""),
            mirror,
        )


def restore_report_draft_state() -> None:
    for key, value in st.session_state.get("report_draft_mirror", {}).items():
        st.session_state.setdefault(key, value)

    context = st.session_state.get("monthly_recovery_context")
    if isinstance(context, dict) and not st.session_state.get("report_draft_mirror"):
        recovered = load_active_draft(
            context.get("browser_token", ""),
            context.get("account_key", ""),
            context.get("report_key", ""),
        )
        if recovered:
            st.session_state["report_draft_mirror"] = recovered
            for key, value in recovered.items():
                st.session_state.setdefault(key, value)
            st.session_state["monthly_recovery_status"] = "Recovered saved active work."


def _field(key: str, default):
    registered = set(st.session_state.get("report_widget_keys", ()))
    registered.add(key)
    st.session_state["report_widget_keys"] = tuple(sorted(registered))
    st.session_state.setdefault(key, default)
    return key


def _move(order_key: str, section_key: str, offset: int) -> None:
    order = list(st.session_state[order_key])
    index = order.index(section_key)
    target = index + offset
    if 0 <= target < len(order):
        order[index], order[target] = order[target], order[index]
        st.session_state[order_key] = order
    preserve_report_draft_state()


def render_monthly_report_workflow(browser_token: str, browser_timezone: str = "") -> None:
    st.session_state.setdefault(
        "monthly_recovery_context",
        {
            "browser_token": browser_token,
            "account_key": st.session_state.get("report_account_key", ""),
            "report_key": st.session_state.get("report_key", "active"),
        },
    )
    restore_report_draft_state()
    st.title("Monthly report")
    from app.monthly_report_guided import render_guided_workflow
    try:
        render_guided_workflow(browser_token, browser_timezone, _field, _move)
    except (ValueError, OSError) as exc:
        st.error(f"The report could not be loaded: {exc}. Your saved versions were not changed.")
    preserve_report_draft_state()
