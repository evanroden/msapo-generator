"""Hidden synthetic QA controls for the existing ordered Monthly Report editor."""
from __future__ import annotations

import streamlit as st

from app import monthly_report_library as library
from app import monthly_report_qa_fixture as fixture
from app import monthly_report_testing as testing
from app.monthly_report_editor import _key, _signature


def _select_fixture():
    st.session_state["report_contract"] = fixture.CONTRACT
    st.session_state["report_change_contract"] = False
    st.session_state["report_month_number"] = fixture.PERIOD.month
    st.session_state["report_year"] = fixture.PERIOD.year
    prefix = "report_sites_" + _key(fixture.CONTRACT)
    for facility in fixture.profile().facilities:
        st.session_state[prefix + "_" + facility.key] = True
    # New real-report visitors enter their own name. QA, unlike a real report,
    # has a verified invented author baked into its known-value fixture. Seed
    # this editor widget only on explicit fixture load; never reinstate a name
    # that the tester deliberately edits or clears on a later rerun.
    editor_prefix = "report_guided_" + _signature((
        fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
    st.session_state[editor_prefix + "_prepared"] = fixture.ACTOR


def _working_report(saved):
    profile = fixture.profile()
    prefix = "report_guided_" + _signature((fixture.CONTRACT, profile.key, fixture.PERIOD.key))
    draft = st.session_state.get(prefix + "_draft", saved.draft)
    if ((draft.profile.contract, draft.profile.key, draft.period) !=
            (fixture.CONTRACT, profile.key, fixture.PERIOD)):
        raise ValueError("The current QA editor does not match this isolated fixture.")
    return draft


def _queue_generation_request():
    """Keep a received QA click through unrelated preview/editor reruns."""
    st.session_state["monthly_qa_generate_queued"] = True


def _active_jobs() -> bool:
    for key, entry in st.session_state.items():
        if key.endswith("_ai_job") and isinstance(entry, dict):
            future = entry.get("future")
            if future is not None and not future.done():
                return True
        if key.endswith("_ordered_previews") and isinstance(entry, dict):
            running = entry.get("running")
            if running is not None and not running[2].done():
                return True
    return False


def _clear_report_widgets():
    # Never let a QA widget, in-memory PDF, or old viewport flow into a real
    # report when the browser switches workflow modes.
    for key in tuple(st.session_state):
        if key.startswith(("report_", "report_guided_", "monthly_qa_")):
            del st.session_state[key]


def render(browser_token: str, browser_timezone: str, field, move, live_storage_root):
    if testing.scope() is None:
        raise ValueError("Testing controls require a server-side isolated context.")
    st.warning("ISOLATED SYNTHETIC TESTING — not a client report. No live report, contact, capacity, logo or design records are accessible here.")
    st.caption("Choose one route below. Known-value prefill checks report editing and generation; original-source replay separately exercises file extraction and placement. Both use the existing report engine.")
    a, b, c = st.columns(3)
    chosen = None
    if a.button("Load known-value report", key="monthly_qa_prefill"):
        chosen = "prefill"
    if b.button("Replay synthetic source files", key="monthly_qa_replay"):
        chosen = "replay"
    if c.button("Reset this test only", key="monthly_qa_reset"):
        if _active_jobs():
            st.error("A test preview or document-reading job is still running. Finish or cancel it before resetting this test.")
        else:
            try:
                testing.reset(live_storage_root)
                from app.monthly_report_preview_store import STORE
                STORE.reset_scope()
            except (ValueError, OSError) as exc:
                st.error("Test reset was stopped: " + str(exc))
            else:
                _clear_report_widgets()
                st.success("Only this isolated synthetic test's data was reset.")
                st.rerun()
    if chosen:
        try:
            fixture.prepare(chosen)
        except (ValueError, OSError) as exc:
            st.error("Isolated fixture could not be installed: " + str(exc))
        else:
            _clear_report_widgets()
            _select_fixture()
            st.session_state["monthly_qa_loaded"] = chosen
            st.rerun()
    saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    if saved:
        # A fresh browser session has no widget state. Keep the same QA
        # fixture's contract, site set and month across refresh/reconnect;
        # otherwise the real editor silently opens this calendar month while
        # the testing header still describes the September fixture.
        # setdefault honors any deliberate selection already in this session.
        st.session_state.setdefault("report_contract", fixture.CONTRACT)
        st.session_state.setdefault("report_month_number", fixture.PERIOD.month)
        st.session_state.setdefault("report_year", fixture.PERIOD.year)
        site_prefix = "report_sites_" + _key(fixture.CONTRACT)
        for site in fixture.profile().facilities:
            st.session_state.setdefault(site_prefix + "_" + site.key, True)
        st.caption("Current fixture: " + ("original-source replay" if saved.draft.sources else "known-value prefill") +
                   " · September 2026 · two invented sites · synthetic only")
        x, y = st.columns(2)
        compare_pressed = x.button("Compare fixture facts", key="monthly_qa_compare")
        y.button("Generate QA Word and PDF", key="monthly_qa_generate",
                 on_click=_queue_generation_request)
        if st.session_state.get("monthly_qa_generate_queued"):
            st.caption("QA generation request received; preparing this exact test report.")
        # Allocate this near the toolbar; resolve content after the editor finalizes.
        result_surface = st.container()
        st.divider()
        st.caption("Edit the loaded synthetic report below; its journals and history remain in this test namespace.")
        from app.monthly_report_guided import render_guided_workflow
        render_guided_workflow(browser_token, browser_timezone, field, move)
        working = _working_report(saved)
        with result_surface:
            if compare_pressed:
                result = fixture.compare(working)
                checks = result["checks"]
                st.session_state["monthly_qa_comparison"] = {
                    "mode": result["mode"], "checks": checks,
                    "fingerprint": working.fingerprint,
                    "matched": sum(bool(v) for v in checks.values()),
                }
            if st.session_state.get("monthly_qa_generate_queued"):
                # A callback receipt persists the user's request even when a
                # section preview/editor rerun happens between the click and
                # this last, fully finalized guided draft. Do not clear until
                # generation finishes or fails with an actionable error.
                from app.monthly_report_docx import generate_report
                try:
                    with st.spinner("Generating isolated Word and PDF files…"):
                        package = generate_report(
                            working, acknowledged_fingerprint=working.fingerprint)
                except (ValueError, OSError) as exc:
                    st.session_state.pop("monthly_qa_generate_queued", None)
                    st.error("QA export was blocked: " + str(exc))
                else:
                    st.session_state["monthly_qa_package"] = (working.fingerprint, package)
                    st.session_state.pop("monthly_qa_generate_queued", None)
            if state := st.session_state.get("monthly_qa_comparison"):
                if state.get("fingerprint") != working.fingerprint:
                    st.info("Previous comparison is outdated. Run Compare fixture facts again after editing.")
                else:
                    st.write(f"{state['mode']}: {state['matched']}/{len(state['checks'])} independent content/provenance checks.")
                    for name, passed in state["checks"].items():
                        st.write(("PASS — " if passed else "CHECK — ") + name)
            retained = st.session_state.get("monthly_qa_package")
            if retained and retained[0] != working.fingerprint:
                st.info("The previous QA export is outdated. Generate again to include your latest edits.")
            if retained and retained[0] == working.fingerprint:
                package = retained[1]
                st.download_button("Download isolated QA DOCX", package.docx,
                                   file_name="SYNTHETIC-QA-only.docx", key="monthly_qa_docx",
                                   on_click="ignore")
                if package.pdf:
                    st.download_button("Download isolated QA PDF", package.pdf,
                                       file_name="SYNTHETIC-QA-only.pdf", key="monthly_qa_pdf",
                                       on_click="ignore")
                if package.pdf_error:
                    st.warning(package.pdf_error)
        # The real browser must not reload a just-edited report until its
        # specific Activity contents have reached the durable recovery journal.
        # Expose only a one-way digest of INVENTED test text inside this
        # already isolated QA namespace, never any real report data. An absent
        # journal provides no acknowledgment and must not pass the browser test.
        from hashlib import sha256
        from app.monthly_report_active_work import load as load_active
        try:
            active = load_active(browser_token, fixture.CONTRACT,
                                 fixture.profile().key, fixture.PERIOD)
        except (library.LibraryError, OSError):
            st.warning("The isolated QA recovery journal could not be verified.")
        else:
            if active:
                activity = next((b.text for b in active.draft.blocks
                                 if b.key == "activity_summary"), "")
                st.caption("QA durable Activity SHA256: " +
                           sha256(activity.encode("utf-8")).hexdigest())
    else:
        st.info("Choose known-value prefill or source replay to populate this isolated test.")
