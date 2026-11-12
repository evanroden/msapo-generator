"""Reviewed, source-bound Accounts Receivable status intake.

Amounts are visible only in internal review and retained in a bounded source
receipt. This module never grants monetary client-output permission. Its
Section 10 derivative contains only invoice identity, dates, status and aging;
a stripped-amount status view is never called a complete AR Aging statement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re

from app.monthly_report_content_policy import contains_price, table_has_pricing
from app.monthly_report_correction_targets import report_identity
from app.monthly_report_model import ReportTable, ResolvedBlock
from app.monthly_report_receivable_schema import inspect_receivable_schema

KIND = "receivables"
VERSION = 1
MAX_ROWS = 150
MAX_RECEIPT = 4_000_000
OUTPUT_COLUMNS = ("Facility", "Item", "Status")
AMOUNT_ROLES = ("invoice_amount", "payment_amount", "credit_amount", "balance")
EDITABLE = ("invoice_id", "customer_id", "site", "invoice_date", "due_date",
            "status", "currency", "description", "notes", *AMOUNT_ROLES)
_NOTICE = ("The reviewed invoice source, report scope, or Section 10 rows changed. "
           "Reopen and review that exact source; saved originals and edits are unchanged.")
_STATES = {
    "open": "Open",
    "unpaid": "Open",
    "outstanding": "Open",
    "partially paid": "Partially paid",
    "partial payment": "Partially paid",
    "partial": "Partially paid",
    "paid": "Paid",
    "paid in full": "Paid",
    "closed": "Closed",
    "credit": "Credit",
    "credit memo": "Credit",
    "disputed": "Disputed",
    "on hold": "On hold",
    "pending": "Pending",
}
_MONEY = re.compile(r"^[+-]?(?:\$)?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$")
# XLSX intake renders a currency-formatted cell as "<number> <marker>"
# (monthly_report_xlsx_currency.currency_evidence_value). Only US-dollar
# markers are read here; any other currency still needs a correction.
_XLSX_USD = re.compile(r"^([+-]?\d+(?:\.\d+)?) (?:\$|USD)$")
_INVOICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./#-]{0,71}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RECEIPT_LINK = "receivable:v1:"


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def _date(value, *, excel_serial=False):
    if not isinstance(value, str):
        return None
    # Legacy saved receipts deliberately interpreted only exact ISO strings.
    # Do not reclassify a formerly ambiguous saved cell on replay.
    raw = value
    if excel_serial and raw.isdecimal():
        # Excel's 1900 date system includes a fictitious leap day (serial 60).
        # Never reinterpret numeric CSV invoice identifiers as dates.
        serial = int(raw)
        if serial == 60 or serial < 1 or serial > 2_958_465:
            return None
        try:
            base = date(1899, 12, 31) if serial < 60 else date(1899, 12, 30)
            return base + timedelta(days=serial)
        except (ValueError, OverflowError):
            return None
    if not _ISO.fullmatch(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _money(value):
    """Preserve unknowns; never turn a missing amount into a zero balance."""
    if not isinstance(value, str):
        raise ValueError("An invoice amount must retain its source text.")
    raw = value.strip()
    if not raw or raw.casefold() in {"unknown", "not available", "n/a", "pending", "—", "-"}:
        return None  # Explicit unknown is not zero; source text remains in receipt.
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1].strip()
    xlsx = _XLSX_USD.fullmatch(raw)
    if xlsx:
        raw = xlsx.group(1)
    if not _MONEY.fullmatch(raw):
        raise ValueError("A monetary cell needs an explicit numeric correction; no balance was inferred.")
    try:
        number = Decimal(raw.replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ValueError("Invoice amount could not be read.") from exc
    return -number if negative else number


def _table_reference(source, number):
    return f"ar-source:{source.id}:table:{number}"


def inspect_content(draft, content, number, *, role_overrides=None):
    """Verify original bytes AND re-extract this one exact CSV/XLSX table."""
    from app import monthly_report_sources as sources
    source = content.source
    matches = [item for item in draft.sources if item.id == source.id]
    if (len(matches) != 1 or matches[0] != source
            or source.suffix not in (".csv", ".xlsx")
            or type(number) is not int or not 1 <= number <= len(content.tables)):
        raise ValueError("Select one unchanged saved invoice source and exact table.")
    raw = sources.source_bytes(draft.profile, source)
    actual = sources._spreadsheet(raw, source.suffix)
    if number > len(actual) or actual[number - 1] != content.tables[number - 1]:
        raise ValueError("The invoice table changed since its original was read.")
    table = actual[number - 1]
    review = inspect_receivable_schema(
        ReportTable(table.columns, table.rows, _table_reference(source, number)),
        source_sha256=source.sha256, role_overrides=role_overrides)
    if len(review.rows) > MAX_ROWS:
        raise ValueError("Review at most 150 invoice rows per intake; split larger source exports.")
    return review


def _profile_site(draft, raw):
    site = " ".join(raw.casefold().split())
    matches = [facility for facility in draft.profile.facilities
               if site and site in {" ".join(name.casefold().split()) for name in
                                    (facility.key, facility.title, *facility.aliases)}]
    if not site and len(draft.profile.facilities) == 1:
        return draft.profile.facilities[0].title
    if len(matches) != 1:
        raise ValueError("Invoice site is missing, foreign, or ambiguous. Correct the exact row before including it.")
    return matches[0].title


def _source_fields(review, row):
    fields = {}
    for col in review.columns:
        if col.candidate_role and col.candidate_role != "aging_bucket":
            fields[col.candidate_role] = row.cells[col.index]
    return fields


def editable_rows(review):
    """Native editor defaults; source strings remain separate immutable cells."""
    return [{**{"Source row": row.position}, **{
        role: _source_fields(review, row).get(role, "")
        for role in EDITABLE}} for row in review.rows]


def _review_row(draft, review, row, changed, as_of, *, invoice_aging=False, excel_serial=False):
    base = _source_fields(review, row)
    if not isinstance(changed, dict) or set(changed) - set(EDITABLE):
        raise ValueError("Unknown invoice correction field.")
    if any(not isinstance(v, str) for v in changed.values()):
        raise ValueError("Invoice corrections must remain text.")
    values = {**base, **changed}
    identifier = values.get("invoice_id", "").strip()
    if identifier.casefold() in {"total", "subtotal", "grand total", "beginning balance"}:
        raise ValueError("A title or total row is not an invoice; review a corrected export without silently counting it.")
    if not _INVOICE.fullmatch(identifier):
        raise ValueError("Invoice number is missing or includes unreviewable characters.")
    facility = _profile_site(draft, values.get("site", ""))
    raw_status = " ".join(values.get("status", "").casefold().split())
    state = _STATES.get(raw_status)
    if state is None:
        if invoice_aging and not raw_status:
            state = "Unknown status"
        else:
            raise ValueError("Invoice status is unknown. Correct the status explicitly.")
    invoice_date = _date(values.get("invoice_date", ""), excel_serial=excel_serial)
    due_date = _date(values.get("due_date", ""), excel_serial=excel_serial)
    source_as_of = values.get("as_of_date", "").strip()
    if source_as_of and _date(source_as_of, excel_serial=excel_serial) != as_of:
        raise ValueError("Source aging as-of date differs or is ambiguous; correct the exact source.")
    source_days = values.get("days_past_due", "").strip()
    if source_days and state not in ("Paid", "Closed", "Credit"):
        computed = max(0, (as_of - due_date).days) if due_date is not None else None
        if not source_days.isdecimal() or computed is None or int(source_days) != computed:
            raise ValueError("Source days past due conflict with the reviewed due/as-of dates.")
    original_date = values.get("invoice_date", "").strip()
    original_due = values.get("due_date", "").strip()
    # Unknown and ambiguous dates remain unknown, not locale-guessed.
    invoice_label = (invoice_date.isoformat() if invoice_date else
                     "unknown date" if not original_date else "date needs review")
    due_label = (due_date.isoformat() if due_date else
                 "unknown due date" if not original_due else "due date needs review")
    if state in ("Paid", "Closed"):
        bucket = "Closed — not aged as open"
    elif state == "Credit":
        bucket = "Credit — not aged as a receivable"
    elif invoice_aging:
        if state == "Unknown status":
            bucket = "Unknown aging — open status not verified"
        elif invoice_date is None:
            bucket = "Unknown aging — invoice date missing or invalid"
        else:
            elapsed = (as_of - invoice_date).days
            bucket = ("Future invoice — not aged" if elapsed < 0 else
                      "Current (0–30 days)" if elapsed <= 30 else
                      "31–60 days" if elapsed <= 60 else
                      "61–90 days" if elapsed <= 90 else
                      "91–120 days" if elapsed <= 120 else "121+ days")
    elif due_date is None:
        bucket = "Unknown aging — due date not established"
    else:
        # Preserve saved legacy receipt interpretation. Never silently migrate
        # a previously approved due-date/as-of status review.
        elapsed = (as_of - due_date).days
        bucket = ("Current" if elapsed <= 0 else "1–30 days" if elapsed <= 30
                  else "31–60 days" if elapsed <= 60 else "61–90 days" if elapsed <= 90
                  else "91+ days")
    financial = {key: values.get(key, "") for key in AMOUNT_ROLES}
    parsed = {key: _money(value) for key, value in financial.items()}
    original, payment, credit, balance = (parsed.get(key) for key in AMOUNT_ROLES)
    if (all(v is not None for v in (original, payment, credit, balance))
            and original - payment - (abs(credit) if invoice_aging else credit) != balance):
        raise ValueError("Invoice, payment, credit and remaining balance disagree; correct the exact row.")
    if state in ("Paid", "Closed") and balance not in (None, Decimal(0)):
        raise ValueError("A paid or closed invoice still has an outstanding source balance.")
    if payment is not None and payment < 0 or (not invoice_aging and credit is not None and credit < 0):
        raise ValueError("Payment or credit has an ambiguous negative sign.")
    account = values.get("customer_id", "").strip()
    # No amount, raw source detail, unreviewed price, or financial total reaches
    # the client block, even for a source the operator describes as a contract.
    aging_label = ("aging by invoice date as of " if invoice_aging else "aging as of ")
    output = (facility, "Invoice " + identifier + " · issued " + invoice_label,
              state + " · due " + due_label + " · " + aging_label +
              as_of.isoformat() + ": " + bucket +
              (" · outstanding balance unknown" if state == "Partially paid" and balance is None else ""))
    if any(contains_price(text) for text in output) or table_has_pricing(OUTPUT_COLUMNS, (output,)):
        raise ValueError("Client invoice status text resembles monetary content; correct the source identifiers.")
    record = {
        "reference": row.reference,
        "cells": list(row.cells),
        "corrections": changed,
        "invoice_id": identifier,
        "account": account,
        "site": facility,
        "status": state,
        "invoice_date_raw": values.get("invoice_date", ""),
        "due_date_raw": values.get("due_date", ""),
        "aging": bucket,
        "source_amounts": financial,
    }
    if invoice_aging:
        # A source balance is accepted as reconciled only when the complete
        # invoice/payment/credit/balance tuple is supplied and agrees.
        reconciled = all(v is not None for v in (original, payment, credit, balance))
        record["open_balance"] = str(balance) if reconciled else None
        record["balance_reconciliation"] = "reconciled" if reconciled else "unresolved"
        record["description"] = values.get("description", "")
        record["notes"] = values.get("notes", "")
    return record, output


def prepare_review(draft, content, table_number, *, as_of, edited, source_kind,
                   confirmed=False, role_overrides=None):
    """Return (new draft, new AR block) only after the *entire* review passes.

    An operator confirms source category for internal record context, not
    financial output permission. Original cells/amounts remain in a receipt
    separate from the three-column client status derivative.
    """
    if not confirmed or source_kind not in (
            "customer_invoice", "vendor_invoice", "contract",
            "enfra_client_report", "unverified"):
        raise ValueError("Confirm the original invoice rows and their source category.")
    stamp = _date(as_of)
    if stamp is None:
        raise ValueError("Enter an explicit ISO aging as-of date; no date is inferred.")
    if stamp != draft.period.end:
        raise ValueError("Invoice-date aging as-of must equal the selected report-month end.")
    section = [s for s in draft.sections if s.key == "accounts_receivable" and s.included]
    if len(section) != 1 or not any(b.key == "accounts_receivable" for b in section[0].blocks):
        raise ValueError("Include the existing Accounts Receivable section before importing.")
    review = inspect_content(draft, content, table_number,
                             role_overrides=role_overrides)
    roles = [col.candidate_role for col in review.columns]
    if (review.duplicate_roles or
            not all(roles.count(role) == 1 for role in ("invoice_id", "invoice_date", "balance"))):
        raise ValueError("Invoice number, invoice date and amount due need one unambiguous heading each.")
    if not review.rows:
        raise ValueError("The invoice table has no rows to review.")
    if not isinstance(edited, dict) or set(edited) != {row.reference for row in review.rows}:
        raise ValueError("Every source invoice row requires an explicit review.")
    records, output, identities = [], [], set()
    for row in review.rows:
        correction = edited[row.reference]
        record, public = _review_row(
            draft, review, row, correction, stamp, invoice_aging=True,
            excel_serial=content.source.suffix == ".xlsx")
        key = (public[0].casefold(), record["account"].casefold(), record["invoice_id"].casefold())
        if key in identities:
            raise ValueError("Two source rows have the same site, account and invoice number. Resolve the duplicate.")
        identities.add(key)
        records.append(record)
        output.append(public)
    if not output:
        raise ValueError("No invoice rows were accepted.")
    from app.monthly_report_correction_targets import report_identity
    receipt = {"kind": KIND, "version": VERSION, "report": report_identity(draft),
               "period": draft.period.key, "source_id": content.source.id,
               "source_sha256": content.source.sha256,
               "table_number": table_number, "table_reference": review.table_reference,
               "table_fingerprint": review.fingerprint,
               "as_of": as_of, "source_kind": source_kind,
               "aging_basis": "invoice_date_month_end",
               "excel_serial_dates": content.source.suffix == ".xlsx",
               "source_heading_roles": [col.candidate_role for col in review.columns],
               "role_overrides": {str(i): value for i, value in
                                  sorted((role_overrides or {}).items())},
               "rows": records, "output_rows": [list(item) for item in output]}
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(payload) > MAX_RECEIPT:
        raise ValueError("Reviewed invoice rows exceed the saved review budget.")
    ref = _RECEIPT_LINK + _digest(receipt)
    blocks = [b for b in draft.blocks if b.key == "accounts_receivable"]
    if len(blocks) > 1:
        raise ValueError("Accounts Receivable block identity is ambiguous.")
    prior = blocks[0] if blocks else ResolvedBlock("accounts_receivable", "This month")
    # Keep ordinary draft notes and unrelated sections. An explicit new review
    # replaces only the AR status rows and their previous invoice receipt.
    from app.monthly_report_sources import source_reference
    origin = source_reference(content.source, table_number)
    updated = replace(prior, source="This month", rows=tuple(output),
                      references=tuple(x for x in prior.references if
                                       not x.startswith(_RECEIPT_LINK) and not x.startswith("ar-source:")
                                       and not (x.split(":")[0] == content.source.id and len(x.split(":")) == 3))
                                 + (origin, ref,),
                      reviewed_fingerprint="", client_reviewed_fingerprint="")
    def is_prior_ar(value):
        try:
            return isinstance(value, str) and json.loads(value).get("kind") == KIND
        except (TypeError, ValueError, AttributeError):
            return False
    saved = [value for value in draft.source_row_reviews if not is_prior_ar(value)]
    saved.append(payload)
    revised = replace(draft,
                      blocks=tuple(updated if b.key == "accounts_receivable" else b for b in draft.blocks)
                             + (() if blocks else (updated,)),
                      source_row_reviews=tuple(saved))
    return revised, updated


def decoded(text):
    """Bounded structural validation for persisted AR receipts."""
    if not isinstance(text, str) or len(text) > MAX_RECEIPT:
        raise ValueError(_NOTICE)
    try:
        item = json.loads(text)
        if (not isinstance(item, dict) or item.get("kind") != KIND or
                item.get("version") != VERSION or
                not all(isinstance(item.get(key), str) for key in (
                    "report", "period", "source_id", "source_sha256",
                    "table_reference", "table_fingerprint", "as_of", "source_kind")) or
                type(item.get("table_number")) is not int or item["table_number"] < 1 or
                not isinstance(item.get("rows"), list) or
                not isinstance(item.get("output_rows"), list) or
                not 0 < len(item["rows"]) <= MAX_ROWS or
                len(item["rows"]) != len(item["output_rows"]) or
                any(not isinstance(row, dict) or not isinstance(row.get("cells"), list)
                    or not isinstance(row.get("reference"), str) for row in item["rows"]) or
                any(not isinstance(row, list) or len(row) != 3 or
                        any(not isinstance(cell, str) for cell in row)
                    for row in item["output_rows"])):
            raise ValueError(_NOTICE)
        if (not re.fullmatch(r"[0-9a-f]{64}", item["source_sha256"]) or
                not re.fullmatch(r"[0-9a-f]{64}", item["table_fingerprint"]) or
                not re.fullmatch(r"[0-9a-f]{64}", item["report"]) or
                _date(item["as_of"]) is None):
            raise ValueError(_NOTICE)
        return item
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(_NOTICE) from exc


def check_review_binding(draft):
    """Fail closed if a source-backed status table outlives its source/receipt.

    Legacy manually entered AR tables without a new receipt remain covered by
    existing general pricing and mandatory preflight rules.
    """
    if not any(section.key == "accounts_receivable" and section.included
               for section in draft.sections):
        return None
    matches = [b for b in draft.blocks if b.key == "accounts_receivable"]
    if len(matches) > 1:
        return _NOTICE
    block = matches[0] if matches else None
    if block is None or block.source == "Omit":
        return None
    refs = [value for value in block.references if value.startswith(_RECEIPT_LINK)]
    if not refs:
        return None
    if len(refs) != 1:
        return _NOTICE
    candidates = []
    for raw in draft.source_row_reviews:
        try:
            record = decoded(raw)
        except ValueError:
            continue  # Other protected receipt kinds are not AR evidence.
        if _RECEIPT_LINK + _digest(record) == refs[0]:
            candidates.append(record)
    if len(candidates) != 1:
        return _NOTICE
    receipt = candidates[0]
    if (receipt["report"] != report_identity(draft) or
            receipt["period"] != draft.period.key or
            block.rows != tuple(tuple(row) for row in receipt["output_rows"])):
        return _NOTICE
    sources = [s for s in draft.sources if s.id == receipt["source_id"]]
    if len(sources) != 1 or sources[0].sha256 != receipt["source_sha256"]:
        return _NOTICE
    from app.monthly_report_sources import source_reference
    if source_reference(sources[0], receipt["table_number"]) not in block.references:
        return _NOTICE
    try:
        from app import monthly_report_sources as source_api
        raw = source_api.source_bytes(draft.profile, sources[0])
        tables = source_api._spreadsheet(raw, sources[0].suffix)
        number = receipt["table_number"]
        if not 1 <= number <= len(tables):
            return _NOTICE
        table = tables[number - 1]
        encoded_mapping = receipt.get("role_overrides", {})
        if (not isinstance(encoded_mapping, dict) or any(
                not isinstance(index, str) or
                not re.fullmatch(r"(?:0|[1-9][0-9]*)", index)
                for index in encoded_mapping)):
            return _NOTICE
        mapping = {int(index): value for index, value in encoded_mapping.items()}
        review = inspect_receivable_schema(
            ReportTable(table.columns, table.rows, receipt["table_reference"]),
            source_sha256=sources[0].sha256, role_overrides=mapping)
        if receipt.get("aging_basis") == "invoice_date_month_end" and (
                [col.candidate_role for col in review.columns] != receipt["source_heading_roles"]):
            return _NOTICE
    except (ValueError, OSError, KeyError, TypeError, OverflowError):
        return _NOTICE
    if (receipt["table_reference"] != _table_reference(sources[0], number) or
            review.fingerprint != receipt["table_fingerprint"] or
            [list(row.cells) for row in review.rows] != [item["cells"] for item in receipt["rows"]]):
        return _NOTICE
    # A saved metadata record is not approval. Rebuild every client status row
    # from the unchanged source and its explicit corrections; any tamper,
    # dropped row, foreign site or monetary text fails closed.
    if len(receipt["rows"]) != len(review.rows):
        return _NOTICE
    if receipt["source_kind"] not in (
            "customer_invoice", "vendor_invoice", "contract", "enfra_client_report", "unverified"):
        return _NOTICE
    basis = receipt.get("aging_basis")
    if basis not in (None, "invoice_date_month_end"):
        return _NOTICE
    if basis == "invoice_date_month_end" and (
            _date(receipt["as_of"]) != draft.period.end
            or receipt.get("excel_serial_dates") is not (sources[0].suffix == ".xlsx")):
        return _NOTICE
    try:
        expected = []
        for row, stored in zip(review.rows, receipt["rows"]):
            regenerated, public = _review_row(
                draft, review, row, stored.get("corrections"), _date(receipt["as_of"]),
                invoice_aging=basis == "invoice_date_month_end",
                excel_serial=basis == "invoice_date_month_end" and sources[0].suffix == ".xlsx")
            if regenerated != stored:
                return _NOTICE
            expected.append(public)
        if tuple(expected) != block.rows:
            return _NOTICE
    except (KeyError, TypeError, ValueError):
        return _NOTICE
    return None
