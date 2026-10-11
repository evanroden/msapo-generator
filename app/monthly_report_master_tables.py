"""Fact-free native grid descriptors from a reviewed pinned ENFRA Word master.

A master supplies **geometry only**. Never transfer authored client rows, old
site names, monetary headings, or contact details to a new site's monthly data.
A table reference identifies one physical Word region, not an ordinal guess.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
import hashlib
import re


def _row_number(value: str) -> int | None:
    """Read explicit source row ordinals; never use their other client data."""
    match = re.fullmatch(r"\s*(\d{1,4})[.)]?\s*", str(value))
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class MasterTable:
    slot: str
    position: int
    reference: str
    columns: tuple[str, ...]
    indices: tuple[int, ...]  # retained physical columns after price exclusions
    physical_width: int
    continuation: bool = False  # No repeated heading in the source frame.


# New clients may rename these labels, but no label from an original's data
# row, client branding, or unchecked cost field may seed their report.
_GENERIC_LABELS = frozenset({
    "facility", "site", "equipment", "equipment description", "equipment tag",
    "asset", "asset tag", "tag", "tag #", "description", "work description",
    "work order", "work order #", "wo #", "wo number", "wo date", "date",
    "finish date", "status", "priority", "vendor", "contractor", "category",
    "scope", "scope of work", "technical notes", "recommendation",
    "summary of deficiency", "end of useful life", "date sub.", "project number",
    "proposal number", "requested item", "response", "comments", "issue",
    "system", "unit", "quantity", "hours", "location", "task", "task code",
    "task code-description", "frequency", "next due", "responsible party",
    "plan", "completed", "remarks", "resolution", "type", "activity",
})


def _heading(value: str, n: int, old_titles: set[str]) -> str:
    """Strict allowlist; do not infer a current client's name from the master."""
    normalized = " ".join(str(value).strip().split())
    key = normalized.casefold()
    # Native continuation/index columns may be only a few points wide. A
    # one-character source ordinal is a *shape clue*, not an old client's
    # current row or a license to print a long "Detail 1" heading vertically.
    if n == 0 and len(normalized) == 1 and (normalized.isdigit() or normalized == "#"):
        return "#"
    if key == "" or key in old_titles or key not in _GENERIC_LABELS:
        return f"Detail {n + 1}"
    return normalized


def from_inspection(inspection) -> tuple[MasterTable, ...]:
    """One independent safe schema per real data table; no source values."""
    from app.monthly_report_content_policy import logical_table_columns, table_price_columns
    from app.monthly_report_model import known_sections

    old_titles = {" ".join(t.casefold().split()) for t in inspection.title_candidates}
    photo_positions = {(x.position, x.part) for x in inspection.items if x.kind == "image"}
    available = set()
    for section in known_sections():
        for block in section.blocks:
            if block.type in ("table", "work_order_grid"):
                available.add(block.key)
    tables = []
    last_by_slot = {}
    for item in inspection.items:
        if (item.kind != "table" or item.part != "word/document.xml"
                or item.suggested_slot not in available or not item.rows
                or (item.position, item.part) in photo_positions):
            continue
        physical_width = len(item.rows[0])
        if physical_width < 2 or physical_width > 32:
            continue  # 1-cell titles and pathological tables are not data grids
        header = item.rows[0]
        if (len(item.rows) > 1 and sum(bool(c.strip()) for c in header) <= 1
                and sum(bool(c.strip()) for c in item.rows[1]) > 1):
            header = item.rows[1]
        logical = logical_table_columns(header)
        if len(logical) != physical_width:
            # No blind padding, inferred columns or old row values.
            continue
        # A long RFI/checklist can continue in a second *physical* Word table
        # without repeating its header. The first row of that second table is
        # real prior-client DATA (for example item 16), not another site's
        # future column headings. Only an explicit consecutive row ordinal,
        # same section, and identical physical grid can borrow the *already
        # sanitized* column geometry from the preceding table.
        previous = last_by_slot.get(item.suggested_slot)
        former_item, former_shape = previous if previous else (None, None)
        first_number = _row_number(item.rows[0][0])
        former_number = _row_number(former_item.rows[-1][0]) if former_item else None
        continuation = bool(
            former_item and former_shape
            and former_item.section == item.section
            and former_shape.physical_width == physical_width
            and first_number is not None and former_number is not None
            and first_number == former_number + 1
        )
        if continuation:
            keep, unique = former_shape.indices, former_shape.columns
        else:
            # No old data row is promoted into a current report grid. Source
            # values are inspected only to exclude monetary columns.
            blocked = set(table_price_columns(logical, item.rows[1:4]))
            keep = tuple(i for i in range(physical_width) if i not in blocked)
            if not keep:
                continue
            labels = tuple(_heading(logical[i], i, old_titles) for i in keep)
            unique = tuple(label + (f" ({n + 1})" if label in labels[:n] else "")
                           for n, label in enumerate(labels))
        shape = MasterTable(item.suggested_slot, item.position,
                            f"master-table:{inspection.sha256}:{item.id}",
                            tuple(unique), keep, physical_width, continuation=continuation)
        tables.append(shape)
        last_by_slot[item.suggested_slot] = (item, shape)
    return tuple(tables)


@lru_cache(maxsize=8)
def _inspect_cached(path: str, digest: str):
    from app.monthly_report_import import inspect_docx
    inspection = inspect_docx(Path(path))
    if inspection.sha256 != digest:
        raise ValueError("The pinned master changed during schema inspection.")
    return from_inspection(inspection)


def for_profile(profile) -> tuple[MasterTable, ...]:
    from app.monthly_report_designs import is_master, source_for
    if not is_master(profile):
        return ()
    path = source_for(profile)
    if path is None:
        return ()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return _inspect_cached(str(path), digest)


def initialize_master_tables(draft):
    """Add only *empty* tables to a newly designed report; never modify work."""
    from app.monthly_report_model import ReportTable, ResolvedBlock

    if draft.profile.imported_from:
        return draft
    discovered = for_profile(draft.profile)
    if not discovered:
        return draft
    blocks = {b.key: b for b in draft.blocks}
    valid = {b.key for s in draft.sections for b in s.blocks}
    grouped: dict[str, list[MasterTable]] = {}
    for table in discovered:
        if table.slot in valid:
            grouped.setdefault(table.slot, []).append(table)
    for key, tables in grouped.items():
        old = blocks.get(key, ResolvedBlock(key, "This month"))
        if old.source == "Omit" or old.rows or old.extra_tables or old.asset_hashes or old.org_nodes:
            continue  # Existing/current content and deliberate removals win.
        blocks[key] = replace(old, source="This month", extra_tables=tuple(
            ReportTable(t.columns, (), t.reference) for t in tables))
    return replace(draft, blocks=tuple(blocks.get(b.key, b) for b in draft.blocks)
                   + tuple(block for key, block in blocks.items()
                           if key not in {prior.key for prior in draft.blocks}))


def rebind_carried_master_tables(draft, previous_blocks, previous_template: str):
    """Retain same-master physical table IDs on new-month rollover only.

    The ordinary design-seed operation deliberately drops source data and
    provenance. Native *design frame identities*, unlike source facts, can be
    carried when both reports have the identical immutable master pin. Fail
    closed for changed master, mismatched columns or unrecognized old refs.
    """
    if draft.profile.template != previous_template:
        return draft
    accepted = {table.reference: table for table in for_profile(draft.profile)}
    if not accepted:
        return draft
    updated = []
    for block in draft.blocks:
        prior = previous_blocks.get(block.key)
        if (prior is None or not block.extra_tables
                or len(prior.extra_tables) != len(block.extra_tables)):
            updated.append(block)
            continue
        tables = []
        for current, former in zip(block.extra_tables, prior.extra_tables):
            master = accepted.get(former.reference)
            if (master is not None and master.slot == block.key
                    and len(current.columns) == len(master.columns)
                    and not current.rows):
                tables.append(replace(current, reference=former.reference))
            else:
                tables.append(current)
        updated.append(replace(block, extra_tables=tuple(tables)))
    return replace(draft, blocks=tuple(updated))
