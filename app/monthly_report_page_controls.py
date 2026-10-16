"""One source/page identity for report-only page edits; no storage writes."""
from dataclasses import replace

from app.monthly_report_asset_review import (
    approve_asset, asset_context, pending_asset_indexes, preserve_asset_reviews, refresh_asset_source_context,
)
from app.monthly_report_content_policy import page_allowed, page_fingerprint
from app.monthly_report_saved_pictures_ui import remove_saved_picture
from app.monthly_report_section_uploads import page_identity


def page_asset_index(block, source_id, number):
    """Only an unambiguous one-page/one-image map authorizes an inline edit."""
    if block is None:
        return None
    pair = (source_id, number)
    matches = [n for n in range(len(block.asset_hashes))
               if {identity for ref in asset_context(block, n)
                   if (identity := page_identity(ref)) is not None} == {pair}]
    return matches[0] if len(matches) == 1 else None


def source_managed_pages(block, contents):
    """Unknown/imported artwork keeps its existing explicit recovery editor."""
    if not block.asset_hashes:
        return False
    known = {content.source.id: content for content in contents}
    for n in range(len(block.asset_hashes)):
        pairs = {pair for ref in asset_context(block, n)
                 if (pair := page_identity(ref)) is not None}
        if len(pairs) != 1:
            return False
        source_id, number = next(iter(pairs))
        content = known.get(source_id)
        if content is None or not 1 <= number <= len(content.source.page_texts):
            return False
        if page_asset_index(block, source_id, number) != n:
            return False
    return True


def included_page_caption(block, source, number):
    """An absent source caption inherits the report value; explicit blank does not."""
    captions = dict(source.captions)
    if number in captions:
        return captions[number]
    index = page_asset_index(block, source.id, number)
    return (block.asset_captions[index] if index is not None
            and index < len(block.asset_captions) else "")


def omitted_section_request(block, contents, *, scope=""):
    """Bind a whole-section inclusion choice to its retained pages and sources."""
    references = (*block.references, *(ref for index in range(len(block.asset_hashes))
                                      for ref in asset_context(block, index)))
    identities = {pair[0] for ref in references
                  if (pair := page_identity(ref)) is not None}
    return {"scope": scope, "block_key": block.key, "block_fingerprint": block.fingerprint,
            "sources": tuple(sorted((content.source.id, content.source.fingerprint)
                                    for content in contents if content.source.id in identities))}


def omitted_section_ready(block, contents):
    """Reviewing one retained page never approves its omitted companions."""
    if block is None or block.source != "Omit":
        return False
    if not block.asset_hashes:
        return bool(block.text.strip() or block.rows or block.extra_tables or block.ai_paragraphs or block.org_nodes)
    if not source_managed_pages(block, contents):
        return False
    sources = {content.source.id: content.source for content in contents}
    for index in range(len(block.asset_hashes)):
        for reference in asset_context(block, index):
            pair = page_identity(reference)
            if pair is not None:
                identity, number = pair
                source = sources.get(identity)
                if (source is None or number not in source.selected_pages
                        or not 1 <= number <= len(source.page_texts) or not page_allowed(source, number)):
                    return False
    return not pending_asset_indexes(block, tuple(sources.values()))


def apply_omitted_section_request(contents, blocks, request, *, scope=""):
    """Include all retained section content only after a distinct scoped choice."""
    key = request.get("block_key") if isinstance(request, dict) else None
    block = blocks.get(key) if isinstance(key, str) else None
    if (block is None or block.source != "Omit"
            or request != omitted_section_request(block, contents, scope=scope)):
        raise ValueError("This section changed after the inclusion action was opened. Your report is unchanged; review the retained pages again.")
    if not omitted_section_ready(block, contents):
        raise ValueError("Review every retained page before including this section. It remains left out of this report.")
    included = replace(block, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint="")
    return {block.key: preserve_asset_reviews(block, included)}


def revise_included_page(block, source, number, action, *, caption=None, all_sources=()):
    """Return an atomic draft/source change without changing the original bytes."""
    index = page_asset_index(block, source.id, number)
    if index is None:
        raise ValueError("This artwork is not mapped to one source page. Use its included-picture editor; no pages were changed.")
    if not 1 <= number <= len(source.page_texts):
        raise ValueError("The source page is unavailable. No pages were changed.")
    # A button click can submit an unblurred caption in the same native event.
    # Apply it within this guarded operation, before review/omit/reorder. The
    # receipt baseline is checked by apply_page_request before either change.
    if caption is not None and action != "caption":
        block, source = revise_included_page(block, source, number, "caption",
                                             caption=caption, all_sources=all_sources)
    if action == "omit":
        reviews, exclusions = dict(source.client_page_reviews), dict(source.client_page_exclusions)
        reviews.pop(number, None)
        exclusions[number] = page_fingerprint(source, number)
        revised = replace(source, selected_pages=tuple(n for n in source.selected_pages if n != number),
                          client_page_reviews=tuple(sorted(reviews.items())),
                          client_page_exclusions=tuple(sorted(exclusions.items())))
        return remove_saved_picture(block, index), revised
    if action in {"earlier", "later"}:
        other = index + (-1 if action == "earlier" else 1)
        if not 0 <= other < len(block.asset_hashes):
            return block, source
        order = list(range(len(block.asset_hashes)))
        order[index], order[other] = order[other], order[index]
        updated = replace(block, asset_hashes=tuple(block.asset_hashes[n] for n in order),
                          asset_captions=tuple(block.asset_captions[n] if n < len(block.asset_captions) else "" for n in order),
                          reviewed_fingerprint="", client_reviewed_fingerprint="")
        return preserve_asset_reviews(block, updated), source
    if action not in {"caption", "review"}:
        raise ValueError("Unknown report-page action. No pages were changed.")
    page_caption = caption if caption is not None else included_page_caption(block, source, number)
    captions = dict(source.captions)
    captions[number] = page_caption
    source = replace(source, captions=tuple(sorted(captions.items())))
    captions = list(block.asset_captions) + [""] * max(0, len(block.asset_hashes) - len(block.asset_captions))
    captions[index] = page_caption
    updated = preserve_asset_reviews(block, replace(block, asset_captions=tuple(captions),
                                                   reviewed_fingerprint="", client_reviewed_fingerprint=""))
    if action == "review":
        reviews, exclusions = dict(source.client_page_reviews), dict(source.client_page_exclusions)
        reviews[number] = page_fingerprint(source, number)
        exclusions.pop(number, None)
        source = replace(source, selected_pages=tuple(sorted(set((*source.selected_pages, number)))),
                         client_page_reviews=tuple(sorted(reviews.items())),
                         client_page_exclusions=tuple(sorted(exclusions.items())))
        if not page_allowed(source, number):
            raise ValueError("This page or caption cannot be included. Correct it or leave this page out.")
    context = tuple(source if s.id == source.id else s for s in all_sources)
    if not any(s.id == source.id for s in context):
        context = (*context, source)
    updated = refresh_asset_source_context(updated, context)
    return (approve_asset(updated, index) if action == "review" else updated), source


def apply_page_request(contents, blocks, request):
    """A stale callback never acts on a different source or newer draft page."""
    fields = ("source_id", "source_fingerprint", "block_key", "block_fingerprint", "action")
    if (not isinstance(request, dict) or any(not isinstance(request.get(k), str) for k in fields)
            or type(request.get("number")) is not int
            or ("caption" in request and not isinstance(request["caption"], str))
            or request["action"] not in {"omit", "review", "earlier", "later"}):
        raise ValueError("This page action could not be recovered. Your report is unchanged; choose the page action again.")
    source_id, key, number = request["source_id"], request["block_key"], request["number"]
    content = next((c for c in contents if c.source.id == source_id), None)
    block = blocks.get(key)
    if (content is None or block is None
            or block.fingerprint != request["block_fingerprint"]
            or content.source.fingerprint != request["source_fingerprint"]):
        raise ValueError("This page changed after the action was opened. Your current report is unchanged; review the page again.")
    revised, source = revise_included_page(block, content.source, number, request["action"],
                                           caption=request.get("caption"),
                                           all_sources=tuple(c.source for c in contents))
    return (tuple(replace(c, source=source) if c.source.id == source_id else c for c in contents),
            {key: revised})
