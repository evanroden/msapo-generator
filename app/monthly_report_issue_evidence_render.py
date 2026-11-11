"""Render deliberately selected, occurrence-bound issue evidence pages.

Issue references are links, not page approval. They never change the source's
whole-document inclusion decisions, saved report blocks or original bytes.
"""
from io import BytesIO

from docx.shared import Inches, Pt
from PIL import Image

from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_allowed
from app.monthly_report_page_reference import page_identity
from app.ocr import _MAX_PIXELS_PER_FRAME

MAX_ISSUE_EVIDENCE_PAGES = 150
MAX_ISSUE_EVIDENCE_IMAGE_BYTES = 60 * 1024 * 1024


def selected_issue_pages(draft):
    """Return (issue, source, page, reference) in saved issue/selection order.

    Never match by the displayed filename, page number alone or raster bytes.
    An old page link cannot silently move onto a replacement or second file.
    """
    valid = {}
    ids = set()
    for source in draft.sources:
        if source.id in ids:
            raise ValueError("Duplicate issue source identities. Reopen Manage source files.")
        ids.add(source.id)
        for number in range(1, len(source.page_texts) + 1):
            valid[sources.source_reference(source, number)] = (source, number)
    # An explicit page exclusion is not undone by merely citing that page
    # on an issue card. Nor may this emitter duplicate an already emitted
    # source-owned page from an included report picture block.
    from app.monthly_report_asset_review import asset_context
    from app.monthly_report_model import used_block_keys
    active_blocks = used_block_keys(draft)
    already_rendered = {
        ref for block in draft.blocks
        if block.key in active_blocks and block.source != "Omit"
        for index in range(len(block.asset_hashes))
        for ref in asset_context(block, index)
    }
    chosen = []
    for issue in draft.follow_ups:
        if issue.category != "issue" or not issue.included:
            continue
        seen = set()
        for reference in issue.references:
            if reference in seen:
                continue  # One occurrence cannot print twice under one issue.
            seen.add(reference)
            pair = valid.get(reference)
            if pair is None:
                identity = page_identity(reference)
                if identity is not None and identity[0] not in ("docx",):
                    raise ValueError("An issue evidence source or page changed. Reopen the issue and remove or reselect the unavailable page.")
                if any(reference.startswith(source_id + ":") for source_id in ids):
                    raise ValueError("An issue evidence page link changed. Reopen the issue and select its current source page.")
                continue  # Other legacy narrative/Word source references.
            source, number = pair
            if source.suffix != ".pdf" and source.suffix not in sources.ocr.SUPPORTED_IMAGE_SUFFIXES:
                raise ValueError(f"Page {number} of {source.filename} is not a raster source page. Review its original in Manage source files.")
            caption = dict(source.captions).get(number, "")
            from app.monthly_report_content_policy import page_fingerprint
            if dict(source.client_page_exclusions).get(number) == page_fingerprint(source, number):
                raise ValueError(
                    f"Page {number} of {source.filename} was explicitly excluded. "
                    "Review the page decision in Manage source files before adding it to an issue.")
            if reference in already_rendered:
                raise ValueError(
                    f"Page {number} of {source.filename} is already emitted as a separate report page. "
                    "Remove that occurrence from Report pages before attaching it to an issue.")
            if not page_allowed(source, number, profile=draft.profile,
                                destination="equipment_issues", output_captions=(caption,)):
                raise ValueError(
                    f"Review page {number} of {source.filename} in Manage source files before emitting issue evidence. "
                    "Pricing, legal, signature, blank and unreviewed pages cannot be included.")
            chosen.append((issue, source, number, reference))
            if len(chosen) > MAX_ISSUE_EVIDENCE_PAGES:
                raise ValueError("Issue evidence exceeds 150 selected pages. Remove some selections.")
    return tuple(chosen)


def append_issue_evidence(document, draft, *, before=None):
    """Add reviewed pages exactly once after issue prose, in source-link order.

    The optional native section anchor keeps evidence inside Issues, without
    touching Water/MBCx/Scorecards or rewriting an existing document block.
    """
    planned = selected_issue_pages(draft)
    if not planned:
        return ()
    if before is not None and before.getparent() is None:
        raise ValueError("The native Issues section changed. Reopen the report design before rendering evidence.")

    def paragraph(text="", *, page_break=False, caption=False):
        p = document.add_paragraph(text)
        if before is not None:
            before.addprevious(p._p)
        p.paragraph_format.page_break_before = page_break
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0 if not caption else 5)
        if caption:
            for run in p.runs:
                run.font.size = Pt(10)
        return p

    current_issue = None
    output = []
    total = 0
    authenticated = set()
    for issue, source, number, reference in planned:
        if source.sha256 not in authenticated:
            # page_image may return a cached derivative without reopening its
            # source. Always authenticate the saved original before emission.
            try:
                sources.source_bytes(draft.profile, source)
            except (OSError, ValueError) as exc:
                raise ValueError(
                    f"Issue evidence source {source.filename} is unavailable or changed. "
                    "Restore the exact original in Manage source files.") from exc
            authenticated.add(source.sha256)
        # A missing/truncated original is a generation refusal, not an omitted
        # evidence page. page_image authenticates original SHA before decoding.
        try:
            picture = sources.page_image(draft.profile, sources.SourceContent(source), number)
        except (ValueError, OSError, IndexError, RuntimeError) as exc:
            raise ValueError(
                f"Issue evidence page {number} of {source.filename} is unavailable. "
                "Restore the exact original or remove this link in the issue editor.") from exc
        total += len(picture.data)
        if total > MAX_ISSUE_EVIDENCE_IMAGE_BYTES:
            raise ValueError("Issue evidence images exceed 60 MB. Reduce the selected pages.")
        if issue.key != current_issue:
            current_issue = issue.key
            paragraph("Evidence for issue: " + issue.text[:180], page_break=True)
            separate = False
        else:
            separate = True
        photo = paragraph(page_break=separate)
        with Image.open(BytesIO(picture.data)) as image:
            if image.width * image.height > _MAX_PIXELS_PER_FRAME:
                raise ValueError("Issue evidence page image exceeds the pixel limit.")
            scale = min(6.8 / image.width, 7.2 / image.height)
            photo.add_run().add_picture(BytesIO(picture.data),
                width=Inches(image.width * scale), height=Inches(image.height * scale))
        caption = dict(source.captions).get(number, "")
        label = f"{source.filename} · page {number}"
        paragraph(label + (" — " + caption if caption else ""), caption=True)
        output.append((issue.key, reference))
    return tuple(output)
