"""Conservative, source-bound inventory of *observable* Monthly extraction.

This ledger does not grant source admission, AI approval, page consent or export
permission. An unrepresented item remains reviewable; it is never called imported
because a file was accepted. Per-element receipts are report-local and inert
outside this display.
"""
from collections import Counter
from dataclasses import dataclass, replace
from hashlib import sha256
import json


STATES = frozenset({"applied", "review", "excluded", "blocked"})
RECEIPT_VERSION = 1
MAX_RECEIPTS = 2500


@dataclass(frozen=True)
class CoverageItem:
    source_id: str
    source_sha256: str
    source_fingerprint: str
    item_id: str
    kind: str
    page: int
    digest: str
    state: str
    reason: str
    destination: str = ""

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError("Each item must have exactly one coverage state.")


@dataclass(frozen=True)
class CoverageLedger:
    source_id: str
    fingerprint: str
    filename: str
    pages: int
    bytes: int | None
    sections: int | None
    tables: int | None
    images: int
    rows: int
    facts: int
    ai_attempts: int | None
    ai_pages_covered: int | None
    items: tuple[CoverageItem, ...]

    @property
    def limited(self):
        return any(item.state == "blocked" for item in self.items)

    @property
    def unread_pages(self):
        return len({item.page for item in self.items
                    if item.page > 0 and item.kind == "visual"
                    and item.state == "blocked"})

    @property
    def needs_review(self):
        return sum(item.state in ("review", "blocked") for item in self.items)

    @property
    def applied(self):
        return sum(item.state == "applied" for item in self.items)

    @property
    def excluded(self):
        return sum(item.state == "excluded" for item in self.items)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             default=str, separators=(",", ":")).encode()).hexdigest()


def _receipt(item, draft, reason):
    return json.dumps({"version": RECEIPT_VERSION, "contract": draft.profile.contract,
                       "period": draft.period.key, "source": item.source_id,
                       "sha256": item.source_sha256, "revision": item.source_fingerprint,
                       "item": item.item_id, "digest": item.digest, "reason": reason},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _exclusion_reason(draft, item):
    for raw in getattr(draft, "source_coverage_receipts", ()):
        try:
            receipt = json.loads(raw)
            if (isinstance(receipt, dict) and receipt.get("version") == RECEIPT_VERSION
                    and receipt.get("contract") == draft.profile.contract
                    and receipt.get("period") == draft.period.key
                    and receipt.get("source") == item.source_id
                    and receipt.get("sha256") == item.source_sha256
                    and receipt.get("revision") == item.source_fingerprint
                    and receipt.get("item") == item.item_id
                    and receipt.get("digest") == item.digest
                    and isinstance(receipt.get("reason"), str)
                    and 8 <= len(receipt["reason"].strip()) <= 300):
                return receipt["reason"]
        except (ValueError, TypeError):
            continue
    return ""


def exclude_from_coverage(draft, item, reason, *, content=None):
    """Record an explicit exclusion; never edit the original or bypass preflight."""
    if item.state != "review":
        raise ValueError("Only reviewable items may receive a reasoned exclusion.")
    reason = reason.strip()
    if not 8 <= len(reason) <= 300:
        raise ValueError("Provide an exclusion reason between 8 and 300 characters.")
    if item.source_id not in {source.id for source in draft.sources}:
        raise ValueError("The source is no longer present.")
    source = next(source for source in draft.sources if source.id == item.source_id)
    if source.sha256 != item.source_sha256 or source.fingerprint != item.source_fingerprint:
        raise ValueError("The source changed. Inspect the current item.")
    # Re-evaluate membership and current state against the saved source before
    # issuing a receipt: stale requests must not approve a replaced element.
    current = source_coverage(draft, source, content)
    matching = [row for row in current.items
                if row.item_id == item.item_id and row.digest == item.digest]
    if len(matching) != 1 or matching[0].state != "review":
        raise ValueError("The coverage item changed. Review it again.")
    record = _receipt(item, draft, reason)
    kept = []
    for value in getattr(draft, "source_coverage_receipts", ()):
        try:
            prior = json.loads(value)
            if (prior.get("source"), prior.get("item"), prior.get("contract"),
                prior.get("period")) == (item.source_id, item.item_id,
                                          draft.profile.contract, draft.period.key):
                continue
        except (AttributeError, ValueError, TypeError):
            pass
        kept.append(value)
    if len(kept) >= MAX_RECEIPTS:
        raise ValueError("Coverage receipt limit reached; resolve older entries.")
    return replace(draft, source_coverage_receipts=(*kept, record))


def source_coverage(draft, source, content=None, *, byte_count=None):
    """Inventory every parser-visible page, table row, image and reading notice.

    SourceContent is optional after a cold reload. Without it, workbook row
    enumeration is explicitly limited rather than returning a false zero.
    """
    from app.monthly_report_source_scope import source_uses, _covered_use
    from app.monthly_report_source_readiness import _INFORMATIONAL_NOTICES
    from app.monthly_report_content_policy import page_fingerprint
    # Hash the large extracted source once, never once per ledger element.
    source_revision = source.fingerprint
    uses = tuple(source_uses(draft, source.id))
    accepted = tuple(use for use in uses
                     if use[0] in {"text", "rows", "follow_up", "organization"}
                     and _covered_use(use, source, draft.profile, draft.period, sources=draft.sources))
    rows = tuple(getattr(content, "tables", ()) or ())
    pictures = tuple(getattr(content, "image_items", ()) or ())
    candidate_images = {int(n) for n in source.needs_vision if type(n) is int}
    candidate_images.update(n for n, _ in pictures if type(n) is int)
    candidate_images.update(source.selected_pages if source.suffix in (".png", ".jpg", ".jpeg",
                           ".webp", ".tif", ".tiff", ".heic", ".heif", ".hif", ".bmp", ".mpo") else ())
    # Parse a report's persisted exclusions once, not once for every table
    # row. An otherwise valid 2,500-receipt workbook must remain bounded.
    exclusions = {}
    for raw in getattr(draft, "source_coverage_receipts", ()):
        try:
            receipt = json.loads(raw)
            if (isinstance(receipt, dict)
                    and receipt.get("version") == RECEIPT_VERSION
                    and receipt.get("contract") == draft.profile.contract
                    and receipt.get("period") == draft.period.key
                    and receipt.get("source") == source.id
                    and receipt.get("sha256") == source.sha256
                    and receipt.get("revision") == source_revision
                    and isinstance(receipt.get("item"), str)
                    and isinstance(receipt.get("digest"), str)
                    and isinstance(receipt.get("reason"), str)
                    and 8 <= len(receipt["reason"].strip()) <= 300):
                exclusions[(receipt["item"], receipt["digest"])] = receipt["reason"]
        except (TypeError, ValueError):
            continue
    items = []

    def add(item_id, kind, page, value, *, state="review", reason="", destination=""):
        item = CoverageItem(source.id, source.sha256, source_revision, item_id, kind,
                            page, _digest(value), state, reason, destination)
        # Native page omission remains a current source-bound human decision.
        excluded_page = (0 < page <= len(source.page_texts)
            and dict(source.client_page_exclusions).get(page) == page_fingerprint(source, page))
        if excluded_page and item.state != "applied":
            item = replace(item, state="excluded",
                           reason="Explicitly omitted original page (current page receipt).")
        if item.state == "review":
            exclusion = exclusions.get((item.item_id, item.digest))
            if exclusion:
                item = replace(item, state="excluded", reason=exclusion)
        items.append(item)

    page_count = len(source.page_texts)
    for number, text in enumerate(source.page_texts, 1):
        if text.strip():
            matching = next(((use[1], use[2]) for use in accepted
                             if use[0] == "text" and isinstance(use[2], str)
                             and text.strip() in use[2]
                             and any(ref.startswith(f"{source.id}:{number}:")
                                     for ref in use[3])), None)
            if matching:
                add(f"page:{number}:text", "text", number, text,
                    state="applied", reason="Exact page text in an accepted contribution.",
                    destination=matching[0])
            else:
                add(f"page:{number}:text", "text", number, text,
                    reason="Parsed text has no exact accepted full-page destination.")
        elif number not in candidate_images:
            add(f"page:{number}:empty", "text", number, "",
                state="blocked",
                reason="No readable text or identified image; verify against the original.")

        if number in candidate_images:
            # A scan-only page must not be mistaken for empty. A page-review
            # receipt alone does not prove a rendered image was attached.
            proof = False
            destination = ""
            if number in source.selected_pages and dict(source.client_page_reviews).get(number) == page_fingerprint(source, number):
                from app.monthly_report_asset_review import asset_context, pending_asset_indexes
                from app.monthly_report_section_uploads import page_identity
                for block in draft.blocks:
                    if block.source == "Omit" or not block.asset_hashes:
                        continue
                    pending = set(pending_asset_indexes(block, draft.sources))
                    for index in range(len(block.asset_hashes)):
                        if index in pending:
                            continue
                        matches = {identity for ref in asset_context(block, index)
                                   if (identity := page_identity(ref)) is not None}
                        if matches == {(source.id, number)}:
                            proof, destination = True, block.key
                            break
                    if proof:
                        break
            add(f"page:{number}:visual", "visual", number,
                (number, tuple(identity for n, identity in pictures if n == number)),
                state="applied" if proof else "blocked",
                reason=("Reviewed attached image with source provenance." if proof else
                        "Image-only or embedded visual needs native page/image review."),
                destination=destination)

    # Index accepted rows once. Rebuilding a complete accepted table per raw
    # row makes ordinary 10k-row exports quadratic on every Streamlit rerun.
    accepted_row_counts = Counter()
    accepted_row_destinations = {}
    for use in accepted:
        if use[0] != "rows" or not isinstance(use[2], tuple):
            continue
        referenced_tables = {table_number for reference in use[3]
                             for table_number in range(1, len(rows) + 1)
                             if reference.startswith(f"{source.id}:{table_number}:")}
        for table_number in referenced_tables:
            for row in use[2][1]:
                key = (table_number, tuple(row))
                accepted_row_counts[key] += 1
                accepted_row_destinations.setdefault(key, use[1])
    for table_number, table in enumerate(rows, 1):
        for row_number, row in enumerate(table.rows, 1):
            key = (table_number, tuple(row))
            result = accepted_row_destinations.get(key, "") if accepted_row_counts[key] else ""
            if result:
                accepted_row_counts[key] -= 1
            add(f"table:{table_number}:row:{row_number}", "row", table_number,
                (table.columns, row), state="applied" if result else "review",
                reason=("Exact accepted row in destination." if result else
                        "Source row has no exact accepted destination."),
                destination=result)
    if len(rows) > page_count:
        add("tables:page-mismatch", "parser", 0, (len(rows), page_count),
            state="blocked",
            reason="Parsed table indexes exceed the retained source items; re-read the original.")
    if content is None and source.suffix in (".csv", ".xlsx"):
        add("tables:unavailable", "parser", 0, source.sha256, state="blocked",
            reason="Table-row inventory unavailable after reload; inspect saved extraction.")

    for fact in source.facts:
        page = fact.page if type(fact.page) is int and 1 <= fact.page <= page_count else 0
        matching = next((use[1] for use in accepted
                         if use[0] == "text" and isinstance(use[2], str)
                         and fact.text.strip() and fact.text.strip() in use[2]
                         and page and any(ref.startswith(f"{source.id}:{page}:") for ref in use[3])), "")
        add("fact:" + fact.id, "fact", page, (fact.kind, fact.text, fact.quote),
            state="applied" if matching else "review",
            reason=("Exact accepted fact in destination." if matching else
                    "Classified fact is not confirmed in an accepted destination."),
            destination=matching)

    from app.monthly_report_content_policy import page_allowed
    from app.monthly_report_vendor_passages import passage_notice_page
    for number, notice in enumerate(source.notices, 1):
        page = passage_notice_page(notice, page_count)
        acknowledged = (page is not None and
                        ((page in source.selected_pages and page_allowed(source, page))
                         or dict(source.client_page_exclusions).get(page) == page_fingerprint(source, page)))
        informational = notice in _INFORMATIONAL_NOTICES
        add(f"notice:{number}", "notice", page if page is not None else 0, notice,
            state="excluded" if informational or acknowledged else "blocked",
            reason=("Known reader description, not a missing element." if informational
                    else "Current source-page decision accounts for this passage." if acknowledged
                    else "Reader limitation: " + notice[:220]))

    if not items:
        add("source:unexamined", "parser", 0, source.sha256, state="blocked",
            reason="No extracted elements are available for this source.")

    # The current reader has no persisted, per-page paid-AI attempt receipt;
    # null is deliberate, rather than interpreting accepted facts as 100% AI coverage.
    return CoverageLedger(source.id, source_revision, source.filename, page_count,
                          byte_count, None,
                          len(rows) if content is not None else None, len(candidate_images), sum(len(t.rows) for t in rows),
                          len(source.facts), None, None, tuple(items))


def all_sources_summary(ledgers):
    ledgers = tuple(ledgers)
    return {"files": len(ledgers), "useful_items_added": sum(x.applied for x in ledgers),
            "issues": sum(x.needs_review for x in ledgers),
            "files_limited": sum(x.limited for x in ledgers),
            "pages_unread": sum(x.unread_pages for x in ledgers)}


def exact_manifest_scores(ledgers, manifest):
    """Evaluate an independently authored manifest; no guessed reader recall.

    Entries are mappings with source_id, item_id, destination, and exact digest.
    Counts represent the explicit manifest only, not every semantic fact.
    """
    observed = {(item.source_id, item.item_id, item.digest): item
                for ledger in ledgers for item in ledger.items}
    by_destination = {}
    supported = 0
    for entry in manifest:
        key = (entry["source_id"], entry["item_id"], entry["digest"])
        item = observed.get(key)
        dest = entry["destination"]
        total, found = by_destination.get(dest, (0, 0))
        success = bool(item and item.state == "applied" and item.destination == dest)
        by_destination[dest] = (total + 1, found + int(success))
        supported += int(success)
    claimed = sum(item.state == "applied" for ledger in ledgers for item in ledger.items)
    return {"recall_by_destination": {
                dest: (matched / total if total else None)
                for dest, (total, matched) in by_destination.items()},
            "exact_supported_precision": supported / claimed if claimed else None,
            "manifest_supported": supported, "claimed_applied": claimed}
