"""Fact-free native table schemas for a new report using an ENFRA master."""

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
import re

from app.monthly_report_model import BlockSpec, ColumnSpec, ReportTable, ResolvedBlock, profile_sections


@dataclass(frozen=True)
class MasterTable:
    slot: str
    position: int
    reference: str
    columns: tuple[str, ...]
    indices: tuple[int, ...]
    header_index: int
    physical_width: int


def _safe_heading(value, index, source_titles):
    value = re.sub(r'\s+', ' ', value).strip()
    if (not value or len(value) > 85 or '@' in value
            or re.search(r'\d{3}[ .()-]*\d{3}[ .-]*\d{4}', value)
            or re.search(r'\b(?:director|manager)\s*:', value, re.I)):
        return f'Column {index + 1}'
    if (value.casefold() in source_titles or re.search(r'\b(?:hospital|medical|memorial|regional|UMMC|USH|RRH)\b', value, re.I)):
        return 'Facility'
    return value


@lru_cache(maxsize=16)
def master_tables(source_path, source_hash):
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_content_policy import logical_table_columns, table_price_columns
    inspection = inspect_docx(Path(source_path))
    if inspection.sha256 != source_hash:
        raise ValueError('The saved master changed while its table design was being read.')
    titles = {x.casefold().strip() for x in inspection.title_candidates}
    result, previous = [], {}
    for item in inspection.items:
        if item.part != 'word/document.xml' or item.kind != 'table' or not item.suggested_slot or not item.rows:
            continue
        # A table used purely to place photographs is not a data-entry schema.
        if any(i.kind == 'image' and i.position == item.position and i.part == item.part for i in inspection.items):
            continue
        width = len(item.rows[0])
        header_index = 0
        first = item.rows[0]
        if (len(item.rows) > 1 and sum(bool(c.strip()) for c in first) <= 1
                and sum(bool(c.strip()) for c in item.rows[1]) > 1):
            header_index = 1
        raw_headers = logical_table_columns(item.rows[header_index])
        # An explicitly numbered continuation row is data, never a heading.
        prior = previous.get(item.suggested_slot)
        continuation = bool(first and re.fullmatch(r'\s*\d+[.)]?\s*', first[0]) and prior and prior.physical_width == width)
        if continuation:
            columns, keep = prior.columns, prior.indices
            header_index = -1
        else:
            excluded = set(table_price_columns(raw_headers, item.rows[header_index + 1:]))
            keep = tuple(i for i in range(width) if i not in excluded)
            columns = tuple(_safe_heading(raw_headers[i], i, titles) for i in keep)
            columns = tuple(c + (f' ({n + 1})' if c in columns[:n] else '') for n, c in enumerate(columns))
        if not columns:
            continue
        value = MasterTable(item.suggested_slot, item.position,
                            f'master-table:{source_hash}:{item.id}', columns, tuple(keep), header_index, width)
        result.append(value)
        previous[item.suggested_slot] = value
    return tuple(result)


def for_profile(profile):
    from app.monthly_report_designs import is_master, source_for
    if not is_master(profile):
        return ()
    source = source_for(profile)
    if source is None:
        return ()
    import hashlib
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return master_tables(str(source), digest)


def initialize_master_tables(draft):
    """Seed editable native headers only; never source values or source facts.

    Saved/current tables remain authoritative. Empty native scaffolds use the
    existing per-table editor, avoiding a second generic input for the same data.
    """
    if draft.profile.imported_from:
        return draft
    designs = for_profile(draft.profile)
    if not designs:
        return draft
    grouped = {}
    for table in designs:
        grouped.setdefault(table.slot, []).append(table)
    blocks = {b.key: b for b in draft.blocks}
    specs = {b.key: b for s in draft.sections for b in s.blocks}
    overrides = {b.key: b for b in draft.profile.block_overrides}
    for slot, tables in grouped.items():
        if slot not in specs:
            continue
        block = blocks.get(slot, ResolvedBlock(slot, 'This month'))
        if block.rows or block.extra_tables or block.asset_hashes:
            continue
        # Continuation frames have no separate input and no invented header.
        editable = [table for table in tables if table.header_index >= 0]
        if not editable:
            continue
        overrides[slot] = replace(specs[slot], columns=tuple(ColumnSpec(f'native_{i}', c) for i, c in enumerate(editable[0].columns)))
        blocks[slot] = replace(block, source='This month', extra_tables=tuple(
            ReportTable(t.columns, (), t.reference) for t in editable))
    profile = replace(draft.profile, block_overrides=tuple(overrides.values()))
    resolved = {s.key: s for s in profile_sections(profile)}
    sections = tuple(replace(s, blocks=tuple(replace(b, required=False) for b in resolved[s.key].blocks)) for s in draft.sections)
    return replace(draft, profile=profile, sections=sections,
                   blocks=tuple(blocks.get(b.key, b) for b in draft.blocks)
                          + tuple(b for key, b in blocks.items() if key not in {old.key for old in draft.blocks}))
