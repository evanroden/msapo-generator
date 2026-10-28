"""Approved, contract-bounded subcontractor roster and pinned report reuse.

Importing/seeing a vendor table never saves it as a contract default. A new
standing record requires an explicit confirmed, CAS-bound write. Report reuse
copies the approved revision, never a live pointer, and never carries an old
monthly service status as a new-month completion.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from hashlib import sha256
import re

from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, ReportProfile, ReportTable, ResolvedBlock

MAX_ROWS = 250
MAX_SITES = 60
ROW_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")
PERIOD = re.compile(r"[12]\d{3}-(?:0[1-9]|1[0-2])\Z")


@dataclass(frozen=True)
class VendorStandingRow:
    id: str
    category: str
    discipline: str
    vendor: str
    contact: str = ""
    phone: str = ""
    msa: str = ""
    sites: tuple[str, ...] = ()           # () means *explicitly approved* contract-wide
    override_of: str = ""                  # only a global-row ID can be overridden
    when_to_contact: str = ""
    status: str = ""
    status_period: str = ""                # status is current ONLY in this month
    source_reference: str = ""             # original immutable row/page receipt


@dataclass(frozen=True)
class VendorRoster:
    contract: str
    revision: int = 0
    rows: tuple[VendorStandingRow, ...] = ()
    actor: str = ""
    updated_at: str = ""

    @property
    def reference(self):
        return "vendor-roster:" + sha256(self.contract.encode()).hexdigest()[:16] + f":r{self.revision:08d}"


@dataclass(frozen=True)
class EffectiveVendor:
    site_key: str
    site_title: str
    row: VendorStandingRow


@dataclass(frozen=True)
class VendorReportReuse:
    master_reference: str
    period_key: str
    selected: tuple[EffectiveVendor, ...]
    historical_statuses: tuple[tuple[str, str, str, str], ...]
    omitted: tuple[tuple[str, str], ...] = ()

    @property
    def current_statuses(self):
        return tuple((record.site_title, record.row.vendor, record.row.status)
                     for record in self.selected
                     if record.row.status and record.row.status_period == self.period_key)


def _root(contract):
    return library._root() / "subcontractor_rosters" / library._contract_directory(contract)


def _validate_fields(row):
    if not isinstance(row, VendorStandingRow) or not ROW_ID.fullmatch(row.id):
        raise ValueError("Give each approved subcontractor a stable, simple row identity.")
    for key in ("category", "discipline", "vendor", "contact", "phone",
                "msa", "when_to_contact", "status", "source_reference"):
        value = getattr(row, key)
        if not isinstance(value, str) or len(value) > (600 if key == "when_to_contact" else 300):
            raise ValueError("Subcontractor fields must be bounded text.")
    if not row.category.strip() or not row.discipline.strip() or not row.vendor.strip():
        raise ValueError("A subcontractor row needs a category, trade and vendor.")
    if (not isinstance(row.sites, tuple) or len(row.sites) > MAX_SITES
            or len(set(row.sites)) != len(row.sites)
            or any(not isinstance(site, str) or not ROW_ID.fullmatch(site)
                   for site in row.sites)):
        raise ValueError("Choose distinct explicit site keys for a site-only subcontractor.")
    if row.override_of and (not ROW_ID.fullmatch(row.override_of)
                            or row.override_of == row.id or not row.sites):
        raise ValueError("An explicit site exception must identify a different contract-wide row.")
    if (row.status_period and not PERIOD.fullmatch(row.status_period)
            or bool(row.status.strip()) != bool(row.status_period)):
        raise ValueError("A recorded subcontractor status needs its exact confirmation month.")
    if row.source_reference and ("\n" in row.source_reference or "\r" in row.source_reference):
        raise ValueError("Source provenance must be one bounded reference.")
    return row


def _validate_rows(rows):
    if not isinstance(rows, tuple) or len(rows) > MAX_ROWS:
        raise ValueError("Store at most 250 approved subcontractor rows.")
    for row in rows:
        _validate_fields(row)
    if len({r.id for r in rows}) != len(rows):
        raise ValueError("Duplicate subcontractor row identities require review.")
    lookup = {row.id: row for row in rows}
    for row in rows:
        if row.override_of:
            parent = lookup.get(row.override_of)
            if parent is None or parent.sites or parent.override_of:
                raise ValueError("A site-specific exception needs its matching approved contract row.")
            if row.vendor.casefold().strip() != parent.vendor.casefold().strip():
                raise ValueError("A site exception may not silently change vendor identity.")
    overrides = set()
    for row in rows:
        if row.override_of:
            for site in row.sites:
                key = (row.override_of, site)
                if key in overrides:
                    raise ValueError("Two vendor exceptions target the same site and contract row.")
                overrides.add(key)
    return rows


def _decode(value, contract):
    if (not isinstance(value, dict) or value.get("schema") != 1
            or value.get("contract") != contract or
            type(value.get("revision")) is not int or value["revision"] < 0):
        raise library.LibraryError("The contract subcontractor roster has an invalid saved identity.")
    try:
        rows = tuple(VendorStandingRow(
            **{**item, "sites": tuple(item.get("sites", ()))})
            for item in value.get("rows", ()))
        result = VendorRoster(contract, value["revision"], rows,
                              value.get("actor", ""), value.get("updated_at", ""))
        _validate_rows(rows)
        return result
    except (TypeError, ValueError, KeyError) as exc:
        raise library.LibraryError("The saved subcontractor roster could not be safely read.") from exc


def load_vendor_roster(contract: str) -> VendorRoster:
    """Read approved contract rows only; no profile/site guess or global fallback."""
    path = _root(contract) / "manifest.json"
    if not path.exists():
        return VendorRoster(contract)
    return _decode(library._read(path), contract)


def roster_version(contract: str, revision: int) -> VendorRoster:
    if type(revision) is not int or revision < 1:
        raise ValueError("Choose an approved historical roster revision.")
    record = _root(contract) / "history" / f"{revision:08d}.json"
    return _decode(library._read(record), contract)


def save_vendor_roster(profile: ReportProfile, rows: tuple[VendorStandingRow, ...], *,
                       expected_revision: int, actor: str, confirmed: bool,
                       removed_ids: tuple[str, ...] = ()) -> VendorRoster:
    """Approve exact standing rows with CAS; no import, browsing or report edit calls this.

    Existing approved rows from other sites are allowed to remain, but a new
    site key must be among the expressly selected profile facilities. Dropping
    a row requires a separate, explicit removal identity, not an omitted form.
    """
    actor = library._confirmation(actor, confirmed)
    _validate_rows(rows)
    chosen = {site.key for site in profile.facilities}
    if (len(set(removed_ids)) != len(removed_ids)
            or any(not ROW_ID.fullmatch(key) for key in removed_ids)):
        raise ValueError("Choose explicit roster rows to retire.")
    folder = _root(profile.contract)
    with library._locked(folder):
        current = load_vendor_roster(profile.contract)
        if current.revision != expected_revision:
            raise library.RevisionConflict(
                "Subcontractor standing data was updated elsewhere. Reload before saving.")
        old = {row.id: row for row in current.rows}
        new = {row.id: row for row in rows}
        removed = set(old) - set(new)
        if removed != set(removed_ids):
            raise ValueError("Approved subcontractors cannot disappear without explicit removal.")
        known_sites = chosen | {site for row in current.rows for site in row.sites}
        for row in rows:
            if row.id not in old or row != old[row.id]:
                if any(site not in known_sites for site in row.sites):
                    raise ValueError("A new subcontractor site requires confirmed contract membership.")
        if rows == current.rows:
            return current
        updated = VendorRoster(profile.contract, current.revision + 1,
                               rows, actor, library._now())
        record = library._json({"schema": 1, **asdict(updated)})
        library._atomic_write(folder / "history" / f"{updated.revision:08d}.json", record)
        library._atomic_write(folder / "manifest.json", record)
        return updated


def effective_vendor_rows(profile: ReportProfile, roster: VendorRoster, period: ReportPeriod,
                          *, omitted: tuple[tuple[str, str], ...] = ()) -> VendorReportReuse:
    """Select one approved contact version per site, with site overrides first."""
    if roster.contract != profile.contract:
        raise ValueError("A different contract's subcontractors cannot enter this report.")
    if roster.revision < 1 or roster_version(profile.contract, roster.revision) != roster:
        raise ValueError("Only an explicitly approved, unchanged subcontractor roster can be reused.")
    _validate_rows(roster.rows)
    sites = {site.key: site.title for site in profile.facilities}
    if (len(omitted) != len(set(omitted)) or
            any(site not in sites or not isinstance(row_id, str)
                for site, row_id in omitted)):
        raise ValueError("Report-only vendor omissions require an exact site and row.")
    omitted_set = set(omitted)
    exclusions = {(site, row.override_of): row for row in roster.rows
                  if row.override_of for site in row.sites}
    selected = []
    for site_key, title in sites.items():
        for row in roster.rows:
            if row.override_of:
                continue  # An exception replaces its global parent; not a second person.
            if row.sites and site_key not in row.sites:
                continue
            chosen = exclusions.get((site_key, row.id), row)
            selected.append(EffectiveVendor(site_key, title, chosen))
    available = {(r.site_key, r.row.id) for r in selected}
    if omitted_set - available:
        raise ValueError("A vendor omission refers to a row that is not active at this site.")
    selected = [r for r in selected if (r.site_key, r.row.id) not in omitted_set]
    # Historical status is still inspectable but never emitted as current.
    history = tuple((r.site_title, r.row.id, r.row.status_period, r.row.status)
                    for r in selected if r.row.status and r.row.status_period != period.key)
    return VendorReportReuse(roster.reference, period.key, tuple(selected),
                             history, omitted)


def report_vendor_block(profile: ReportProfile, review: VendorReportReuse, *,
                        existing: ResolvedBlock | None = None) -> ResolvedBlock:
    """Explicit report-only pinned reuse, never a write to the contract master.

    Status/when-to-contact is a separate table; category bands are attributes,
    never standalone fake person/contact rows.
    """
    if not review.selected:
        raise ValueError("There are no approved subcontractor contacts for these sites.")
    sites = {site.key: site.title for site in profile.facilities}
    if (review.period_key is None or not PERIOD.fullmatch(review.period_key)
            or any(item.site_key not in sites or sites[item.site_key] != item.site_title
                   for item in review.selected)):
        raise ValueError("The subcontractor review no longer matches the selected sites.")
    # A crafted or stale review must not create vendor facts without the exact
    # approved contract/version and site omission decision it claims to use.
    match = re.fullmatch(r"vendor-roster:([0-9a-f]{16}):r([0-9]{8})",
                         review.master_reference)
    if (match is None or match.group(1) != sha256(profile.contract.encode()).hexdigest()[:16]
            or not int(match.group(2))):
        raise ValueError("The subcontractor approval reference is invalid.")
    expected = effective_vendor_rows(
        profile, roster_version(profile.contract, int(match.group(2))),
        ReportPeriod(*map(int, review.period_key.split("-"))), omitted=review.omitted)
    if expected != review:
        raise ValueError("The subcontractor selection no longer matches its approved source.")
    contacts = []
    instructions = []
    for record in review.selected:
        row = record.row
        discipline = row.category if row.category == row.discipline else (
            row.category + " / " + row.discipline)
        contacts.append((record.site_title, discipline, row.vendor,
                         row.contact, row.phone, row.msa))
        current = row.status if row.status_period == review.period_key else ""
        # Reusable instructions may persist; past statuses never become current.
        if row.when_to_contact or current:
            instructions.append((record.site_title, row.category, row.discipline,
                                 row.vendor, row.when_to_contact, current,
                                 row.status_period if current else ""))
    from app.monthly_report_content_policy import table_has_pricing
    headers = ("Facility", "Discipline", "Vendor", "Contact", "Phone", "MSA")
    if table_has_pricing(headers, tuple(contacts)):
        raise ValueError("Subcontractor contact records contain unreviewed pricing.")
    status_cols = ("Facility", "Category", "Trade", "Vendor", "When to contact",
                   "Current status", "Confirmed month")
    if instructions and table_has_pricing(status_cols, tuple(instructions)):
        raise ValueError("Subcontractor status/instruction data contains unreviewed pricing.")
    extra = (ReportTable(status_cols, tuple(instructions), review.master_reference),) if instructions else ()
    candidate = ResolvedBlock("subcontractor_matrix", "Library",
                              rows=tuple(contacts),
                              references=(review.master_reference,),
                              extra_tables=extra)
    if existing is None:
        return candidate
    if existing.key != "subcontractor_matrix":
        raise ValueError("Choose the Sub-Contractor Status report section.")
    if existing == candidate:
        return existing
    if (existing.source == "Omit" or existing.rows or existing.extra_tables
            or existing.text.strip() or existing.asset_hashes):
        raise ValueError("This report has subcontractor edits or an omission. "
                         "Review replacement before reusing the master.")
    return candidate



def rollover_subcontractor_block(block: ResolvedBlock, period: ReportPeriod) -> ResolvedBlock:
    """Retain pinned contacts/instructions; never reassert old monthly status.

    Normal report rollover copies the exact saved block. Its optional current
    status table must therefore clear statuses confirmed for an *older* month,
    while preserving site/trade/vendor identity, contact rows, Omit and author
    notes. The old snapshot and approved contract master stay untouched.
    Custom/imported tables do not use this specific recognized schema.
    """
    if block.key != "subcontractor_matrix":
        return block
    expected = ("Facility", "Category", "Trade", "Vendor", "When to contact",
                "Current status", "Confirmed month")
    tables = []
    for table in block.extra_tables:
        if (tuple(table.columns) != expected or
                not table.reference.startswith("vendor-roster:")):
            tables.append(table)
            continue
        updated_rows = tuple(
            (*row[:5], row[5] if len(row) == 7 and row[6] == period.key else "",
             row[6] if len(row) == 7 and row[6] == period.key else "")
            if len(row) == 7 else row for row in table.rows
        )
        tables.append(replace(table, rows=updated_rows))
    if tuple(tables) == block.extra_tables:
        return block
    return replace(block, extra_tables=tuple(tables),
                   reviewed_fingerprint="", client_reviewed_fingerprint="")
