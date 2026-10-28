"""Conservative source-bound conversion of issue registers into reviewable cards.

A row is an issue only when the source table explicitly identifies a description
and status, plus an owner, action or date. Unrecognized layouts retain the
existing generic table migration and can be corrected without inferred fields.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from app.monthly_report_content_policy import table_price_columns


@dataclass(frozen=True)
class RegisterIssue:
    key: str
    text: str
    status: str = "ongoing"
    update: str = ""
    evidence_note: str = ""


_DESCRIPTION = {"issue", "issue description", "description", "finding",
                "problem", "equipment issue", "equipment issue description"}
_STATUS = {"status", "issue status", "state"}
_OWNER = {"owner", "assigned to", "assignee", "responsible", "responsible party", "person responsible"}
_ACTION = {"action", "action required", "next action", "corrective action", "resolution action"}
_DATE = {"date", "date opened", "open date", "reported date", "date reported",
         "identified", "date identified", "closed date", "date closed",
         "updated date", "last updated", "target date", "due date"}


def _label(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).strip()


def mapped_issue_register(columns, rows, reference="") -> tuple[RegisterIssue, ...] | None:
    """Read only unambiguous register schemas; keep all technical source cells.

    The workflow's status is **not** taken as resolved from a source's "Closed"
    or "Done" cell. The operator must confirm resolution and its evidence.
    All original non-price fields, including source status and unknown columns,
    are visible in the card description and therefore also in Word/PDF output.
    """
    if not rows or not columns:
        return None
    width = max(len(columns), *(len(row) for row in rows))
    headings = tuple(str(value) for value in columns) + tuple(
        f"Detail {i + 1}" for i in range(len(columns), width))
    normalized = tuple(_label(h) for h in headings)
    if len(set(normalized)) != len(normalized):
        return None
    desc = [i for i, label in enumerate(normalized) if label in _DESCRIPTION]
    status = [i for i, label in enumerate(normalized) if label in _STATUS]
    contextual = [i for i, label in enumerate(normalized)
                  if label in _OWNER or label in _ACTION or label in _DATE]
    if len(desc) != 1 or len(status) != 1 or not contextual:
        return None
    if any(len([i for i, label in enumerate(normalized) if label in group]) > 1
           for group in (_DESCRIPTION, _STATUS, _OWNER, _ACTION)):
        return None
    prices = set(table_price_columns(headings, rows))
    if desc[0] in prices or status[0] in prices:
        return None

    result = []
    for index, row in enumerate(rows):
        original = tuple(str(value or "") for value in row)
        values = original + ("",) * (width - len(original))
        if not any(value.strip() for i, value in enumerate(values) if i not in prices):
            continue
        if tuple(_label(value) for value in values) == normalized:
            continue  # Repeated register header is not a source issue.
        issue = values[desc[0]].strip()
        fields = [(headings[i], value.strip()) for i, value in enumerate(values)
                  if i not in prices and i != desc[0] and value.strip()]
        # A blank/missing description becomes an explicitly unresolved row,
        # not a fabricated equipment finding or a silently dropped record.
        text = issue or "Unresolved issue-register row (description missing)"
        if fields:
            text += "\n" + "; ".join(f"{title}: {value}" for title, value in fields)
        # Source status remains visible, but does not authorize a resolution.
        source_status = values[status[0]].strip()
        note = ("Imported issue register row " + str(index + 1) +
                ". Review the source status" +
                (f" ({source_status})" if source_status else " (blank)") +
                " and any action/date before confirming this report's status.")
        digest = hashlib.sha256(json.dumps(
            ["issue-register-v1", reference, index, headings, original],
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
        result.append(RegisterIssue("follow-" + digest, text, evidence_note=note))
    return tuple(result)
