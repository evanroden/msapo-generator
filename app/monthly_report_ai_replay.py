"""Replay explicitly accepted, source-quoted AI facts from saved earlier months.

The acceptance journal records identity and quote receipts, not model output.
The newest prior saved month is authoritative for corrections and removals.
Historical work is displayed as evidence, never asserted as this month's work.
"""
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import re

from app import monthly_report_library as library


@dataclass(frozen=True)
class ReviewedReplay:
    reusable: tuple = ()
    historical: tuple = ()
    from_period: str = ""


def _scope(profile, source):
    from app.monthly_report_source_scope import reviewed_scope
    # A site label must resolve to exactly one selected facility. A generic
    # contract-artwork authorization is not authorization for technical facts.
    facility = source.facility.strip().casefold()
    if facility:
        matched = [site for site in profile.facilities if facility in
                   {name.strip().casefold() for name in (site.key, site.title, *site.aliases)}]
        if len(matched) != 1:
            return None
    if source.scope_review:
        record = reviewed_scope(source, profile)
        if record is None or record.get("kind") != "sites":
            return None
    elif not facility:
        return None
    record = {
        "contract": profile.contract,
        "profile_key": profile.key,
        "facilities": [asdict(site) for site in profile.facilities],
        "source_id": source.id,
        "sha256": source.sha256,
        "suffix": source.suffix,
        "pages": sha256(library._json(list(source.page_texts))).hexdigest(),
        "facility": source.facility,
        "scope_review": source.scope_review,
    }
    return record


def _same_scope(stored, expected):
    # Facility aliases are tuples in dataclasses and lists after JSON loading.
    # Compare canonical wire values, preserving every source/site binding.
    return library._json(stored) == library._json(expected)


def _path(profile, scope):
    identity = sha256(library._json(scope)).hexdigest()
    return library._profile_path(profile.contract, profile.key) / "ai" / "accepted" / (identity + ".json")


def _supported(fact, source):
    from app import monthly_report_ai as ai
    from app.monthly_report_content_policy import contains_price
    if (fact.source_id != source.id or not re.fullmatch(r"fact-[a-zA-Z0-9_-]{4,100}", fact.id)
            or type(fact.page) is not int or not 1 <= fact.page <= len(source.page_texts)
            or fact.kind not in ai.FACT_KINDS or not isinstance(fact.text, str)
            or not fact.text.strip() or len(fact.text) > 2000
            or not isinstance(fact.quote, str) or not fact.quote.strip()
            or len(fact.quote) > 4000 or fact.flags
            or contains_price(fact.text) or contains_price(fact.quote)
            or ai.numbers(fact.text) - ai.numbers(fact.quote)):
        return False
    native = " ".join(source.page_texts[fact.page - 1].split()).casefold()
    if not ai._quote_on_source_token_boundaries(native, fact.quote):
        return False
    if fact.date:
        try:
            date.fromisoformat(fact.date)
        except (ValueError, TypeError):
            return False
    return True


def _static(fact):
    # A recommendation with no dated event/status can be reused as reference
    # material. Inspections, completions, findings and follow-ups need period review.
    if fact.kind != "recommendation" or fact.date or fact.status:
        return False
    return not re.search(
        r"\b(?:completed|repaired|replaced|inspected|performed|scheduled|pending|"
        r"today|yesterday|this month|last month|jan(?:uary)?|feb(?:ruary)?|"
        r"mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
        r"sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b|"
        r"\b20\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        fact.text, re.IGNORECASE,
    )


def record_acceptance(profile, source, facts):
    """Record a delivered native Use-these-facts action; no model claims alone."""
    from app.monthly_report_sources import source_bytes
    scope = _scope(profile, source)
    # The ordinary user can still accept flagged facts for this month's draft.
    # Those facts are NOT eligible for an automatic future-month replay.
    eligible = tuple(fact for fact in facts if _supported(fact, source))
    if scope is None or not eligible:
        return False
    source_bytes(profile, source)  # Recheck immutable original, not only cached text.
    path = _path(profile, scope)
    with library._locked(path.parent):
        value = library._read(path) if path.exists() else {"schema": 1, "scope": scope, "facts": {}}
        if not _same_scope(value.get("scope"), scope) or not isinstance(value.get("facts"), dict):
            raise library.LibraryError("Saved fact acceptance belongs to a different source scope.")
        accepted = dict(value["facts"])
        for fact in eligible:
            receipt = {"page": fact.page, "quote_sha256": sha256(fact.quote.encode()).hexdigest()}
            if fact.id in accepted and accepted[fact.id] != receipt:
                raise library.LibraryError("A previously accepted fact changed its source quote.")
            accepted[fact.id] = receipt
        library._atomic_write(path, library._json({"schema": 1, "scope": scope, "facts": accepted}))
    return True


def replay_reviewed_facts(draft, source):
    """Read only the nearest prior saved month; never synthesize current work."""
    from app.monthly_report_model import ReportPeriod
    from app.monthly_report_sources import source_bytes
    scope = _scope(draft.profile, source)
    if scope is None:
        return ReviewedReplay()
    path = _path(draft.profile, scope)
    if not path.exists():
        return ReviewedReplay()
    value = library._read(path)
    if not _same_scope(value.get("scope"), scope) or not isinstance(value.get("facts"), dict):
        raise library.LibraryError("Saved fact acceptance source scope changed.")
    # A replaced/corrupt original never inherits an earlier acceptance.
    source_bytes(draft.profile, source)
    root = library._profile_path(draft.profile.contract, draft.profile.key, snapshots=True)
    library._qa_path_guard(root)
    candidates = sorted((p.stem for p in root.glob("????-??.json")
                         if re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", p.stem)
                         and p.stem < draft.period.key), reverse=True)
    if not candidates:
        return ReviewedReplay()
    year, month = map(int, candidates[0].split("-"))
    period = ReportPeriod(year, month)
    previous = library.load_snapshot(draft.profile.contract, draft.profile.key, period)
    if previous is None or previous.draft.profile.facilities != draft.profile.facilities:
        return ReviewedReplay()
    old = next((item for item in previous.draft.sources
                if item.id == source.id and item.sha256 == source.sha256
                and _scope(previous.draft.profile, item) == scope), None)
    if old is None:
        return ReviewedReplay()  # Latest saved removal wins over earlier approval.
    reusable, historical = [], []
    for fact in old.facts:
        receipt = value["facts"].get(fact.id)
        if (not isinstance(receipt, dict)
                or receipt != {"page": fact.page, "quote_sha256": sha256(fact.quote.encode()).hexdigest()}
                or not _supported(fact, source)):
            continue
        (reusable if _static(fact) else historical).append(fact)
    return ReviewedReplay(tuple(reusable), tuple(historical), period.key)
