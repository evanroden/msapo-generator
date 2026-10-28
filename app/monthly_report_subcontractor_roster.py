"""Explicit, versioned subcontractor contact/status reuse within one contract.

The shared roster contains *reviewed table data only*. Source-page images,
their report-specific approval receipts, originals, and authored notes never
move to this store. One report's edit cannot silently advance standing data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import re
from uuid import uuid4

from app import monthly_report_library as library
from app.monthly_report_content_policy import table_has_pricing
from app.monthly_report_model import ReportProfile, ReportTable, ResolvedBlock


MAX_ROSTERS = 64
MAX_TABLES = 24
MAX_ROWS = 1000
MAX_CELLS = 32000
MAX_CELL_CHARS = 4000
SHARED_REF_PREFIX = "subcontractor-roster:v1:"
_SITE_COLUMNS = {"site", "facility", "location"}
_SHARED_SITES = {"", "all", "all sites", "contract wide", "contract-wide", "shared"}


@dataclass(frozen=True)
class ApprovedRoster:
    id: str
    sites: tuple[str, ...]  # () explicitly means approved for the whole contract.
    site_labels: tuple[tuple[str, tuple[str, ...]], ...]
    tables: tuple[ReportTable, ...]
    origin_references: tuple[str, ...]
    actor: str
    saved_at: str


@dataclass(frozen=True)
class RosterState:
    contract: str
    revision: int
    entries: tuple[ApprovedRoster, ...]


def _key(value):
    return " ".join(str(value).casefold().split())


def _path(contract):
    return library._root() / "subcontractor_rosters" / library._contract_directory(contract)


def _site_column(table):
    choices = [index for index, heading in enumerate(table.columns)
               if _key(heading) in _SITE_COLUMNS]
    return choices[0] if len(choices) == 1 else None


def _tables(block, spec):
    if block.key != "subcontractor_matrix" or block.source == "Omit":
        raise ValueError("Include vendor contacts in this report before sharing them.")
    columns = tuple(column.title for column in spec.columns)
    if block.rows and not columns:
        raise ValueError("The vendor table needs reviewed column headings.")
    tables = tuple(([ReportTable(columns, block.rows)] if block.rows else [])
                   + list(block.extra_tables))
    return tuple(table for table in tables if table.rows)


def _validate_tables(tables):
    if not tables or len(tables) > MAX_TABLES:
        raise ValueError("Choose reviewed vendor contact rows to share (at most 24 tables).")
    rows = sum(len(table.rows) for table in tables)
    cells = sum(len(table.columns) * len(table.rows) for table in tables)
    if rows > MAX_ROWS or cells > MAX_CELLS:
        raise ValueError("The vendor roster exceeds its table or row limit.")
    for table in tables:
        if (not 1 <= len(table.columns) <= 100
                or any(len(row) != len(table.columns) for row in table.rows)
                or any(not isinstance(cell, str) or len(cell) > MAX_CELL_CHARS
                       for cell in (*table.columns, *(value for row in table.rows for value in row)))):
            raise ValueError("A vendor table has missing columns or oversized cells.")
        if table_has_pricing(table.columns, table.rows):
            raise ValueError("The proposed shared roster contains pricing; remove it from client-facing vendor contacts.")
    return tuple(tables)


def _facility_labels(profile):
    return tuple((facility.key, tuple(dict.fromkeys(
        _key(value) for value in (facility.title, *facility.aliases) if value.strip())))
        for facility in profile.facilities)


def _site_validation(tables, labels, scope_sites):
    # A Site/Facility cell is a scope declaration, not a decorative heading.
    # Unrecognized populated locations cannot silently be approved globally or
    # mapped into a different facility's report. A full-width category band is
    # retained exactly, without guessing which row it belongs to.
    known = {name for key, names in labels if key in scope_sites for name in names}
    for table in tables:
        col = _site_column(table)
        if col is None:
            continue
        for row in table.rows:
            value = _key(row[col])
            if value in _SHARED_SITES or sum(bool(cell.strip()) for cell in row) == 1:
                continue
            if not scope_sites:
                raise ValueError("This vendor table names a site. Share it for the reviewed sites, not as a contract-wide row.")
            if value not in known:
                raise ValueError("A vendor row names an unconfirmed site. Correct the site before sharing the roster.")


def load_rosters(contract):
    """Read only this contract's current immutable head; never scan neighbors."""
    path = _path(contract) / "manifest.json"
    if not path.exists():
        return RosterState(contract, 0, ())
    value = library._read(path)
    try:
        if value["contract"] != contract or type(value["revision"]) is not int or value["revision"] < 1:
            raise ValueError("Contract or revision mismatch")
        entries = []
        for raw in value["entries"]:
            tables = tuple(ReportTable(tuple(t["columns"]),
                                       tuple(tuple(row) for row in t["rows"]),
                                       str(t.get("reference", ""))) for t in raw["tables"])
            _validate_tables(tables)
            entry = ApprovedRoster(
                str(raw["id"]), tuple(raw["sites"]),
                tuple((str(key), tuple(values)) for key, values in raw["site_labels"]),
                tables, tuple(raw["origin_references"]), str(raw["actor"]),
                str(raw["saved_at"]),
            )
            if (not re.fullmatch(r"[a-f0-9]{32}", entry.id)
                    or len(set(entry.sites)) != len(entry.sites)
                    or any(site not in dict(entry.site_labels) for site in entry.sites)
                    or any(len(ref) > 1000 for ref in entry.origin_references)):
                raise ValueError("Invalid roster scope or provenance")
            entries.append(entry)
        if len(entries) > MAX_ROSTERS or len({entry.sites for entry in entries}) != len(entries):
            raise ValueError("Duplicate roster scope")
        return RosterState(contract, value["revision"], tuple(entries))
    except (KeyError, TypeError, ValueError) as exc:
        raise library.LibraryError("Saved subcontractor rosters cannot be read; existing data is unchanged.") from exc


def save_roster(profile: ReportProfile, block: ResolvedBlock, spec, *,
                site_keys=(), expected_revision, actor, confirmed=False):
    """Explicit standing promotion, guarded by contract revision under lock.

    Empty site_keys is an affirmative *contract-wide* decision, never a default
    obtained from an unreviewed report or an empty site's old upload.
    """
    if not confirmed:
        raise ValueError("Confirm the contract and sites before sharing vendor contacts.")
    actor = library._confirmation(actor, confirmed)
    selected = {facility.key for facility in profile.facilities}
    site_keys = tuple(sorted(site_keys))
    if len(set(site_keys)) != len(site_keys) or any(key not in selected for key in site_keys):
        raise ValueError("Shared vendor roster sites must be explicitly selected in this report.")
    original_tables = _validate_tables(_tables(block, spec))
    labels = _facility_labels(profile)
    _site_validation(original_tables, labels, site_keys)
    # Source-page attachments remain private to the owning report/profile.
    # Preserve the original table's references in the history receipt, while
    # a consumer receives a new contract-scoped version reference instead.
    reference = tuple(dict.fromkeys((*block.references, *(t.reference for t in original_tables
                                                        if t.reference))))
    snapshot = tuple(ReportTable(table.columns, table.rows, "")
                     for table in original_tables)
    path = _path(profile.contract)
    with library._locked(path):
        current = load_rosters(profile.contract)
        if current.revision != expected_revision:
            raise library.RevisionConflict(
                "Shared subcontractors changed. Reload the saved roster; your report-only edits are unchanged.")
        previous = tuple(entry for entry in current.entries if entry.sites != site_keys)
        if len(previous) >= MAX_ROSTERS:
            raise ValueError("Too many separately approved vendor scopes. Review old scopes before saving.")
        entry = ApprovedRoster(uuid4().hex, site_keys, labels, snapshot, reference,
                               actor, library._now())
        state = RosterState(profile.contract, current.revision + 1, (*previous, entry))
        raw = library._json({"schema": 1, **asdict(state)})
        library._atomic_write(path / "history" / f"{state.revision:08d}.json", raw)
        library._atomic_write(path / "manifest.json", raw)
        return state


def eligible_rosters(state: RosterState, profile: ReportProfile):
    if state.contract != profile.contract:
        return ()
    selected = {facility.key for facility in profile.facilities}
    # A saved single-site roster cannot silently appear in a two-site report.
    # A contract-wide roster requires the separate explicit promotion above.
    return tuple(entry for entry in state.entries
                 if not entry.sites or selected.issubset(set(entry.sites)))


def _for_sites(table, entry, profile):
    col = _site_column(table)
    if col is None:
        return table
    selected = {facility.key for facility in profile.facilities}
    labels = {name: key for key, names in entry.site_labels for name in names}
    rows = []
    for row in table.rows:
        value = _key(row[col])
        if (value in _SHARED_SITES or
                sum(bool(cell.strip()) for cell in row) == 1 or
                labels.get(value) in selected):
            rows.append(row)
    return replace(table, rows=tuple(rows))


def apply_roster(state: RosterState, entry: ApprovedRoster, profile: ReportProfile,
                 block: ResolvedBlock, spec, *, replace_existing=False):
    """Copy selected approved rows into *only* this report's editable block.

    Keeping imported vendor-page images/notes and their original provenance is
    intentional; a roster never claims ownership of or approves those pages.
    """
    if (block.key != "subcontractor_matrix" or entry not in eligible_rosters(state, profile)):
        raise ValueError("This approved roster does not belong to the selected contract and sites.")
    existing_tables = bool(block.rows or any(table.rows for table in block.extra_tables))
    if existing_tables and not replace_existing:
        raise ValueError("Review this report's existing vendor rows before replacing them with the shared roster.")
    tables = tuple(_for_sites(table, entry, profile) for table in entry.tables)
    tables = tuple(table for table in tables if table.rows)
    if not tables:
        raise ValueError("No approved subcontractor rows match this report's selected sites.")
    ref = f"{SHARED_REF_PREFIX}{state.revision}:{entry.id}"
    tables = tuple(replace(table, reference=f"{ref}:{index}") for index, table in enumerate(tables))
    native_columns = tuple(column.title for column in spec.columns)
    if tables[0].columns == native_columns:
        rows = tables[0].rows
        extra = tables[1:]
    else:
        rows = ()
        extra = tables
    # Only retain old source references if their notes/pages still survive the
    # table swap. A changed table's removed source reference must not falsely
    # certify that the new roster's cells came from that old source.
    references = (block.references if block.text.strip() or block.asset_hashes else ())
    from app.monthly_report_asset_review import preserve_asset_reviews
    updated = replace(block, source="Library", rows=rows, extra_tables=extra,
                      references=tuple(dict.fromkeys((*references, ref))),
                      reviewed_fingerprint="", client_reviewed_fingerprint="")
    return preserve_asset_reviews(block, updated)
