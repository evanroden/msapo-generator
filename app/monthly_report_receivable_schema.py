"""Read-only invoice-table discovery; not AR approval, ingestion or output.

Field roles are candidates based on complete source headings. No dates, amounts,
statuses, balances, aging buckets or duplicate rows are inferred or rewritten.
The caller supplies the original source's digest and exact table reference.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from app.monthly_report_content_policy import table_price_columns
from app.monthly_report_model import ReportTable


_HEADINGS = {
    "invoice_id": ("invoice", "invoice number", "invoice no", "invoice id", "invoice #"),
    "customer_id": ("customer id", "customer number", "customer account", "account number"),
    "site": ("site", "facility", "location"),
    "invoice_date": ("invoice date", "date invoiced"),
    "due_date": ("due date", "payment due date"),
    "status": ("status", "invoice status", "payment status"),
    "as_of_date": ("as of date", "aging as of", "aging as of date"),
    "days_past_due": ("days past due", "days overdue"),
    "currency": ("currency", "currency code"),
    "invoice_amount": ("invoice amount", "original amount"),
    "balance": ("balance", "balance due", "outstanding balance", "amount due"),
    "payment_amount": ("amount paid", "paid amount", "payment amount"),
    "credit_amount": ("credit amount", "credit balance"),
}
_FINANCIAL_ROLES = frozenset((
    "invoice_amount", "balance", "payment_amount", "credit_amount", "aging_bucket",
))
_ROLE_BY_HEADING = {heading: role for role, headings in _HEADINGS.items() for heading in headings}


def _heading(value):
    return " ".join(value.casefold().strip().rstrip(".").split())


@dataclass(frozen=True)
class ReceivableColumn:
    index: int
    heading: str
    candidate_role: str
    policy_controlled: bool


@dataclass(frozen=True)
class ReceivableRow:
    # One-based data-row position, not a claim about a workbook or PDF line.
    position: int
    reference: str
    cells: tuple[str, ...]
    blank_roles: tuple[str, ...]


@dataclass(frozen=True)
class ReceivableSchemaReview:
    source_sha256: str
    table_reference: str
    fingerprint: str
    columns: tuple[ReceivableColumn, ...]
    rows: tuple[ReceivableRow, ...]
    duplicate_roles: tuple[str, ...]
    unknown_columns: tuple[int, ...]
    missing_roles: tuple[str, ...]
    # These decisions must be resolved before wiring this diagnostic to intake.
    pending_decisions: tuple[str, ...] = (
        "output audience and permitted fields (#458)",
        "invoice identity scope and duplicate/conflict handling",
        "aging date basis, as-of date and bucket boundaries",
        "partial payments, credits, paid and closed records",
    )


def inspect_receivable_schema(table: ReportTable, *, source_sha256: str) -> ReceivableSchemaReview:
    """Inventory raw source fields without authorizing any report contribution.

    A repeated role is deliberately not selected. All source cells, including
    empty values, money and repeated rows, remain in this diagnostic only.
    This does not verify that a supplied digest corresponds to source bytes.
    """
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("Provide the original source's SHA-256 digest.")
    if not isinstance(table.reference, str) or not table.reference.strip():
        raise ValueError("Provide the source table reference.")
    if (not table.columns or any(not isinstance(value, str) for value in table.columns)
            or any(len(row) != len(table.columns) or any(not isinstance(value, str) for value in row)
                   for row in table.rows)):
        raise ValueError("Review requires a rectangular table of source text cells.")

    roles = [_ROLE_BY_HEADING.get(_heading(title), "") for title in table.columns]
    # "Current" and ranges are financial buckets only in an explicit invoice
    # and balance/amount context. No generic technical table is reclassified.
    invoice_context = "invoice_id" in roles and any(role in _FINANCIAL_ROLES for role in roles)
    if invoice_context:
        for index, title in enumerate(table.columns):
            heading = _heading(title)
            if not roles[index] and (heading == "current" or re.fullmatch(
                    r"\d+\s*[-–]\s*(?:\d+|over)(?:\s+days)?|\d+\+\s*(?:days)?", heading)):
                roles[index] = "aging_bucket"

    policy_columns = set(table_price_columns(table.columns, table.rows))
    columns = tuple(ReceivableColumn(index, title, roles[index],
        index in policy_columns or roles[index] in _FINANCIAL_ROLES)
        for index, title in enumerate(table.columns))
    # Different aging columns are intentional, unlike two competing Due dates.
    duplicates = tuple(sorted(role for role in set(roles) - {"", "aging_bucket"}
                              if roles.count(role) > 1))
    rows = tuple(ReceivableRow(index + 1, f"{table.reference}:row:{index + 1}", tuple(row),
        tuple(role for role, value in zip(roles, row) if role and not value.strip()))
        for index, row in enumerate(table.rows))
    payload = {"source_sha256": source_sha256, "reference": table.reference,
               "columns": table.columns, "rows": table.rows}
    fingerprint = sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                                    sort_keys=True).encode()).hexdigest()
    return ReceivableSchemaReview(source_sha256, table.reference, fingerprint, columns, rows,
        duplicates, tuple(index for index, role in enumerate(roles) if not role),
        tuple(role for role in ("invoice_id", "site", "status", "due_date", "as_of_date")
              if role not in roles))
