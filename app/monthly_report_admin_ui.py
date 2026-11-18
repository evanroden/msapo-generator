"""Separate Monthly administration routes; navigation carries no report data."""
from functools import lru_cache
from urllib.parse import urlencode

import streamlit as st

ADMIN_KINDS = ("directory", "logos", "storage", "master")


def report_url():
    """Normal Monthly route in the same supported live/test mode."""
    query = {"workflow": "monthly"}
    mode = st.query_params.get("monthly_qa")
    if mode in {"isolated", "fixtures", "logo-recovery"}:
        query["monthly_qa"] = mode
    return "?" + urlencode(query)


def admin_url(kind="directory"):
    """Only public route selectors enter the URL, never a report identity."""
    if kind not in ADMIN_KINDS:
        raise ValueError("Choose directory, logos, storage or master administration.")
    return report_url() + "&" + urlencode({"monthly_admin": kind})


# 1024px includes portrait tablets. The native opener stays outside stSidebar.
# Hiding the closed *container* (not merely translating or fading its content)
# removes the otherwise transparent overlay from hit-testing and keyboard focus.
MOBILE_SIDEBAR_CSS = """<style>
[data-testid="stSidebar"][aria-expanded="false"] {
    display: none !important;
    pointer-events: none !important;
}
@media (max-width: 1024px) {
    .st-key-monthly_sidebar_administration { display: none !important; }
}
@media (min-width: 1025px) {
    .st-key-monthly_inline_administration { display: none !important; }
}
</style>"""

_MOBILE_SIDEBAR_JS = r"""
export default function(component) {
    const media = window.matchMedia('(max-width: 1024px)');
    // The component rerenders with the editor. Remember the initial viewport
    // only within this document, not in a saved report or a browser cookie.
    const state = window.__epcMobileSidebar || (window.__epcMobileSidebar = {
        initialized: false, narrow: false, pending: false
    });
    if (!state.initialized) {
        state.initialized = true;
        state.narrow = media.matches;
        state.pending = media.matches;
    }
    let frame = null;
    let disposed = false;
    const collapseIfNeeded = () => {
        frame = null;
        if (disposed || !state.pending || !media.matches) return;
        const sidebar = document.querySelector('[data-testid="stSidebar"]');
        if (!sidebar || !sidebar.hasAttribute('aria-expanded')) return;
        if (sidebar.getAttribute('aria-expanded') === 'false') {
            state.pending = false;
            return;
        }
        // Use the actual Streamlit control, retaining the framework's state;
        // never manipulate React attributes or a report input directly.
        const button = sidebar.querySelector(
            '[data-testid="stSidebarCollapseButton"] button');
        if (!button) return;
        state.pending = false;
        button.click();
    };
    const schedule = () => {
        if (!disposed && state.pending && frame === null)
            frame = requestAnimationFrame(collapseIfNeeded);
    };
    const resized = () => {
        const narrow = media.matches;
        if (narrow && !state.narrow) state.pending = true;
        if (!narrow) state.pending = false;
        state.narrow = narrow;
        schedule();
    };
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, {
        subtree: true, childList: true, attributes: true,
        attributeFilter: ['aria-expanded']
    });
    media.addEventListener('change', resized);
    window.addEventListener('resize', resized);
    resized();
    schedule();
    return () => {
        disposed = true;
        observer.disconnect();
        media.removeEventListener('change', resized);
        window.removeEventListener('resize', resized);
        if (frame !== null) cancelAnimationFrame(frame);
    };
}
"""


@lru_cache(maxsize=2)
def _mobile_sidebar_controller(runtime):
    return st.components.v2.component(
        "enfra_monthly_mobile_sidebar", js=_MOBILE_SIDEBAR_JS,
        isolate_styles=False)


def _links(place):
    st.caption("Opens separately; your report tab stays available.")
    for kind, label in (("directory", "Contract and site directory"),
                        ("logos", "Shared contract logos"),
                        ("storage", "Storage maintenance"),
                        ("master", "Master design administration")):
        # Different stable widget keys ensure each responsive surface owns its
        # own native link, even though CSS renders just one surface at a time.
        st.link_button(label, admin_url(kind), on_click="ignore",
                       key=f"monthly_admin_{place}_{kind}")


def render_administration_links():
    """The same scoped routes, visible in-page on narrow screens only."""
    from streamlit.runtime import Runtime
    st.html(MOBILE_SIDEBAR_CSS)
    _mobile_sidebar_controller(Runtime.instance())(
        key="monthly_mobile_sidebar_controller", data={}, height=1, width="stretch")
    with st.sidebar:
        with st.container(key="monthly_sidebar_administration"):
            with st.expander("Administration", expanded=False):
                _links("sidebar")
    with st.container(key="monthly_inline_administration"):
        with st.expander("Administration", expanded=False):
            _links("inline")


def render_administration(kind, field, *, mode):
    from html import escape
    from app.monthly_report_testing import scope
    if mode not in {"live", "isolated", "fixtures", "logo-recovery"} or (mode == "live") != (scope() is None):
        raise ValueError("Monthly administration could not verify its storage context; no records were used.")
    if mode == "isolated":
        st.warning("ISOLATED SYNTHETIC TESTING — not a client report. No live report, contact, capacity, logo or design records are accessible here.")
    elif mode == "fixtures":
        st.warning("ISOLATED SHARED-FIXTURE TESTING — not a client report. No live report, contact, capacity, logo or design records are accessible here.")
        st.caption("Changes affect this browser's fixture workspace. Shared uploaded originals stay unchanged.")
    elif mode == "logo-recovery":
        from app.monthly_report_logo_recovery_sample import render_banner
        render_banner()
    st.markdown('<a href="' + escape(report_url(), quote=True) + '" target="_self">Back to Monthly reports</a>', unsafe_allow_html=True)
    if kind not in ADMIN_KINDS:
        st.error("Choose a Monthly administration page.")
        return
    links = []
    for choice, label in (("directory", "Directory"), ("logos", "Logos"), ("storage", "Storage"), ("master", "Master design")):
        if choice == kind:
            links.append(escape(label))
        else:
            links.append('<a href="' + escape(admin_url(choice), quote=True) + '" target="_self">' + label + '</a>')
    st.markdown(" · ".join(links), unsafe_allow_html=True)
    if kind == "directory":
        if mode == "isolated":
            from app.monthly_report_directory_recovery_sample import render_sample
            render_sample()
        from app.monthly_report_directory_ui import render_directory
        render_directory(field)
    elif kind == "logos":
        if mode == "isolated":
            st.link_button("Open separate logo recovery sample", "?workflow=monthly&monthly_qa=logo-recovery&monthly_admin=logos", on_click="ignore")
        elif mode == "logo-recovery":
            from app.monthly_report_logo_recovery_sample import render_sample
            render_sample()
        from app.monthly_report_branding_ui import render_branding
        render_branding(field)
    elif kind == "storage":
        st.subheader("Storage maintenance — all contracts")
        render_storage_maintenance()
    else:
        from app.monthly_report_designs_ui import render_design_settings
        st.subheader("Master design administration — all contracts")
        actor = st.text_input("Design editor name", key=field("report_admin_master_actor", ""), max_chars=160)
        st.caption("Your name attributes master changes; it is not a sign-in.")
        render_design_settings(actor, "report_admin_master")


def render_storage_maintenance():
    """Administrative tools kept out of ordinary monthly authoring."""
    if st.button("Check available storage", key="report_storage_check"):
        from app.monthly_report_directory_retention import expire_quietly
        from app.monthly_report_storage import storage_summary
        try:
            expire_quietly(force=True)  # apply the 30-day directory workbook retention now
            st.session_state["report_storage_summary"] = storage_summary()
        except OSError:
            st.session_state.pop("report_storage_summary", None)
            st.warning("Storage could not be measured right now. Your saved reports were not changed.")
    if storage := st.session_state.get("report_storage_summary"):
        from app.monthly_report_storage import readable_bytes
        st.write(f"Disk capacity: {readable_bytes(storage['total'])} · Available: {readable_bytes(storage['free'])} · Monthly report files: {'at least ' if not storage['complete'] else ''}{readable_bytes(storage['monthly'])}")
        st.caption("Measured when you click Check available storage. The disk is also used by other app workflows. Report originals are retained; contact-directory workbooks are deleted 30 days after their latest import. Identical new assets and source files share one stored copy across all contracts and sites. Monthly history keeps references, so changing one site's selection does not change another report. Existing files can be consolidated below.")
        if storage["free"] < max(512 * 1024 * 1024, storage["total"] * .05):
            st.warning("Storage is running low. Keep space available before importing more large reports. This check deletes only contact-directory workbooks past their 30-day retention.")
    if st.button("Consolidate duplicate stored files", key="report_storage_consolidate"):
        from app.monthly_report_objects import consolidate_existing
        from app.monthly_report_storage import storage_summary, readable_bytes
        try:
            with st.spinner("Sharing identical stored files; originals and history remain available…"):
                result = consolidate_existing()
            st.session_state["report_storage_summary"] = storage_summary()
            st.success(f"Consolidated {result['changed']} files; released {readable_bytes(result['reclaimed'])} from duplicate copies.")
            if not result["complete"]:
                st.info("This batch is complete. Run consolidation again to continue through the remaining files.")
        except (ValueError, OSError):
            st.warning("Consolidation stopped. Original paths and report history remain available; completed files can safely be reused when you retry.")
