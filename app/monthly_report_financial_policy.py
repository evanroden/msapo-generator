"""Non-enabling foundation for source-aware Monthly financial output.

No current output gate calls this module. Review records must be created by a
trusted, explicit application review of verified original bytes; parser/AI labels
are NOT authorization. Fingerprints bind data, not signatures or authenticity.
A caller must map every monetary dependency to the exact current output item;
this module cannot detect omitted dependencies or visually inspect image totals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re


def _digest(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


# Owner decision for #458 (13 November 2026): the Accounts Receivable section of
# the monthly client report is a status-only view. Invoice amounts, payments,
# credits, balances and aged totals never go into client output from this
# section, whatever the source or its review. This is narrower than the general
# 28 October allowance for verified contract/ENFRA client amounts elsewhere.
RECEIVABLE_STATUS_ONLY = ('Accounts Receivable is a status-only section in monthly client '
                          'reports; amounts are never exported from it.')
_RECEIVABLE_BLOCKS = frozenset({'accounts_receivable', 'accounts_receivable_notes'})


def _is_receivable_locator(locator: str) -> bool:
    head = locator.strip().split(':', 1)[0].strip().lower()
    return head in _RECEIVABLE_BLOCKS


@dataclass(frozen=True)
class FinancialScope:
    contract_id: str
    site_id: str


@dataclass(frozen=True)
class SourceFinancialReview:
    source_id: str
    source_sha256: str
    scope: FinancialScope
    role: str
    audience: str
    version: int = 1

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(('financial-review-v1\0' + payload).encode()).hexdigest()


@dataclass(frozen=True)
class MonetaryEvidence:
    source_id: str
    review_fingerprint: str
    locator: str
    content_sha256: str
    kind: str


@dataclass(frozen=True)
class FinancialDecision:
    allowed: bool
    reason: str


def financial_permission(*, purpose: str, scope: FinancialScope, locator: str,
                         content_sha256: str, evidence: tuple[MonetaryEvidence, ...],
                         reviews: tuple[SourceFinancialReview, ...],
                         current_sources: tuple[tuple[str, str], ...]) -> FinancialDecision:
    """Evaluate trusted, complete item provenance without mutating original data.

    `locator` is destination/item scoped, not merely a source-page number: copying
    a value elsewhere cannot reuse its permission implicitly. `current_sources`
    must come from verified original bytes, never unchecked imported metadata.
    All source dependencies must pass; one forbidden/unknown dependency denies.
    Non-Monthly callers retain their own policy; unsupported purposes are denied.
    """
    def deny(reason):
        return FinancialDecision(False, reason)

    if purpose == 'internal_display':
        return FinancialDecision(True, 'Internal display does not authorize client output.')
    if purpose != 'monthly_export':
        return deny('Unsupported purpose; use the existing workflow policy.')
    if (not scope.contract_id.strip() or not scope.site_id.strip()
            or not locator.strip() or not _digest(content_sha256)):
        return deny('Missing or malformed current content/scope binding.')
    if not evidence:
        return deny('Monetary provenance is missing.')
    by_source = {r.source_id: r for r in reviews}
    originals = dict(current_sources)
    if len(by_source) != len(reviews) or len(originals) != len(current_sources):
        return deny('Ambiguous source identities.')
    for item in evidence:
        if item.kind == 'vendor_invoice_total':
            return deny('Vendor-invoice totals cannot appear in monthly reports.')
        if item.kind != 'amount':
            return deny('Unclassified monetary content.')
        review = by_source.get(item.source_id)
        if review is None or review.version != 1:
            return deny('Missing or unsupported source review.')
        if (not review.source_id.strip() or not _digest(review.source_sha256)
                or originals.get(review.source_id) != review.source_sha256
                or review.scope != scope or item.review_fingerprint != review.fingerprint):
            return deny('Source review is stale or outside the current scope.')
        if (item.locator != locator or item.content_sha256 != content_sha256):
            return deny('Content changed or permission was copied to another item.')
        if review.role == 'vendor_invoice':
            return deny('Vendor financial content has no monthly-output permission.')
        if review.role == 'contract':
            if review.audience not in ('client', 'internal'):
                return deny('Source audience is unknown.')
        elif review.role == 'enfra_client_report':
            if review.audience != 'client':
                return deny('ENFRA source is not confirmed client-facing.')
        else:
            return deny('Source is not an approved contract or client-facing ENFRA report.')
    if _is_receivable_locator(locator):
        return deny(RECEIVABLE_STATUS_ONLY)
    return FinancialDecision(True, 'All monetary dependencies have current permitted provenance.')


@dataclass(frozen=True)
class ReviewedFinancialPage:
    number: int
    fingerprint: str
    source_review_fingerprint: str
    semantics: str
    version: int = 1
