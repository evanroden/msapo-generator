"""Section-local evidence routing without copying or reclassifying saved sources."""

from dataclasses import dataclass, replace
import re

from app import monthly_report_sources as sources
from app.monthly_report_page_reference import page_identity


SECTION_UPLOADS = {
    "vendor_reports": ("Supporting service reports", "Service report files"),
    "improvements": ("Activity service reports and photos", "Activity service report files"),
    "water_reports": ("Water-treatment reports", "Water-treatment files"),
    "mbcx_report": ("System performance reports", "MBCx report files"),
    "utility_analysis": ("Monthly Scorecards", "Scorecard files"),
}
CLASSIFICATION_DESTINATIONS = {
    "Vendor service": "improvements", "Water treatment": "water_reports",
    "MBCx": "mbcx_report", "Utility results": "utility_analysis",
    "Improvement / training photo": "improvements",
}

SOURCE_ROUTE_PREFIX = "section-source-route:v1:"


def source_route(reference):
    """Read routing metadata, never an image inclusion or evidence approval."""
    if not reference.startswith(SOURCE_ROUTE_PREFIX):
        return None
    parts = reference[len(SOURCE_ROUTE_PREFIX):].split(":")
    if (len(parts) != 3 or parts[0] not in SECTION_UPLOADS
            or any(re.fullmatch(r"[0-9a-f]{64}", part) is None for part in parts[1:])):
        return None
    return tuple(parts)


def included_pages(blocks):
    """Retain ownership even when a section is temporarily omitted."""
    result = {}
    for key, block in blocks.items():
        if key not in sources.PAGE_DESTINATIONS or not block.asset_hashes:
            continue
        # Narrative evidence may retain a removed page's reference. Only
        # provenance on an actually included image establishes page ownership.
        from app.monthly_report_asset_review import asset_context
        for index in range(len(block.asset_hashes)):
            for reference in asset_context(block, index):
                identity = page_identity(reference)
                if identity:
                    result.setdefault(identity, set()).add(key)
    return result


def source_destinations(contents, bindings, blocks):
    """Actual draft pages take precedence over session routing and suggestions."""
    owners = {}
    for (source_id, _), destinations in included_pages(blocks).items():
        owners.setdefault(source_id, set()).update(destinations)
    for content in contents:
        identity = content.source.id
        if identity not in owners:
            retained = {key for key, block in blocks.items() for reference in block.references
                        if source_route(reference) == (key, identity, content.source.sha256)}
            slot = bindings.get(identity) or CLASSIFICATION_DESTINATIONS.get(content.source.classification)
            owners[identity] = retained or ({slot} if slot else set())
    return owners


def section_contents(contents, destination, bindings, blocks):
    if destination not in SECTION_UPLOADS:
        raise ValueError("Unknown report section for uploaded pages.")
    owners = source_destinations(contents, bindings, blocks)
    return tuple(c for c in contents if destination in owners[c.source.id])


def pending_pages(contents, destination, blocks):
    """Only new page identities can be appended by a section-local upload."""
    owners = included_pages(blocks)
    result = []
    for content in contents:
        for number in content.source.selected_pages:
            if number in sources.image_numbers(content) and (content.source.id, number) not in owners:
                result.append((content.source.id, number))
    return tuple(result)



@dataclass(frozen=True)
class AutomaticWaterUpload:
    """One native-text PDF admission decision; not a human visual approval."""

    content: sources.SourceContent
    pages: tuple[int, ...]
    exceptions: tuple[str, ...]


def automatic_water_upload(profile, period, content, blocks):
    """Screen a *new* Water PDF locally, preserving every original page.

    This path deliberately refuses scanned/image-bearing pages because native
    text cannot establish whether a picture contains prices or signatures.
    It does not run OCR/AI, reclassify a file, or revive deliberately removed
    pages. The caller prepares only the returned source/page identities.
    """
    from app.monthly_report_content_policy import (
        contains_price, page_fingerprint, page_status,
    )
    from app.monthly_report_source_details import facility_choice, source_date
    from app.monthly_report_source_scope import reviewed_scope
    from app.monthly_report_model import ReportPeriod

    source = content.source
    if not isinstance(period, ReportPeriod) or source.suffix != ".pdf":
        return AutomaticWaterUpload(content, (), ("Use a Water-treatment PDF for automatic page inclusion.",))
    if source.classification != "Water treatment":
        return AutomaticWaterUpload(content, (), (
            "The file type is not confirmed as Water treatment; use page review to select its destination.",))
    if blocks.get("water_reports") is not None and blocks["water_reports"].source == "Omit":
        return AutomaticWaterUpload(content, (), ("Water treatment is left out of this report; its retained pages were not changed.",))
    when = source_date(source.service_date)
    site = facility_choice(source, profile)
    allowed_sites = {facility.key for facility in profile.facilities}
    if (when is None or (when.year, when.month) != (period.year, period.month)
            or site not in allowed_sites
            or source.scope_review and reviewed_scope(source, profile) is None):
        return AutomaticWaterUpload(content, (), (
            "Confirm the PDF's exact source date and site for this report before including its pages.",))

    from app.monthly_report_sources import source_bytes
    import pymupdf as fitz
    try:
        original = source_bytes(profile, source)
        pdf = fitz.open(stream=original, filetype="pdf")
    except (OSError, ValueError, RuntimeError) as exc:
        return AutomaticWaterUpload(content, (), ("Unable to inspect the saved PDF: " + str(exc),))
    permitted, exceptions = [], []
    try:
        if pdf.page_count != len(source.page_texts):
            return AutomaticWaterUpload(content, (), (
                "The saved PDF page count changed; re-upload it before selecting report pages.",))
        owned = included_pages(blocks)
        exact_names = {" ".join(name.casefold().split()) for facility in profile.facilities
                       for name in (facility.key, facility.title, *facility.aliases)}
        for number, page in enumerate(pdf, 1):
            text = source.page_texts[number - 1]
            label = f"Page {number}: "
            if (source.id, number) in owned:
                continue
            if dict(source.client_page_exclusions).get(number) == page_fingerprint(source, number):
                continue
            kind, reason = page_status(text, unreadable=number in source.needs_vision)
            caption = dict(source.captions).get(
                number, f"{source.filename} · page/item {number}")
            if kind != "technical" or contains_price(caption):
                exceptions.append(label + ("Caption may contain pricing." if contains_price(caption) else reason))
                continue
            if number not in source.selected_pages:
                exceptions.append(label + "Not selected for this report.")
                continue
            # Explicit per-page facility/date labels win over a first-page
            # file-level suggestion. Unknown/foreign labels are not auto-routed.
            sites = re.findall(r"(?im)^[ \t]*(?:facility|site|building)[ \t]*[:=][ \t]*([^\r\n]{1,160})", text)
            if any(" ".join(value.casefold().split()) not in exact_names for value in sites):
                exceptions.append(label + "Site does not match the report; review this page.")
                continue
            dates = re.findall(r"(?im)^[ \t]*(?:date|service date|report date|completed date)[ \t]*[:=][ \t]*([^\r\n]{1,120})", text)
            from app.monthly_report_sources import _date
            if any(not _date(value) or _date(value)[:7] != period.key for value in dates):
                exceptions.append(label + "Date does not match the report month; review this page.")
                continue
            # Images, scanned overlays, annotations and interactive form fields
            # can conceal pricing that native text extraction cannot see.
            if (page.get_image_info() or next(page.annots() or (), None) is not None
                    or next(page.widgets() or (), None) is not None):
                exceptions.append(label + "Image or annotation needs visual review; not automatically included.")
                continue
            permitted.append(number)
    finally:
        pdf.close()
    if not permitted:
        return AutomaticWaterUpload(content, (), tuple(exceptions))
    reviews = dict(source.client_page_reviews)
    for number in permitted:
        reviews[number] = page_fingerprint(source, number)
    notice = ("Automatic native-text screen included eligible Water pages; "
              "it did not visually approve image content. Review the attached pages before final export.")
    updated = replace(source, client_page_reviews=tuple(sorted(reviews.items())),
                      notices=tuple(dict.fromkeys((*source.notices, notice))))
    return AutomaticWaterUpload(replace(content, source=updated), tuple(permitted), tuple(exceptions))


MAX_PREPARED_IMAGE_BYTES = 60 * 1024 * 1024


@dataclass(frozen=True)
class WholePdfPreflight:
    """Read-only capacity for including every *remaining* page of one PDF."""

    new_pages: int
    already_included: int
    available_pages: int
    remaining_bytes: int | None = None
    new_image_bytes: int | None = None
    measured_all: bool = False

    @property
    def pages_fit(self):
        return self.new_pages <= self.available_pages

    @property
    def images_fit(self):
        if self.new_image_bytes is None:
            return None
        return (self.measured_all and self.new_image_bytes <= self.remaining_bytes)


def preflight_whole_pdf(profile, content, destination, blocks, assets=None, *,
                        measure_bytes=False):
    """Check a complete PDF before page-by-page approval.

    Does not approve images, change source selection, or insert report assets.
    Counting always checks all PDF pages rather than just auto-suggested pages.
    Exact prepared-image size is optional because print rasterization can be
    expensive; stop counting as soon as an over-budget outcome is proven.
    """
    if destination not in SECTION_UPLOADS or content.source.suffix != ".pdf":
        raise ValueError("Select a PDF and its report section to check whole-document capacity.")
    owners = included_pages(blocks)
    source_id = content.source.id
    if any(identity == source_id and any(slot != destination for slot in slots)
           for (identity, _), slots in owners.items()):
        raise ValueError("This PDF already has pages in another section. Review it there; no pages were added.")
    images = sources.image_numbers(content)
    incoming = tuple(n for n in images if (source_id, n) not in owners)
    existing = sum(len(block.asset_hashes) for key, block in blocks.items()
                   if key in sources.PAGE_DESTINATIONS)
    capacity = WholePdfPreflight(
        new_pages=len(incoming),
        already_included=len(images) - len(incoming),
        available_pages=max(0, sources.MAX_EMBED_PAGES - existing),
    )
    if not measure_bytes or not capacity.pages_fit:
        return capacity
    from app import monthly_report_library as library
    assets = {} if assets is None else assets
    used = sum(len(assets[ref] if ref in assets else library.read_asset(
        profile.contract, profile.key, ref))
        for key, block in blocks.items() if key in sources.PAGE_DESTINATIONS
        for ref in block.asset_hashes)
    remaining = max(0, MAX_PREPARED_IMAGE_BYTES - used)
    total, measured = 0, 0
    for page in incoming:
        total += len(sources.page_image(profile, content, page).data)
        measured += 1
        if total > remaining:
            break
    return replace(capacity, remaining_bytes=remaining, new_image_bytes=total,
                   measured_all=measured == len(incoming))


def prepare_section_pages(profile, contents, destination, blocks, assets=None, *,
                          only_pages=None):
    """Validate selected source/page additions; never mutate the draft.

    The optional subset permits only pages selected in the *current* explicit
    review interaction, even if other formerly selected pages have since been
    removed from this report. Their original source record stays unchanged.
    """
    if destination not in SECTION_UPLOADS:
        raise ValueError("Unknown report section for uploaded pages.")
    owners = included_pages(blocks)
    for content in contents:
        elsewhere = {slot for (identity, _), slots in owners.items()
                     if identity == content.source.id for slot in slots if slot != destination}
        if elsewhere:
            raise ValueError(f"{content.source.filename} already has pages in another section. Use its existing section to update it; no duplicate pages were added.")
    pending = set(pending_pages(contents, destination, blocks))
    if only_pages is not None:
        requested = set(only_pages)
        if not requested or not requested.issubset(pending):
            raise ValueError(
                "The reviewed page selection changed. Reopen that page and choose Include again.")
        pending = requested
    if not pending:
        return {}
    existing_count = sum(len(block.asset_hashes) for key, block in blocks.items()
                         if key in sources.PAGE_DESTINATIONS)
    if existing_count + len(pending) > sources.MAX_EMBED_PAGES:
        raise ValueError("Embedding limit is 150 selected image/PDF pages per report. Remove pages before adding more.")
    destinations = tuple((c.source.id, destination) for c in contents
                         if any(identity == c.source.id for identity, _ in pending))
    # A default Add is append-only, just like an explicit page selection.
    # Do not re-rasterize or recheck pages already included in this report.
    prepared = sources.prepare_pages(
        profile, contents, destinations, only_pages=frozenset(pending))
    result = {}
    for block in prepared:
        indexes = tuple(n for n, reference in enumerate(block.references) if page_identity(reference) in pending)
        if not indexes:
            continue
        updates = dict(asset_hashes=tuple(block.asset_hashes[n] for n in indexes),
                       asset_captions=tuple(block.asset_captions[n] for n in indexes),
                       references=tuple(block.references[n] for n in indexes),
                       client_reviewed_fingerprint="")
        kept, references = set(updates["asset_hashes"]), set(updates["references"])
        updates["asset_provenance"] = tuple((asset, tuple(r for r in refs if r in references))
                                            for asset, refs in block.asset_provenance if asset in kept)
        filtered = replace(block, **updates)
        from app.monthly_report_asset_instances import reindex_asset_instances, with_asset_instances
        filtered = with_asset_instances(filtered, reindex_asset_instances(block, indexes))
        # Every returned page has passed the existing page-level review policy.
        from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
        filtered = refresh_asset_source_context(filtered, tuple(c.source for c in contents))
        filtered = approve_all_assets(filtered)
        result[block.key] = filtered
    from app import monthly_report_library as library
    assets = assets or {}
    total_bytes = 0
    for block in (*blocks.values(), *result.values()):
        if block.key in sources.PAGE_DESTINATIONS:
            for reference in block.asset_hashes:
                data = assets[reference] if reference in assets else library.read_asset(profile.contract, profile.key, reference)
                total_bytes += len(data)
                if total_bytes > 60 * 1024 * 1024:
                    raise ValueError("Prepared images exceed 60 MB for this report. Remove pages before adding more.")
    return result
