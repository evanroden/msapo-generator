"""Review an entire contact workbook without treating contracts as facilities.

Plans are immutable snapshots. Saving is revision guarded per contract, preserves
unmentioned records, and reports partial outcomes rather than claiming a batch
transaction. Only explicit aliases and exact names link saved identities.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import re

from app import contracts as contract_catalog
from app import monthly_report_directory as directory
from app import monthly_report_library as library
from app.config import FACILITIES
from app.monthly_report_model import ReportProfile


def _identity(value):
    return " ".join(str(value).casefold().split())


# Reviewed spelling relationships only; never substring/fuzzy membership.
CONTRACT_ALIASES = {
    "OCHSNER JEFFERSON": "Ochsner Jefferson", "OCHSNER GROVE": "Ochsner Grove",
    "OCHSNER BAPTIST": "Ochsner Baptist", "ENMU (Eastern New Mexico University)": "ENMU",
    "SHAW BLDG": "Shaw", "EAMC (Opelika/Valley)": "EAMC",
    "MIDLAND MEMORIAL HOSPITAL": "Midland Memorial Health",
    "LCMC CHILDREN'S HOSPITAL": "LCMC - Children's",
    "LCMC TOURO INFIRMARY & WOLDENBERG VILLAGE": "LCMC - Touro/Woldenberg",
    "LCMC EAST JEFFERSON MEDICAL CENTER": "LCMC - East Jefferson",
    "LCMC WEST JEFFERSON MEDICAL CENTER": "LCMC - West Jefferson",
    "UMC (Universtiy Medical Ctr)": "UMC",
    "LCMC AUDUBON RETIREMENT VILLAGE - HANKEL": "LCMC - Hainkel House",
    "LCMC PECHE - LAKEVIEW HOSPITAL & LAKESIDE HOSPITAL": "LCMC - Lakeside/Lakeview",
    "TULANE UNIVERSITY": "Tulane", "HAMPTON UNIVERSITY": "Hampton",
    "BAPTIST AR": "Baptist AR", "UNO (The University of New Orleans)": "UNO",
    "CFNI (Community Foundation of NW Indiana)": "CFNI",
    "MAURY REGIONAL MEDICAL CENTER": "Maury", "CONWAY MEDICAL CENTER": "Conway",
    "HMH (Hackensack Meridian Health)": "Hackensack", "UNITY": "Unity Health",
    "Abilene Christian University": "CFC-ACU", "Novant Health": "NOVANT",
    "Clinton Foundation": "Clinton", "Rochester": "Rochester Regional Health",
    "Memorial Health IL": "Memorial IL", "Permian Basin (MCH)": "PBBH",
    "Touro": "LCMC - Touro/Woldenberg", "Peche": "LCMC - Lakeside/Lakeview",
    "Adventist": "Adventist Health", "PIH": "PIH Health",
    "Rochester Regional": "Rochester Regional Health", "Tufts MC": "Tufts",
    "MaineHealth": "Maine Health", "Multicare WA": "Multicare",
}

SITE_ALIASES = {
    "CHRISTUS": {"St. Michael Hospital": "St. Michael", "St. Francis Cabrini Hospital": "St. Francis Cabrini",
                  "Santa Rosa San Marcos Hospital": "Santa Rosa San Marcos"},
    "Hackensack": {"HACKENSTACK UNIVERSITY MEDICAL CENTER": "Hackensack University Medical Center"},
    "Unity Health": {"WHITE COUNTY MEDICAL CENTER": "White County", "UNITY HEALTH - JACKSONVILLE": "Jacksonville",
                     "UNITY HEALTH - SPECIALTY CARE": "Specialty Care", "UNITY HEALTH - NEWPORT": "Newport"},
    "Adventist Health": {"Adventist Health Montebello": "Adventist Health White Memorial Montebello",
                        "Adventist Health Ukiah": "Adventist Health Ukiah Valley"},
    "PIH Health": {"GOOD SAMARITAN": "Good Samaritan Hospital", "WHITTIER": "Whittier Hospital", "DOWNEY": "Downey Hospital"},
    "NOVANT": {"New Hanover Regional MC": "New Hanover Regional Medical Center", "Bruswick Medical Center": "Brunswick Medical Center",
               "New Hanover Orthopedic": "New Hanover Orthopedic Hospital"},
    "Rochester Regional Health": {"Clifton Springs Hospital": "Clifton Springs Hospital & Clinic",
                                  "Canton Potsdam Hospital": "Canton-Potsdam Hospital"},
}

HOLD_CONTRACTS = {"hartford health": "The Hartford detail tab repeats Multicare site headings. Confirm contract and site ownership before importing Hartford records."}


@dataclass(frozen=True)
class ContactRows:
    role: str
    name_row: int
    phone_row: int
    email_row: int


@dataclass(frozen=True)
class WorksheetMapping:
    worksheet: str
    scope: str
    header_row: int
    label_column: int
    address_row: int
    groups: tuple[ContactRows, ...]
    targets: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class WorkbookExclusion:
    worksheet: str
    reason: str
    column: str = ""


@dataclass(frozen=True)
class ProposedChange:
    """A saved detail the workbook changes; the saved value stays unless accepted.

    A contact change replaces ``before`` with ``after`` in its scope; an
    address change (``before`` is None) sets that site's address.
    """
    id: str
    site_key: str
    applies_to: str
    detail: str
    saved: str
    workbook: str
    before: directory.DirectoryContact | None = None
    after: directory.DirectoryContact | None = None
    address: str = ""


@dataclass(frozen=True)
class ContractPlan:
    contract: str
    expected_revision: int
    sites: tuple[directory.DirectorySite, ...]
    contract_contacts: tuple[directory.DirectoryContact, ...]
    source_sheets: tuple[str, ...]
    conflicts: tuple[str, ...] = ()
    changed: bool = True
    existing: bool = False
    imported_site_count: int = 0
    imported_contact_count: int = 0
    new_contract: bool = False
    changes: tuple[ProposedChange, ...] = ()

    @property
    def can_save(self):
        return (self.changed or bool(self.changes)) and not self.conflicts


@dataclass(frozen=True)
class WorkbookPlan:
    workbook_sha256: str
    entries: tuple[ContractPlan, ...]
    notices: tuple[str, ...] = ()
    exclusions: tuple[WorkbookExclusion, ...] = ()
    mappings: tuple[WorksheetMapping, ...] = ()

    @property
    def contract_count(self):
        return len(self.entries)

    @property
    def site_count(self):
        return sum(e.imported_site_count for e in self.entries)

    @property
    def contact_count(self):
        return sum(e.imported_contact_count for e in self.entries)


@dataclass(frozen=True)
class BatchSaveResult:
    saved: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    blocked: tuple[tuple[str, str], ...] = ()
    failed: tuple[tuple[str, str], ...] = ()
    revisions: tuple[tuple[str, int], ...] = ()
    not_created: tuple[str, ...] = ()


def _sheet_title(sheet):
    return re.sub(r"\s+Sites$", "", re.sub(r"^\d+\s*[-.]\s*", "", sheet.name), flags=re.I).strip()


def _canonical(name, aliases, known):
    target = aliases.get(_identity(name), " ".join(name.split()))
    return known.get(_identity(target), target)


def worksheet_contract(sheet, *, contract_aliases=None):
    """The contract a detail tab names exactly or by reviewed alias, else "".

    A reviewed alias gives its canonical name even before that contract has a
    catalog entry or saved directory, as batch import saves it.
    """
    aliases = {_identity(k): v for k, v in (CONTRACT_ALIASES | (contract_aliases or {})).items()}
    known = {_identity(n): n for n in (*contract_catalog.contract_names(), *directory.directory_contracts())}
    title = _sheet_title(sheet)
    return _canonical(title, aliases, known) if _identity(title) in aliases or _identity(title) in known else ""


def site_alias_targets(contract):
    """Reviewed workbook spellings of a contract's sites, keyed by normalized spelling."""
    return {_identity(k): v for k, v in SITE_ALIASES.get(contract, {}).items()}


def _mapping(sheet):
    header, label, address, groups = directory.suggest_matrix(sheet)
    return header, label, address, groups


def _sites_or_exclusion(workbook, sheet, mapping, exclusions):
    """One unreadable worksheet is excluded by name; the rest of the batch continues."""
    try:
        return directory.matrix_sites(workbook, sheet, *mapping)
    except ValueError as exc:
        exclusions.append(WorkbookExclusion(
            sheet.name, f"Could not read this worksheet's site or contract columns ({exc}) Review it separately."))
        return None


def _public_mapping(sheet, scope, mapping, targets):
    header, label, address, groups = mapping
    return WorksheetMapping(sheet.name, scope, header, label, address, tuple(
        ContactRows(g["Role"], int(g["Name row"]), int(g["Phone row"]), int(g["Email row"]))
        for g in groups if g.get("Use")), tuple(targets))


_MAX_SOURCE_TEXT = 1000


def _source_union(*sources):
    """Join provenance references, bounded below the directory review budget.

    The first reference and the newest ones that fit are kept; each saved
    directory revision still holds the complete earlier chain.
    """
    parts = list(dict.fromkeys(s for source in sources for s in source.split(";") if s))
    if len(";".join(parts)) <= _MAX_SOURCE_TEXT or len(parts) < 2:
        return ";".join(parts)
    first, kept, size = parts[0], [], len(parts[0])
    for part in reversed(parts[1:]):
        if size + 1 + len(part) > _MAX_SOURCE_TEXT:
            break
        kept.insert(0, part)
        size += 1 + len(part)
    return ";".join((first, *kept))


def _same(field, value, other):
    return directory.same_contact_value(field, value, other)


def _same_values(old, contact):
    return all(_same(f, getattr(old, f), getattr(contact, f)) for f in ("name", "phone", "email"))


def _coalesce_incoming_contacts(incoming, context):
    """Join complementary rows for one named person; contradictions need review."""
    result, positions, conflicts = [], {}, []
    for contact in incoming:
        identity = (_identity(contact.role), _identity(contact.name))
        index = positions.get(identity) if identity[1] else None
        if index is None:
            if identity[1]:
                positions[identity] = len(result)
            result.append(contact)
            continue
        old = result[index]
        changed = [field for field in ("phone", "email")
                   if getattr(old, field).strip() and getattr(contact, field).strip()
                   and not _same(field, getattr(old, field), getattr(contact, field))]
        if changed:
            conflicts.append(
                f"{context}: {old.role} ({old.name}) has conflicting {', '.join(changed)} "
                "values in this workbook. Review that person before saving.")
            continue
        filled = {field: getattr(old, field) if getattr(old, field).strip() else getattr(contact, field)
                  for field in ("phone", "email")}
        if any(filled[field] != getattr(old, field) for field in filled):
            result[index] = replace(old, **filled, source=_source_union(old.source, contact.source))
    return tuple(result), tuple(conflicts)


def _contact_text(contact):
    return " · ".join(value for value in (contact.name, contact.phone, contact.email) if value.strip()) or "(blank)"


def _merge_contacts(existing, incoming, context):
    """Fill omissions for the same person; differing populated fields are proposed changes.

    Rows for one named person are coalesced first. Distinct incoming people
    are compared with saved contacts only, so people sharing a role are kept.
    When a role repeats, people are matched by name. A new named person is an
    addition only while every saved person in that role is still listed;
    otherwise it may be a replacement and needs review. A saved contact whose
    name, phone or email differs is kept, with the workbook version returned
    as a (saved, workbook) change to accept explicitly; a different person
    never inherits the saved phone or email.
    """
    incoming, incoming_conflicts = _coalesce_incoming_contacts(incoming, context)
    result, conflicts, changes = list(existing), list(incoming_conflicts), []
    saved = len(result)
    for contact in incoming:
        role = _identity(contact.role)
        if any(_identity(c.role) == role and _same_values(c, contact) for c in result):
            # The same values from a re-saved workbook are not new information:
            # keep the saved record and its provenance so the import is a no-op.
            continue
        matches = [i for i in range(saved) if _identity(result[i].role) == role]
        if not matches:
            result.append(contact)
            continue
        listed = [c for c in incoming if _identity(c.role) == role]
        if len(matches) > 1 or len(listed) > 1:
            name = _identity(contact.name)
            people = [i for i in matches if name and _identity(result[i].name) == name]
            still_listed = all(any(_identity(c.name) == _identity(result[i].name) for c in listed)
                               for i in matches if result[i].name.strip())
            if not people and name and still_listed:
                result.append(contact)
                continue
            if len(people) != 1:
                conflicts.append(f"{context}: more than one saved contact has role {contact.role}; review that role separately.")
                continue
            matches = people
        i, old = matches[0], result[matches[0]]
        changed_fields = [f for f in ("name", "phone", "email") if getattr(old, f).strip() and getattr(contact, f).strip()
                          and not _same(f, getattr(old, f), getattr(contact, f))]
        # A phone-only record is not proof of the incoming named person's identity.
        if contact.name and not old.name and (old.phone or old.email):
            matching_id = any(getattr(contact, f) and _same(f, getattr(contact, f), getattr(old, f))
                              for f in ("phone", "email"))
            if not matching_id:
                changed_fields.append("contact identity")
        if changed_fields:
            # A blank name is an omitted detail, not a request to replace the person.
            same_person = not contact.name.strip() or (old.name.strip() and _same("name", old.name, contact.name))
            after = (replace(old, **{f: getattr(contact, f) or getattr(old, f) for f in ("phone", "email")},
                             source=_source_union(old.source, contact.source)) if same_person else contact)
            changes.append((old, after))
            continue
        filled = {f: getattr(old, f) or getattr(contact, f) for f in ("name", "phone", "email")}
        if all(filled[f] == getattr(old, f) for f in filled):
            continue  # a subset of the saved values adds nothing; keep it as saved
        result[i] = replace(old, **filled, source=_source_union(old.source, contact.source))
    return tuple(result), tuple(conflicts), tuple(changes)


def _catalog_sites(contract):
    if contract != contract_catalog.RRH_CONTRACT:
        return tuple(directory.DirectorySite(re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:60], title)
                     for title in contract_catalog.sites_for_contract(contract))
    return tuple(directory.DirectorySite(key, value["name"],
                 (FACILITIES["st_marys"]["name"],) if key == "unity_specialty" and "st_marys" in FACILITIES else ())
                 for key, value in FACILITIES.items() if not (key == "st_marys" and "unity_specialty" in FACILITIES))


def _people(site):
    return {_identity(c.name) for c in site.contacts if c.name.strip()}


def _repeated_sites(details):
    """Site columns whose heading also appears on another contract's worksheet.

    A copy lists the same people, or one side lists none to tell them apart;
    same-named sites whose people differ belong to their own contracts.
    Columns are grouped by heading and people, so a heading repeated across
    many worksheets stays cheap to check.
    """
    by_title = {}
    for sheet, contract, _, sites in details:
        for site in sites:
            by_title.setdefault(_identity(site.title), []).append((sheet.name, contract, site, frozenset(_people(site))))
    repeated = {}
    for entries in by_title.values():
        if len({contract for _, contract, _, _ in entries}) < 2:
            continue
        sheets, every = {}, {}
        for name, contract, _, people in entries:
            sheets.setdefault(people, {}).setdefault(contract, {})[name] = None
            every.setdefault(contract, {})[name] = None
        for name, contract, site, people in entries:
            pools = (sheets[people], sheets.get(frozenset(), {})) if people else (every,)
            others = dict.fromkeys(other for pool in pools for owner, names in pool.items()
                                   if owner != contract for other in names)
            if others:
                repeated[site.source] = tuple(others)
    return repeated


def _owned(current, contract, site, aliases):
    """The catalog, the saved directory or a reviewed site alias already places this site in the contract.

    An inactive saved site, and the catalog entry it uniquely retires, is not
    evidence; this is the directory's own available-sites rule.
    """
    if _identity(site.title) in aliases:
        return True
    catalog = tuple(s.facility for s in _catalog_sites(contract))
    names = directory.facility_names(site)
    return any(names & directory.facility_names(f) for f in directory.available_sites(catalog, current))


def _change(contract, site_key, applies_to, detail, saved, workbook, before=None, after=None, address=""):
    identity = hashlib.sha256(repr((contract, site_key, detail, saved, workbook)).encode()).hexdigest()[:16]
    return ProposedChange(identity, site_key, applies_to, detail, saved, workbook, before, after, address)


def _contact_changes(contract, site_key, applies_to, pairs):
    return [_change(contract, site_key, applies_to, before.role, _contact_text(before), _contact_text(after), before, after)
            for before, after in pairs]


def _merge_sites(contract, existing, incoming, aliases):
    result, conflicts, changes = list(existing), [], []
    catalog = _catalog_sites(contract)
    used = set()
    for site in incoming:
        target = aliases.get(_identity(site.title), site.title)
        names = directory.facility_names(site) | {_identity(target)}
        saved_matches = [s for s in result if names & directory.facility_names(s)]
        catalog_matches = [s for s in catalog if names & directory.facility_names(s)]
        matches = saved_matches or catalog_matches
        if len(matches) > 1:
            conflicts.append(f"{site.title}: more than one site matches its name or reviewed alias.")
            continue
        old = matches[0] if matches else None
        key = old.key if old else site.key
        if key in used:
            conflicts.append(f"{site.title}: two workbook columns resolve to one site; review them separately.")
            continue
        used.add(key)
        if old:
            contacts, contact_conflicts, contact_changes = _merge_contacts(old.contacts, site.contacts, old.title)
            conflicts.extend(contact_conflicts)
            changes.extend(_contact_changes(contract, old.key, old.title, contact_changes))
            if old.address and site.address and _identity(old.address) != _identity(site.address):
                changes.append(_change(contract, old.key, old.title, "Address", old.address, site.address,
                                       address=site.address))
            titles = tuple(dict.fromkeys((*old.aliases, *site.aliases, site.title, target)))
            merged = replace(old, aliases=tuple(n for n in titles if _identity(n) != _identity(old.title)),
                             address=old.address or site.address, contacts=contacts)
            # Only a real change records the new workbook as provenance.
            if merged != old:
                merged = replace(merged, source=_source_union(old.source, site.source))
        else:
            # Source-based keys remain stable on exact re-import; later versions
            # match this explicit title/alias rather than manufacturing identities.
            contacts, contact_conflicts, _ = _merge_contacts((), site.contacts, site.title)
            conflicts.extend(contact_conflicts)
            merged = replace(site, contacts=contacts, title=target, aliases=tuple(dict.fromkeys((*site.aliases, site.title)))
                             if _identity(target) != _identity(site.title) else site.aliases)
        index = next((i for i, s in enumerate(result) if s.key == key), None)
        if index is None:
            result.append(merged)
        else:
            result[index] = merged
    if result:
        try:
            ReportProfile(contract, "directory-plan", "Directory validation", tuple(s.facility for s in result), "multi_site")
        except ValueError as exc:
            conflicts.append(str(exc))
    return tuple(result), tuple(conflicts), tuple(changes)


def prepare_workbook(workbook, *, contract_aliases=None, site_aliases=None):
    """Produce a review snapshot; reading/planning never writes directories."""
    aliases = {_identity(k): v for k, v in (CONTRACT_ALIASES | (contract_aliases or {})).items()}
    known = {_identity(n): n for n in (*contract_catalog.contract_names(), *directory.directory_contracts())}
    site_maps = {contract: {_identity(k): v for k, v in mapping.items()}
                 for contract, mapping in (SITE_ALIASES | (site_aliases or {})).items()}
    records, exclusions, mappings, proposed, states = {}, [], [], set(), {}

    def saved_state(contract):
        # One read per contract: ownership evidence and the plan's expected
        # revision come from the same directory state.
        if contract not in states:
            try:
                states[contract] = directory.load_directory(contract, include_archived=True), None
            except (ValueError, library.LibraryError) as exc:
                states[contract] = None, exc
        return states[contract]

    def bucket(contract):
        return records.setdefault(contract, {"sites": [], "contacts": [], "sheets": []})

    def record(contract, sheet, sites=(), contacts=()):
        item = bucket(contract)
        item["sites"].extend(sites)
        item["contacts"].extend(contacts)
        if sheet.name not in item["sheets"]:
            item["sheets"].append(sheet.name)

    # Only an explicitly labelled active-contract summary can create contract
    # records. Index and Totals sheets are never interpreted as facilities.
    for sheet in workbook.sheets:
        if not sheet.summary:
            continue
        if _identity(_sheet_title(sheet)) != "active contracts" or sheet.hidden:
            exclusions.append(WorkbookExclusion(sheet.name, "Index, totals, hidden, or unclassified summary worksheet; no contacts imported."))
            continue
        mapping = _mapping(sheet)
        if not mapping[3]:
            exclusions.append(WorkbookExclusion(sheet.name, "No contact-role rows were found."))
            continue
        extracted = _sites_or_exclusion(workbook, sheet, mapping, exclusions)
        if extracted is None:
            continue
        targets = []
        for column in extracted:
            contract = _canonical(column.title, aliases, known)
            coordinate = column.source.rsplit("!", 1)[-1]
            if re.search(r"\b(inactive|closed|terminated)\b", column.title, re.I):
                exclusions.append(WorkbookExclusion(sheet.name, "Marked inactive or closed in the workbook; not activated.", coordinate))
            elif _identity(contract) in HOLD_CONTRACTS:
                exclusions.append(WorkbookExclusion(sheet.name, HOLD_CONTRACTS[_identity(contract)], coordinate))
            elif not column.contacts:
                exclusions.append(WorkbookExclusion(sheet.name, "No populated contact records in this contract column.", coordinate))
            else:
                # A heading that is not a catalog, saved or reviewed-alias
                # contract is only a proposal; saving never creates it implicitly.
                if _identity(contract) not in known and _identity(column.title) not in aliases:
                    proposed.add(contract)
                known.setdefault(_identity(contract), contract)
                record(contract, sheet, contacts=column.contacts)
                targets.append((coordinate, contract))
        mappings.append(_public_mapping(sheet, "contract", mapping, targets))

    details = []
    for sheet in workbook.sheets:
        if sheet.summary:
            continue
        contract = _canonical(_sheet_title(sheet), aliases, known)
        reason = HOLD_CONTRACTS.get(_identity(contract))
        if sheet.hidden:
            reason = "Hidden worksheet; review it separately before importing."
        if not reason and _identity(contract) not in known and _identity(_sheet_title(sheet)) not in aliases:
            reason = "The worksheet contract does not exactly match an active contract or reviewed alias. Map it separately."
        if reason:
            exclusions.append(WorkbookExclusion(sheet.name, reason))
            continue
        mapping = _mapping(sheet)
        if not mapping[3]:
            exclusions.append(WorkbookExclusion(sheet.name, "No contact-role rows were found."))
            continue
        sites = _sites_or_exclusion(workbook, sheet, mapping, exclusions)
        if sites is None:
            continue
        if not any(s.contacts for s in sites):
            exclusions.append(WorkbookExclusion(sheet.name, "No populated contact records; this appears to be an unfinished template."))
            continue
        details.append((sheet, contract, mapping, sites))
    # A copied heading is not proof of membership: exclude that site column
    # unless the contract already owns the site, and keep the tab's other sites.
    repeated = _repeated_sites(details)
    for sheet, contract, mapping, sites in details:
        kept = []
        for site in sites:
            others = repeated.get(site.source)
            if others and not _owned(saved_state(contract)[0], contract, site, site_maps.get(contract, {})):
                exclusions.append(WorkbookExclusion(sheet.name, f"{site.title} also appears on worksheet {', '.join(others)}. "
                    "Copied worksheet headings are not proof of membership; confirm which contract owns this site, "
                    "then import it separately.", site.source.rsplit("!", 1)[-1]))
            else:
                kept.append(site)
        if kept:
            record(contract, sheet, sites=kept)
            mappings.append(_public_mapping(sheet, "site", mapping, [(s.source.rsplit("!", 1)[-1], s.title) for s in kept]))

    entries = []
    for contract, item in sorted(records.items(), key=lambda pair: pair[0].casefold()):
        conflicts = []
        current, error = saved_state(contract)
        if error:
            conflicts.append(str(error))
        if current and current.archived:
            conflicts.append("This directory is archived. Restore and review it before importing new contacts.")
        old_sites = current.sites if current else ()
        old_contacts = current.contract_contacts if current else ()
        sites, site_conflicts, site_changes = _merge_sites(contract, old_sites, tuple(item["sites"]), site_maps.get(contract, {}))
        contacts, contact_conflicts, contact_changes = _merge_contacts(old_contacts, tuple(item["contacts"]),
                                                                       contract + " (contract-wide)")
        conflicts.extend((*site_conflicts, *contact_conflicts))
        changed = sites != old_sites or contacts != old_contacts
        entries.append(ContractPlan(contract, current.revision if current else 0, sites, contacts, tuple(item["sheets"]),
                       tuple(conflicts), changed, current is not None, len(item["sites"]),
                       len(item["contacts"]) + sum(len(s.contacts) for s in item["sites"]), contract in proposed,
                       (*_contact_changes(contract, "", "Contract-wide", contact_changes), *site_changes)))
    return WorkbookPlan(workbook.sha256, tuple(entries), workbook.notices, tuple(exclusions), tuple(mappings))


def _apply_changes(entry, accepted):
    """The reviewed plan with the accepted workbook values in place of the saved ones."""
    def contacts(values, key):
        result = list(values)
        for change in accepted:
            if change.site_key == key and change.before is not None:
                if change.before not in result:
                    raise ValueError("A selected change no longer matches the preview. Refresh and review it again.")
                result[result.index(change.before)] = change.after
        return tuple(result)
    addresses = {c.site_key: c.address for c in accepted if c.before is None}
    sites = tuple(replace(site, contacts=contacts(site.contacts, site.key), address=addresses.get(site.key, site.address))
                  for site in entry.sites)
    return sites, contacts(entry.contract_contacts, "")


def save_workbook_plan(plan, raw, *, actor, confirmed, contracts=None, create=(), accept=()):
    """Apply the reviewed snapshot; each successful contract has its own revision.

    A proposed new contract is created only when it is also named in ``create``;
    confirming the import alone never adds a contract to the directory. A
    proposed change replaces a saved value only when its id is in ``accept``.
    """
    actor = library._confirmation(actor, confirmed)
    if hashlib.sha256(raw).hexdigest() != plan.workbook_sha256:
        raise ValueError("The uploaded workbook changed. Read it again and review a new preview.")
    selected = set(contracts) if contracts is not None else {e.contract for e in plan.entries}
    if selected - {e.contract for e in plan.entries} or set(create) - {e.contract for e in plan.entries if e.new_contract}:
        raise ValueError("An unreviewed contract was selected. Refresh and review the preview.")
    if set(accept) - {c.id for e in plan.entries for c in e.changes}:
        raise ValueError("An unreviewed change was selected. Refresh and review the preview.")
    with directory._batch_reads(raw):
        return _save_selected_entries(plan, raw, actor, selected, set(create), set(accept))


def _save_selected_entries(plan, raw, actor, selected, create, accept):
    saved, unchanged, blocked, failed, revisions, not_created = [], [], [], [], [], []
    for entry in plan.entries:
        if entry.contract not in selected:
            continue
        if entry.new_contract and entry.contract not in create:
            not_created.append(entry.contract)
            continue
        if entry.conflicts:
            blocked.append((entry.contract, " ".join(entry.conflicts)))
            continue
        try:
            current = directory.load_directory(entry.contract, include_archived=True)
            if entry.expected_revision != (current.revision if current else 0):
                raise library.RevisionConflict("This directory changed after the preview. Refresh and review it again.")
            accepted = [change for change in entry.changes if change.id in accept]
            if not entry.changed and not accepted:
                unchanged.append(entry.contract)
                continue
            sites, contacts = _apply_changes(entry, accepted)
            result = directory.save_directory(entry.contract, sites, contract_contacts=contacts,
                expected_revision=entry.expected_revision, actor=actor, confirmed=True, raw=raw,
                source_sha256=plan.workbook_sha256, source_sheet=entry.source_sheets[0], action="workbook-import")
            # Verify the just-written durable head rather than assuming all
            # contracts completed because an earlier one succeeded.
            readback = directory.load_directory(entry.contract)
            if readback != result:
                raise library.LibraryError("The saved revision could not be verified. Reload this contract before retrying.")
            saved.append(entry.contract)
            revisions.append((entry.contract, result.revision))
        except library.RevisionConflict as exc:
            blocked.append((entry.contract, str(exc)))
        except (ValueError, OSError, library.LibraryError) as exc:
            failed.append((entry.contract, str(exc)))
    return BatchSaveResult(tuple(saved), tuple(unchanged), tuple(blocked), tuple(failed), tuple(revisions),
                           tuple(not_created))
