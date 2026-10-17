"""Conservative display facts for the ordinary source-file manager.

This is a display decision, not an import, review, save or export gate. Optional
references stay available without a routine warning; specific problems remain
actionable. Only current included image pages can earn resolved status.
Originals receive only a bounded stat; their bytes are still verified by the
existing readers and output paths.
"""

from collections import defaultdict
from dataclasses import dataclass
import stat

from app import monthly_report_sources as sources
from app import monthly_report_testing as testing
from app.monthly_report_asset_review import asset_context, pending_asset_indexes
from app.monthly_report_content_policy import contains_price, page_allowed, page_fingerprint
from app.monthly_report_model import used_block_keys
from app.monthly_report_page_controls import included_page_caption
from app.monthly_report_section_uploads import (
    CLASSIFICATION_DESTINATIONS, page_identity,
)
from app.monthly_report_source_details import (
    KEEP_FACILITY, facility_choice, source_date,
)


@dataclass(frozen=True)
class SourceManagerStatus:
    source_id: str
    filename: str
    resolved: bool
    reason: str
    pages: int
    destinations: tuple[str, ...]
    needs_correction: bool = True


def source_manager_status(draft, contents, *, unavailable=(), pending=False):
    """Describe only fully reviewed, currently included image-page sources.

    Text, spreadsheets, reference-only files and retained-but-omitted pages
    retain their existing management route. References in narrative alone do
    not establish that a page image is attached. No record is changed here.
    """
    contents = tuple(contents)
    available = defaultdict(list)
    current = defaultdict(list)
    for content in contents:
        available[content.source.id].append(content)
    for source in draft.sources:
        current[source.id].append(source)
    missing = {source.id for source in unavailable}

    owners = defaultdict(list)
    active_keys = used_block_keys(draft)
    blocks = tuple(block for block in draft.blocks
                   if block.key in active_keys and block.source != "Omit"
                   and block.key in sources.PAGE_DESTINATIONS)
    for block_number, block in enumerate(blocks):
        for index in range(len(block.asset_hashes)):
            context = asset_context(block, index)
            pairs = {pair for reference in context
                     if (pair := page_identity(reference)) is not None}
            for pair in pairs:
                owners[pair].append((block_number, block, index, context, pairs))
    unreviewed = {}

    def attached_page(source, number):
        matches = owners.get((source.id, number), ())
        if len(matches) != 1:
            return None, "Review the selected page’s report inclusion." if not matches else "Resolve duplicate or ambiguous attached pages."
        block_number, block, index, context, pairs = matches[0]
        if pairs != {(source.id, number)}:
            return None, "Resolve ambiguous attached-page provenance."
        # A full-source reference is intentionally checked conservatively.
        # Its stable page identity alone cannot establish current source facts.
        expected_reference = sources.source_reference(source, number)
        page_references = tuple(reference for reference in context
                                if page_identity(reference) is not None)
        if (not page_references
                or any(reference != expected_reference for reference in page_references)):
            return None, "Review the attached page against the current source details."
        if any(page_identity(reference) is None
               and not reference.startswith("asset-source-context:v1:")
               for reference in context):
            return None, "Resolve ambiguous attached-page provenance."
        caption = block.asset_captions[index] if index < len(block.asset_captions) else ""
        if contains_price(caption):
            return None, "Remove pricing from the attached page caption."
        if caption != included_page_caption(block, source, number):
            return None, "Use the current source caption on the attached page."
        if block_number not in unreviewed:
            unreviewed[block_number] = set(pending_asset_indexes(block, draft.sources))
        if index in unreviewed[block_number]:
            return None, "Review the new or changed attached page."
        return block.key, ""

    def status(source, content):
        selected = tuple(source.selected_pages)
        attached, destinations = [], set()
        for number in set(selected):
            destination, _ = attached_page(source, number)
            if destination:
                attached.append(number)
                destinations.add(destination)

        def result(reason="", *, needs_correction=True):
            return SourceManagerStatus(source.id, source.filename, not reason, reason,
                                       len(attached), tuple(sorted(destinations)),
                                       bool(reason) and needs_correction)

        if pending:
            return result("Finish adding the current file selection to the report.")
        if source.id in missing or content is None:
            return result("Restore the original source file.")
        if len(available[source.id]) != 1 or len(current[source.id]) != 1:
            return result("Resolve the current source identity.")
        if source != current[source.id][0]:
            return result("Use the current source details before closing review.")
        # Resolving the generic library path can initialize a new QA namespace.
        # Display never establishes a lease or creates storage as a side effect.
        if testing.scope() is not None and testing.generation() is None:
            return result("Restore the original source file in the current test workspace.")
        try:
            original = sources._path(draft.profile, source.sha256, source.suffix).stat()
            limit = 128 * 1024 * 1024 if source.suffix == ".docx" else sources.MAX_FILE_BYTES
            if not stat.S_ISREG(original.st_mode) or not 0 < original.st_size <= limit:
                return result("Restore the original source file within its size limit.")
        except (ValueError, OSError):
            return result("Restore the original source file.")
        if source.notices:
            return result("Resolve the source reading notices.")
        if source.classification not in CLASSIFICATION_DESTINATIONS:
            return result("Review this file's use in the report.", needs_correction=False)
        numbers = tuple(sources.image_numbers(content))
        if (content.tables or not numbers
                or set(numbers) != set(range(1, len(source.page_texts) + 1))
                or len(numbers) != len(set(numbers))):
            return result("Review the extracted text or spreadsheet content.", needs_correction=False)
        when = source_date(source.service_date)
        if when is None or not draft.period.start <= when <= draft.period.end:
            return result("Check the source reporting date.")
        if facility_choice(source, draft.profile) in ("", KEEP_FACILITY):
            return result("Check the source facility.")
        if (not selected or len(selected) != len(set(selected))
                or any(type(number) is not int or number not in numbers for number in selected)):
            return result("Review which pages belong in the report.")
        exclusions = dict(source.client_page_exclusions)
        for number in numbers:
            if number in selected:
                if number in exclusions or not page_allowed(source, number):
                    return result("Review the selected page and its caption.")
                _, reason = attached_page(source, number)
                if reason:
                    return result(reason)
            elif (exclusions.get(number) != page_fingerprint(source, number)
                  or owners.get((source.id, number))):
                return result("Decide whether to include or leave out each page.")
        return result()

    entries, seen = [], set()
    for content in contents:
        if content.source.id not in seen:
            entries.append(status(content.source, content))
            seen.add(content.source.id)
    for source in draft.sources:
        if source.id not in seen:
            entries.append(status(source, None))
            seen.add(source.id)
    return tuple(entries)
