"""Revision-bound ordering of native progress photos and their captions."""

from dataclasses import asdict, replace
from hashlib import sha256
import json

from app.monthly_report_asset_review import preserve_asset_reviews, refresh_asset_source_context


def _source_revisions(draft, block):
    references = (*block.references, *(value for _, values in block.asset_provenance for value in values))
    return tuple((source.id, source.fingerprint) for source in draft.sources
                 if any(value == source.id or value.startswith(source.id + ':')
                        or value.startswith('asset-source-context:v1:' + source.id + ':')
                        for value in references))


def photo_caption_identity(draft, block, *, scope):
    """Ordinary edits keep native IDs; replacement/reset/source changes do not."""
    block = refresh_asset_source_context(block, draft.sources)
    value = (scope, block.key, block.asset_hashes, block.references, block.asset_provenance,
             _source_revisions(draft, block))
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def photo_order_identity(draft, block, *, scope, cycle):
    """A rendered action belongs to one report incarnation and photo revision."""
    block = refresh_asset_source_context(block, draft.sources)
    value = (asdict(draft.profile), asdict(draft.period), scope, cycle,
             block.fingerprint, block.asset_provenance, _source_revisions(draft, block))
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def photo_move_request(identity, block, index, offset):
    return {"identity": identity, "index": index, "asset": block.asset_hashes[index],
            "offset": offset}


def move_photo(draft, block, request, captions, photos_per_page, *, scope, cycle):
    """Validate the original revision, then commit captions and order together.

    Caption delivery changes the block fingerprint. Its comparison therefore
    uses the original block, before applying any delivered caption or density.
    Original bytes, source ownership and every other block field are retained.
    """
    message = "The photos changed after this action was opened. Your order is unchanged. Review the current photos and move one again."
    if not isinstance(request, dict) or set(request) != {"identity", "index", "asset", "offset"}:
        raise ValueError(message)
    index, offset = request["index"], request["offset"]
    if (not scope or not cycle
            or request["identity"] != photo_order_identity(draft, block, scope=scope, cycle=cycle)
            or type(index) is not int or type(offset) is not int or offset not in (-1, 1)
            or not 0 <= index < len(block.asset_hashes)
            or not 0 <= index + offset < len(block.asset_hashes)
            or request["asset"] != block.asset_hashes[index]
            or len(captions) != len(block.asset_hashes)
            or any(not isinstance(caption, str) for caption in captions)
            or type(photos_per_page) is not int or photos_per_page not in range(1, 7)):
        raise ValueError(message)
    indexes = list(range(len(block.asset_hashes)))
    indexes[index], indexes[index + offset] = indexes[index + offset], indexes[index]
    return preserve_asset_reviews(block, replace(
        block, source="Omit" if block.source == "Omit" else "This month",
        asset_hashes=tuple(block.asset_hashes[n] for n in indexes),
        asset_captions=tuple(captions[n] for n in indexes), photos_per_page=photos_per_page,
    ))


def remove_photo(draft, block, request, captions, photos_per_page, *, scope, cycle):
    """Remove one exact photo after collecting all delivered sibling captions."""
    message = "The photos changed after this action was opened. Your photos are unchanged. Review the current photos and remove one again."
    if not isinstance(request, dict) or set(request) != {"identity", "index", "asset"}:
        raise ValueError(message)
    index = request['index']
    if (not scope or not cycle
            or request['identity'] != photo_order_identity(draft, block, scope=scope, cycle=cycle)
            or type(index) is not int or not 0 <= index < len(block.asset_hashes)
            or request['asset'] != block.asset_hashes[index]
            or len(captions) != len(block.asset_hashes)
            or any(not isinstance(caption, str) for caption in captions)
            or type(photos_per_page) is not int or photos_per_page not in range(1, 7)):
        raise ValueError(message)
    indexes = tuple(n for n in range(len(block.asset_hashes)) if n != index)
    return preserve_asset_reviews(block, replace(
        block, source='Omit' if block.source == 'Omit' else 'This month',
        asset_hashes=tuple(block.asset_hashes[n] for n in indexes),
        asset_captions=tuple(captions[n] for n in indexes), photos_per_page=photos_per_page))
