"""Conservative display facts for the ordinary source-file manager.

This is a display decision, not an import, review, save or export gate. Optional
references stay available without a routine warning; specific problems remain
actionable. Accepted text/table contributions and original-page reviews are
separate tasks; neither approves the other.
Originals receive only a bounded stat; their bytes are still verified by the
existing readers and output paths.
"""

from collections import defaultdict
from dataclasses import dataclass
import stat

from app import monthly_report_sources as sources
from app import monthly_report_testing as testing
from app.monthly_report_asset_review import (asset_context, pending_asset_indexes,
                                             current_source_page_review_matches)
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
    summary: str = ""


def source_manager_status(draft, contents, *, unavailable=(), pending=False):
    """Describe current source tasks without changing their acceptance state.

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
        from app.monthly_report_asset_review import _source_context_marker
        from app.monthly_report_source_scope import reviewed_scope
        # A site-scope decision changes the full source fingerprint without
        # changing reviewed page bytes/caption. Existing targeted provenance
        # proves the relevant current page facts; the asset review below must
        # still match it. A raw page identity alone never supplies that proof.
        current_scoped_page = (reviewed_scope(source, draft.profile) is not None
                               and _source_context_marker(source, number) in context)
        # A genuine caption/page re-review also proves current evidence without
        # inventing a site-scope override. All admission checks below still apply.
        if (len(set(page_references)) != 1
                or any(reference != expected_reference for reference in page_references)
                and not (current_scoped_page or current_source_page_review_matches(block, index, source, number))):
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
        from app.monthly_report_source_readiness import content_readiness
        reading = content_readiness(draft, source)
        summary = (reading.summary if reading.included else "Pages included"
                   if any(identity == source.id for identity, _ in owners) else "Not included")
        selected = tuple(source.selected_pages)
        attached, destinations = [], set(reading.destinations)
        for number in set(selected):
            destination, _ = attached_page(source, number)
            if destination:
                attached.append(number)
                destinations.add(destination)

        def result(reason="", *, needs_correction=True, resolved=None, summary=summary):
            return SourceManagerStatus(source.id, source.filename, not reason if resolved is None else resolved, reason,
                                       len(attached), tuple(sorted(destinations)),
                                       bool(reason) and needs_correction, summary)

        if pending:
            # One unsettled batch is a report-wide task, not a separate
            # missing-details defect in every retained source. Keep resolution
            # blocked until the pending operation actually completes.
            return result("Finish adding the current file selection to the report.",
                          needs_correction=False)
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
        from app.monthly_report_source_readiness import unresolved_reading_notices
        if unresolved_reading_notices(source):
            return result("Resolve the source reading notices.")
        from app.monthly_report_source_scope import included_scope_valid, reviewed_scope
        if reading.included:
            site = facility_choice(source, draft.profile)
            if site == KEEP_FACILITY:
                return result("Check the source facility.")
            if reading.problem:
                return result(reading.problem)
            if (not source.facility or source.scope_review) and not included_scope_valid(draft, source):
                return result("Check the source facility.")
        numbers = tuple(sources.image_numbers(content))
        if not numbers:
            if reading.included:
                # Accepted mapped dates/sites/totals are already bound to this
                # report. Do not invent a second file-level review ritual.
                # Reviewed wording alone does not accept a file date. Match
                # preflight's existing applicability so reference-only and
                # explicitly unselected historical sources stay available.
                if not reading.period_bound and selected and source.classification != "Reference only":
                    when = source_date(source.service_date)
                    if when is None or not draft.period.start <= when <= draft.period.end:
                        return result("Check the source reporting date.")
                # Plain native text is described as included, not reviewed.
                return result(resolved=reading.accepted, needs_correction=False)
            return result(resolved=False, needs_correction=False)
        # Accepted text/tables do not approve the separate image-page use.
        # Sources without image pages already returned above.
        if source.classification not in CLASSIFICATION_DESTINATIONS:
            return result("Review this file's use in the report.", needs_correction=False)
        if (len(numbers) != len(set(numbers))
                or any(type(number) is not int or not 1 <= number <= len(source.page_texts) for number in numbers)):
            return result("Resolve the original-page identities.")
        when = source_date(source.service_date)
        if when is None or not draft.period.start <= when <= draft.period.end:
            return result("Check the source reporting date.")
        if (facility_choice(source, draft.profile) in ("", KEEP_FACILITY)
                or source.scope_review and (reviewed_scope(source, draft.profile) is None
                                           or not included_scope_valid(draft, source))):
            return result("Check the source facility.")
        if ((not selected and not reading.accepted) or len(selected) != len(set(selected))
                or any(type(number) is not int or not 1 <= number <= len(source.page_texts) for number in selected)):
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
        return result(resolved=not reading.included or reading.accepted,
                      summary=(reading.summary + " · Pages reviewed" if reading.included else "Pages reviewed"))

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
