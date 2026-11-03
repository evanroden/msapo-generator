"""Current output receipts and targeted retries, separate from draft recovery."""
from hashlib import sha256

import streamlit as st


def package_identity(package):
    return (package.fingerprint, sha256(package.docx).hexdigest())


def record_shared_save(prefix, package, *, saved=None, error=""):
    st.session_state[prefix + "_package_save"] = {
        "identity": package_identity(package), "revision": saved.revision if saved else None,
        "saved_at": saved.generated_at if saved else "", "error": error,
        "base_revision": st.session_state.get(prefix + "_revision"),
    }


def render_output_status(package, draft, snapshot, prefix):
    """Return whether this exact package still needs a shared-version save."""
    status = st.session_state.get(prefix + "_package_save")
    if not status or status["identity"] != package_identity(package):
        status = None
    # The snapshot was read before generation. Prefer the exact package's
    # successful receipt so that an older identical draft cannot relabel it.
    revision = status["revision"] if status else None
    # A genuinely later matching checkpoint can still establish shared save.
    # After a failed/pending attempt, the old base snapshot is not evidence
    # that this attempt succeeded; keep its warning and retry available.
    baseline = status.get("base_revision") if status else None
    if revision is not None:
        baseline = revision
    if (snapshot and snapshot.draft.fingerprint == draft.fingerprint
            and (status is None or (baseline is not None and snapshot.revision > baseline))):
        revision = snapshot.revision
    st.success("Word and PDF ready to download" if package.pdf else "Word ready to download")
    if notice := getattr(package, "contents_notice", ""):
        st.warning(notice)
    if revision is not None:
        st.caption(f"[Shared version {revision}](#shared-report-history) · {draft.period.label}")
        return False
    error = status["error"] if status else ""
    st.warning("Shared save failed: " + error if error else "Shared save not confirmed.")
    st.caption("Retry saving below. Files remain available; this won\'t regenerate them.")
    return True


def queue_retry(prefix, kind, identity, scope, revision):
    st.session_state[prefix + "_pending_output_" + kind] = (identity, scope, revision)


def take_retries(prefix):
    # Consume even when a delivered native edit retires the old package. A
    # stale action cannot sit pending until an older draft is opened again.
    return {kind: st.session_state.pop(prefix + "_pending_output_" + kind, None)
            for kind in ("save", "pdf")}


def matches_retry(request, package, scope, revision):
    return request == (package_identity(package), scope, revision)


# The finished bytes exist only in the current browser session. Shared report
# history persists a draft, not an immutable PDF, so this viewer must never
# imply that a saved revision can be reopened or silently regenerated.
MAX_INLINE_FINAL_PDF_BYTES = 25 * 1024 * 1024


def _final_pdf_scope(prefix: str, session_scope: str) -> str:
    """Bind disposable page tickets to the active browser/report incarnation."""
    if not isinstance(prefix, str) or not prefix or not isinstance(session_scope, str) or not session_scope:
        raise ValueError("The finished PDF preview needs a current report session.")
    return "monthly-finished-pdf:" + sha256((prefix + "\x00" + session_scope).encode()).hexdigest()


def discard_current_session_pdf_preview(prefix: str, session_scope: str) -> None:
    """Retire only this generated PDF's disposable cache on a draft reset."""
    from app.reference_preview import discard_reference_scope
    discard_reference_scope(_final_pdf_scope(prefix, session_scope))



def replace_current_session_pdf_package(prefix: str, session_scope: str, package) -> None:
    """Retire the previous PDF before a newly generated/retried package takes over.

    A retained preview fragment otherwise remains authorized by its old ticket
    even if new generation for the *same draft* returned no usable PDF.
    """
    previous = st.session_state.get(prefix + "_package")
    if (previous is not None and previous is not package
            and getattr(previous, "generated_contents", False) and getattr(package, "generated_contents", False)
            and previous.fingerprint == package.fingerprint and package.pdf
            and previous.docx != package.docx):
        from app.monthly_report_contents_pagination import only_generated_cache_changed
        status = st.session_state.get(prefix + "_package_save")
        if (status and status["identity"] == package_identity(previous)
                and only_generated_cache_changed(previous.docx, package.docx)):
            # PDF retry fills only verified Word page-number caches. Preserve
            # the existing save receipt/error for the otherwise identical work.
            st.session_state[prefix + "_package_save"] = {
                **status, "identity": package_identity(package),
            }
    if previous is not package:
        discard_current_session_pdf_preview(prefix, session_scope)
    st.session_state[prefix + "_package"] = package


def render_current_session_pdf_preview(package, draft, prefix: str, *, session_scope: str) -> None:
    """Inspect the exact current package, never a saved draft or another session.

    The common bounded source viewer rasterizes only visible pages behind a
    private, expiring ticket. It creates no PDF endpoint, save or regeneration.
    """
    if (package is None or st.session_state.get(prefix + "_package") is not package
            or package.fingerprint != draft.fingerprint or not package.pdf):
        return
    with st.expander("View PDF here (this session)", expanded=False,
                     key=prefix + "_finished_pdf_view"):
        st.caption("Only this generated PDF is available here. Shared version history stores "
                   "the report draft, not finished PDF files. This view does not certify Word layout.")
        if (type(package.pdf) is not bytes or not package.pdf.startswith(b"%PDF-")
                or len(package.pdf) > MAX_INLINE_FINAL_PDF_BYTES):
            st.info("In-site PDF preview unavailable. Download PDF remains available.")
            return
        from app.reference_preview import render_reference
        render_reference(key="finished_report_pdf",
                         owner_scope=_final_pdf_scope(prefix, session_scope),
                         title="Finished report PDF", raw=package.pdf,
                         filename=package.pdf_name or "report.pdf")
