"""Retire accepted intake from report fallbacks without deleting human work."""

from collections import Counter
from dataclasses import replace

from app.monthly_report_saved_pictures_ui import remove_saved_picture


def retire_contributions(block, contributions):
    """Detach only the identified pages or unchanged source-owned table rows.

    Equal prose is never proof of ownership. Picture provenance and the actual
    accepted batch identify pages; an unlinked image with equal bytes stays.
    Explicit omission preserves all retained content for deliberate recovery.
    Originals and historical snapshots are not modified.
    """
    if block is None or block.source == "Omit":
        return block
    for contribution in contributions:
        if contribution.key != block.key:
            continue
        owned = set(contribution.references)
        remaining = Counter(contribution.asset_hashes)
        contexts = dict(block.asset_provenance)
        remove = []
        for index, reference in enumerate(block.asset_hashes):
            context = set(contexts.get(reference, ()))
            # Imported pages have explicit source/page provenance. Do not infer
            # it from coincidentally equal human images or surrounding text.
            if remaining[reference] and owned.intersection(context):
                remove.append(index)
                remaining[reference] -= 1
        for index in reversed(remove):
            block = remove_saved_picture(block, index)
        # The detailed editor replaces a mapped table as one source-owned set.
        # Manual table entry drops these source references; changed/populated
        # independent rows therefore survive even when their text is equal.
        if (contribution.rows and block.rows == contribution.rows
                and owned and set(block.references) == owned):
            block = replace(block, rows=(), reviewed_fingerprint="")
        tables = tuple(table for table in block.extra_tables if not any(
            original.reference and table.reference == original.reference and table == original
            for original in contribution.extra_tables))
        if tables != block.extra_tables:
            block = replace(block, extra_tables=tables, reviewed_fingerprint="")
    return block


def record_retired_contributions(retired, accepted, replacement):
    """Return report-scoped receipts for destinations omitted by a new batch."""
    updated = dict(retired)
    for key in replacement:
        updated.pop(key, None)
    for key, block in accepted.items():
        if key not in replacement:
            prior = updated.get(key, ())
            if block not in prior:
                updated[key] = (*prior, block)
    return updated
