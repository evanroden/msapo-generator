"""Item-specific scope evidence; no filename, classification or blanket waiver.

Source corrections bind the exact source revision and contract. Accepted
mapping/totals receipts bind the particular contribution and reporting window.
Neither changes original bytes or turns a report-only edit into standing data.
"""
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import replace
from hashlib import sha256
import json

from app.monthly_report_model import included_sections, used_block_keys

MULTIPLE_FACILITIES = "__source_multiple_facilities__"
CONTRACT_ARTWORK = "__source_contract_artwork__"
USE_PREFIX = "source-scope-use:v1:"
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
                   client_page_reviews=(), client_page_exclusions=()).fingerprint


def source_review(source):
    return _decode(source.scope_review) if source.scope_review else {}


def reviewed_scope(source, profile):
    record = source_review(source)
    if (record.get("version") != 1 or record.get("source") != source.id
            or record.get("sha256") != source.sha256 or record.get("revision") != revision(source)
            or record.get("contract") != profile.contract):
        return None
    sites = record.get("facilities")
    if not isinstance(sites, list) or any(not isinstance(key, str) for key in sites):
        return None
    if record.get("kind") == "sites" and sites and set(sites) <= {site.key for site in profile.facilities}:
        return record
    if record.get("kind") == "contract_artwork" and not sites:
        return record
    return None


def correct_scope(source, profile, facilities=(), *, contract_artwork=False, artwork_keys=()):
    selected = tuple(dict.fromkeys(facilities))
    if contract_artwork:
        if selected or not artwork_keys or not all(is_artwork_key(key) for key in artwork_keys):
            raise ValueError("Contract-wide scope is only available for this source's shared report artwork.")
    elif not selected or set(selected) - {site.key for site in profile.facilities}:
        raise ValueError("Choose the exact selected sites covered by this source.")
    record = {"version": 1, "source": source.id, "sha256": source.sha256,
              "revision": revision(source), "contract": profile.contract,
              "kind": "contract_artwork" if contract_artwork else "sites",
              "facilities": list(selected)}
    return replace(source, scope_review=_encode(record))


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


def _table_sites_match(columns, rows, profile):
    """Current explicit site cells remain geographic proof after a row edit.

    A receipt still has to establish this source/revision, target and mapped
    schema. It does not freeze independent descriptions or prevent valid
    report-only row removal and merges of two accepted source mappings.
    """
    positions = [i for i, title in enumerate(columns) if title.strip().casefold() in {"facility", "site"}]
    if len(positions) != 1:
        return False
    names = {name.strip().casefold() for site in profile.facilities for name in (site.key, site.title, *site.aliases)}
    index = positions[0]
    return bool(rows) and all(index < len(row) and row[index].strip().casefold() in names
                              for row in rows if any(cell.strip() for cell in row))


def _covered_use(use, source, profile, period):
    kind, key, value, references = use
    accepted_text, accepted_references, independent = set(), set(), []
    for ref in references:
        if not ref.startswith(USE_PREFIX):
            continue
        record = _decode(ref[len(USE_PREFIX):])
        origin = record.get("reference", "")
        if not isinstance(origin, str):
            continue
        same_revision = (record["source_revision"] == revision(source) if record.get("source_revision")
                         else origin.split(":")[-1] == source.fingerprint)
        if (record.get("version") != 1 or _source_id(origin) != source.id
                or not same_revision
                or record.get("contract") != profile.contract
                or record.get("facilities") != sorted(site.key for site in profile.facilities)
                or record.get("period") != period.key or record.get("key") != key
                or record.get("kind") != kind):
            continue
        if kind == "text" and isinstance(record.get("text"), str) and record["text"] in value.split("\n\n"):
            accepted_text.add(record["text"])
            accepted_references.add(origin)
            independent.append(record.get("allows_independent_text") is True)
        if kind == "rows":
            columns, rows = value
            if (record.get("columns") == list(columns) and
                    (record.get("table") == _table_digest(columns, rows)
                     or _table_sites_match(columns, rows, profile))):
                return True
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
    return all(_covered_use(use, source, draft.profile, draft.period) for use in uses)
