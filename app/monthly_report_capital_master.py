"""Explicit, versioned contract-level Priority Capital Renewal reuse.

This is an approved-default store, not an import parser or an automatic report
migration. Imported capital rows remain report-only unless someone reviews and
explicitly promotes a bounded, site-scoped list. A report pins the selected
approved revision; later master updates never edit that report/history.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from hashlib import sha256
import re

from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, ReportProfile, ReportTable, ResolvedBlock
from app.monthly_report_content_policy import contains_price, price_column, table_has_pricing

MAX_ROWS = 250
MAX_EXTRA_FIELDS = 12
MAX_SITES = 60
ROW_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")
MONTH = re.compile(r"(?:19|20|21)\d{2}-(?:0[1-9]|1[0-2])\Z")
DATE = re.compile(r"(?:19|20|21)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\Z")


@dataclass(frozen=True)
class CapitalItem:
    key: str
    priority: str
    recommendation: str
    asset: str = ""
    status: str = ""
    status_period: str = ""        # date/context, never automatic current work
    target_date: str = ""          # ISO full date or unknown empty
    site_keys: tuple[str, ...] = ()  # () is explicitly approved contract-wide
    override_of: str = ""          # site exception for an approved global item
    extra_fields: tuple[tuple[str, str], ...] = ()
    source_reference: str = ""     # reviewed source occurrence, not a file path


@dataclass(frozen=True)
class CapitalMaster:
    contract: str
    revision: int = 0
    items: tuple[CapitalItem, ...] = ()
    actor: str = ""
    updated_at: str = ""

    @property
    def reference(self):
        return ("capital-master:" + sha256(self.contract.encode()).hexdigest()[:16]
                + f":r{self.revision:08d}")


@dataclass(frozen=True)
class CapitalOccurrence:
    site_key: str
    site_title: str
    item: CapitalItem


@dataclass(frozen=True)
class CapitalSelection:
    master_reference: str
    period_key: str
    occurrences: tuple[CapitalOccurrence, ...]
    omitted: tuple[tuple[str, str], ...] = ()

    @property
    def historical_statuses(self):
        return tuple((entry.site_title, entry.item.key,
                      entry.item.status_period, entry.item.status)
                     for entry in self.occurrences
                     if entry.item.status and entry.item.status_period != self.period_key)


def _path(contract):
    return library._root() / "capital_masters" / library._contract_directory(contract)


def _item(item):
    if not isinstance(item, CapitalItem) or not isinstance(item.key, str) or not ROW_ID.fullmatch(item.key):
        raise ValueError("Each capital item needs one stable row identity.")
    for field in ("priority", "recommendation", "asset", "status",
                  "source_reference"):
        value = getattr(item, field)
        if not isinstance(value, str) or len(value) > (1200 if field == "recommendation" else 400):
            raise ValueError("Capital values must be bounded text.")
    if not item.priority.strip() or not item.recommendation.strip():
        raise ValueError("Supply the original reviewed priority and recommendation.")
    if (not isinstance(item.site_keys, tuple) or len(item.site_keys) > MAX_SITES
            or len(set(item.site_keys)) != len(item.site_keys)
            or any(not isinstance(site, str) or not ROW_ID.fullmatch(site)
                   for site in item.site_keys)):
        raise ValueError("Use explicit distinct site identifiers for capital applicability.")
    if item.override_of and (not ROW_ID.fullmatch(item.override_of)
                             or item.override_of == item.key or not item.site_keys):
        raise ValueError("A site exception must identify a separate contract-wide item.")
    if item.status_period and not MONTH.fullmatch(item.status_period):
        raise ValueError("Status confirmation needs an exact month.")
    if bool(item.status.strip()) != bool(item.status_period):
        raise ValueError("A capital status and its recorded month must be reviewed together.")
    if item.target_date:
        if not DATE.fullmatch(item.target_date):
            raise ValueError("The capital target date must be ISO YYYY-MM-DD or blank.")
        try:
            date.fromisoformat(item.target_date)
        except ValueError as exc:
            raise ValueError("The capital target date is not a real calendar day.") from exc
    if (not isinstance(item.extra_fields, tuple)
            or len(item.extra_fields) > MAX_EXTRA_FIELDS
            or any(not isinstance(entry, tuple) or len(entry) != 2
                   or any(not isinstance(v, str) or len(v) > 400 for v in entry)
                   for entry in item.extra_fields)):
        raise ValueError("Keep at most twelve bounded additional source fields.")
    names = [k.strip().casefold() for k, _ in item.extra_fields]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Name each unknown source field once.")
    # Content can remain in the *immutable raw source* for operator review,
    # but explicitly approved client defaults may not include leaked finance.
    text = (item.priority, item.recommendation, item.asset, item.status,
            *(v for _, v in item.extra_fields))
    if any(contains_price(value) for value in text):
        raise ValueError("Remove or explicitly resolve financial content before approving capital defaults.")
    if any(price_column(name) for name, _ in item.extra_fields):
        raise ValueError("Financial source columns cannot enter approved client-report defaults.")
    if "\n" in item.source_reference or "\r" in item.source_reference:
        raise ValueError("Source reference must be a single bounded identity.")
    return item


def _validate(items):
    if not isinstance(items, tuple) or len(items) > MAX_ROWS:
        raise ValueError("Use at most 250 approved capital entries.")
    for item in items:
        _item(item)
    if len({item.key for item in items}) != len(items):
        raise ValueError("Duplicate capital IDs need explicit review.")
    index = {item.key: item for item in items}
    overrides = set()
    for item in items:
        if not item.override_of:
            continue
        parent = index.get(item.override_of)
        if parent is None or parent.site_keys or parent.override_of:
            raise ValueError("Capital site overrides require one approved contract-wide parent.")
        if item.asset.casefold().strip() != parent.asset.casefold().strip():
            raise ValueError("A site exception cannot silently change capital asset identity.")
        for site in item.site_keys:
            signature = (item.override_of, site)
            if signature in overrides:
                raise ValueError("Two capital overrides cannot target the same site and item.")
            overrides.add(signature)
    return items


def _decode(data, contract):
    if (not isinstance(data, dict) or data.get("schema") != 1
            or data.get("contract") != contract
            or type(data.get("revision")) is not int or data["revision"] < 0):
        raise library.LibraryError("The saved capital master has an invalid contract or revision.")
    try:
        items = tuple(CapitalItem(
            **{**record,
               "site_keys": tuple(record.get("site_keys", ())),
               "extra_fields": tuple(tuple(v) for v in record.get("extra_fields", ()) )})
            for record in data.get("items", ()))
        _validate(items)
        return CapitalMaster(contract, data["revision"], items,
                             data.get("actor", ""), data.get("updated_at", ""))
    except (ValueError, KeyError, TypeError) as exc:
        raise library.LibraryError("The saved capital master is unreadable; existing data was retained.") from exc


def load_capital_master(contract: str, revision: int | None = None) -> CapitalMaster:
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ValueError("Choose an approved capital master revision.")
    path = _path(contract) / (
        f"history/{revision:08d}.json" if revision else "manifest.json")
    if not path.exists() and revision is None:
        return CapitalMaster(contract)
    return _decode(library._read(path), contract)


def save_capital_master(profile: ReportProfile, items: tuple[CapitalItem, ...], *,
                        expected_revision: int, actor: str,
                        confirmed: bool, removed_ids: tuple[str, ...] = ()) -> CapitalMaster:
    """Explicit approval with CAS; imported report-only rows are never auto-shared."""
    actor = library._confirmation(actor, confirmed)
    _validate(items)
    if (type(expected_revision) is not int or expected_revision < 0
            or not isinstance(removed_ids, tuple)
            or len(removed_ids) != len(set(removed_ids))
            or any(not isinstance(key, str) or not ROW_ID.fullmatch(key)
                   for key in removed_ids)):
        raise ValueError("Capital update needs an exact revision and removal identities.")
    folder = _path(profile.contract)
    chosen = {site.key for site in profile.facilities}
    with library._locked(folder):
        previous = load_capital_master(profile.contract)
        if expected_revision != previous.revision:
            raise library.RevisionConflict(
                "Capital defaults changed in another view. Reload before approving.")
        old = {item.key: item for item in previous.items}
        incoming = {item.key: item for item in items}
        if set(old) - set(incoming) != set(removed_ids):
            raise ValueError("Previously approved capital entries need explicit removal.")
        if any(key not in old for key in removed_ids):
            raise ValueError("Only existing approved capital entries can be removed.")
        # Exact row retirement may not erase an independently approved site
        # merely because another site has a current edit. Global rows require
        # deliberate contract-level approval; they are not inferred here.
        for key in removed_ids:
            old_item = old[key]
            if old_item.site_keys and not set(old_item.site_keys) <= chosen:
                raise ValueError("Removing another site's capital item requires its approved scope.")
        known_sites = chosen | {site for item in previous.items for site in item.site_keys}
        for item in items:
            if item.key not in old or item != old[item.key]:
                if any(key not in known_sites for key in item.site_keys):
                    raise ValueError("A new capital site requires explicit confirmed contract membership.")
                if (item.key in old and old[item.key].site_keys and
                        any(key not in chosen for key in old[item.key].site_keys)):
                    raise ValueError("Do not replace another site's capital entry from this report.")
        if items == previous.items:
            return previous
        saved = CapitalMaster(profile.contract, previous.revision + 1,
                              items, actor, library._now())
        raw = library._json({"schema": 1, **asdict(saved)})
        library._atomic_write(folder / "history" / f"{saved.revision:08d}.json", raw)
        library._atomic_write(folder / "manifest.json", raw)
        return saved


def select_capital(profile: ReportProfile, master: CapitalMaster,
                   period: ReportPeriod, *,
                   omitted: tuple[tuple[str, str], ...] = ()) -> CapitalSelection:
    """Return exactly one approved item version for each selected site."""
    if master.contract != profile.contract:
        raise ValueError("Capital defaults cannot cross contract boundaries.")
    if (master.revision < 1 or
            load_capital_master(profile.contract, master.revision) != master):
        raise ValueError("Only a verified approved capital revision can be reused.")
    _validate(master.items)
    sites = {site.key: site.title for site in profile.facilities}
    if (not isinstance(omitted, tuple) or len(omitted) != len(set(omitted))
            or any(not isinstance(item, tuple) or len(item) != 2
                   or item[0] not in sites or not isinstance(item[1], str)
                   for item in omitted)):
        raise ValueError("Capital omissions require exact current site and row identities.")
    exceptions = {(site, item.override_of): item for item in master.items
                  if item.override_of for site in item.site_keys}
    candidates = []
    for site, title in sites.items():
        for item in master.items:
            if item.override_of or item.site_keys and site not in item.site_keys:
                continue
            selected = exceptions.get((site, item.key), item)
            candidates.append(CapitalOccurrence(site, title, selected))
    available = {(item.site_key, item.item.key) for item in candidates}
    if set(omitted) - available:
        raise ValueError("A capital omission points to a row no longer selected at this site.")
    result = tuple(item for item in candidates
                   if (item.site_key, item.item.key) not in set(omitted))
    return CapitalSelection(master.reference, period.key, result, omitted)


def capital_report_block(profile: ReportProfile, selection: CapitalSelection,
                         *, existing: ResolvedBlock | None = None,
                         include_details: bool = True) -> ResolvedBlock:
    """Copy a pinned report-only Section 9 block; never advance shared defaults."""
    if not selection.occurrences:
        raise ValueError("There are no approved capital recommendations for this report.")
    label = re.fullmatch(r"capital-master:([a-f0-9]{16}):r([0-9]{8})",
                         selection.master_reference)
    if (label is None or
            label.group(1) != sha256(profile.contract.encode()).hexdigest()[:16]
            or int(label.group(2)) < 1 or not MONTH.fullmatch(selection.period_key)):
        raise ValueError("Capital source or reporting period is not valid.")
    period = ReportPeriod(*map(int, selection.period_key.split("-")))
    approved = load_capital_master(profile.contract, int(label.group(2)))
    if select_capital(profile, approved, period, omitted=selection.omitted) != selection:
        raise ValueError("Capital review differs from the approved site-specific source.")
    rows = tuple((item.site_title, item.item.priority, item.item.recommendation)
                 for item in selection.occurrences)
    headers = ("Facility", "Priority", "Recommendation")
    if table_has_pricing(headers, rows):
        raise ValueError("Capital recommendations contain unreviewed financial content.")
    details = []
    if include_details:
        for chosen in selection.occurrences:
            item = chosen.item
            fields = (
                ("Capital ID", item.key), ("Asset", item.asset),
                ("Recorded status", item.status),
                ("Status recorded month", item.status_period),
                ("Target date", item.target_date),
                *item.extra_fields,
            )
            details.extend((chosen.site_title, item.key, name, value)
                           for name, value in fields if value != "")
    detail_columns = ("Facility", "Capital ID", "Field", "Value")
    if details and table_has_pricing(detail_columns, tuple(details)):
        raise ValueError("Capital detail fields contain unreviewed financial content.")
    extra = ((ReportTable(detail_columns, tuple(details),
                          selection.master_reference),) if details else ())
    block = ResolvedBlock(
        "capital_renewal", "Library", rows=rows, extra_tables=extra,
        references=(selection.master_reference,))
    if existing is None:
        return block
    if existing.key != "capital_renewal":
        raise ValueError("Choose the Priority Capital Renewal section.")
    if existing == block:
        return existing
    if (existing.source == "Omit" or existing.rows or existing.extra_tables
            or existing.text.strip() or existing.asset_hashes
            or existing.references):
        raise ValueError("Existing report-only capital edits or omissions require explicit replacement.")
    return block
