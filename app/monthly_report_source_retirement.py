"""Retire accepted intake from report fallbacks without deleting human work."""

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
        from app.monthly_report_asset_instances import (asset_instances, source_page_identity,
                                                        valid_instances, with_asset_instances)
        from app.monthly_report_asset_review import asset_context, preserve_asset_reviews
        current_instances = asset_instances(block)
        accepted_instances = asset_instances(contribution)
        remove = []
        legacy_matched, legacy_unmatched = set(), False
        for n, accepted in enumerate(accepted_instances):
            if valid_instances(contribution) and not accepted.key.startswith("legacy:"):
                matches = [index for index, item in enumerate(current_instances)
                           if index not in remove and item.key == accepted.key
                           and item.asset == accepted.asset
                           and source_page_identity(item) == source_page_identity(accepted)
                           and source_page_identity(item) is not None]
            else:
                # An old snapshot has no occurrence ID. Its exact accepted
                # caption and source/page must identify one candidate. Ambiguous
                # equal-byte neighbours stay intact instead of deleting a guess.
                caption = contribution.asset_captions[n] if n < len(contribution.asset_captions) else ""
                matches = [index for index, item in enumerate(current_instances)
                           if index not in remove and item.key.startswith("legacy:")
                           and item.asset == accepted.asset
                           and owned.intersection(asset_context(block, index))
                           and (block.asset_captions[index] if index < len(block.asset_captions) else "") == caption]
                if len(matches) == 1:
                    legacy_matched.add(accepted.asset)
                else:
                    legacy_unmatched = True
            if len(matches) == 1:
                remove.append(matches[0])
        if legacy_matched and not legacy_unmatched:
            # Every old occurrence this receipt owned was identified. Equal-byte
            # neighbours share only the old hash-level link, so they become
            # independent of this source, as after an explicit choice; one
            # receipt never asks for a second removal.
            block = preserve_asset_reviews(block, with_asset_instances(block, tuple(
                _detached(item, owned, (block.key, contribution.fingerprint, item.key))
                if (index not in remove and item.key.startswith("legacy:") and item.asset in legacy_matched
                    and owned.intersection(asset_context(block, index))) else item
                for index, item in enumerate(current_instances))))
        # Accepted order can differ from the current report-picture order.
        # Remove highest current positions first so earlier removals cannot
        # shift a later owned occurrence onto an independent neighbour.
        for index in sorted(set(remove), reverse=True):
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


def _retirement_page_key(reference):
    """Identify a source/page for detachment only; never authorize a review."""
    if not isinstance(reference, str):
        return None
    parts = reference.split(":")
    if (len(parts) != 3 or not parts[0] or not parts[2] or not 1 <= len(parts[1]) <= 6
            or not parts[1].isascii() or not parts[1].isdecimal()):
        return None
    # Historical page references may have a leading zero; never parse an
    # unbounded integer or mistake a malformed token for page ownership.
    number = parts[1].lstrip("0")
    return (parts[0], number) if number else None


def _detached(item, owned, token=None):
    """Detach only an accepted source/page; retain unrelated page evidence."""
    from app.monthly_report_asset_instances import new_asset_instance
    context_prefix = "asset-source-context:v1:"
    owned_pages = {_retirement_page_key(ref) for ref in owned}
    owned_pages.discard(None)
    references = tuple(ref for ref in item.references
        if ref not in owned and not (ref.startswith(context_prefix)
                                    and _retirement_page_key(ref[len(context_prefix):]) in owned_pages))
    if token is None:
        return new_asset_instance(item.asset, references)
    # Retirement reruns on every render; the same receipt yields the same record.
    from hashlib import sha256
    import json
    from app.monthly_report_model import AssetInstance
    key = "detached:" + sha256(json.dumps(token, ensure_ascii=False).encode()).hexdigest()
    return AssetInstance(key, item.asset, tuple(sorted(set(references))))


def record_retired_contributions(retired, accepted, replacement):
    """Return report-scoped receipts for destinations omitted by a new batch."""
    updated = dict(retired)
    for key, block in accepted.items():
        if key not in replacement:
            prior = updated.get(key, ())
            if block not in prior:
                updated[key] = (*prior, block)
    return updated


def retirement_pending(block, contribution):
    """Retain an ambiguous legacy receipt until a person identifies its page."""
    if block is None or block.key != contribution.key:
        return False
    if block.source == "Omit":
        return True
    if retire_contributions(block, (contribution,)) != block:
        return True
    from app.monthly_report_asset_instances import valid_instances
    if valid_instances(contribution) and all(not item.key.startswith("legacy:")
                                            for item in contribution.asset_instances):
        return False
    return bool(legacy_retirement_candidates(block, contribution))


def legacy_retirement_candidates(block, contribution):
    """Ambiguous old ownership needs an explicit occurrence selection."""
    from app.monthly_report_asset_instances import asset_instances
    from app.monthly_report_asset_review import asset_context
    owned = set(contribution.references)
    return tuple(index for index, item in enumerate(asset_instances(block))
                 if item.key.startswith("legacy:") and item.asset in contribution.asset_hashes
                 and owned.intersection(asset_context(block, index)))


def resolve_legacy_retirement(block, contribution, index):
    """Use an explicit owner's choice without assigning old hash ownership again.

    The operator identifies the old imported occurrence. Other matching legacy
    occurrences become independent of this removal, retaining any other source
    links. Their changed provenance requires its normal picture review.
    """
    from app.monthly_report_asset_instances import asset_instances, with_asset_instances
    from app.monthly_report_asset_review import preserve_asset_reviews
    candidates = legacy_retirement_candidates(block, contribution)
    if index not in candidates or block.source == "Omit":
        raise ValueError("This old source-page removal changed. Reopen the current pictures before choosing one.")
    owned = set(contribution.references)
    instances = asset_instances(block)
    updated = with_asset_instances(block, tuple(
        _detached(item, owned) if n in candidates and n != index else item
        for n, item in enumerate(instances)))
    updated = remove_saved_picture(updated, index)
    native_content = bool(updated.text.strip() or updated.rows or updated.extra_tables
                          or updated.ai_paragraphs or updated.org_nodes)
    if not native_content:
        retained = {ref for item in updated.asset_instances for ref in item.references}
        updated = replace(updated, references=tuple(ref for ref in updated.references if ref not in owned or ref in retained))
    return preserve_asset_reviews(block, updated)


def acknowledge_retired_contributions(current, applied, saved, draft, expected_revision):
    """Retire only receipts actually represented by this successful exact save.

    Preparing a replacement or creating output is not persistence. A failed
    save, a different report/version, a retained omitted block, and any receipt
    queued after this draft was assembled remain pending for recovery.
    """
    if saved.revision != expected_revision + 1 or saved.draft != draft:
        return dict(current)
    blocks = {block.key: block for block in saved.draft.blocks}
    remaining = {}
    for key, receipts in current.items():
        block = blocks.get(key)
        pending = tuple(receipt for receipt in receipts
                        if receipt not in applied.get(key, ())
                        or retirement_pending(block, receipt))
        if pending:
            remaining[key] = pending
    return remaining
