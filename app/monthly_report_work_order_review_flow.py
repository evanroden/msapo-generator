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
    FIELDS, ColumnMapping as ColumnMapping, correct_row, exclude_row, restore_review, review_record,
)
from app.monthly_report_cross_source_conflicts import claim as source_claim, compare as compare_claims
from app.monthly_report_work_order_counts import count_reviewed_work_orders
from app.monthly_report_work_order_coverage import CoverageDecision, restore_decision
from app.monthly_report_work_order_csv_review import review_spreadsheet
from app.monthly_report_service_call_mapping import (
    FIELDS as CALL_FIELDS, correct_service_call, exclude_service_call,
    exclude_unmatched_call as exclude_unmatched_call, confirm_financial_exclusion as confirm_financial_exclusion, confirm_word_layout as confirm_word_layout,
    restore_service_call_review, service_call_review_record, review_service_calls,
    reviewed_service_call_block, suggest_call_mapping,
)


CALL_FIELDS = CALL_FIELDS  # Preserve the historical report-review export.


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
        if (not isinstance(value.get("coverage", []), list)
                or len(value.get("coverage", [])) > 50):
            raise ValueError(message)
        for item in value.get("coverage", []):
            restore_decision(item)
        choices = value.get("cross_source_decisions", [])
        if (not isinstance(choices, list) or len(choices) > 200
                or any(not isinstance(item, dict) or set(item) != {"binding", "winner"}
                       or not isinstance(item.get("binding"), str)
                       or len(item["binding"]) != 64
                       or any(char not in "0123456789abcdef" for char in item["binding"])
                       or item.get("winner") not in ("existing", "incoming")
                       for item in choices)):
            raise ValueError(message)
        if "grid_receipt" in value:
            from app.monthly_report_rolling_workflow import validate_receipt
            validate_receipt(value["grid_receipt"])
        if "maintenance_projection" in value:
            from app.monthly_report_maintenance_workflow import validate_state
            validate_state(value["maintenance_projection"])
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
    for item in value.get("coverage", []):
        entry = restore_decision(item)
        if (value["kind"] != "workorders" or entry.contract != draft.profile.contract
                or entry.profile_key != draft.profile.key
                or entry.site not in {site.key for site in draft.profile.facilities}
                or entry.source_sha256 != source.sha256
                or entry.source_fingerprint != source.fingerprint
                or not 1 <= entry.table_number <= len(value["groups"])):
            raise ValueError("Coverage belongs to another contract, site, source or table.")
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


def confirm_coverage(draft, bundle, *, table_number, site, start_month, end_month,
                     evidence, confirmed):
    """Explicit AM act, scoped to one reviewed row table and its original bytes."""
    _validate(draft, bundle)
    source = next(s for s in draft.sources if s.id == bundle["source_id"])
    if (bundle["kind"] != "workorders" or confirmed is not True
            or source.suffix not in (".csv", ".xlsx")
            or type(table_number) is not int
            or not 1 <= table_number <= len(bundle["groups"])):
        raise ValueError("Confirm one source table's coverage before saving it.")
    group = bundle["groups"][table_number - 1]
    if not group["record"] or restore_review(group["record"]).kind != "records":
        raise ValueError("Coverage requires a reviewed row-based source table.")
    value = json.loads(encoded(bundle))
    entry = CoverageDecision(draft.profile.contract, draft.profile.key, site,
        source.sha256, source.fingerprint, table_number, start_month, end_month,
        "am_confirmed", evidence)
    if entry.to_record() not in value.setdefault("coverage", []):
        value["coverage"].append(entry.to_record())
    return _validate(draft, value)


def revoke_coverage(draft, bundle, *, site, table_number):
    """Revoke exactly one site's table coverage without touching row edits."""
    _validate(draft, bundle)
    if type(table_number) is not int:
        raise ValueError("Select a source table before revoking coverage.")
    value = json.loads(encoded(bundle))
    value["coverage"] = [item for item in value.get("coverage", [])
                         if not (restore_decision(item).site == site
                                 and restore_decision(item).table_number == table_number)]
    return _validate(draft, value)


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
        "kind": kind, "date_order": date_order, "groups": [], "published": [],
        "coverage": []}
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
                unmatched=[f"PDF page {page.page}, {origin}: {' | '.join(row)}"
                           for row, origin in zip(page.unmatched_rows,
                                                  page.unmatched_origins)]))
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
    if value["filename"].casefold().endswith(".pdf"):
        # An edited WO may release (or create) a collision on another page.
        # Never promote either page without re-evaluating both source rows.
        from app.monthly_report_work_order_pdf_review import reconcile_pdf_group_duplicates
        reconcile_pdf_group_duplicates(value["groups"])
    return json.loads(encoded(value))


def remap_group(draft, content, bundle, index, choices, date_order=""):
    native_word = (content.source.suffix == ".docx"
                   and bundle["kind"] == "workorders")
    if content.source.suffix not in (".csv", ".xlsx") and not native_word:
        raise ValueError("Native PDF/Word layouts retain their inspected schema. Correct individual rows or use a spreadsheet export.")
    if native_word and date_order:
        raise ValueError("Native Word numeric dates need row correction; do not infer their date order.")
    value = json.loads(encoded(bundle))
    original = restored_group(value, value["groups"][index])
    if value["kind"] == "workorders":
        from app.monthly_report_work_order_csv_review import mapped_columns
        mapping = mapped_columns(original.original_columns, choices)
        if native_word:
            # A deliberate mapping changes only this inspected Word table.
            # It cannot flatten other tables or silently replace saved edits.
            from app.monthly_report_work_order_docx_review import review_docx_workorders
            result = review_docx_workorders(draft.profile, content, draft.period,
                mapping_by_item={original.table_number: mapping})
            selected = next((table for table in result.tables
                if table.source_item == original.table_number), None)
            if selected is None or selected.review is None:
                raise ValueError("The Word source table is no longer reviewable.")
            reviewed = selected.review
            value["groups"][index]["notes"] = list(selected.notices)
            value["groups"][index]["unmatched"] = [
                f"Word row {row.word_row}: {row.reason} — {' | '.join(row.cells)}"
                for row in selected.unmatched]
        else:
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


def _selected_work_order_claims(bundle):
    """Rows under explicit source review; never infer completion from missing cells."""
    for group in bundle["groups"]:
        if group["omitted"] or not group["record"]:
            continue
        review = restored_group(bundle, group)
        for row in review.rows:
            if not row.excluded and not row.issues:
                yield source_claim(review, row)


def cross_source_candidates(draft, bundle, included_tables=None):
    """Compare this report's new claims with other still-published source rows.

    Missing or changed original-source revisions are not authority to discard
    previously printed rows. Refuse a stale comparison rather than accepting
    a potentially false status or bypassing the current report-only review.
    """
    _validate(draft, bundle)
    if bundle["kind"] != "workorders":
        return ()
    current = next((b for b in draft.blocks if b.key == "work_orders"), None)
    included = tuple(current.extra_tables if current else ()) if included_tables is None else tuple(included_tables)
    incoming = tuple(_selected_work_order_claims(bundle))
    if not incoming:
        return ()
    # Index by the explicit work-order identity. A source can have thousands
    # of unrelated rows, so don't compare every old row with every new row.
    by_event = {}
    for candidate in incoming:
        by_event.setdefault(candidate.event, []).append(candidate)
    seen, matches = set(), []
    for text in draft.source_row_reviews:
        other = saved_receipt(text)
        if (other.get("kind") != "workorders" or other.get("scope") != bundle["scope"]
                or other.get("source_id") == bundle["source_id"] or not other.get("published")):
            continue
        published = tuple(ReportTable(tuple(t["columns"]), tuple(tuple(r) for r in t["rows"]), t["reference"])
                          for t in other["published"])
        if not any(t in included for t in published):
            continue
        source = next((s for s in draft.sources if s.id == other["source_id"]), None)
        if source is None or source.fingerprint != other["source_fingerprint"]:
            raise ValueError("An included work-order source was changed or removed. Review its saved original and published rows before resolving a conflicting claim.")
        _validate(draft, other)
        # A source correction may already have superseded one old row while
        # retaining the original in the saved review. Compare only its still
        # published source rows, never obsolete assertions in the audit trail.
        published_rows = {
            tuple(row) for table in published
            if table.columns[:2] == ("Work order", "Site")
            for row in table.rows if len(row) == 7
        }
        for older in _selected_work_order_claims(other):
            printed = (older.work_order, older.site, older.work_date,
                       older.completed_date, older.status,
                       older.work_type or "Unclassified", older.trade)
            if printed not in published_rows:
                continue
            for newer in by_event.get(older.event, ()):
                candidate = compare_claims(older, newer, report_scope=bundle["scope"])
                if candidate and candidate.binding not in seen:
                    seen.add(candidate.binding)
                    matches.append(candidate)
                    if len(matches) > 10000:
                        raise ValueError("Too many conflicting work-order rows to compare in one review. Split the source by site or reporting period without discarding originals.")
    return tuple(sorted(matches, key=lambda c: (c.incoming.source_id, c.incoming.row_number,
                                                 c.existing.source_id, c.existing.row_number)))


def record_cross_source_decision(draft, bundle, binding, winner, *, expected_revision):
    """One report-only correction. Old choices remain readable but go stale on edits."""
    _validate(draft, bundle)
    if revision(bundle) != expected_revision or winner not in ("existing", "incoming"):
        raise ValueError("The reviewed work-order source changed. Check both original claims again.")
    current = saved_bundle(draft, bundle["source_id"], "workorders")
    if current is None or revision(current) != expected_revision:
        raise ValueError("Another row correction was saved. Reopen the current source and compare again.")
    candidate = next((c for c in cross_source_candidates(draft, bundle)
                      if c.binding == binding and c.kind == "conflict"), None)
    if candidate is None:
        raise ValueError("The conflicting source/date/status changed. Compare current originals again.")
    value = json.loads(encoded(bundle))
    choices = value.setdefault("cross_source_decisions", [])
    if not any(item["binding"] == binding and item["winner"] == winner for item in choices):
        choices.append({"binding": binding, "winner": winner})
    if len(choices) > 200:
        raise ValueError("Too many earlier conflict decisions. Save and review a fresh source bundle.")
    return store_bundle(draft, value, expected_revision=expected_revision)


def reviewed_tables(draft, bundle, *, include_trades=False, skip_rows=(), allow_empty=False):
    """No partial insertion: every selected source group must be resolved."""
    _validate(draft, bundle)
    skipped = set(skip_rows)
    tables, identities = [], set()
    for group in bundle["groups"]:
        if group["omitted"]:
            continue
        if (not group["record"] or group["notes"]
                or group["unmatched"] and not group["omit_unmatched"]):
            raise ValueError("Review or explicitly omit unsupported source groups and unmatched rows first.")
        review = restored_group(bundle, group)
        if skipped and bundle["kind"] == "workorders":
            review = replace(review, rows=tuple(
                replace(row, excluded=True) if row.key in skipped else row for row in review.rows))
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
        if allow_empty:
            return ()
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
    # Validate the entire incoming review before considering duplicate suppression.
    reviewed_tables(draft, bundle, include_trades=include_trades)
    previous = tuple(ReportTable(tuple(t["columns"]), tuple(tuple(r) for r in t["rows"]), t["reference"])
                     for t in bundle["published"])
    remaining = list(current.extra_tables)
    for old in previous:
        if old not in remaining:
            raise ValueError("Previously included rows were edited or removed. Keep those edits; remove this review's remaining report tables before including a replacement.")
        remaining.remove(old)
    result = draft
    decisions = {item["binding"]: item["winner"] for item in bundle.get("cross_source_decisions", [])}
    if bundle["kind"] == "workorders":
        candidates = cross_source_candidates(draft, bundle, remaining)
        missing = next((c for c in candidates if c.kind == "conflict" and c.binding not in decisions), None)
        if missing:
            raise ValueError(
                "Two sources disagree on a work-order date/status: "
                f"{missing.existing.locator} records {missing.existing.status or 'unknown'} "
                f"on {missing.existing.work_date or 'unknown date'}; "
                f"{missing.incoming.locator} records {missing.incoming.status or 'unknown'} "
                f"on {missing.incoming.work_date or 'unknown date'}. "
                "Choose which reviewed source to use; neither claim was overwritten.")
        skip_new = {c.incoming.row_key for c in candidates
                    if c.kind == "duplicate" or decisions.get(c.binding) == "existing"}
        remove_old = {}
        for candidate in candidates:
            if candidate.kind == "conflict" and decisions.get(candidate.binding) == "incoming":
                remove_old.setdefault(candidate.existing.source_id, set()).add(candidate.existing.row_key)
        # Rebuild only the exact previously published source table(s), retaining
        # unrelated rows and their count summaries. All operations are on a
        # detached draft; a stale/manual table edit leaves the caller unchanged.
        for source_id, skipped in remove_old.items():
            other = saved_bundle(result, source_id, "workorders")
            if other is None:
                raise ValueError("A previously published source changed. Compare the two originals again.")
            old_tables = tuple(ReportTable(tuple(t["columns"]), tuple(tuple(r) for r in t["rows"]), t["reference"])
                               for t in other["published"])
            if not old_tables or any(table not in remaining for table in old_tables):
                raise ValueError("Earlier included work-order rows were edited or removed. Preserve the human changes and review this conflict again.")
            position = min(remaining.index(table) for table in old_tables)
            for table in old_tables:
                remaining.remove(table)
            revised_tables = reviewed_tables(result, other, include_trades=bool(other.get("include_trades")),
                                             skip_rows=skipped, allow_empty=True)
            remaining[position:position] = revised_tables
            revised_other = json.loads(encoded(other))
            revised_other["published"] = [asdict(table) for table in revised_tables]
            revised_other.setdefault("cross_source_superseded", []).extend(
                {"source": bundle["source_id"], "row": key} for key in sorted(skipped))
            result = store_bundle(result, revised_other, expected_revision=revision(other))
        tables = reviewed_tables(result, bundle, include_trades=include_trades,
                                 skip_rows=skip_new, allow_empty=True)
        receipt = [{"binding": c.binding, "kind": c.kind,
                    "winner": ("existing" if c.kind == "duplicate" else decisions[c.binding])}
                   for c in candidates]
    else:
        tables = reviewed_tables(draft, bundle, include_trades=include_trades)
        receipt = []
        # Maintenance visits are not ENFRA work-order service calls. Retain
        # their independent strict no-overlap gate; never auto-merge actors.
        incoming = {(row.site, row.wo.casefold())
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
                old_ids = {(row.site, row.wo.casefold())
                           for group in other["groups"] if group["record"] and not group["omitted"]
                           for row in restored_group(other, group).rows if not row.excluded}
                if incoming & old_ids:
                    raise ValueError("Another included source already contains these work-order identities. Compare the sources and remove or omit duplicate rows before adding them.")
    all_tables = tuple(remaining) + tuple(tables)
    if current.source != "Omit" and all_tables == current.extra_tables:
        updated = current
    else:
        updated = replace(current, source="This month", extra_tables=all_tables,
            references=tuple(dict.fromkeys((*current.references, *(t.reference for t in tables)))),
            reviewed_fingerprint="", client_reviewed_fingerprint="")
    value = json.loads(encoded(bundle))
    value["published"] = [asdict(t) for t in tables]
    value["include_trades"] = bool(include_trades)
    if receipt:
        value["cross_source_receipts"] = receipt
    result = store_bundle(result, value, expected_revision=expected_revision)
    if updated is current:
        return result
    blocks = {b.key: b for b in result.blocks}
    blocks[destination] = updated
    return replace(result, blocks=tuple(blocks.values()))
