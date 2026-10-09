"""Confirmed contract/site directories, separate from report membership.

XLSX is read as bounded, sparse XML: no macros, formulas, links or objects run.
Only reviewed records become runtime data. Each contract has an atomic head and
restorable history; directory updates never mutate profiles or report snapshots.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from collections import Counter
from io import BytesIO
import hashlib
import re
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from app import monthly_report_library as library
from app.monthly_report_import import _resolve
from app.monthly_report_model import BlockSpec, ColumnSpec, Facility, ReportProfile, ResolvedBlock

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_PART_BYTES = 16 * 1024 * 1024
MAX_CELLS = 100_000
MAX_TEXT = 4_000_000
MAX_SITES = 500
MAX_XML_ELEMENTS = 750_000
MAX_XML_TEXT = 8_000_000
MAX_XML_DEPTH = 64
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


@dataclass(frozen=True)
class DirectoryCell:
    row: int
    column: int
    value: str
    formula: bool = False


@dataclass(frozen=True)
class DirectorySheet:
    name: str
    cells: tuple[DirectoryCell, ...]
    hidden: bool = False

    @property
    def summary(self):
        name = re.sub(r"^\d+\s*[-.]\s*", "", self.name).strip().casefold()
        return name in ("index", "contents", "totals", "summary", "active contracts", "contracts")

    def values(self):
        return {(c.row, c.column): c.value for c in self.cells}


@dataclass(frozen=True)
class DirectoryWorkbook:
    sha256: str
    sheets: tuple[DirectorySheet, ...]
    notices: tuple[str, ...]


@dataclass(frozen=True)
class DirectoryContact:
    role: str
    name: str = ""
    phone: str = ""
    email: str = ""
    source: str = ""


@dataclass(frozen=True)
class DirectorySite:
    key: str
    title: str
    aliases: tuple[str, ...] = ()
    address: str = ""
    contacts: tuple[DirectoryContact, ...] = ()
    source: str = ""
    active: bool = True

    @property
    def facility(self):
        return Facility(self.key, self.title, self.aliases)


@dataclass(frozen=True)
class DirectoryState:
    contract: str
    revision: int
    sites: tuple[DirectorySite, ...]
    actor: str
    updated_at: str
    source_sha256: str = ""
    source_sheet: str = ""
    action: str = "save"
    archived: bool = False


def _coord(address):
    match = re.fullmatch(r"([A-Z]{1,3})([1-9]\d{0,6})", address or "")
    if not match:
        raise ValueError("Invalid workbook cell address.")
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - 64
    if column > 16384 or int(match[2]) > 1048576:
        raise ValueError("Workbook cell is outside Excel's bounds.")
    return int(match[2]), column


def column_name(column):
    result = ""
    while column:
        column, rem = divmod(column - 1, 26)
        result = chr(65 + rem) + result
    return result


@dataclass
class _XmlBudget:
    elements: int = 0
    text: int = 0


def _stream_xml(archive, part, budget, consume):
    """Read events without building a tree, including unknown/ignored XML.

    Clearing only cells leaves all other elements attached to the root. A SAX
    target allocates no Element objects; budgets also cover metadata, rich text,
    attributes and unexpected elements rather than only recognized cell values.
    """
    class Target:
        def __init__(self):
            self.path = []

        def start(self, tag, attrs):
            budget.elements += 1
            if budget.elements > MAX_XML_ELEMENTS or len(self.path) >= MAX_XML_DEPTH or len(attrs) > 64:
                raise ValueError("Workbook XML exceeds the safe parsing budget.")
            self._text(sum(len(k) + len(v) for k, v in attrs.items()))
            self.path.append(tag)
            consume("start", tuple(self.path), attrs)

        def end(self, tag):
            consume("end", tuple(self.path), None)
            self.path.pop()

        def _text(self, size):
            budget.text += size
            if budget.text > MAX_XML_TEXT:
                raise ValueError("Workbook XML text exceeds the safe parsing budget.")

        def data(self, value):
            self._text(len(value))
            consume("text", tuple(self.path), value)

        def close(self):
            return None

    parser = ET.XMLParser(target=Target(), forbid_dtd=True)
    with archive.open(part) as stream:
        while chunk := stream.read(16 * 1024):
            parser.feed(chunk)
        parser.close()


def _workbook_metadata(archive, names, budget):
    relations, sheets = {}, []
    rel_tag = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"

    def relationship(event, path, value):
        if event == "start" and len(path) == 2 and path[-1] == rel_tag:
            identity = value.get("Id", "")
            if identity in relations:
                raise ValueError("Duplicate workbook relationship identity.")
            if len(relations) >= 2000:
                raise ValueError("Workbook relationships exceed the safe parsing budget.")
            target = "" if value.get("TargetMode", "").casefold() == "external" else _resolve("xl/workbook.xml", value.get("Target", ""))
            relations[identity] = target, value.get("Type", "")

    def worksheet(event, path, value):
        if event == "start" and path == (S + "workbook", S + "sheets", S + "sheet"):
            if len(sheets) >= 50:
                raise ValueError("Directory exceeds 50 worksheets; split it before importing.")
            sheets.append(dict(value))

    if "xl/_rels/workbook.xml.rels" in names:
        _stream_xml(archive, "xl/_rels/workbook.xml.rels", budget, relationship)
    _stream_xml(archive, "xl/workbook.xml", budget, worksheet)
    return relations, sheets


def inspect_workbook(raw: bytes) -> DirectoryWorkbook:
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Choose a nonempty XLSX directory up to 30 MB.")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            names = [m.filename for m in members]
            if (len(names) > 2000 or len(names) != len(set(names))
                    or any(n.startswith("/") or "\\" in n or ".." in n.split("/") for n in names)
                    or sum(m.file_size for m in members) > MAX_EXPANDED_BYTES
                    or any(m.file_size > MAX_PART_BYTES or m.flag_bits & 1 for m in members)):
                raise ValueError("Workbook package exceeds the safe parsing budget or has unsafe parts.")
            if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names:
                raise ValueError("Choose a valid XLSX workbook.")
            if any("vbaproject" in n.casefold() for n in names):
                raise ValueError("Macro-enabled workbooks are not supported. Save a macro-free XLSX copy.")
            budget = _XmlBudget()
            strings, total_text = [], 0
            string_parts, string_length = None, 0

            def shared_text(event, path, value):
                nonlocal string_parts, string_length, total_text
                if event == "start" and path == (S + "sst", S + "si"):
                    string_parts, string_length = [], 0
                elif event == "text" and string_parts is not None and path[-1] == S + "t":
                    string_length += len(value)
                    if string_length > 10000:
                        raise ValueError("Workbook shared text exceeds the review budget.")
                    string_parts.append(value)
                elif event == "end" and path == (S + "sst", S + "si"):
                    text = "".join(string_parts)
                    total_text += len(text)
                    if len(strings) >= MAX_CELLS or total_text > MAX_TEXT:
                        raise ValueError("Workbook shared text exceeds the review budget.")
                    strings.append(text)
                    string_parts = None

            if "xl/sharedStrings.xml" in names:
                _stream_xml(archive, "xl/sharedStrings.xml", budget, shared_text)
            relations, sheet_nodes = _workbook_metadata(archive, names, budget)
            sheets, total_cells, formulas = [], 0, 0
            for node in sheet_nodes:
                target, kind = relations.get(node.get(R + "id"), ("", ""))
                if not target or not target.startswith("xl/worksheets/") or not kind.endswith("/worksheet") or target not in names:
                    raise ValueError("Workbook has a missing, external or unsafe worksheet relationship.")
                cells, seen = [], set()
                cell, cell_path, cached, inline, cell_length, is_formula = None, (), [], [], 0, False

                def worksheet_cell(event, path, value):
                    nonlocal cell, cell_path, cached, inline, cell_length, is_formula
                    nonlocal total_cells, total_text, formulas
                    if event == "start" and path[-1] == S + "c":
                        if cell is not None:
                            raise ValueError("Workbook contains nested cells.")
                        coordinate = _coord(value.get("r"))
                        if coordinate in seen:
                            raise ValueError("Workbook contains duplicate cell coordinates.")
                        seen.add(coordinate)
                        total_cells += 1
                        if total_cells > MAX_CELLS:
                            raise ValueError("Workbook exceeds 100,000 stored cells. Remove unused formatting or split it.")
                        cell, cell_path = (coordinate, value.get("t", "")), path
                        cached, inline, cell_length, is_formula = [], [], 0, False
                    elif cell is not None:
                        if event == "start" and path == (*cell_path, S + "f"):
                            is_formula = True
                        elif event == "text" and (path == (*cell_path, S + "v") or path[-1] == S + "t"):
                            cell_length += len(value)
                            if cell_length > 10000:
                                raise ValueError("Workbook cell text exceeds the review budget.")
                            (cached if path[-1] == S + "v" else inline).append(value)
                        elif event == "end" and path == cell_path:
                            coordinate, kind = cell
                            value = "".join(cached)
                            if kind == "s":
                                try:
                                    index = int(value)
                                    if index < 0:
                                        raise IndexError
                                    value = strings[index]
                                except (ValueError, IndexError) as exc:
                                    raise ValueError("Invalid workbook shared-string reference.") from exc
                            elif kind == "inlineStr":
                                value = "".join(inline)
                            elif kind == "b":
                                value = "Yes" if value == "1" else "No" if value == "0" else ""
                            elif kind == "e":
                                value = ""  # Failed formulas must not become contact identities.
                            value = value.strip()
                            total_text += len(value)
                            if len(value) > 10000 or total_text > MAX_TEXT:
                                raise ValueError("Workbook cell text exceeds the review budget.")
                            formulas += int(is_formula)
                            if value or is_formula:
                                cells.append(DirectoryCell(*coordinate, value, is_formula))
                            cell = None

                _stream_xml(archive, target, budget, worksheet_cell)
                sheets.append(DirectorySheet(node.get("name", ""), tuple(cells), node.get("state", "visible") != "visible"))
            if not sheets or len({s.name for s in sheets}) != len(sheets):
                raise ValueError("Workbook needs uniquely named worksheets.")
            notices = ["Only saved cell values are read. Links, macros, embedded objects and formulas are never executed."]
            if formulas:
                notices.append(f"{formulas} formula cells use their last saved values, which may be stale or blank. Check the proposed sites and contacts.")
            if any(s.hidden for s in sheets):
                notices.append("Hidden worksheets are marked and not selected automatically.")
            return DirectoryWorkbook(hashlib.sha256(raw).hexdigest(), tuple(sheets), tuple(notices))
    except (BadZipFile, KeyError, ET.ParseError, DefusedXmlException) as exc:
        raise ValueError("Workbook is invalid or contains unsafe XML; nothing was saved.") from exc


def suggest_matrix(sheet: DirectorySheet):
    """Find a plausible header and contact groups, never confirmed membership."""
    values = sheet.values()
    rows = sorted({r for r, _ in values})
    label_col = min((c for _, c in values), default=1)
    labels = {r: values.get((r, label_col), "") for r in rows}
    address = next((r for r in rows if "address" in labels[r].casefold()), 0)
    roles = [r for r in rows if re.search(r"manager|director|executive|administrator|engineer|supervisor|leadership|analyst|point of contact", labels[r], re.I)
             and not re.search(r"phone|email|address", labels[r], re.I)]
    boundary = min([*roles, *([address] if address else [])], default=50)
    counts = Counter(r for (r, c), value in values.items() if c > label_col and value)
    candidates = [r for r in rows if r < boundary and counts[r]]
    header = max(candidates, key=lambda r: (counts[r], -r), default=rows[0] if rows else 1)
    groups = []
    for row in roles:
        next_role = next((r for r in roles if r > row), row + 5)
        phone = next((r for r in rows if row < r < min(next_role, row + 5) and re.search(r"phone|telephone|mobile", labels[r], re.I)), 0)
        email = next((r for r in rows if row < r < min(next_role, row + 5) and re.search(r"e.?mail", labels[r], re.I)), 0)
        groups.append({"Use": True, "Role": labels[row], "Name row": row, "Phone row": phone, "Email row": email})
    return header, label_col, address, groups


def matrix_sites(workbook: DirectoryWorkbook, sheet: DirectorySheet, header_row: int, label_column: int,
                 address_row: int, groups: list[dict]) -> tuple[DirectorySite, ...]:
    values = sheet.values()
    sites = []
    for column in sorted({c for r, c in values if r == header_row and c > label_column}):
        title = values.get((header_row, column), "").strip()
        if not title or re.fullmatch(r"(?:grand\s+)?totals?|summary", title, re.I):
            continue
        source = f"{workbook.sha256}:{sheet.name}!{column_name(column)}{header_row}"
        contacts = []
        for group in groups:
            if not group.get("Use"):
                continue
            role = str(group.get("Role") or "").strip()
            if not role:
                raise ValueError("Give every included contact group a role.")
            def at(key):
                return values.get((int(group.get(key) or 0), column), "")
            fields = (at("Name row"), at("Phone row"), at("Email row"))
            if any(fields):
                coordinates = ",".join(f"{column_name(column)}{int(group[k])}" for k in ("Name row", "Phone row", "Email row") if group.get(k))
                contacts.append(DirectoryContact(role, *fields, source=f"{workbook.sha256}:{sheet.name}!{coordinates}"))
        sites.append(DirectorySite("site-" + hashlib.sha256(source.encode()).hexdigest()[:24], title,
                                   address=values.get((address_row, column), ""), contacts=tuple(contacts), source=source))
    if not sites or len(sites) > MAX_SITES:
        raise ValueError("Choose a header with between 1 and 500 site columns.")
    return tuple(sites)


def sheet_findings(workbook, selected):
    """A tab name is not proof that copied template columns belong to a contract."""
    def titles(sheet):
        header, label, _, _ = suggest_matrix(sheet)
        return {" ".join(c.value.casefold().split()) for c in sheet.cells
                if c.row == header and c.column > label and c.value}
    selected_titles = titles(selected)
    findings = []
    for sheet in workbook.sheets:
        if sheet.name == selected.name or sheet.summary:
            continue
        overlap = selected_titles & titles(sheet)
        if overlap:
            findings.append(f"{len(overlap)} proposed site name(s) also appear on worksheet {sheet.name}. Confirm which contract owns them; copied worksheet headings are not proof of membership.")
    _, _, _, groups = suggest_matrix(selected)
    contact_rows = {int(g[k]) for g in groups for k in ("Name row", "Phone row", "Email row") if g[k]}
    if not any(c.value for c in selected.cells if c.row in contact_rows and c.column > 1):
        findings.append("No populated leadership/contact records were found for the suggested roles. Check that this tab is current rather than an unfinished template.")
    return tuple(findings)


def proposed_contacts(existing, incoming):
    """Blank updates cannot erase saved details or attach an old phone to a new person."""
    result = list(existing)
    for contact in incoming:
        matches = [i for i, c in enumerate(result) if c.role.casefold() == contact.role.casefold()]
        if len(matches) == 1 and sum(c.role.casefold() == contact.role.casefold() for c in incoming) == 1:
            index = matches[0]
            old = result[index]
            same_person = not contact.name or contact.name.casefold() == old.name.casefold()
            if same_person:
                contact = replace(contact, name=contact.name or old.name, phone=contact.phone or old.phone,
                                  email=contact.email or old.email,
                                  source=";".join(dict.fromkeys(s for s in (contact.source, old.source) if s)))
            result[index] = contact
        else:
            result.append(contact)
    return tuple(result)


def _contract_identity(contract):
    library._contract_directory(contract)  # Preserve the shared length/blank validation.
    return " ".join(contract.casefold().split())


def canonical_contract(contract):
    """Canonical spelling only; no fuzzy aliases or routing changes."""
    from app import contracts
    identity = _contract_identity(contract)
    return next((name for name in contracts.contract_names() if _contract_identity(name) == identity),
                " ".join(contract.split()))


def _directory_records():
    root = library._root() / "directory"
    return tuple((path.parent, _state(library._read(path))) for path in sorted(root.glob("*/manifest.json")))


def _path(contract):
    """Reuse old case-sensitive storage paths, keeping history in place.

    Exact legacy names remain addressable if pre-existing directories collide.
    New saves cannot create another case/whitespace variant of a known record.
    """
    identity = _contract_identity(contract)
    direct = library._root() / "directory" / library._contract_directory(contract)
    if (direct / "manifest.json").exists():
        if _state(library._read(direct / "manifest.json")).contract != contract:
            raise library.LibraryError("Directory contract identity mismatch.")
        return direct
    matches = [(path, state) for path, state in _directory_records() if _contract_identity(state.contract) == identity]
    if len(matches) == 1:
        return matches[0][0]
    if matches:
        for label in (contract, canonical_contract(contract)):
            exact = [path for path, state in matches if state.contract == label]
            if len(exact) == 1:
                return exact[0]
        raise library.LibraryError("More than one saved contact list uses this contract name. Open the saved directory and archive the duplicate by its original name.")
    return library._root() / "directory" / library._contract_directory(canonical_contract(contract))


def _state(value):
    try:
        sites = tuple(DirectorySite(**(s | {"aliases": tuple(s.get("aliases", ())),
                      "contacts": tuple(DirectoryContact(**c) for c in s.get("contacts", ())) })) for s in value["sites"])
        return DirectoryState(value["contract"], value["revision"], sites, value["actor"], value["updated_at"],
                              value.get("source_sha256", ""), value.get("source_sheet", ""), value.get("action", "save"),
                              value.get("archived", False))
    except (KeyError, TypeError, ValueError) as exc:
        raise library.LibraryError("Saved site directory could not be read; existing data was preserved.") from exc


def load_directory(contract, revision=None, *, include_archived=False):
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ValueError("Invalid directory revision.")
    path = _path(contract) / (f"history/{revision:08d}.json" if revision else "manifest.json")
    if not path.exists() and revision is None:
        return None
    state = _state(library._read(path))
    if _contract_identity(state.contract) != _contract_identity(contract):
        raise library.LibraryError("Directory contract identity mismatch.")
    if revision is None and state.archived and not include_archived:
        # Archiving one legacy spelling must not hide the remaining live list
        # for the same canonical contract from report setup.
        live = [other for _, other in _directory_records()
                if not other.archived and _contract_identity(other.contract) == _contract_identity(contract)]
        if len(live) > 1:
            raise library.LibraryError("More than one active contact list uses this contract name. Archive the duplicate lists by their original names.")
        return live[0] if live else None
    return state


def directory_contracts(*, include_archived=False):
    states = [state for _, state in _directory_records()]
    if include_archived:
        # Keep legacy colliding records individually reachable for recovery.
        return tuple(sorted({state.contract for state in states}, key=lambda name: (name.casefold(), name)))
    result = {}
    for state in sorted(states, key=lambda state: (state.contract.casefold(), state.contract)):
        if not state.archived:
            result.setdefault(_contract_identity(state.contract), canonical_contract(state.contract))
    return tuple(sorted(result.values(), key=str.casefold))


def save_directory(contract, sites, *, expected_revision, actor, confirmed, raw=None,
                   source_sha256="", source_sheet="", action="save", _archived=False):
    actor = library._confirmation(actor, confirmed)
    sites = tuple(sites)
    if not sites or len(sites) > MAX_SITES:
        raise ValueError("Confirm between 1 and 500 sites.")
    for site in sites:
        library._valid_key(site.key)
        if len(site.title) > 200 or len(site.address) > 2000 or len(site.contacts) > 50 or len(site.aliases) > 30:
            raise ValueError("Site record exceeds its review budget.")
        if any(len(getattr(c, field)) > 2000 for c in site.contacts for field in ("role", "name", "phone", "email", "source")):
            raise ValueError("Contact record exceeds its review budget.")
        if any(not c.role.strip() for c in site.contacts):
            raise ValueError("Every contact needs a role.")
    # Reuse the explicit facility identity/alias ambiguity checks without inferring scope.
    ReportProfile(contract, "directory-check", "Directory validation", tuple(s.facility for s in sites), "multi_site")
    if raw is not None:
        inspection = inspect_workbook(raw)
        if source_sha256 != inspection.sha256 or source_sheet not in {s.name for s in inspection.sheets}:
            raise ValueError("Directory source no longer matches the reviewed workbook.")
    elif source_sha256 and not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("Invalid directory source fingerprint.")
    identity = _contract_identity(contract)
    # One lock covers every casing, including concurrent first saves.
    lock = library._root() / "directory_locks" / library._contract_directory(identity)
    with library._locked(lock):
        path = _path(contract)
        current = load_directory(contract, include_archived=True)
        if expected_revision != (current.revision if current else 0):
            raise library.RevisionConflict("Someone changed this directory. Reload and review the new version before saving.")
        # Preserve legacy spelling when updating its existing history so a
        # separately saved collision remains explicitly addressable.
        stored_contract = current.contract if current else canonical_contract(contract)
        state = DirectoryState(stored_contract, expected_revision + 1, sites, actor, library._now(), source_sha256, source_sheet, action, _archived)
        encoded = library._json({"schema": 1, **asdict(state)})
        if raw is not None:
            library._atomic_write(library._root() / "directory_sources" / (source_sha256 + ".xlsx"), raw)
        library._atomic_write(path / "history" / f"{state.revision:08d}.json", encoded)
        library._atomic_write(path / "manifest.json", encoded)
        return state


def merge_sites(existing, incoming):
    """Only explicit keys link identities; omitted existing sites are retained."""
    if len({s.key for s in incoming}) != len(incoming):
        raise ValueError("Two imported columns link to one site. Confirm aliases in one record instead.")
    result = {s.key: s for s in existing}
    result.update({s.key: s for s in incoming})
    return tuple(result.values())


def restore_directory(contract, revision, *, expected_revision, actor, confirmed):
    actor = library._confirmation(actor, confirmed)
    prior = load_directory(contract, revision)
    return save_directory(contract, prior.sites, expected_revision=expected_revision, actor=actor, confirmed=confirmed,
                          source_sha256=prior.source_sha256, source_sheet=prior.source_sheet, action=f"restore:{revision}")


def archive_directory(contract, *, expected_revision, actor, confirmed):
    actor = library._confirmation(actor, confirmed)
    current = load_directory(contract, include_archived=True)
    if current is None:
        raise library.LibraryError("That contact list no longer exists.")
    if current.revision != expected_revision:
        raise library.RevisionConflict("Someone changed this directory. Reload and review the new version before archiving.")
    return save_directory(contract, current.sites, expected_revision=expected_revision, actor=actor, confirmed=confirmed,
                          source_sha256=current.source_sha256, source_sheet=current.source_sheet,
                          action="archive", _archived=True)


CONTACT_SPEC = BlockSpec("contact_matrix", "table", columns=tuple(
    ColumnSpec(key, title) for key, title in (("facility", "Facility"), ("role", "Role"), ("name", "Name"), ("phone", "Phone"), ("email", "Email"))))


def facility_names(facility):
    """Exact display names/confirmed aliases, with only case/space normalization."""
    return {" ".join(n.casefold().split()) for n in (facility.title, *facility.aliases) if n.strip()}


def available_sites(catalog, state):
    """A partial directory supplements the catalog; explicit retirements win.

    A unique name/alias overlap avoids duplicate choices, not an automatic
    change to any report's membership. Ambiguous overlaps remain visible.
    """
    if state is None:
        return tuple(catalog)
    result = [s.facility for s in state.sites if s.active]
    by_key = {s.key for s in state.sites}
    matches = {
        f.key: tuple(s.key for s in state.sites if facility_names(f) & facility_names(s))
        for f in catalog
    }
    counts = Counter(k for keys in matches.values() for k in keys)
    for facility in catalog:
        keys = matches[facility.key]
        if facility.key in by_key or (len(keys) == 1 and counts[keys[0]] == 1):
            continue
        result.append(facility)
    return tuple(result)


def suggest_contact_bindings(state, facilities, confirmed=None):
    """Suggest unique exact-name matches; applying contacts still needs review.

    Saved links/identities take precedence. A retired saved link stays unresolved
    instead of being retargeted to a different person/site with a similar name.
    """
    confirmed = confirmed or {}
    all_sites = {s.key: s for s in state.sites}
    active = {k: s for k, s in all_sites.items() if s.active}
    result, candidates = {}, {}
    for facility in facilities:
        if facility.key in confirmed or facility.key in all_sites:
            key = confirmed.get(facility.key, facility.key)
            result[facility.key] = key if key in active else ""
        else:
            candidates[facility.key] = tuple(k for k, s in active.items() if facility_names(facility) & facility_names(s))
    counts = Counter(k for keys in candidates.values() for k in keys)
    reserved = set(result.values())
    for key, matches in candidates.items():
        result[key] = matches[0] if len(matches) == 1 and counts[matches[0]] == 1 and matches[0] not in reserved else ""
    return result


def contact_block(state: DirectoryState, facilities: tuple[Facility, ...], bindings=None):
    by_id = {s.key: s for s in state.sites}
    bindings = bindings or {}
    rows, missing, used, links = [], [], set(), []
    for facility in facilities:
        site = by_id.get(bindings.get(facility.key, facility.key))
        if not site or not site.active:
            missing.append(facility.title)
            continue
        if site.key in used:
            raise ValueError("Two report facilities link to one directory site. Review membership and aliases first.")
        used.add(site.key)
        links.append(f"directory-site:{facility.key}:{site.key}")
        rows.extend((facility.title, c.role, c.name, c.phone, c.email) for c in site.contacts)
    reference = f"directory:{library._contract_directory(state.contract)}:{state.revision}"
    return ResolvedBlock("contact_matrix", "This month", rows=tuple(rows), references=(reference, *links)), tuple(missing)


def apply_contacts(draft, block):
    """Called only after a visible side-by-side, content-bound confirmation."""
    sections = tuple(replace(s, included=True, blocks=tuple(CONTACT_SPEC if b.key == "contact_matrix" else b for b in s.blocks))
                     if any(b.key == "contact_matrix" for b in s.blocks) else s for s in draft.sections)
    if not any(b.key == "contact_matrix" for s in sections for b in s.blocks):
        raise ValueError("The saved design has no contact-matrix destination. Add it in the advanced layout editor first.")
    blocks = {b.key: b for b in draft.blocks}
    blocks[block.key] = block
    return replace(draft, sections=sections, blocks=tuple(blocks.values()))
