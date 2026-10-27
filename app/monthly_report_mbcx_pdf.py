"""Explicit whole-PDF inclusion using the existing source/page policy."""

from dataclasses import replace
import hashlib

from app.monthly_report_content_policy import contains_price, page_fingerprint, page_status
from app.monthly_report_section_uploads import included_pages, prepare_section_pages
from app import monthly_report_sources as sources


def _captions(source):
    saved = dict(source.captions)
    return tuple((number, saved.get(number, f"{source.filename} · page/item {number}"))
                 for number in range(1, len(source.page_texts) + 1))


def whole_pdf_pages(content, blocks):
    """Return a fresh complete selection, or explain why it cannot be added.

    This shortcut never restores a previous page decision or partial selection.
    Existing individual-page controls remain authoritative for those files.
    """
    source = content.source
    if source.suffix != ".pdf" or not source.page_texts:
        raise ValueError("Choose a PDF containing report pages.")
    block = blocks.get("mbcx_report")
    if block is not None and block.source == "Omit":
        raise ValueError("MBCx pages are left out. Include the section before adding a PDF.")
    pages = tuple(range(1, len(source.page_texts) + 1))
    owners = included_pages(blocks)
    owned = {number: owners.get((source.id, number), set()) for number in pages}
    if any(destinations - {"mbcx_report"} for destinations in owned.values()):
        raise ValueError("This PDF already has pages in another section. Use its existing section to change them.")
    if all("mbcx_report" in destinations for destinations in owned.values()):
        return ()
    if (any(owned.values()) or source.client_page_reviews or source.client_page_exclusions):
        raise ValueError("This PDF has saved page decisions. Use Review individual pages to keep or change that selection.")
    for number, caption in _captions(source):
        kind, reason = page_status(source.page_texts[number - 1], unreadable=number in source.needs_vision)
        if kind in {"pricing", "legal", "blank", "signature"} or contains_price(caption):
            detail = "The page caption contains pricing." if contains_price(caption) else reason
            raise ValueError(f"The complete PDF cannot be added: page {number}. {detail}. Review individual pages to choose a smaller selection.")
    current = sum(len(block.asset_hashes) for key, block in blocks.items()
                  if key in sources.PAGE_DESTINATIONS)
    if current + len(pages) > sources.MAX_EMBED_PAGES:
        raise ValueError(f"This PDF has {len(pages)} pages; this report has room for {max(0, sources.MAX_EMBED_PAGES - current)} more. No pages were added.")
    return pages


def prepare_whole_pdf(profile, content, blocks, assets=None):
    """Called only after explicit whole-document confirmation; failure is atomic."""
    pages = whole_pdf_pages(content, blocks)
    if not pages:
        return content, {}
    source = replace(content.source, selected_pages=pages, captions=_captions(content.source))
    source = replace(source, client_page_reviews=tuple(
        (number, page_fingerprint(source, number)) for number in pages))
    revised = replace(content, source=source)
    additions = prepare_section_pages(profile, (revised,), "mbcx_report", blocks, assets,
                                     only_pages=frozenset((source.id, n) for n in pages))
    if len(additions["mbcx_report"].asset_hashes) != len(pages):
        raise ValueError("The complete PDF could not be prepared. No report pages were changed.")
    return revised, additions


def render_whole_pdf(profile, content, blocks, assets, prefix, editor_prefix, field, *, period):
    """None selects the existing individual-page workflow; otherwise one batch."""
    import streamlit as st
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_upload_ui import render_source_details

    source = content.source
    key = prefix + "_" + source.id + "_whole_pdf"
    if st.toggle("Review individual pages", key=key + "_individual",
                 help="Use saved page choices, captions or a selection smaller than the full PDF."):
        return None
    source = render_source_details(source, profile, prefix + "_" + source.id, field)
    content = replace(content, source=source)
    problem, pages = "", ()
    try:
        pages = whole_pdf_pages(content, blocks)
        original = sources.source_bytes(profile, source)
    except (ValueError, OSError) as exc:
        problem = str(exc)
    else:
        st.download_button("Download PDF to review", original, file_name=source.filename,
                           mime="application/pdf", key=key + "_download", on_click="ignore")
    if problem:
        st.warning(problem)
    elif not pages:
        st.caption(f"All {len(source.page_texts)} PDF pages are already in MBCx. Existing page reviews still apply.")
    else:
        st.caption(f"Include all {len(pages)} pages in their original order. This confirms you checked the complete PDF and its captions for relevant content with no pricing. A written update is optional.")
    # A native click belongs to this exact report, source and page inventory.
    # A changed source/draft gets a different widget ID, not an old approval.
    stamp = hashlib.sha256(repr((_rich_text_scope(editor_prefix), profile, period,
        source.fingerprint, tuple(sorted((k, b.fingerprint) for k, b in blocks.items())))).encode()).hexdigest()[:24]
    if st.button(f"Include all {len(source.page_texts)} PDF pages", key=key + "_include_" + stamp,
                 disabled=bool(problem) or not pages, type="primary"):
        try:
            with st.spinner("Including the complete PDF…"):
                content, additions = prepare_whole_pdf(profile, content, blocks, assets)
        except (ValueError, OSError) as exc:
            st.error(str(exc))
            st.caption("Your report is unchanged. The PDF remains available to retry or review page by page.")
        else:
            st.session_state[editor_prefix + "_period_editor_refresh"] = True
            return content, additions
    return content, {}
