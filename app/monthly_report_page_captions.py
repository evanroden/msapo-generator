"""Synchronize source-caption corrections with the exact attached occurrence."""
from dataclasses import dataclass, replace

from app.monthly_report_asset_instances import asset_instances, source_page_identity, with_asset_instances
from app.monthly_report_content_policy import page_allowed, page_fingerprint
from app.monthly_report_page_controls import page_asset_index, revise_included_page


@dataclass(frozen=True)
class CaptionConflict:
    block_key: str
    source_id: str
    number: int
    report_caption: str
    source_caption: str


def synchronize_source_captions(blocks, previous_sources, current_sources, *, decision=None):
    """Capture delivered source changes without replacing independent wording.

    A stored source-caption base distinguishes a source update from a human
    report edit. Legacy blocks can acquire that base only when the prior exact
    source/page caption agrees. Explicit Include reviews only its own page;
    opening the manager or editing a caption never approves an image.
    """
    previous = {source.id: source for source in previous_sources}
    changed = dict(blocks)
    conflicts = []
    for source in current_sources:
        prior_source = previous.get(source.id)
        excluded = {number for number, receipt in source.client_page_exclusions
                    if prior_source is not None and prior_source.sha256 == source.sha256
                    and number not in source.selected_pages
                    and dict(prior_source.client_page_exclusions).get(number) != receipt
                    and receipt == page_fingerprint(source, number)}
        for number in sorted(set(dict(source.captions)) | excluded):
            candidates = [(key, page_asset_index(block, source.id, number)) for key, block in changed.items()]
            candidates = [(key, index) for key, index in candidates if index is not None]
            if len(candidates) != 1:
                continue
            key, index = candidates[0]
            block = changed[key]
            submitted_here = (isinstance(decision, dict) and decision.get("source") == source.id
                and decision.get("fingerprint") == source.fingerprint and decision.get("page") == number
                and (block.key, block.fingerprint) in decision.get("blocks", ()))
            if number in excluded:
                block, _ = revise_included_page(block, source, number, "omit",
                    caption=dict(source.captions).get(number), all_sources=current_sources)
                changed[key] = block
                continue
            caption = dict(source.captions)[number]
            report_caption = block.asset_captions[index] if index < len(block.asset_captions) else ""
            instances = list(asset_instances(block))
            item = instances[index]
            baseline = item.source_caption
            if baseline is None and prior_source is not None and prior_source.sha256 == source.sha256:
                prior_caption = dict(prior_source.captions).get(number,
                    f"{prior_source.filename} · page/item {number}")
                if report_caption == prior_caption and source_page_identity(item) == (source.id, number):
                    baseline = prior_caption
            if report_caption != caption:
                if baseline is None or report_caption != baseline:
                    conflicts.append(CaptionConflict(key, source.id, number, report_caption, caption))
                    continue
                instances[index] = replace(item, source_caption=baseline)
                block = with_asset_instances(block, instances)
                block, _ = revise_included_page(block, source, number, "caption", caption=caption,
                                                all_sources=current_sources)
            # The source Include callback publishes a new exact page review.
            # A known byte-identity change still needs actual page preparation.
            submitted = (page_allowed(source, number) and
                ((submitted_here and decision.get("action") == "keep")
                 or (prior_source is not None and prior_source.sha256 == source.sha256
                     and dict(prior_source.client_page_reviews).get(number)
                     != dict(source.client_page_reviews).get(number))))
            if submitted:
                block, _ = revise_included_page(block, source, number, "review", caption=caption,
                                                all_sources=current_sources)
            changed[key] = block
    return changed, tuple(conflicts)
