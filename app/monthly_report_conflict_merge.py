"""Conservative three-way merge for stale *browser* Monthly drafts.

This module never writes. Callers must recheck the remote journal's exact
revision/generation under active_work.save's CAS after explicit user choice.
Ambiguous structural changes are a conflict, never a positional rebase.
"""
from dataclasses import dataclass, fields, replace
import json

from app.monthly_report_model import (
    ReportDraft, ReportSource, ResolvedBlock, ReportTable, TrainingSessionTable,
)


@dataclass(frozen=True)
class MergeBase:
    """The saved draft that a three-way merge compares against.

    Kept in session state beside the working draft. It is wrapped so that
    anything looking for the working ReportDraft (by type, or by a key that
    ends in "_draft") cannot pick the merge base instead.
    """
    draft: ReportDraft


def merge_base(value):
    """The wrapped merge-base draft, or None for anything else."""
    return value.draft if isinstance(value, MergeBase) else None


@dataclass(frozen=True)
class FieldConflict:
    path: str
    before: object
    this_page: object
    newer: object


def _same_scope(left, right):
    return (left.profile.contract, left.profile.key, left.period.key,
            tuple(site.key for site in left.profile.facilities)) == (
            right.profile.contract, right.profile.key, right.period.key,
            tuple(site.key for site in right.profile.facilities))


def _receipt_index(values):
    """Use only validated *identity shape*, not the saved review's free text.

    A receipt can contain financial or sensitive source data. We keep its raw
    bytes opaque and never normalize, interpret, or export its content here.
    Unknown/duplicate/malformed identities reject granular reconciliation.
    """
    if len(values) > 100 or sum(len(value) for value in values if isinstance(value, str)) > 16_000_000:
        raise ValueError("Source-review collection exceeds its budget.")
    result = {}
    for raw in values:
        if not isinstance(raw, str) or len(raw) > 4_000_000:
            raise ValueError("Unsupported source-review record.")
        try:
            item = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError("Malformed source-review record.") from exc
        if (not isinstance(item, dict) or type(item.get("schema")) is not int or item["schema"] != 1
                or item.get("kind") not in ("training", "workorders", "maintenance")
                or not all(isinstance(item.get(k), str) and item[k] for k in
                           ("scope", "source_id", "source_fingerprint"))):
            raise ValueError("Unknown source-review identity.")
        table = item.get("table") if item["kind"] == "training" else None
        if item["kind"] == "training" and (type(table) is not int or table < 1):
            raise ValueError("Unknown Training source table.")
        identity = (item["kind"], item["scope"], item["source_id"],
                    item["source_fingerprint"], table)
        if identity in result:
            raise ValueError("Duplicate source-review identity.")
        result[identity] = raw
    return result


def merge_drafts(base: ReportDraft, this_page: ReportDraft, newer: ReportDraft, choices=None):
    """Return (draft, unresolved conflicts) without mutating any of the copies.

    Each decision is an exact conflict path mapped to 'this_page' or 'newer'.
    The UI binds those decisions to the currently compared pair and lets the
    journal CAS reject an intervening writer. Rows without stable identities
    remain atomic rather than being merged by a possibly shifted index.
    """
    if not all(isinstance(item, ReportDraft) for item in (base, this_page, newer)):
        raise ValueError("Recovery comparison needs three complete report drafts.")
    if not (_same_scope(base, this_page) and _same_scope(base, newer)):
        raise ValueError("Recovery copies refer to different report sites or months.")
    choices = choices or {}
    conflicts = []

    def conflict(path, old, ours, theirs):
        if choices.get(path) == "this_page":
            return ours
        if choices.get(path) == "newer":
            return theirs
        conflicts.append(FieldConflict(path, old, ours, theirs))
        return theirs  # only a preview value; caller MUST NOT save unresolved.

    def merge(path, old, ours, theirs, *, headers=()):
        if ours == theirs:
            return ours
        if ours == old:
            return theirs
        if theirs == old:
            return ours
        if type(old) is not type(ours) or type(old) is not type(theirs):
            return conflict(path, old, ours, theirs)

        # Dataclass shape is stable; contract/site/period and complex design
        # values are never recursively made into synthetic hybrid identities.
        if isinstance(old, (ReportDraft, ResolvedBlock, ReportSource, ReportTable)):
            if (isinstance(old, ReportTable)
                    and (old.columns != ours.columns or old.columns != theirs.columns)):
                return conflict(path, old, ours, theirs)
            if (isinstance(old, ReportDraft)
                    and ((old.sources != ours.sources and old.source_row_reviews != theirs.source_row_reviews)
                         or (old.sources != theirs.sources and old.source_row_reviews != ours.source_row_reviews))):
                return conflict("source identity and reviewed corrections", old, ours, theirs)
            changes = {}
            for field in fields(old):
                name = field.name
                values = (getattr(item, name) for item in (old, ours, theirs))
                a, b, c = values
                next_path = f"{path}.{name}" if path else name
                if isinstance(old, ReportTable) and name == "rows":
                    changes[name] = merge(next_path, a, b, c, headers=old.columns)
                else:
                    changes[name] = merge(next_path, a, b, c)
            result = replace(old, **changes)
            if isinstance(result, ReportTable) and any(len(row) != len(result.columns) for row in result.rows):
                # A simultaneous schema change cannot silently misalign cells.
                return conflict(path, old, ours, theirs)
            return result

        if isinstance(old, tuple) and isinstance(ours, tuple) and isinstance(theirs, tuple):
            if path == "source_row_reviews":
                try:
                    before, page, current = (_receipt_index(values) for values in (old, ours, theirs))
                except ValueError:
                    return conflict(path, old, ours, theirs)
                order = tuple(dict.fromkeys((*before, *current, *page)))
                kept = []
                for key in order:
                    label = f"{key[0]} · source {key[2]}" + (
                        f" · table {key[4]}" if key[4] is not None else "")
                    entry = merge(f"{path}[{label}]", before.get(key), page.get(key), current.get(key))
                    if entry is not None:
                        kept.append(entry)
                return tuple(kept)
            if len(old) != len(ours) or len(old) != len(theirs):
                return conflict(path, old, ours, theirs)
            leaf = path.rsplit(".", 1)[-1]
            if leaf in ("blocks", "sources", "extra_tables"):
                attr = {"blocks": "key", "sources": "id", "extra_tables": "reference"}[leaf]
                identities = [tuple(getattr(item, attr, None) for item in seq) for seq in (old, ours, theirs)]
                if (identities[0] == identities[1] == identities[2]
                        and len(set(identities[0])) == len(identities[0])):
                    return tuple(merge(f"{path}[{identity}]", a, b, c)
                                 for identity, a, b, c in zip(identities[0], old, ours, theirs))
            if leaf == "row_tokens" and old and len(set(old)) == len(old):
                return tuple(merge(f"{path}[row {i + 1}]", a, b, c)
                             for i, (a, b, c) in enumerate(zip(old, ours, theirs)))
            if leaf == "rows":
                # A stable first-cell identity is required. If the row order,
                # row membership or label changed, treat the whole grid as
                # conflicting; a deletion/recreation is not the old row.
                if headers[:2] == ("Team member", "Site"):
                    identity_size = 2
                elif "blocks[contact_matrix].rows" in path:
                    identity_size = 3  # site + role + name; phone/email are editable
                elif "training:events:v1" in path:
                    identity_size = 2  # topic + session date
                else:
                    identity_size = 1
                identities = [tuple(row[:identity_size] if isinstance(row, tuple)
                                    and len(row) >= identity_size else None for row in seq)
                              for seq in (old, ours, theirs)]
                valid_rows = all(
                    isinstance(a, tuple) and isinstance(b, tuple) and isinstance(c, tuple)
                    and len(a) == len(b) == len(c) for a, b, c in zip(old, ours, theirs))
                if (valid_rows and identities[0] == identities[1] == identities[2]
                        and None not in identities[0]
                        and len(set(identities[0])) == len(identities[0])):
                    values = []
                    for i, (a, b, c) in enumerate(zip(old, ours, theirs)):
                        label = str(a[0])
                        values.append(tuple(merge(
                            f"{path}[row {i + 1}: {label}].{headers[j] if j < len(headers) else 'column ' + str(j + 1)}",
                            x, y, z) for j, (x, y, z) in enumerate(zip(a, b, c))))
                    return tuple(values)
        return conflict(path or "report", old, ours, theirs)

    merged = merge("", base, this_page, newer)
    return (merged if not conflicts else None), tuple(conflicts)
