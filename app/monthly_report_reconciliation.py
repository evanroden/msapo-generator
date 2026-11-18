"""Conservative, immutable cross-file candidate reconciliation for Monthly reports.

Facts are observations, not approval to publish or count a service call.
This module neither persists changes nor invents mappings, dates or completion.
Refs #270, #277, #281, #287, #297.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import re
from typing import Literal

from app.monthly_report_content_policy import contains_price


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PERIOD = re.compile(r"(?:19|20)\d{2}-(?:0[1-9]|1[0-2])\Z")
_CONTACT = re.compile(r"(?<!\w)[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
_NOT_COMPLETED = re.compile(
    r"\b(?:not completed|not performed|did not|was not|were not|"
    r"pending|scheduled|planned|proposed|awaiting|would not|will be|to be done)\b", re.I)


@dataclass(frozen=True)
class CandidateFact:
    """One exact source assertion; row/item are 1-based, zero means not present.

    Verification is separate from confidence: an unreviewed model result cannot
    become a verified fact merely by reporting a high numeric confidence.
    A source date is not evidence of completed work without its own status.
    """
    source_hash: str
    source_id: str
    page: int
    item: int
    row: int
    source_date: str
    source_period: str
    contract: str
    facility: str
    section: str
    quote: str
    value: str
    typed_value: str | int | float | bool | None
    confidence: float
    verification: Literal["native", "reviewed", "model", "unverified"]
    claim: Literal["reported", "completed", "standing"]
    scope: Literal["report", "standing"] = "report"
    event_id: str = ""
    subject_key: str = ""
    actor: Literal["vendor", "enfra", "unknown"] = "unknown"
    related_sources: tuple[str, ...] = ()

    def __post_init__(self):
        if not _SHA.fullmatch(self.source_hash):
            raise ValueError("Candidate source hash must be a SHA-256 hex digest.")
        if not self.source_id or not self.contract or not self.section:
            raise ValueError("Candidate identity, contract and section are required.")
        if any(type(n) is not int or n < 0 for n in (self.page, self.item, self.row)):
            raise ValueError("Candidate page/item/row must be nonnegative integers.")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Candidate confidence must be in [0, 1].")
        if self.source_period and not _PERIOD.fullmatch(self.source_period):
            raise ValueError("Candidate period must be YYYY-MM.")
        if self.source_date:
            try:
                parsed = date.fromisoformat(self.source_date)
            except ValueError as error:
                raise ValueError("Candidate source date must be an ISO date.") from error
            if parsed.isoformat() != self.source_date:
                raise ValueError("Candidate source date must be canonical ISO.")
        if self.claim == "standing" and self.scope != "standing":
            raise ValueError("Standing defaults must not masquerade as report facts.")
        if self.claim != "standing" and self.scope == "standing":
            raise ValueError("Report claims must not alter standing defaults.")
        if not self.quote.strip() or not self.value.strip():
            raise ValueError("Candidate must retain the actual quoted assertion and value.")
        if not isinstance(self.typed_value, (str, int, float, bool, type(None))):
            raise ValueError("Normalized value must be an immutable scalar.")

    @property
    def locator(self) -> tuple[str, int, int, int]:
        return self.source_hash, self.page, self.item, self.row

    @property
    def provenance(self) -> str:
        return f"{self.source_hash}:{self.page}:{self.item}:{self.row}"


@dataclass(frozen=True)
class AcceptedFact:
    fact: CandidateFact
    supporting: tuple[CandidateFact, ...] = ()


@dataclass(frozen=True)
class FactConflict:
    first: CandidateFact
    second: CandidateFact
    reason: str


@dataclass(frozen=True)
class DeferredFact:
    fact: CandidateFact
    reason: str


@dataclass(frozen=True)
class Reconciliation:
    accepted: tuple[AcceptedFact, ...]
    conflicts: tuple[FactConflict, ...]
    exceptions: tuple[DeferredFact, ...]
    duplicates: tuple[CandidateFact, ...]
    protected: tuple[CandidateFact, ...]

    def rows(self, section: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Only safe current-period entries, with all original source receipts."""
        return tuple((entry.fact.value,
                      tuple(f.provenance for f in (entry.fact, *entry.supporting)))
                     for entry in self.accepted if entry.fact.section == section and entry.fact.scope == "report")


def _event_key(fact: CandidateFact):
    context = (fact.contract, fact.facility, fact.scope, fact.section, fact.claim)
    if fact.event_id and fact.source_date:
        # WO identifiers are opaque. Never strip zeroes or merge different visits.
        return ("event", *context, fact.source_date, fact.event_id)
    if fact.subject_key and (fact.source_period or fact.scope == "standing"):
        # Same slot, different explicitly documented values -> review conflict.
        return ("field", *context, fact.source_period, fact.subject_key)
    return ("origin", *context, fact.locator)


def _priority(fact: CandidateFact):
    verified = {"reviewed": 0, "native": 1, "model": 2, "unverified": 3}
    return (verified[fact.verification], -fact.confidence,
            fact.source_hash, fact.page, fact.item, fact.row, fact.source_id)


def reconcile_candidates(
    candidates: tuple[CandidateFact, ...],
    *,
    contract: str,
    facilities: tuple[str, ...],
    period: str,
    verified_aliases: tuple[tuple[str, str], ...] = (),
    excluded_locators: frozenset[tuple[str, int, int, int]] = frozenset(),
    protected_keys: frozenset[tuple] = frozenset(),
    omitted_sections: frozenset[str] = frozenset(),
) -> Reconciliation:
    """Return a deterministic plan, never directly mutate a ReportDraft.

    Conflicts are paired source claims, not last-writer-wins. Only explicit,
    verified facility aliases can be applied; an unknown site stays unassigned.
    The caller must persist deliberate omissions/edits and apply accepted facts
    only through the existing reviewed source-receipt path.
    """
    if not _PERIOD.fullmatch(period) or not contract or not facilities or len(set(facilities)) != len(facilities):
        raise ValueError("A confirmed contract, unique facilities and month are required.")
    allowed = set(facilities)
    aliases = {}
    for alias, canonical in verified_aliases:
        if canonical not in allowed or not alias.strip() or (alias in aliases and aliases[alias] != canonical):
            raise ValueError("Every alias must have one explicitly verified in-scope facility.")
        aliases[alias] = canonical

    valid, exceptions, protected = [], [], []
    for fact in candidates:
        if fact.locator in excluded_locators or fact.section in omitted_sections:
            protected.append(fact)
            continue
        if fact.contract != contract:
            exceptions.append(DeferredFact(fact, "other_contract"))
            continue
        facility = aliases.get(fact.facility, fact.facility)
        if facility not in allowed:
            exceptions.append(DeferredFact(fact, "unverified_facility"))
            continue
        if facility != fact.facility:
            fact = replace(fact, facility=facility)
        if _event_key(fact) in protected_keys:
            protected.append(fact)
            continue
        if (fact.scope == "report" and fact.source_period != period):
            exceptions.append(DeferredFact(fact, "other_or_unknown_period"))
            continue
        if fact.claim == "completed" and (
                not fact.source_date or not fact.source_date.startswith(period)
                or _NOT_COMPLETED.search(fact.quote) or fact.actor == "unknown"):
            exceptions.append(DeferredFact(fact, "completion_unverified"))
            continue
        if (fact.verification not in ("native", "reviewed") or fact.confidence < 0.8):
            exceptions.append(DeferredFact(fact, "needs_source_verification"))
            continue
        if (contains_price(fact.quote) or contains_price(fact.value)
                or _CONTACT.search(fact.quote) or _CONTACT.search(fact.value)):
            exceptions.append(DeferredFact(fact, "sensitive_or_priced"))
            continue
        valid.append(fact)

    groups = {}
    for fact in valid:
        groups.setdefault(_event_key(fact), []).append(fact)
    accepted, duplicates, conflicts = [], [], []
    for key in sorted(groups, key=repr):
        group = sorted(groups[key], key=_priority)
        first = group[0]
        supports = []
        conflicting = []
        for subsequent in group[1:]:
            if (subsequent.typed_value, subsequent.actor) == (first.typed_value, first.actor):
                if subsequent.locator == first.locator or any(
                        p.locator == subsequent.locator for p in supports):
                    duplicates.append(subsequent)
                else:
                    supports.append(subsequent)
            else:
                conflicting.append(subsequent)
        if conflicting:
            conflicts.append(FactConflict(first, conflicting[0], "different_verified_values"))
            for other in conflicting[1:]:
                exceptions.append(DeferredFact(other, "additional_conflicting_claim"))
            # The supporting claims remain traceable, but nothing publishes.
            continue
        accepted.append(AcceptedFact(first, tuple(supports)))
    # An exact-looking narrative in two unrelated files has no defensible
    # shared event identity. Do not publish it twice or silently collapse two
    # genuine visits. Surface both source choices for explicit identification.
    by_quote = {}
    for entry in accepted:
        if not entry.fact.event_id and not entry.fact.subject_key:
            key = (entry.fact.contract, entry.fact.facility, entry.fact.section,
                   entry.fact.source_period, entry.fact.claim,
                   " ".join(entry.fact.value.casefold().split()))
            by_quote.setdefault(key, []).append(entry)
    uncertain = {id(entry) for entries in by_quote.values() if len(entries) > 1
                 for entry in entries}
    for entry in accepted:
        if id(entry) in uncertain:
            exceptions.append(DeferredFact(entry.fact, "possible_duplicate_needs_identity"))
    accepted = [entry for entry in accepted if id(entry) not in uncertain]
    return Reconciliation(tuple(accepted), tuple(conflicts), tuple(exceptions),
                          tuple(duplicates), tuple(protected))


def preserve_noop_block(block, **changes):
    """Never revoke human approval merely because an unchanged source was read.

    No text, row, reference or review value changes without new evidence. The
    previous approved block object remains byte-for-byte identical on replay.
    """
    if all(getattr(block, field) == value for field, value in changes.items()):
        return block
    return replace(block, **changes, reviewed_fingerprint="")
