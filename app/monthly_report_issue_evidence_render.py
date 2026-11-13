"""Render deliberately selected, occurrence-bound issue evidence pages.

Issue references are links, not page approval. They never change the source's
whole-document inclusion decisions, saved report blocks or original bytes.
"""
from io import BytesIO
import re

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
    # Imported issue-register tables provide provenance links, not explicit
    # approval to print their original PDF page as raster evidence. The
    # tables themselves are stripped from the review draft, so canonical_issues
    # carries their page references as "issue-table:<reference>" markers on
    # the equipment_issues block; read those alongside any tables still present.
    from app.monthly_report_issues import ISSUE_TABLE_PROVENANCE_PREFIX
    table_provenance = {table.reference for block in draft.blocks
                        for table in block.extra_tables if table.reference}
    table_provenance |= {ref[len(ISSUE_TABLE_PROVENANCE_PREFIX):]
                         for block in draft.blocks if block.key == "equipment_issues"
                         for ref in block.references
                         if ref.startswith(ISSUE_TABLE_PROVENANCE_PREFIX)}
    already_rendered = {
        ref for block in draft.blocks
        if block.key in active_blocks and block.source != "Omit"
        for index in range(len(block.asset_hashes))
        for ref in asset_context(block, index)
    }
    chosen = []
    owners = {}
    caption_metrics = None
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
            # Non-raster links are citations (including existing TXT/CSV links),
            # not source-page artwork. Never decode or print them as pictures.
            if source.suffix != ".pdf" and source.suffix not in sources.ocr.SUPPORTED_IMAGE_SUFFIXES:
                continue
            # Legacy register imports cite the originating table page before
            # any image review. Do not turn a table citation into image consent.
            # Explicit page links outside table provenance still fail closed.
            if (reference in table_provenance
                    and number not in dict(source.client_page_reviews)):
                continue
            previous = owners.get(reference)
            if previous is not None and previous != issue.key:
                raise ValueError(
                    f"Page {number} of {source.filename} is linked to multiple issues. "
                    "Keep one issue owner or use independently reviewed evidence.")
            owners[reference] = issue.key
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
            label = f"{source.filename} · page {number}" + (" — " + caption if caption else "")
            if re.search(r"[\x00-\x08\x0e-\x1b\x1f\ud800-\udfff\ufffe\uffff]", label):
                raise ValueError(
                    f"Remove unsupported characters from the caption or filename of {source.filename} page {number}.")
            if caption_metrics is None:
                from app.monthly_report_visuals import wrapped, font, _measure
                caption_metrics = (_measure(), font(28))
            from app.monthly_report_visuals import wrapped
            draw, face = caption_metrics
            if sum(max(1, len(wrapped(line, face, 1000, draw)))
                   for line in label.split("\n")) > 3:
                raise ValueError(
                    f"Shorten the caption for {source.filename} page {number} to at most three lines before generating.")
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
        original_key = (source.sha256, source.suffix)
        if original_key not in authenticated:
            # page_image may return a cached derivative without reopening its
            # source. Always authenticate the saved original before emission.
            try:
                sources.source_bytes(draft.profile, source)
            except (OSError, ValueError) as exc:
                raise ValueError(
                    f"Issue evidence source {source.filename} is unavailable or changed. "
                    "Restore the exact original in Manage source files.") from exc
            authenticated.add(original_key)
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
        try:
            with Image.open(BytesIO(picture.data)) as image:
                if image.width * image.height > _MAX_PIXELS_PER_FRAME:
                    raise ValueError("Issue evidence page image exceeds the pixel limit.")
                scale = min(6.8 / image.width, 7.2 / image.height)
                photo.add_run().add_picture(BytesIO(picture.data),
                    width=Inches(image.width * scale), height=Inches(image.height * scale))
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError(
                f"Issue evidence artwork for {source.filename} page {number} is invalid or too large. "
                "Restore the original or review the page in Manage source files.") from exc
        caption = dict(source.captions).get(number, "")
        label = f"{source.filename} · page {number}"
        paragraph(label + (" — " + caption if caption else ""), caption=True)
        output.append((issue.key, reference))
    return tuple(output)
