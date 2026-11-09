"""Report-owned row reviews shared by the visible source workspace and exports.

No upload or passive rerender approves a record. Existing source adapters own
extraction; this module owns explicit correction, durable receipts and guarded
publication into the existing report blocks.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json

from app.monthly_report_row_review_receipts import decoded as saved_receipt

from app.monthly_report_model import ReportTable, ResolvedBlock
from app.monthly_report_work_order_normalized import (
    FIELDS, ColumnMapping, correct_row, exclude_row, restore_review, review_record,
)
from app.monthly_report_work_order_counts import count_reviewed_work_orders
from app.monthly_report_work_order_csv_review import review_spreadsheet
from app.monthly_report_service_call_mapping import (
    FIELDS as CALL_FIELDS, correct_service_call, exclude_service_call,
    exclude_unmatched_call, confirm_financial_exclusion, confirm_word_layout,
    restore_service_call_review, service_call_review_record, review_service_calls,
    reviewed_service_call_block, suggest_call_mapping,
)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def revision(value):
    return sha256(encoded(value).encode()).hexdigest()


def scope(draft):
    return revision((draft.profile.contract, draft.profile.key,
        [asdict(site) for site in draft.profile.facilities], draft.period.key))


def decoded(text):
    """Validate stored structure without granting current source/site authority.

    Stale but intact receipts remain untouched for explicit manual recovery.
    Malformed evidence raises a controlled error; it is never silently dropped.
    """
    message = "The saved row review is damaged or exceeds its budget. Original report and source evidence remain unchanged."
    if not isinstance(text, str) or len(text) > 4_000_000:
        raise ValueError(message)
    try:
        value = json.loads(text)
        if (not isinstance(value, dict) or type(value.get("schema")) is not int
                or value["schema"] != 1
                or value.get("kind") not in ("workorders", "maintenance")
                or any(not isinstance(value.get(key), str) for key in
                       ("scope", "source_id", "source_fingerprint", "filename", "date_order"))
                or not isinstance(value.get("groups"), list)
                or not isinstance(value.get("published"), list)
                or ("include_trades" in value and type(value["include_trades"]) is not bool)):
            raise ValueError(message)
        for group in value["groups"]:
            if (not isinstance(group, dict) or not isinstance(group.get("label"), str)
                    or any(not isinstance(group.get(key), list)
                           or any(not isinstance(item, str) for item in group[key])
                           for key in ("notes", "unmatched"))
                    or any(type(group.get(key)) is not bool for key in ("omitted", "omit_unmatched"))
                    or "record" not in group
                    or (group["record"] is not None and not isinstance(group["record"], dict))):
                raise ValueError(message)
            if group["record"] is not None:
                restored_group(value, group)  # Existing source-row integrity checks, no current-scope approval.
        for table in value["published"]:
            if (not isinstance(table, dict) or not isinstance(table.get("reference"), str)
                    or not isinstance(table.get("columns"), list)
                    or any(not isinstance(column, str) for column in table["columns"])
                    or not isinstance(table.get("rows"), list)
                    or any(not isinstance(row, list) or len(row) != len(table["columns"])
                           or any(not isinstance(cell, str) for cell in row) for row in table["rows"])):
                raise ValueError(message)
        return value
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError, RecursionError) as exc:
        raise ValueError(message) from exc


def _validate(draft, value):
    decoded(encoded(value))
    if value.get("schema") != 1 or value.get("scope") != scope(draft):
        raise ValueError("This row review belongs to a different site or reporting month. Review the source again.")
    source = next((s for s in draft.sources if s.id == value["source_id"]), None)
    if not source or source.fingerprint != value["source_fingerprint"]:
        raise ValueError("The source changed or was removed. Saved row corrections are retained; review the current file before replacing them.")
    if value.get("kind") not in ("workorders", "maintenance"):
        raise ValueError("Unknown row-review destination.")
    if len(encoded(value)) > 4_000_000:
        raise ValueError("This row review exceeds the saved-review budget. Use a smaller source table.")
    for group in value["groups"]:
        if group.get("record"):
            restored = restored_group(value, group)
            if (restored.source_id != source.id or restored.source_sha256 != source.sha256
                    or restored.source_fingerprint != source.fingerprint
                    or restored.period_key != draft.period.key):
                raise ValueError("A row review lost its source or reporting-period identity.")
    return value


def saved_bundle(draft, source_id, kind):
    source = next((s for s in draft.sources if s.id == source_id), None)
    for text in draft.source_row_reviews:
        value = saved_receipt(text)
        if (source and value.get("source_id") == source_id and value.get("kind") == kind
                and value.get("scope") == scope(draft)
                and value.get("source_fingerprint") == source.fingerprint):
            return _validate(draft, value)
    return None


def store_bundle(draft, value, *, expected_revision=""):
    _validate(draft, value)
    records = list(draft.source_row_reviews)
    match = next((i for i, text in enumerate(records)
        if tuple(saved_receipt(text).get(key) for key in ("source_id", "kind", "scope", "source_fingerprint"))
        == tuple(value[key] for key in ("source_id", "kind", "scope", "source_fingerprint"))), None)
    existing = saved_receipt(records[match]) if match is not None else None
    if (revision(existing) if existing else "") != expected_revision:
        raise ValueError("The saved row review changed. Reopen it before applying this edit.")
    text = encoded(value)
    if match is None:
        records.append(text)
    else:
        records[match] = text
    if len(records) > 100 or sum(map(len, records)) > 16_000_000:
        raise ValueError("The report's row-review budget is full. Existing reviews remain unchanged.")
    return replace(draft, source_row_reviews=tuple(records))


def restored_group(bundle, group):
    return (restore_review(group["record"]) if bundle["kind"] == "workorders"
            else restore_service_call_review(group["record"]))


def _group(label, record=None, *, notes=(), unmatched=()):
    return {"label": label, "record": record, "notes": list(notes),
            "unmatched": list(unmatched), "omit_unmatched": False, "omitted": False}


def prepare_bundle(draft, content, *, kind="workorders", mapping=None, date_order=""):
    """Explicit user action only; reuse the original saved source adapters."""
    source = content.source
    value = {"schema": 1, "scope": scope(draft), "source_id": source.id,
        "source_fingerprint": source.fingerprint, "filename": source.filename,
        "kind": kind, "date_order": date_order, "groups": [], "published": []}
    # A source-detail edit changes its fingerprint, not its original byte
    # identity. Re-review may replace only the last exact published tables;
    # it must not append a second copy or erase intervening manual edits.
    for text in draft.source_row_reviews:
        prior = saved_receipt(text)
        if (prior.get("source_id") == source.id and prior.get("kind") == kind
                and prior.get("scope") == value["scope"] and prior.get("published")):
            value["published"] = prior["published"]
    if kind == "workorders" and source.suffix in (".csv", ".xlsx"):
        for number, table in enumerate(content.tables, 1):
            result = review_spreadsheet(content, draft.profile, draft.period, mapping=mapping,
                                numeric_date_order=date_order, table_number=number)
            value["groups"].append(_group(table.name or source.filename,
                review_record(result.workorders)))
    elif kind == "workorders" and source.suffix == ".pdf":
        from app.monthly_report_work_order_pdf_review import review_pdf_workorders
        result = review_pdf_workorders(draft.profile, content, draft.period)
        for page in result.pages:
            value["groups"].append(_group(f"Page {page.page}",
                review_record(page.review) if page.review else None,
                notes=page.notices if not page.review else (),
                unmatched=[" | ".join(row) for row in page.unmatched_rows]))
    elif kind == "workorders" and source.suffix == ".docx":
        from app.monthly_report_work_order_docx_review import review_docx_workorders
        result = review_docx_workorders(draft.profile, content, draft.period)
        for table in result.tables:
            value["groups"].append(_group(f"Word source item {table.source_item}",
                review_record(table.review) if table.review else None,
                notes=table.notices,
                unmatched=[f"Word row {r.word_row}: {r.reason} — {' | '.join(r.cells)}" for r in table.unmatched]))
    elif kind == "maintenance" and source.suffix in (".csv", ".xlsx"):
        for number, table in enumerate(content.tables, 1):
            result = review_service_calls(content, draft.profile, draft.period,
                                          table_number=number, mapping=mapping)
            value["groups"].append(_group(table.name or source.filename,
                                          service_call_review_record(result)))
    elif kind == "maintenance" and source.suffix == ".docx":
        from app.monthly_report_service_call_word import review_word_maintenance
        result = review_word_maintenance(draft.profile, content, draft.period)
        for table in result.tables:
            value["groups"].append(_group(f"Word source item {table.item_number}",
                service_call_review_record(table.review) if table.review else None,
                notes=table.notices))
    else:
        raise ValueError("Use a CSV, workbook or supported Word maintenance table; work orders also support native-text PDFs. Scans require a readable export.")
    if not value["groups"]:
        raise ValueError("No supported tables were identified. Keep the original source and use a row-based export or the existing manual table editor.")
    return _validate(draft, json.loads(encoded(value)))


def change_row(bundle, group_index, row_key, changes, *, excluded=None):
    value = json.loads(encoded(bundle))
    group = value["groups"][group_index]
    review = restored_group(value, group)
    if value["kind"] == "workorders":
        if changes:
            review = correct_row(review, row_key, changes, expected_revision=review.revision)
        if excluded is not None:
            review = exclude_row(review, row_key, excluded=excluded, expected_revision=review.revision)
        group["record"] = review_record(review)
    else:
        if changes:
            review = correct_service_call(review, row_key, changes, expected_revision=review.revision)
        if excluded is not None:
            review = exclude_service_call(review, row_key, excluded=excluded, expected_revision=review.revision)
        group["record"] = service_call_review_record(review)
    return json.loads(encoded(value))


def remap_group(draft, content, bundle, index, choices, date_order=""):
    if content.source.suffix not in (".csv", ".xlsx"):
        raise ValueError("Native PDF/Word layouts retain their inspected schema. Correct individual rows or use a spreadsheet export.")
    value = json.loads(encoded(bundle))
    original = restored_group(value, value["groups"][index])
    if value["kind"] == "workorders":
        from app.monthly_report_work_order_csv_review import mapped_columns
        mapping = mapped_columns(original.original_columns, choices)
        reviewed = review_spreadsheet(content, draft.profile, draft.period, mapping=mapping,
            numeric_date_order=date_order, table_number=original.table_number).workorders
        record = review_record(reviewed)
    else:
        mapping = suggest_call_mapping(original.original_columns, choices)
        reviewed = review_service_calls(content, draft.profile, draft.period,
            table_number=original.table_number, mapping=mapping)
        record = service_call_review_record(reviewed)
    value["groups"][index]["record"] = record
    value["groups"][index]["date_order"] = date_order
    return json.loads(encoded(value))


def group_decisions(bundle, index, *, omitted, omit_unmatched=False, financial=False, layout=False):
    value = json.loads(encoded(bundle))
    group = value["groups"][index]
    group.update(omitted=bool(omitted), omit_unmatched=bool(omit_unmatched))
    if value["kind"] == "maintenance" and group["record"]:
        review = restored_group(value, group)
        # These native checkboxes are reversible decisions. The outer receipt
        # CAS guards the complete change; unchecked must restore the review
        # requirement rather than silently retain a previous approval.
        review = replace(review,
            unmatched=tuple(replace(item, excluded=bool(omit_unmatched)) for item in review.unmatched),
            financial_exclusion_confirmed=bool(financial), native_layout_confirmed=bool(layout))
        group["record"] = service_call_review_record(review)
    return json.loads(encoded(value))


def reviewed_tables(draft, bundle, *, include_trades=False):
    """No partial insertion: every selected source group must be resolved."""
    _validate(draft, bundle)
    tables, identities = [], set()
    for group in bundle["groups"]:
        if group["omitted"]:
            continue
        if (not group["record"] or group["notes"]
                or group["unmatched"] and not group["omit_unmatched"]):
            raise ValueError("Review or explicitly omit unsupported source groups and unmatched rows first.")
        review = restored_group(bundle, group)
        for row in review.rows:
            if row.excluded:
                continue
            identity = (row.site, (row.work_order if bundle["kind"] == "workorders" else row.wo).casefold())
            if identity in identities:
                raise ValueError("Duplicate work-order identities across source groups need correction or explicit omission.")
            identities.add(identity)
        if bundle["kind"] == "maintenance":
            block = reviewed_service_call_block(review)
            from app.monthly_report_service_call_mapping import OUTPUT_COLUMNS
            tables.append(ReportTable(OUTPUT_COLUMNS, block.rows, review.source_reference))
        else:
            if review.questions or any(row.issues for row in review.rows if not row.excluded):
                raise ValueError("Correct or explicitly omit unresolved work-order rows before inclusion.")
            counts = count_reviewed_work_orders(review, approved_revision=review.revision,
                period=draft.period, selected_sites=tuple(s.key for s in draft.profile.facilities),
                include_trades=include_trades)
            if not counts.overall.total:
                continue
            accepted = [r for r in review.rows if r.key in counts.overall.row_keys]
            tables.append(ReportTable(("Work order", "Site", "Work date", "Completed date", "Recorded status", "PM / Non-PM", "Trade"),
                tuple((r.work_order, r.site, r.work_date, r.completed_date, r.status,
                       r.work_type or "Unclassified", r.trade) for r in accepted), review.source_reference))
            tables.append(counts.summary_table())
            if include_trades:
                tables.append(ReportTable(("Uploaded sample trade", "Total", "Recorded completed", "Recorded open"),
                    tuple((g.label, str(g.total), str(g.completed), str(g.open)) for g in counts.trades), review.source_reference))
    if not identities or not tables:
        raise ValueError("No reviewed rows remain to include.")
    from app.monthly_report_content_policy import table_has_pricing
    if any(table_has_pricing(t.columns, t.rows, work_orders=True) for t in tables):
        raise ValueError("Reviewed rows contain pricing. Correct or omit that content before inclusion.")
    return tuple(tables)


def publish_bundle(draft, bundle, *, expected_revision, expected_block, include_trades=False, include_omitted=False):
    destination = "work_orders" if bundle["kind"] == "workorders" else "service_calls"
    current = next((b for b in draft.blocks if b.key == destination), ResolvedBlock(destination, "This month"))
    if current.fingerprint != expected_block:
        raise ValueError("The report table changed. Your edits are retained; review the current table before adding rows.")
    if current.source == "Omit" and not include_omitted:
        raise ValueError("This report section is deliberately omitted. Include it before adding reviewed rows.")
    tables = reviewed_tables(draft, bundle, include_trades=include_trades)
    previous = tuple(ReportTable(tuple(t["columns"]), tuple(tuple(r) for r in t["rows"]), t["reference"])
                     for t in bundle["published"])
    remaining = list(current.extra_tables)
    for old in previous:
        if old not in remaining:
            raise ValueError("Previously included rows were edited or removed. Keep those edits; remove this review's remaining report tables before including a replacement.")
        remaining.remove(old)
    # Different files/exports can overlap. Refuse known accepted identities
    # from other still-included review receipts rather than double-counting
    # the same source work in a combined report.
    incoming = {(row.site, (row.work_order if bundle["kind"] == "workorders" else row.wo).casefold())
                for group in bundle["groups"] if group["record"] and not group["omitted"]
                for row in restored_group(bundle, group).rows if not row.excluded}
    for text in draft.source_row_reviews:
        other = saved_receipt(text)
        if (other.get("kind") != bundle["kind"] or other.get("source_id") == bundle["source_id"]
                or other.get("scope") != bundle["scope"] or not other.get("published")):
            continue
        still_included = any(ReportTable(tuple(t["columns"]), tuple(tuple(r) for r in t["rows"]), t["reference"])
                             in remaining for t in other["published"])
        if still_included:
            old_ids = {(row.site, (row.work_order if bundle["kind"] == "workorders" else row.wo).casefold())
                for group in other["groups"] if group["record"] and not group["omitted"]
                for row in restored_group(other, group).rows if not row.excluded}
            if incoming & old_ids:
                raise ValueError("Another included source already contains these work-order identities. Compare the sources and remove or omit duplicate rows before adding them.")
    # Existing manual/native rows remain separate and are never retyped.
    updated = replace(current, source="This month", extra_tables=tuple(remaining) + tables,
        references=tuple(dict.fromkeys((*current.references, *(t.reference for t in tables)))),
        reviewed_fingerprint="", client_reviewed_fingerprint="")
    value = json.loads(encoded(bundle))
    value["published"] = [asdict(t) for t in tables]
    value["include_trades"] = bool(include_trades)
    result = store_bundle(draft, value, expected_revision=expected_revision)
    blocks = {b.key: b for b in result.blocks}
    blocks[destination] = updated
    return replace(result, blocks=tuple(blocks.values()))
