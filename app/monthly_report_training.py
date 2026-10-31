"""Scoped training requirements and report tables, without inferred completion."""
from dataclasses import replace
from datetime import date
from hashlib import sha256
import math
import re
from uuid import uuid4

from app import monthly_report_library as library
from app.monthly_report_model import ReportTable, ResolvedBlock, TrainingSessionTable

MATRIX_REF = "training:matrix:v1"
EVENT_REF = "training:events:v1"
# A retained blank is a distinct historical value, not an inferred status.
# New requirements still explicitly default to "Not recorded" in the editor.
STATUSES = ("", "Not recorded", "Completed", "Pending", "Not required")
EVENT_COLUMNS = ("Training", "Date", "Format", "Participants", "Hours")
FORMATS = ("In person", "Virtual", "Asynchronous")


YEAR_MATRIX_PREFIX = "training:matrix:v2:"


def matrix_year(reference):
    """Only a canonical explicit year is annual; legacy status dates are unknown."""
    if not reference.startswith(YEAR_MATRIX_PREFIX):
        return None
    value = reference[len(YEAR_MATRIX_PREFIX):]
    if not re.fullmatch(r"[1-9][0-9]{3}", value):
        raise ValueError("The training requirements year is invalid.")
    return int(value)


def year_matrix_reference(year):
    if type(year) is not int or not 1000 <= year <= 9999:
        raise ValueError("Choose a four-digit training requirements year.")
    return YEAR_MATRIX_PREFIX + str(year)


def is_matrix_reference(reference):
    return reference == MATRIX_REF or matrix_year(reference) is not None


def matrix_title(reference):
    if not is_matrix_reference(reference):
        return ""
    year = matrix_year(reference)
    return (f"Training requirements — {year}" if year is not None
            else "Training requirements — year not recorded")


def _matrix_in(block):
    tables = tuple(t for t in block.extra_tables if is_matrix_reference(t.reference))
    if len(tables) > 1:
        raise ValueError("This report has more than one requirements matrix. Review them before editing.")
    return tables[0] if tables else None


def _year_sites(stored, year):
    years = stored.get("years", {})
    if not isinstance(years, dict):
        raise ValueError("Saved annual training needs review; existing records were preserved.")
    record = years.get(str(year), {}) if year is not None else stored
    if not isinstance(record, dict) or not isinstance(record.get("sites", {}), dict):
        raise ValueError("Saved annual training needs review; existing records were preserved.")
    return record.get("sites", {})


def matrix_for_year(profile, matrix, stored, year, directory=None):
    """Explicit annual transition: reuse that year's saved rows, otherwise reset.

    Never reinterpret an unknown or older completion as current-year completion.
    Preserve blank cells, source tables and every shared historical year.
    """
    reference = year_matrix_reference(year)
    validate_matrix(matrix)
    if matrix.reference == reference:
        return hospital_matrix(profile, matrix, directory)
    saved = _year_sites(stored, year)
    selected = {f.key: f.title for f in profile.facilities}
    columns = []
    for key, title in selected.items():
        columns.extend(saved[key]["columns"] if key in saved else matrix.columns[2:])
    columns = tuple(dict.fromkeys(columns))
    rows = []
    for key, title in selected.items():
        if key in saved:
            source_columns = saved[key]["columns"]
            source_rows = saved[key]["rows"]
        else:
            source_columns = matrix.columns[2:]
            source_rows = tuple((row[0], *("" if value == "" else "Not recorded"
                                          for value in row[2:]))
                                for row in matrix.rows if row[1] == title)
        for row in source_rows:
            values = dict(zip(source_columns, row[1:]))
            rows.append((row[0], title, *(values.get(c, "Not recorded") for c in columns)))
    result = ReportTable(("Team member", "Site", *columns), tuple(rows), reference)
    return hospital_matrix(profile, result, directory)


def _path(contract):
    from app.monthly_report_directory import canonical_contract
    return library._root() / "training" / library._contract_directory(canonical_contract(contract))


def load_training(contract):
    path = _path(contract) / "manifest.json"
    return library._read(path) if path.exists() else {"schema": 1, "revision": 0, "sites": {}}


def validate_matrix(table):
    if table.columns[:2] != ("Team member", "Site") or len({" ".join(c.casefold().split()) for c in table.columns}) != len(table.columns):
        raise ValueError("Training names must be unique and different from the team and site headings.")
    if len(table.columns) > 52 or len(table.rows) > 500:
        raise ValueError("Use at most 50 trainings and 500 team members.")
    seen = set()
    for row in table.rows:
        if len(row) != len(table.columns) or not all(row[:2]):
            raise ValueError("Each training row needs a team member and site.")
        identity = tuple(" ".join(value.casefold().split()) for value in row[:2])
        if identity in seen:
            raise ValueError("Keep one row per team member at each site.")
        seen.add(identity)
        if any(value not in STATUSES for value in row[2:]):
            raise ValueError("Choose a recorded training status.")
    return table


def save_training(profile, table, *, expected_revision, actor):
    """Only update selected sites, with immutable versions and stale-write checks."""
    validate_matrix(table)
    if not is_matrix_reference(table.reference):
        raise ValueError("Choose a recognized training requirements matrix before saving.")
    year = matrix_year(table.reference)
    actor = library._confirmation(actor, True)
    sites = {facility.title: facility.key for facility in profile.facilities}
    if any(row[1] not in sites for row in table.rows):
        raise ValueError("Training rows must belong to this report's selected sites.")
    path = _path(profile.contract)
    with library._locked(path):
        current = load_training(profile.contract)
        if current["revision"] != expected_revision:
            raise library.RevisionConflict("Training was updated elsewhere. Reload the saved training before applying your changes.")
        saved_sites = dict(_year_sites(current, year))
        for title, key in sites.items():
            saved_sites[key] = {"columns": list(table.columns[2:]),
                                "rows": [[row[0], *row[2:]] for row in table.rows if row[1] == title]}
        value = {**current, "revision": current["revision"] + 1,
                 "actor": actor, "updated_at": library._now()}
        if year is None:
            value["sites"] = saved_sites
        else:
            value["years"] = {**current.get("years", {}), str(year): {"sites": saved_sites}}
        raw = library._json(value)
        library._atomic_write(path / "history" / f'{value["revision"]:08d}.json', raw)
        library._atomic_write(path / "manifest.json", raw)
        return value


def _person(value):
    return " ".join(value.casefold().split())


def _directory_people(profile, directory):
    """Use explicit employer/role evidence within uniquely matched sites only."""
    from app.monthly_report_directory import canonical_contract, suggest_contact_bindings
    if (profile is None or directory is None or directory.archived
            or canonical_contract(profile.contract).casefold() != canonical_contract(directory.contract).casefold()):
        return {}, set()
    bindings = suggest_contact_bindings(directory, profile.facilities)
    sites = {site.key: site for site in directory.sites if site.active}
    eligible, excluded = {}, set()
    for facility in profile.facilities:
        site = sites.get(bindings.get(facility.key))
        if site is None:
            continue
        identities = {}
        names = {}
        for contact in site.contacts:
            if not contact.name.strip():
                continue
            name = _person(contact.name)
            role = _person(contact.role)
            affiliation = None
            if re.search(r"\b(enfra|bernhard|asset[ -]+manager|vendor|contractor|sub[ -]?contractor)\b", role):
                affiliation = 'provider'
            elif re.search(r"\b(hospital|client|medical[ -]+cent(?:er|re)|health[ -]+system)\b", role):
                affiliation = 'hospital'
            identities.setdefault(name, set())
            if affiliation:
                identities[name].add(affiliation)
            names.setdefault(name, contact.name.strip())
        # Conflicting same-name records are not enough evidence to classify or
        # remove an existing person. They also must not create a new enrollment.
        eligible[facility.key] = tuple(names[name] for name, values in identities.items() if values == {'hospital'})
        excluded.update((name, _person(facility.title)) for name, values in identities.items() if values == {'provider'})
    return eligible, excluded


def hospital_matrix(profile, table, directory=None):
    """Filter proved provider identities in a working copy, never rewrite history."""
    validate_matrix(table)
    _, excluded = _directory_people(profile, directory)
    rows = tuple(row for row in table.rows if (_person(row[0]), _person(row[1])) not in excluded)
    return replace(table, rows=rows) if rows != table.rows else table


def seed_matrix(profile, block, stored, directory=None, *, year=None):
    existing = _matrix_in(block)
    if existing:
        return hospital_matrix(profile, existing, directory)
    # A saved report pins its own matrix. A fresh report may reuse the exact
    # annual store, but an old unscoped store stays explicitly year-unrecorded.
    sites = _year_sites(stored, None)
    if year is not None:
        year_matrix_reference(year)
        selected = {f.key for f in profile.facilities}
        prior = dict(sites)
        # Fresh new-year reports may reuse earlier annual rosters/columns as
        # uncompleted requirements, never earlier status claims or future years.
        for value in sorted(stored.get("years", {})):
            prior_year = matrix_year(YEAR_MATRIX_PREFIX + value)
            if prior_year >= year:
                continue
            prior.update({k: v for k, v in _year_sites(stored, prior_year).items() if k in selected})
        exact = _year_sites(stored, year)
        annual = bool(selected & exact.keys())
        inherited = any(prior.get(k) != sites.get(k) for k in selected)
        if annual or inherited:
            unscoped = seed_matrix(profile, block, {"sites": prior}, directory)
            return matrix_for_year(profile, unscoped, stored, year, directory)
    reference = year_matrix_reference(year) if year is not None and not sites else MATRIX_REF
    columns, rows = [], []
    eligible, excluded = _directory_people(profile, directory)
    selected = {f.key: f for f in profile.facilities}
    for key in selected:
        columns.extend(sites.get(key, {}).get("columns", ()))
    columns = list(dict.fromkeys(columns))
    for key, facility in selected.items():
        site = sites.get(key, {})
        known = set()
        for row in site.get("rows", ()):
            if (_person(row[0]), _person(facility.title)) in excluded:
                continue
            values = dict(zip(site.get("columns", ()), row[1:]))
            rows.append((row[0], facility.title, *(values.get(c, "Not recorded") for c in columns)))
            known.add(_person(row[0]))
        for name in eligible.get(key, ()):
            if _person(name) not in known:
                rows.append((name, facility.title, *("Not recorded" for _ in columns)))
                known.add(_person(name))
    return validate_matrix(ReportTable(("Team member", "Site", *columns), tuple(rows), reference))


def matrix_differs_from_current_standing(profile, block, stored, directory=None):
    """Flag an older report matrix before it can replace newer shared rows.

    Reports retain their original saved matrix. A fresh editor must explicitly
    load newer standing information when the report's matrix disagrees with
    the current selected-site records; a new global revision is not proof the
    older table can safely overwrite the shared roster.
    """
    previous = _matrix_in(block)
    if previous is None:
        return False
    year = matrix_year(previous.reference)
    if not any(f.key in _year_sites(stored, year) for f in profile.facilities):
        return False
    without = replace(block, extra_tables=tuple(t for t in block.extra_tables if not is_matrix_reference(t.reference)))
    current = seed_matrix(profile, without, stored, directory, year=year)
    return seed_matrix(profile, block, stored, directory) != current


def session_row_tokens(table):
    """Read row snapshot identities without migrating or writing old reports.

    Legacy rows have deterministic tokens bound to the exact old collection.
    An explicit mutation retains those tokens for its untouched rows and uses
    a fresh token for an added/changed row. A later removal/recreation therefore
    cannot accidentally match an editor opened on the previous incarnation.
    """
    if table is None:
        return ()
    tokens = getattr(table, "row_tokens", ())
    if (len(tokens) == len(table.rows)
            and all(isinstance(token, str) and token for token in tokens)
            and len(set(tokens)) == len(tokens)):
        return tokens
    baseline = sha256(library._json({"columns": table.columns, "rows": table.rows,
        "reference": table.reference, "unverified_tokens": tokens})).hexdigest()
    return tuple("legacy:" + sha256(f"{baseline}:{index}".encode()).hexdigest()
                 for index in range(len(table.rows)))


def remove_event(table, index):
    tokens = session_row_tokens(table)
    return TrainingSessionTable(table.columns,
        tuple(row for n, row in enumerate(table.rows) if n != index), table.reference,
        tuple(token for n, token in enumerate(tokens) if n != index))


def replace_event(table, index, row):
    if table.rows[index] == row:
        return table
    tokens = session_row_tokens(table)
    return TrainingSessionTable(table.columns,
        tuple(row if n == index else saved for n, saved in enumerate(table.rows)), table.reference,
        tuple(uuid4().hex if n == index else token for n, token in enumerate(tokens)))


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
    if row in rows:
        return table
    return TrainingSessionTable(table.columns if table else EVENT_COLUMNS,
        (*rows, row), table.reference if table else EVENT_REF,
        (*session_row_tokens(table), uuid4().hex))


def apply_tables(block, matrix, events):
    # None means the standing matrix could not be loaded/validated, not deletion.
    tables = tuple(t for t in block.extra_tables if t.reference != EVENT_REF
                   and not (matrix is not None and is_matrix_reference(t.reference)))
    if matrix is not None and len(matrix.columns) > 2 and matrix.rows:
        tables += (validate_matrix(matrix),)
    if events and events.rows:
        tables += (events,)
    if tables == block.extra_tables:
        return block
    return replace(block, source="This month", extra_tables=tables, reviewed_fingerprint="", client_reviewed_fingerprint="")


def training_block(blocks):
    return blocks.get("training_summary", ResolvedBlock("training_summary", "This month"))


def new_month_training(block):
    """Carry standing requirements without carrying monthly completion tables.

    Role references distinguish the standing matrix from monthly sessions.
    Unidentified imported schemas keep the existing empty-schema rollover
    behavior; column names alone do not establish ownership. Historical
    snapshots and the shared Training store are never changed here.
    """
    tables = tuple(
        table if is_matrix_reference(table.reference) else ReportTable(table.columns, (), "")
        for table in block.extra_tables if table.reference != EVENT_REF
    )
    return ResolvedBlock(
        block.key, "Omit" if block.source == "Omit" else "This month",
        photos_per_page=block.photos_per_page, extra_tables=tables,
    )


def events_for_period(block, period):
    """A standing completion is not evidence that training happened this month."""
    table = next((t for t in block.extra_tables if t.reference == EVENT_REF), None)
    if table is None:
        return None
    indices = []
    for index, row in enumerate(table.rows):
        try:
            when = date.fromisoformat(row[1])
        except (ValueError, IndexError):
            continue
        if period.start <= when <= period.end:
            indices.append(index)
    if len(indices) == len(table.rows):
        return table
    changes = {"rows": tuple(table.rows[index] for index in indices)}
    if isinstance(table, TrainingSessionTable):
        tokens = session_row_tokens(table)
        changes["row_tokens"] = tuple(tokens[index] for index in indices)
    return replace(table, **changes)
