"""Item-specific scope evidence; no filename, classification or blanket waiver.

Source corrections bind the scope-determining source revision and contract. Accepted
mapping/totals receipts bind the particular contribution and reporting window.
Neither changes original bytes or turns a report-only edit into standing data.
"""
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json

from app.monthly_report_model import included_sections, used_block_keys

MULTIPLE_FACILITIES = "__source_multiple_facilities__"
CONTRACT_ARTWORK = "__source_contract_artwork__"
USE_PREFIX = "source-scope-use:v1:"
_ROW_COVER_WORK_LIMIT = 200_000
ARTWORK_KEYS = frozenset({"brand_logo", "client_logo", "business_hours_workflow", "after_hours_workflow"})


def _encode(value):
    return urlsafe_b64encode(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).decode()


def _decode(value):
    try:
        record = json.loads(urlsafe_b64decode(value))
        return record if isinstance(record, dict) else {}
    except (ValueError, TypeError, UnicodeError):
        return {}


def _source_id(reference):
    parts = reference.split(":") if isinstance(reference, str) else ()
    return parts[0] if len(parts) == 3 and parts[1].isdigit() else None


def revision(source):
    # Inclusion and visual-review controls do not change which sites the
    # original file covers. Binding them would require another site decision
    # after every page Include/Exclude/caption review. Extracted content and
    # source metadata remain revision-bound; original bytes are bound below.
    return replace(source, scope_review="", selected_pages=(), captions=(),
                   client_page_reviews=(), client_page_exclusions=(),
                   financial_source_review=None, financial_page_reviews=()).fingerprint


def _site_revision(source):
    # A site's explicit decision is independent of optional descriptive labels.
    # Keep contribution_receipt's existing revision above: changing a source
    # identity used by accepted work-order rows still needs factual review.
    return revision(replace(source, vendor="", work_order=""))


def source_review(source):
    return _decode(source.scope_review) if source.scope_review else {}


def reviewed_scope(source, profile):
    record = source_review(source)
    version = record.get("version")
    if (version not in (1, 2) or record.get("source") != source.id
            or record.get("sha256") != source.sha256
            or record.get("contract") != profile.contract):
        return None
    expected = _site_revision(source) if version == 2 else revision(source)
    if record.get("revision") != expected:
        return None
    sites = record.get("facilities")
    if not isinstance(sites, list) or any(not isinstance(key, str) for key in sites):
        return None
    if record.get("kind") == "sites" and sites and set(sites) <= {site.key for site in profile.facilities}:
        return record
    if record.get("kind") == "contract_artwork" and not sites:
        return record
    return None


def visual_source_scope_valid(source, profile, *, artwork_keys=()):
    """Source-site admission before publishing a reviewed reusable visual.

    Match the report check's strict foreign-site refusal. An unknown or
    explicitly corrected scope must retain its current source/hash/contract
    receipt; image/page approval is not site approval. Only established shared
    artwork roles may use a contract-artwork receipt (not organization charts).
    """
    names = {name.strip().casefold() for site in profile.facilities
             for name in (site.key, site.title, *site.aliases)}
    facility = source.facility.strip().casefold()
    if facility and facility not in names:
        return False
    if not facility or source.scope_review:
        scope = reviewed_scope(source, profile)
        if not scope:
            return False
        return scope["kind"] == "sites" or bool(artwork_keys) and all(
            is_artwork_key(key) for key in artwork_keys)
    return True


def correct_scope(source, profile, facilities=(), *, contract_artwork=False, artwork_keys=()):
    selected = tuple(dict.fromkeys(facilities))
    if contract_artwork:
        if selected or not artwork_keys or not all(is_artwork_key(key) for key in artwork_keys):
            raise ValueError("Contract-wide scope is only available for this source's shared report artwork.")
    elif not selected or set(selected) - {site.key for site in profile.facilities}:
        raise ValueError("Choose the exact selected sites covered by this source.")
    record = {"version": 2, "source": source.id, "sha256": source.sha256,
              "revision": _site_revision(source), "contract": profile.contract,
              "kind": "contract_artwork" if contract_artwork else "sites",
              "facilities": list(selected)}
    return replace(source, scope_review=_encode(record))


def preserve_descriptive_scope(previous, updated, profile):
    """Carry a valid legacy site decision through a delivered vendor/job edit.

    Browsing leaves historical records untouched. The old full revision must
    validate before its descriptive edit, and every actual scope determinant
    must still match afterwards. A stale or replaced receipt is never renewed.
    """
    if (previous.scope_review != updated.scope_review
            or (previous.vendor, previous.work_order) == (updated.vendor, updated.work_order)
            or _site_revision(previous) != _site_revision(updated)):
        return updated
    record = reviewed_scope(previous, profile)
    if not record or record["version"] != 1:
        return updated
    return replace(updated, scope_review=_encode({**record, "version": 2,
                                                  "revision": _site_revision(updated)}))


def is_artwork_key(key):
    return key in ARTWORK_KEYS or key.startswith("divider_")


def source_uses(draft, source_id):
    """Included contributions, preserving the ordinary source provenance model."""
    uses = []
    def cites(references):
        return any(_source_id(ref) == source_id for ref in references)
    keys = used_block_keys(draft)
    specs = {spec.key: spec for section in included_sections(draft.sections) for spec in section.blocks}
    for block in draft.blocks:
        if block.key not in keys or block.source == "Omit":
            continue
        broad = cites(block.references)
        if block.text.strip() and broad:
            uses.append(("text", block.key, block.text, block.references))
        if any(cell.strip() for row in block.rows for cell in row) and broad:
            columns = tuple(c.title for c in specs.get(block.key).columns) if block.key in specs else ()
            uses.append(("rows", block.key, (columns, block.rows), block.references))
        for table in block.extra_tables:
            if any(cell.strip() for row in table.rows for cell in row) and (broad or cites((table.reference,))):
                uses.append(("rows", block.key, (table.columns, table.rows), block.references))
        for paragraph in block.ai_paragraphs:
            if paragraph.text.strip() and cites(paragraph.references):
                uses.append(("text", block.key, paragraph.text, ()))
        provenance = dict(block.asset_provenance)
        if any(broad or cites(provenance.get(asset, ())) for asset in block.asset_hashes):
            uses.append(("artwork" if is_artwork_key(block.key) else "image", block.key, None, ()))
        if block.org_nodes and broad:
            uses.append(("organization", block.key, None, ()))
    sections = {section.key for section in included_sections(draft.sections)}
    for item in draft.follow_ups:
        key = "issues" if item.category == "issue" else "proposals"
        if item.included and key in sections and cites(item.references):
            uses.append(("follow_up", key, None, ()))
    return tuple(uses)


def text_edit_references(block, text):
    """Retire an exactly deleted accepted paragraph, never an edited claim.

    The old and new paragraphs are known at the ordinary edit boundary. Only
    whole-paragraph deletions qualify, and only a receipt that explicitly kept
    independent wording can identify the source contribution being removed.
    Ambiguous edits and mixed text/table/picture uses retain their safety gates.
    This does not mutate a source, its original bytes or historical snapshots.
    """
    # A completely empty block already has no included use. Preserve its
    # references for the existing explicit Clear/Undo action, which restores
    # text into that exact block rather than inventing fresh provenance.
    if not text.strip():
        return block.references
    before = Counter(part for part in block.text.split("\n\n") if part)
    after = Counter(part for part in text.split("\n\n") if part)
    if before == after or not after <= before:
        return block.references
    if (block.ai_written or block.ai_paragraphs or block.asset_hashes or block.org_nodes
            or any(cell.strip() for row in block.rows for cell in row)
            or any(cell.strip() for table in block.extra_tables for row in table.rows for cell in row)):
        return block.references
    records = {reference: _decode(reference[len(USE_PREFIX):])
               for reference in block.references if reference.startswith(USE_PREFIX)}
    retired = set()
    for reference, record in records.items():
        paragraph, origin = record.get("text"), record.get("reference")
        if (record.get("version") == 1 and record.get("kind") == "text"
                and record.get("key") == block.key
                and record.get("allows_independent_text") is True
                and isinstance(paragraph, str) and paragraph and before[paragraph]
                and not after[paragraph] and _source_id(origin)
                and origin in block.references):
            retired.add(reference)
    # Another receipt may still use this exact source/page reference. Keep it
    # unless every receipt paired with it was removed by this exact edit.
    origins = {records[reference]["reference"] for reference in retired}
    origins = {origin for origin in origins if all(
        reference in retired for reference, record in records.items()
        if record.get("reference") == origin)}
    return tuple(reference for reference in block.references
                 if reference not in retired and reference not in origins)


def contribution_dates_bound(draft, source):
    """Every included use has current accepted row/totals reporting dates.

    Wording review, site review and a receipt for just one of several uses do
    not establish the date of the others. Original page/image uses stay on the
    existing file-date path even when this source also supplied accepted rows.
    """
    uses = source_uses(draft, source.id)
    return bool(uses) and all(use[0] in {"text", "rows"} and _covered_use(
        use, source, draft.profile, draft.period, sources=draft.sources) for use in uses)


def artwork_scope_keys(draft, source_id):
    uses = source_uses(draft, source_id)
    return tuple(dict.fromkeys(use[1] for use in uses)) if uses and all(use[0] == "artwork" for use in uses) else ()


def contribution_receipt(reference, profile, period, key, *, text="", columns=(), rows=(), source=None,
                         prior_block=None):
    """Record a real, source-bound acceptance; caller supplies its actual result."""
    if _source_id(reference) is None:
        return ""  # Legacy non-source references are not scope evidence.
    record = {"version": 1, "reference": reference, "contract": profile.contract,
              "facilities": sorted(site.key for site in profile.facilities), "period": period.key,
              "key": key, "kind": "text" if text else "rows", "text": text,
              "columns": list(columns),
              "table": _table_digest(columns, rows) if not text else ""}
    if not text:
        record["row_values"] = [list(row) for row in rows]
    if source is not None:
        if _source_id(reference) != source.id or reference.split(":")[-1] != source.fingerprint:
            raise ValueError("This source changed before its contribution was accepted.")
        record["source_revision"] = revision(source)
    if text:
        # Scope belongs to these accepted totals, not every paragraph which
        # happens to share a block-wide source reference. Independent human
        # and other-source wording is allowed only when this source had no
        # prior narrative, or its earlier contribution is already covered.
        prior_cites_source = (prior_block is not None and prior_block.text.strip()
            and any(_source_id(ref) == _source_id(reference) for ref in prior_block.references))
        record["allows_independent_text"] = bool(prior_block is not None and
            (not prior_cites_source or source is not None and _covered_use(
                ("text", key, prior_block.text, prior_block.references), source, profile, period)))
    return USE_PREFIX + _encode(record)


def _table_digest(columns, rows):
    return sha256(json.dumps([columns, rows], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _current_receipt(record, source, profile, period, key, kind):
    origin = record.get("reference", "")
    if not isinstance(origin, str):
        return False
    same_revision = (record["source_revision"] == revision(source) if record.get("source_revision")
                     else origin.split(":")[-1] == source.fingerprint)
    return (record.get("version") == 1 and _source_id(origin) == source.id and same_revision
            and record.get("contract") == profile.contract
            and record.get("facilities") == sorted(site.key for site in profile.facilities)
            and record.get("period") == period.key and record.get("key") == key
            and record.get("kind") == kind)


def _accepted_rows_cover(key, columns, rows, records):
    # Only the established service-description field is freely editable.
    # Counts, dates, identity, area, tags and custom schemas remain bound.
    service_columns = ("Facility", "WO #", "Finish Date", "Area", "Task Code-Description", "Tag #")
    description = 4 if key == "service_calls" and tuple(columns) == service_columns else None

    def facts(row):
        return tuple("" if i == description else cell for i, cell in enumerate(row))

    available = Counter()
    for record in records:
        accepted = record.get("row_values")
        if (record.get("columns") != list(columns) or not isinstance(accepted, list)
                or any(not isinstance(row, list) or len(row) != len(columns)
                       or any(not isinstance(cell, str) for cell in row) for row in accepted)
                or record.get("table") != _table_digest(columns, accepted)):
            continue
        # A repeated receipt/source cannot multiply an already accepted row.
        available |= Counter(facts(row) for row in accepted if any(cell.strip() for cell in row))
    pending = []
    for row in rows:
        if not any(cell.strip() for cell in row):
            continue
        wanted = facts(row)
        if len(wanted) != len(columns) or not columns:
            return False
        # Reserve every exact output occurrence before considering merged rows.
        # A partial row must not be consumed merely because it is compatible.
        if available[wanted]:
            available[wanted] -= 1
        else:
            pending.append(wanted)
    if not pending:
        return True
    pending.sort()  # Equivalent output permutations have the same search.
    by_cell = [{} for _ in columns]
    for candidate, count in available.items():
        if count:
            for i, value in enumerate(candidate):
                by_cell[i].setdefault(value, set()).add(candidate)

    class CoverageLimit(Exception):
        pass

    budget = _ROW_COVER_WORK_LIMIT

    def spend(amount=1):
        nonlocal budget
        budget -= amount
        if budget < 0:
            raise CoverageLimit

    def covers(wanted):
        # Existing merges may fill blanks from other current accepted sources.
        # Every resulting fact must have evidence; each occurrence is used once.
        index = min(range(len(columns)), key=lambda i:
                    len(by_cell[i].get("", ())) + len(by_cell[i].get(wanted[i], ())))
        candidates = set(by_cell[index].get("", ())) | set(by_cell[index].get(wanted[index], ()))
        spend(len(candidates) * len(columns))
        compatible = sorted(candidate for candidate in candidates if available[candidate]
                            and all(not value or value == wanted[i]
                                    for i, value in enumerate(candidate)))
        required = [i for i, value in enumerate(wanted) if value]
        full = sum(1 << i for i in required)
        if not full:
            return ()  # No exact occurrence remains to prove this empty fact row.
        masks = [sum(1 << i for i in required if candidate[i]) for candidate in compatible]
        providers = {i: [j for j, mask in enumerate(masks) if mask & (1 << i)] for i in required}
        if any(not choices for choices in providers.values()):
            return ()
        stack, seen, options = [(0, ())], {()}, set()
        while stack:
            spend()
            covered, chosen = stack.pop()
            if covered == full:
                # Keep only inclusion-minimal covers, not redundant partial rows.
                spend(len(chosen) ** 2)
                minimal = True
                for omitted in chosen:
                    remainder = 0
                    for j in chosen:
                        if j != omitted:
                            remainder |= masks[j]
                    if remainder == full:
                        minimal = False
                        break
                if minimal:
                    options.add(tuple(compatible[j] for j in chosen))
                continue
            cell = min((i for i in required if not covered & (1 << i)),
                       key=lambda i: (len(providers[i]), i))
            for j in providers[cell]:
                next_chosen = tuple(sorted((*chosen, j)))
                if next_chosen not in seen:
                    spend()
                    seen.add(next_chosen)
                    stack.append((covered | masks[j], next_chosen))
        return sorted(options, key=lambda option: (len(option), option))

    try:
        # Iterative backtracking lets a later row retain evidence needed by it.
        # Exhaustion stays unresolved; there is no recursion or blanket waiver.
        stack = [[0, iter(covers(pending[0])), None]]
        while stack:
            spend()
            frame = stack[-1]
            if frame[2] is not None:
                for candidate in frame[2]:
                    available[candidate] += 1
                frame[2] = None
            choice = next(frame[1], None)
            if choice is None:
                stack.pop()
                continue
            for candidate in choice:
                available[candidate] -= 1
            frame[2] = choice
            following = frame[0] + 1
            if following == len(pending):
                return True
            stack.append([following, iter(covers(pending[following])), None])
    except CoverageLimit:
        return False
    return False


def _covered_use(use, source, profile, period, *, sources=()):
    kind, key, value, references = use
    accepted_text, accepted_references, independent = set(), set(), []
    current_sources = {item.id: item for item in sources}
    current_sources[source.id] = source
    records, own_records = [], []
    for ref in references:
        if not ref.startswith(USE_PREFIX):
            continue
        record = _decode(ref[len(USE_PREFIX):])
        origin = record.get("reference", "")
        owner = current_sources.get(_source_id(origin))
        if owner is None or not _current_receipt(record, owner, profile, period, key, kind):
            continue
        records.append(record)
        if owner.id != source.id:
            continue
        own_records.append(record)
        if kind == "text" and isinstance(record.get("text"), str) and record["text"] in value.split("\n\n"):
            accepted_text.add(record["text"])
            accepted_references.add(origin)
            independent.append(record.get("allows_independent_text") is True)
        if kind == "rows":
            columns, rows = value
            if (record.get("columns") == list(columns)
                    and record.get("table") == _table_digest(columns, rows)):
                return True
    if kind == "rows" and own_records:
        return _accepted_rows_cover(key, *value, records)
    if kind == "text" and accepted_text:
        if set(filter(None, value.split("\n\n"))) <= accepted_text:
            return True
        source_references = {ref for ref in references if _source_id(ref) == source.id}
        return all(independent) and source_references <= accepted_references
    return False


def included_scope_valid(draft, source):
    uses = source_uses(draft, source.id)
    if not uses:
        return True
    scope = reviewed_scope(source, draft.profile)
    if scope:
        return scope["kind"] == "sites" or all(use[0] == "artwork" for use in uses)
    return all(_covered_use(use, source, draft.profile, draft.period, sources=draft.sources) for use in uses)
