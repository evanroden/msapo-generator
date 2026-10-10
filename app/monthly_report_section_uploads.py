"""Section-local evidence routing without copying or reclassifying saved sources."""

from dataclasses import replace

from app import monthly_report_sources as sources


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


def page_identity(reference):
    """Read the stable source/page identity, independent of mutable source facts."""
    parts = reference.split(":")
    return (parts[0], int(parts[1])) if len(parts) == 3 and parts[1].isdigit() else None


def included_pages(blocks):
    """Retain ownership even when a section is temporarily omitted."""
    result = {}
    for key, block in blocks.items():
        if key not in sources.PAGE_DESTINATIONS or not block.asset_hashes:
            continue
        for reference in block.references:
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
            slot = bindings.get(identity) or CLASSIFICATION_DESTINATIONS.get(content.source.classification)
            owners[identity] = {slot} if slot else set()
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


def prepare_section_pages(profile, contents, destination, blocks, assets=None):
    """Validate a complete addition before returning it; never mutate the draft."""
    if destination not in SECTION_UPLOADS:
        raise ValueError("Unknown report section for uploaded pages.")
    owners = included_pages(blocks)
    for content in contents:
        elsewhere = {slot for (identity, _), slots in owners.items()
                     if identity == content.source.id for slot in slots if slot != destination}
        if elsewhere:
            raise ValueError(f"{content.source.filename} already has pages in another section. Use its existing section to update it; no duplicate pages were added.")
    pending = set(pending_pages(contents, destination, blocks))
    if not pending:
        return {}
    existing_count = sum(len(block.asset_hashes) for key, block in blocks.items()
                         if key in sources.PAGE_DESTINATIONS)
    if existing_count + len(pending) > sources.MAX_EMBED_PAGES:
        raise ValueError("Embedding limit is 150 selected image/PDF pages per report. Remove pages before adding more.")
    destinations = tuple((c.source.id, destination) for c in contents
                         if any(identity == c.source.id for identity, _ in pending))
    prepared = sources.prepare_pages(profile, contents, destinations)
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
