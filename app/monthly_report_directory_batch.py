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

    @property
    def can_save(self):
        return self.changed and not self.conflicts


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


def _sheet_title(sheet):
    return re.sub(r"\s+Sites$", "", re.sub(r"^\d+\s*[-.]\s*", "", sheet.name), flags=re.I).strip()


def _canonical(name, aliases, known):
    target = aliases.get(_identity(name), " ".join(name.split()))
    return known.get(_identity(target), target)


def _mapping(sheet):
    header, label, address, groups = directory.suggest_matrix(sheet)
    return header, label, address, groups


def _public_mapping(sheet, scope, mapping, targets):
    header, label, address, groups = mapping
    return WorksheetMapping(sheet.name, scope, header, label, address, tuple(
        ContactRows(g["Role"], int(g["Name row"]), int(g["Phone row"]), int(g["Email row"]))
        for g in groups if g.get("Use")), tuple(targets))


def _source_union(*sources):
    return ";".join(dict.fromkeys(s for source in sources for s in source.split(";") if s))


def _merge_contacts(existing, incoming, context):
    """Fill omissions for the same person; conflicting populated fields block."""
    result, conflicts = list(existing), []
    for contact in incoming:
        matches = [i for i, old in enumerate(result) if _identity(old.role) == _identity(contact.role)]
        if not matches:
            result.append(contact)
            continue
        exact = [i for i in matches if all(_identity(getattr(result[i], f)) == _identity(getattr(contact, f))
                                         for f in ("name", "phone", "email"))]
        if len(exact) == 1:
            i = exact[0]
            result[i] = replace(result[i], source=_source_union(result[i].source, contact.source))
            continue
        if len(matches) != 1:
            conflicts.append(f"{context}: more than one saved contact has role {contact.role}; review that role separately.")
            continue
        i, old = matches[0], result[matches[0]]
        changed_fields = [f for f in ("name", "phone", "email") if getattr(old, f).strip() and getattr(contact, f).strip()
                          and _identity(getattr(old, f)) != _identity(getattr(contact, f))]
        # A phone-only record is not proof of the incoming named person's identity.
        if contact.name and not old.name and (old.phone or old.email):
            matching_id = any(getattr(contact, f) and _identity(getattr(contact, f)) == _identity(getattr(old, f))
                              for f in ("phone", "email"))
            if not matching_id:
                changed_fields.append("contact identity")
        if changed_fields:
            conflicts.append(f"{context}: {contact.role} differs in {', '.join(changed_fields)}. Saved values were retained.")
            continue
        result[i] = replace(old, **{f: getattr(old, f) or getattr(contact, f) for f in ("name", "phone", "email")},
                            source=_source_union(old.source, contact.source))
    return tuple(result), tuple(conflicts)


def _catalog_sites(contract):
    if contract != contract_catalog.RRH_CONTRACT:
        return tuple(directory.DirectorySite(re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:60], title)
                     for title in contract_catalog.sites_for_contract(contract))
    return tuple(directory.DirectorySite(key, value["name"],
                 (FACILITIES["st_marys"]["name"],) if key == "unity_specialty" and "st_marys" in FACILITIES else ())
                 for key, value in FACILITIES.items() if not (key == "st_marys" and "unity_specialty" in FACILITIES))


def _merge_sites(contract, existing, incoming, aliases):
    result, conflicts = list(existing), []
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
            contacts, contact_conflicts = _merge_contacts(old.contacts, site.contacts, old.title)
            conflicts.extend(contact_conflicts)
            if old.address and site.address and _identity(old.address) != _identity(site.address):
                conflicts.append(f"{old.title}: the workbook address differs from the saved address. Saved values were retained.")
            titles = tuple(dict.fromkeys((*old.aliases, *site.aliases, site.title, target)))
            merged = replace(old, aliases=tuple(n for n in titles if _identity(n) != _identity(old.title)),
                             address=old.address or site.address, contacts=contacts,
                             source=_source_union(old.source, site.source))
        else:
            # Source-based keys remain stable on exact re-import; later versions
            # match this explicit title/alias rather than manufacturing identities.
            merged = replace(site, title=target, aliases=tuple(dict.fromkeys((*site.aliases, site.title)))
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
    return tuple(result), tuple(conflicts)


def prepare_workbook(workbook, *, contract_aliases=None, site_aliases=None):
    """Produce a review snapshot; reading/planning never writes directories."""
    aliases = {_identity(k): v for k, v in (CONTRACT_ALIASES | (contract_aliases or {})).items()}
    known = {_identity(n): n for n in (*contract_catalog.contract_names(), *directory.directory_contracts())}
    site_maps = {contract: {_identity(k): v for k, v in mapping.items()}
                 for contract, mapping in (SITE_ALIASES | (site_aliases or {})).items()}
    records, exclusions, mappings = {}, [], []

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
        extracted = directory.matrix_sites(workbook, sheet, *mapping)
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
                known.setdefault(_identity(contract), contract)
                record(contract, sheet, contacts=column.contacts)
                targets.append((coordinate, contract))
        mappings.append(_public_mapping(sheet, "contract", mapping, targets))

    detail_headers = {}
    for sheet in workbook.sheets:
        if not sheet.summary:
            header, label, _, _ = _mapping(sheet)
            detail_headers[sheet.name] = {_identity(c.value) for c in sheet.cells if c.row == header and c.column > label and c.value.strip()}
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
        sites = directory.matrix_sites(workbook, sheet, *mapping)
        if not any(s.contacts for s in sites):
            exclusions.append(WorkbookExclusion(sheet.name, "No populated contact records; this appears to be an unfinished template."))
            continue
        overlaps = [name for name, titles in detail_headers.items() if name != sheet.name
                    and titles and titles == detail_headers[sheet.name]]
        if overlaps:
            exclusions.append(WorkbookExclusion(sheet.name, "All site headings repeat another worksheet (" + ", ".join(overlaps) + "). Review contract ownership separately."))
            continue
        record(contract, sheet, sites=sites)
        mappings.append(_public_mapping(sheet, "site", mapping, [(s.source.rsplit("!", 1)[-1], s.title) for s in sites]))

    entries = []
    for contract, item in sorted(records.items(), key=lambda pair: pair[0].casefold()):
        conflicts = []
        try:
            current = directory.load_directory(contract, include_archived=True)
        except (ValueError, library.LibraryError) as exc:
            current = None
            conflicts.append(str(exc))
        if current and current.archived:
            conflicts.append("This directory is archived. Restore and review it before importing new contacts.")
        old_sites = current.sites if current else ()
        old_contacts = current.contract_contacts if current else ()
        sites, site_conflicts = _merge_sites(contract, old_sites, tuple(item["sites"]), site_maps.get(contract, {}))
        contacts, contact_conflicts = _merge_contacts(old_contacts, tuple(item["contacts"]), contract + " (contract-wide)")
        conflicts.extend((*site_conflicts, *contact_conflicts))
        changed = sites != old_sites or contacts != old_contacts
        entries.append(ContractPlan(contract, current.revision if current else 0, sites, contacts, tuple(item["sheets"]),
                       tuple(conflicts), changed, current is not None, len(item["sites"]),
                       len(item["contacts"]) + sum(len(s.contacts) for s in item["sites"])))
    return WorkbookPlan(workbook.sha256, tuple(entries), workbook.notices, tuple(exclusions), tuple(mappings))


def save_workbook_plan(plan, raw, *, actor, confirmed, contracts=None):
    """Apply the reviewed snapshot; each successful contract has its own revision."""
    actor = library._confirmation(actor, confirmed)
    if hashlib.sha256(raw).hexdigest() != plan.workbook_sha256:
        raise ValueError("The uploaded workbook changed. Read it again and review a new preview.")
    selected = set(contracts) if contracts is not None else {e.contract for e in plan.entries}
    if selected - {e.contract for e in plan.entries}:
        raise ValueError("An unreviewed contract was selected. Refresh and review the preview.")
    saved, unchanged, blocked, failed, revisions = [], [], [], [], []
    for entry in plan.entries:
        if entry.contract not in selected:
            continue
        if entry.conflicts:
            blocked.append((entry.contract, " ".join(entry.conflicts)))
            continue
        try:
            current = directory.load_directory(entry.contract, include_archived=True)
            if entry.expected_revision != (current.revision if current else 0):
                raise library.RevisionConflict("This directory changed after the preview. Refresh and review it again.")
            if not entry.changed:
                unchanged.append(entry.contract)
                continue
            result = directory.save_directory(entry.contract, entry.sites, contract_contacts=entry.contract_contacts,
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
    return BatchSaveResult(tuple(saved), tuple(unchanged), tuple(blocked), tuple(failed), tuple(revisions))
