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
    "utility_analysis": ("Utility results and charts", "Utility result files"),
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
    prepared = sources.prepare_pages(
        profile, contents, destinations,
        only_pages=frozenset(pending) if only_pages is not None else None)
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
