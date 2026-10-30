"""Content-bound picture approvals, independent of unrelated block editing.

Assets are content-addressed and verified by the library reader. A review binds
the immutable reference, caption, destination and source provenance. Legacy
whole-block approvals are migrated only while their original digest still
matches; these functions never modify historical snapshots.
"""

import hashlib
import json
from dataclasses import replace

from app.monthly_report_page_reference import page_identity


_SOURCE_CONTEXT = "asset-source-context:v1:"


def _references(block):
    # Reporting-period confirmation has its own gate. It does not change the
    # picture's bytes, caption or original source provenance.
    return tuple(dict.fromkeys(r for r in block.references
                               if not r.startswith(("report-period:", "report-origin:", "period-item:v1:",
                                                    "source-scope-use:v1:"))))


def asset_context(block, index):
    """Return explicit provenance, or conservatively bind an unmapped image."""
    reference = block.asset_hashes[index]
    available = _references(block)
    from app.monthly_report_asset_instances import valid_instances
    mapped = (block.asset_instances[index].references if valid_instances(block)
              else dict(block.asset_provenance).get(reference))
    # A removed/replaced source invalidates an inherited map. Never approve an
    # image under a provenance reference that the block no longer contains.
    if mapped is not None and all(value.startswith(_SOURCE_CONTEXT) or value in available for value in mapped):
        return tuple(sorted(set(mapped)))
    # The historical page importer emitted one reference per picture. This is
    # only unambiguous in a pure picture block; mixed text/tables keep their
    # conservative full context until a source-aware importer supplies a map.
    if (not block.text.strip() and not block.rows and not block.extra_tables
            and not block.ai_paragraphs and not block.org_nodes
            and len(available) == len(block.asset_hashes)):
        return tuple(sorted(set(available[n] for n, asset in enumerate(block.asset_hashes)
                                if asset == reference)))
    return tuple(sorted(available))


def asset_fingerprint(block, index):
    caption = block.asset_captions[index] if index < len(block.asset_captions) else ""
    context = asset_context(block, index)
    scoped_pages = {tuple(value[len(_SOURCE_CONTEXT):].split(":")[:2])
                    for value in context if value.startswith(_SOURCE_CONTEXT)}
    normalized_context = []
    for value in context:
        parts = value.split(":")
        if page_identity(value) is not None and tuple(parts[:2]) in scoped_pages:
            # A historical full-source hash includes unrelated pages and review
            # toggles. Once a targeted marker exists, it supplies the relevant
            # source context and the raw reference supplies only page identity.
            value = f"source-page:{parts[0]}:{parts[1]}"
        normalized_context.append(value)
    payload = ("client-asset-v1", block.key, block.asset_hashes[index], caption,
               tuple(sorted(set(normalized_context))))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def _legacy_reviewed(block):
    # Once migrated, a compatibility whole-block stamp can no longer approve
    # newly changed provenance (the historical digest predates that new field).
    return (not block.client_asset_reviews and not block.asset_provenance and not block.asset_instances
            and block.client_reviewed_fingerprint == block.fingerprint)


def asset_reviewed(block, index):
    # This exact comparison is the only bridge from old whole-block approvals.
    # Once anything changes, a legacy stamp alone grants no approval.
    return asset_fingerprint(block, index) in block.client_asset_reviews or _legacy_reviewed(block)


def pending_asset_indexes(block, sources=None):
    if sources is not None:
        block = refresh_asset_source_context(block, sources)
    return tuple(index for index in range(len(block.asset_hashes))
                 if not asset_reviewed(block, index))


def _source_context_marker(source, number):
    text = source.page_texts[number - 1] if 1 <= number <= len(source.page_texts) else None
    values = (source.sha256, number, text, dict(source.captions).get(number, ""),
              source.vendor, source.facility, source.service_date, source.work_order)
    from app.monthly_report_mbcx_financial_pages import has_financial_page_review
    if has_financial_page_review(source, number):
        values = (*values, source.financial_source_review.fingerprint if source.financial_source_review else "",
                  tuple((p.fingerprint, p.source_review_fingerprint, p.semantics, p.version) for p in source.financial_page_reviews if p.number == number))
    digest = hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
    return f"{_SOURCE_CONTEXT}{source.id}:{number}:{digest}"



def current_source_page_review_matches(block, index, source, number, *, profile=None):
    """Read-only current per-page evidence, not source/site admission or consent.

    Whole-source fingerprints may change after a genuine caption review. The
    original explicit page identity plus its exact current context and existing
    asset/page receipts can establish that this occurrence was reviewed again.
    Callers retain independent source identity, scope and output-byte checks.
    """
    from app.monthly_report_content_policy import page_allowed
    from app.monthly_report_asset_instances import valid_instances
    if not 0 <= index < len(block.asset_hashes) or not 1 <= number <= len(source.page_texts):
        return False
    asset = block.asset_hashes[index]
    individual = valid_instances(block)
    if not individual and block.asset_hashes.count(asset) != 1:
        return False
    mappings = [references for ref, references in block.asset_provenance if ref == asset]
    if len(mappings) != 1:
        return False
    # Equal bytes do not identify an occurrence. Only the validated positional
    # record may narrow its provenance; legacy hash maps remain unambiguous-only.
    references = block.asset_instances[index].references if individual else mappings[0]
    plain = [ref for ref in references if not ref.startswith(_SOURCE_CONTEXT)]
    if len(plain) != 1 or plain[0] not in block.references:
        return False
    if page_identity(plain[0]) != (source.id, number):
        return False
    markers = [ref for ref in references if ref.startswith(_SOURCE_CONTEXT)]
    return (markers == [_source_context_marker(source, number)]
            and asset_reviewed(block, index) and page_allowed(source, number, profile=profile, destination=block.key))


def refresh_asset_source_context(block, sources):
    """Bind reviews to relevant current source facts without broad invalidation.

    Other pages' selection, review state and metadata never change this page's
    marker. A legacy source reference can acquire its first marker without a
    new review only when its original full source fingerprint still matches.
    Missing source evidence gets an unapprovable current-context marker.
    """
    block = normalize_asset_reviews(block)
    from app.monthly_report_asset_instances import valid_instances, with_asset_instances
    individual = valid_instances(block)
    instances = []
    source_index = {source.id: source for source in sources}
    contexts = {}
    trusted_migrations = set()
    unavailable = set()
    for index, asset in enumerate(block.asset_hashes):
        prior = asset_context(block, index)
        plain = tuple(value for value in prior if not value.startswith(_SOURCE_CONTEXT))
        markers = tuple(value for value in prior if value.startswith(_SOURCE_CONTEXT))
        current_markers = []
        trusted = True
        for reference in plain:
            identity = page_identity(reference)
            if identity is None:
                # An invalid source/page token must never inherit an old page
                # approval. Keep its original bytes and mark this occurrence
                # unavailable only when it names a known source.
                pieces = reference.split(":")
                if len(pieces) == 3 and pieces[0] in source_index:
                    current_markers.append(f"{_SOURCE_CONTEXT}{pieces[0]}:invalid:missing")
                    trusted = False
                    unavailable.add(index)
                continue
            source_id, number = identity
            source = source_index.get(source_id)
            if source is None or not 1 <= number <= len(source.page_texts):
                current_markers.append(f"{_SOURCE_CONTEXT}{source_id}:{number}:missing")
                trusted = False
                unavailable.add(index)
                continue
            marker = _source_context_marker(source, number)
            current_markers.append(marker)
            if not markers and parts[2] != source.fingerprint:
                trusted = False
        context = tuple(sorted(set((*plain, *current_markers))))
        contexts[asset] = tuple(sorted(set((*contexts.get(asset, ()), *context))))
        if individual:
            instances.append(replace(block.asset_instances[index], references=context))
        if current_markers and not markers and trusted and asset_reviewed(block, index):
            trusted_migrations.add(index)
    updated = (with_asset_instances(block, instances) if individual else
               replace(block, asset_provenance=tuple(contexts.items())))
    reviews = set(block.client_asset_reviews)
    for index in trusted_migrations:
        reviews.add(asset_fingerprint(updated, index))
    return replace(updated, client_asset_reviews=tuple(dict.fromkeys(
        asset_fingerprint(updated, n) for n, asset in enumerate(updated.asset_hashes)
        if n not in unavailable and asset_fingerprint(updated, n) in reviews)))


def normalize_asset_reviews(block):
    """Pin provenance and migrate only valid approvals on an immutable copy."""
    fingerprints = tuple(asset_fingerprint(block, n) for n in range(len(block.asset_hashes)))
    reviews = (fingerprints if _legacy_reviewed(block)
               else tuple(value for value in fingerprints if value in block.client_asset_reviews))
    from app.monthly_report_asset_instances import valid_instances, with_asset_instances
    if valid_instances(block):
        current = with_asset_instances(block, tuple(replace(item, references=asset_context(block, n))
                                                   for n, item in enumerate(block.asset_instances)))
        return replace(current, client_asset_reviews=tuple(dict.fromkeys(reviews)))
    provenance = tuple(dict.fromkeys((reference, asset_context(block, n))
                                    for n, reference in enumerate(block.asset_hashes)))
    return replace(block, client_asset_reviews=tuple(dict.fromkeys(reviews)), asset_provenance=provenance,
                   asset_instances=())


def preserve_asset_reviews(original, updated):
    """Carry approvals through edits; only still-identical pictures remain ready.

    Call before discarding the original legacy stamp. Explicit provenance on a
    new image wins; otherwise its context is the new references in this edit,
    falling back to the full block context when the caller cannot distinguish it.
    """
    original = normalize_asset_reviews(original)
    if original.asset_instances or updated.asset_instances:
        from app.monthly_report_asset_instances import reconcile_asset_instances
        updated = reconcile_asset_instances(original, updated)
        current = normalize_asset_reviews(updated)
        reviews = set((*original.client_asset_reviews, *current.client_asset_reviews))
        return replace(current, client_asset_reviews=tuple(dict.fromkeys(
            asset_fingerprint(current, n) for n in range(len(current.asset_hashes))
            if asset_fingerprint(current, n) in reviews)))
    original_context = dict(original.asset_provenance)
    updated_context = dict(updated.asset_provenance)
    added_references = tuple(r for r in _references(updated) if r not in _references(original))
    for reference in updated.asset_hashes:
        if reference not in updated_context:
            updated_context[reference] = original_context.get(reference, added_references or _references(updated))
    updated = replace(updated, asset_provenance=tuple((ref, updated_context[ref])
                                                     for ref in dict.fromkeys(updated.asset_hashes)))
    current = normalize_asset_reviews(updated)
    reviews = set((*original.client_asset_reviews, *current.client_asset_reviews))
    return replace(current, client_asset_reviews=tuple(dict.fromkeys(
        asset_fingerprint(current, n) for n in range(len(current.asset_hashes))
        if asset_fingerprint(current, n) in reviews)))


def approve_asset(block, index):
    block = normalize_asset_reviews(block)
    fingerprint = asset_fingerprint(block, index)
    return replace(block, client_asset_reviews=tuple(dict.fromkeys((*block.client_asset_reviews, fingerprint))))


def approve_all_assets(block):
    block = normalize_asset_reviews(block)
    return replace(block, client_asset_reviews=tuple(dict.fromkeys(
        asset_fingerprint(block, n) for n in range(len(block.asset_hashes)))),
        client_reviewed_fingerprint=block.fingerprint)
