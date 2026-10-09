"""Scoped training requirements and report tables, without inferred completion."""
from dataclasses import replace
from datetime import date
import math

from app import monthly_report_library as library
from app.monthly_report_model import ReportTable, ResolvedBlock

MATRIX_REF = "training:matrix:v1"
EVENT_REF = "training:events:v1"
STATUSES = ("Not recorded", "Completed", "Pending", "Not required")
EVENT_COLUMNS = ("Training", "Date", "Format", "Participants", "Hours")
FORMATS = ("In person", "Virtual", "Asynchronous")


def _path(contract):
    from app.monthly_report_directory import canonical_contract
    return library._root() / "training" / library._contract_directory(canonical_contract(contract))


def load_training(contract):
    path = _path(contract) / "manifest.json"
    return library._read(path) if path.exists() else {"schema": 1, "revision": 0, "sites": {}}


def validate_matrix(table):
    if table.columns[:2] != ("Team member", "Site") or len({c.strip().casefold() for c in table.columns}) != len(table.columns):
        raise ValueError("Training names must be unique and different from the team and site headings.")
    if len(table.columns) > 52 or len(table.rows) > 500:
        raise ValueError("Use at most 50 trainings and 500 team members.")
    seen = set()
    for row in table.rows:
        if len(row) != len(table.columns) or not all(row[:2]):
            raise ValueError("Each training row needs a team member and site.")
        identity = tuple(value.strip().casefold() for value in row[:2])
        if identity in seen:
            raise ValueError("Keep one row per team member at each site.")
        seen.add(identity)
        if any(value not in STATUSES for value in row[2:]):
            raise ValueError("Choose a recorded training status.")
    return table


def save_training(profile, table, *, expected_revision, actor):
    """Only update selected sites, with immutable versions and stale-write checks."""
    validate_matrix(table)
    actor = library._confirmation(actor, True)
    sites = {facility.title: facility.key for facility in profile.facilities}
    if any(row[1] not in sites for row in table.rows):
        raise ValueError("Training rows must belong to this report's selected sites.")
    path = _path(profile.contract)
    with library._locked(path):
        current = load_training(profile.contract)
        if current["revision"] != expected_revision:
            raise library.RevisionConflict("Training was updated elsewhere. Reload the saved training before applying your changes.")
        saved_sites = dict(current["sites"])
        for title, key in sites.items():
            saved_sites[key] = {"columns": list(table.columns[2:]),
                                "rows": [[row[0], *row[2:]] for row in table.rows if row[1] == title]}
        value = {"schema": 1, "revision": current["revision"] + 1, "sites": saved_sites,
                 "actor": actor, "updated_at": library._now()}
        raw = library._json(value)
        library._atomic_write(path / "history" / f'{value["revision"]:08d}.json', raw)
        library._atomic_write(path / "manifest.json", raw)
        return value


def seed_matrix(profile, block, stored, directory=None):
    existing = next((t for t in block.extra_tables if t.reference == MATRIX_REF), None)
    if existing:
        return validate_matrix(existing)
    columns, rows = [], []
    from app.monthly_report_directory import suggest_contact_bindings
    bindings = suggest_contact_bindings(directory, profile.facilities) if directory else {}
    selected = {f.key: f for f in profile.facilities}
    for key in selected:
        columns.extend(stored.get("sites", {}).get(key, {}).get("columns", ()))
    columns = list(dict.fromkeys(columns))
    for key, facility in selected.items():
        site = stored.get("sites", {}).get(key, {})
        known = set()
        for row in site.get("rows", ()):
            values = dict(zip(site.get("columns", ()), row[1:]))
            rows.append((row[0], facility.title, *(values.get(c, "Not recorded") for c in columns)))
            known.add(row[0].casefold())
        if directory:
            # Client representatives are not assumed to be ENFRA employees.
            contacts = [contact for s in directory.sites if s.key == bindings.get(key) for contact in s.contacts]
            for contact in contacts:
                role = contact.role.casefold()
                if contact.name.strip() and contact.name.casefold() not in known and any(
                    term in role for term in ("enfra", "asset manager", "operator", "technician")):
                    rows.append((contact.name, facility.title, *("Not recorded" for _ in columns)))
                    known.add(contact.name.casefold())
    return ReportTable(("Team member", "Site", *columns), tuple(rows), MATRIX_REF)


def add_event(table, *, title, when, mode, participants, hours, period):
    title = title.strip()
    if not title or not participants:
        raise ValueError("Enter the training title and at least one participant.")
    if not isinstance(when, date) or not period.start <= when <= period.end:
        raise ValueError("Choose a training date within this reporting month.")
    if mode not in FORMATS:
        raise ValueError("Choose the training format.")
    value = str(hours).strip()
    if value:
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError("Hours must be a positive number, or left blank if unknown.") from exc
        if not math.isfinite(number) or number <= 0:
            raise ValueError("Hours must be a positive number, or left blank if unknown.")
    row = (title, when.isoformat(), mode, "; ".join(dict.fromkeys(participants)), value)
    rows = table.rows if table else ()
    return ReportTable(EVENT_COLUMNS, rows if row in rows else (*rows, row), EVENT_REF)


def apply_tables(block, matrix, events):
    tables = tuple(t for t in block.extra_tables if t.reference not in (MATRIX_REF, EVENT_REF))
    if len(matrix.columns) > 2 and matrix.rows:
        tables += (validate_matrix(matrix),)
    if events and events.rows:
        tables += (events,)
    if tables == block.extra_tables:
        return block
    return replace(block, source="This month", extra_tables=tables, reviewed_fingerprint="", client_reviewed_fingerprint="")


def training_block(blocks):
    return blocks.get("training_summary", ResolvedBlock("training_summary", "This month"))


def events_for_period(block, period):
    """A standing completion is not evidence that training happened this month."""
    table = next((t for t in block.extra_tables if t.reference == EVENT_REF), None)
    if table is None:
        return None
    rows = []
    for row in table.rows:
        try:
            when = date.fromisoformat(row[1])
        except (ValueError, IndexError):
            continue
        if period.start <= when <= period.end:
            rows.append(row)
    return replace(table, rows=tuple(rows))
