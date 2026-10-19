"""Occurrence identity layered over immutable, content-addressed picture bytes.

The hash-level map stays readable for older snapshots and broad source audits.
New intake additionally identifies each actual occurrence so equal bytes never
transfer ownership. Only original bytes are shared; captions and removal are not.
"""
from dataclasses import replace
from hashlib import sha256
import json
from uuid import uuid4

from app.monthly_report_model import AssetInstance


def _provenance(instances):
    contexts = {}
    for item in instances:
        contexts[item.asset] = tuple(sorted(set((*contexts.get(item.asset, ()), *item.references))))
    return tuple(contexts.items())


def valid_instances(block):
    items = block.asset_instances
    return (bool(items) and len(items) == len(block.asset_hashes)
            and len({item.key for item in items}) == len(items)
            and all(item.key and item.asset == asset for item, asset in zip(items, block.asset_hashes))
            and dict(_provenance(items)) == dict(block.asset_provenance))


def asset_instances(block):
    """Return exact new records or conservative, deterministic legacy records."""
    if valid_instances(block):
        return block.asset_instances
    from app.monthly_report_asset_review import asset_context
    result = []
    for index, asset in enumerate(block.asset_hashes):
        caption = block.asset_captions[index] if index < len(block.asset_captions) else ""
        references = asset_context(block, index)
        token = (block.key, index, asset, caption, references)
        key = "legacy:" + sha256(json.dumps(token, ensure_ascii=False).encode()).hexdigest()
        result.append(AssetInstance(key, asset, references))
    return tuple(result)


def new_asset_instance(asset, references=(), *, source_caption=None):
    """Allocate only for an explicit new inclusion/upload, never for browsing."""
    return AssetInstance(uuid4().hex, asset, tuple(sorted(set(references))), source_caption)


def has_human_asset(block, asset):
    """An unchanged human upload is idempotent; a source page is independent."""
    # Missing unique page identity can mean ambiguous/multiple source owners.
    # Only explicit unowned context identifies a prior human upload safely.
    return any(item.asset == asset and not item.references
               for item in asset_instances(block))


def append_human_asset(block, asset, caption=""):
    """Append an explicit photo upload without taking another occurrence's origin."""
    if has_human_asset(block, asset):
        return block
    from app.monthly_report_asset_review import preserve_asset_reviews
    captions = tuple(block.asset_captions[index] if index < len(block.asset_captions) else ""
                     for index in range(len(block.asset_hashes)))
    updated = replace(block, source="This month", asset_hashes=(*block.asset_hashes, asset),
                      asset_captions=(*captions, caption), reviewed_fingerprint="",
                      client_reviewed_fingerprint="")
    return preserve_asset_reviews(block, with_asset_instances(updated,
        (*asset_instances(block), new_asset_instance(asset))))


def with_asset_instances(block, instances):
    items = tuple(instances)
    if (len(items) != len(block.asset_hashes)
            or len({item.key for item in items}) != len(items)
            or any(item.asset != asset for item, asset in zip(items, block.asset_hashes))):
        raise ValueError("The picture occurrences changed. Reopen the current pictures before editing them.")
    return replace(block, asset_instances=items, asset_provenance=_provenance(items))


def reindex_asset_instances(block, indexes):
    return tuple(asset_instances(block)[index] for index in indexes)


def reconcile_asset_instances(original, updated):
    """Keep legacy callers safe when their unique image list changes.

    New ordering/removal paths supply exact occurrence records themselves.
    This compatibility path only reuses an unambiguous immutable image match;
    a changed explicit hash-level provenance map remains authoritative.
    """
    if valid_instances(updated):
        return updated
    original_items = asset_instances(original)
    from app.monthly_report_asset_review import asset_context
    indexes = set(range(len(original.asset_hashes)))
    result = []
    changed_provenance = dict(updated.asset_provenance) != dict(original.asset_provenance)
    for index, asset in enumerate(updated.asset_hashes):
        caption = updated.asset_captions[index] if index < len(updated.asset_captions) else ""
        matches = [n for n in indexes if original.asset_hashes[n] == asset]
        exact = [n for n in matches if (original.asset_captions[n] if n < len(original.asset_captions) else "") == caption]
        selected = exact[0] if len(exact) == 1 else matches[0] if len(matches) == 1 else None
        if selected is not None:
            indexes.remove(selected)
            item = original_items[selected]
            if changed_provenance:
                item = replace(item, references=asset_context(updated, index), source_caption=None)
        else:
            # No source ownership is invented for an ambiguous/new legacy edit.
            item = asset_instances(replace(updated, asset_instances=()))[index]
        result.append(item)
    return with_asset_instances(updated, result)


def source_page_identity(instance):
    from app.monthly_report_section_uploads import page_identity
    pairs = {pair for ref in instance.references if (pair := page_identity(ref)) is not None}
    return next(iter(pairs)) if len(pairs) == 1 else None


def merge_picture_occurrences(existing, incoming):
    """Merge a source page by origin; keep equal independent occurrences apart."""
    records = list(asset_instances(existing))
    images = list(existing.asset_hashes)
    captions = list(existing.asset_captions) + [""] * (len(images) - len(existing.asset_captions))
    for index, item in enumerate(asset_instances(incoming)):
        caption = incoming.asset_captions[index] if index < len(incoming.asset_captions) else ""
        page = source_page_identity(item)
        matches = ([n for n, prior in enumerate(records) if source_page_identity(prior) == page]
                   if page is not None else [n for n, prior in enumerate(records) if prior.key == item.key])
        if not matches and item.key.startswith("legacy:") and page is None:
            # Unchanged legacy report imports have no explicit inclusion ID.
            # Context and caption must agree as well as bytes; a new source is
            # an independent occurrence even when its raster happens to match.
            matches = [n for n, prior in enumerate(records)
                       if prior.key.startswith("legacy:") and prior.asset == item.asset
                       and prior.references == item.references and captions[n] == caption]
        if len(matches) > 1:
            raise ValueError("This source page has more than one report occurrence. Open its report pictures and identify the page before applying the source caption.")
        if matches:
            n = matches[0]
            prior = records[n]
            if captions[n] != caption:
                if prior.source_caption is None or captions[n] != prior.source_caption:
                    raise ValueError("The report page has an independent caption. In Manage source files, choose whether to keep the report caption or use the source caption; neither version was overwritten.")
                captions[n] = caption
            images[n] = item.asset
            records[n] = replace(item, key=prior.key)
        else:
            images.append(item.asset)
            captions.append(caption)
            records.append(item)
    return tuple(images), tuple(captions), tuple(records)
