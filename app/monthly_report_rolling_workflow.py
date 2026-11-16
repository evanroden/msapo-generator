"""Apply independently confirmed source coverage to the report's native grids.

One explicit action binds one reviewed export table to the four metric frames.
It preserves other report content, and a receipt lets preflight detect a
changed review, coverage decision, source, or manually edited published grid.
"""
from dataclasses import asdict, replace
from datetime import date
import json

from app import config
from app.monthly_report_model import ReportTable, ResolvedBlock
from app.monthly_report_work_order_coverage import restore_decision
from app.monthly_report_work_order_rolling import (
    METRICS, CoveredMonth, bind_template_grids, rolling_labels, rolling_months,
    tally_reviewed_months,
)


_HEADINGS = {
    "pm received": "pm_received", "pm closed": "pm_closed",
    "non-pm received": "non_pm_received", "non-pm closed": "non_pm_closed",
    "non pm received": "non_pm_received", "non pm closed": "non_pm_closed",
}


def _table(value):
    if (not isinstance(value, dict) or not isinstance(value.get("reference"), str)
            or not isinstance(value.get("columns"), list) or len(value["columns"]) != 13
            or any(not isinstance(cell, str) for cell in value["columns"])
            or not isinstance(value.get("rows"), list) or len(value["rows"]) > 2
            or any(not isinstance(row, list) or len(row) != 13
                   or any(not isinstance(cell, str) for cell in row) for row in value["rows"])):
        raise ValueError("Invalid saved work-order grid receipt.")
    return ReportTable(tuple(value["columns"]), tuple(tuple(row) for row in value["rows"]), value["reference"])


def validate_receipt(receipt):
    if (not isinstance(receipt, dict) or receipt.get("schema") != 1
            or type(receipt.get("group_index")) is not int or receipt["group_index"] < 0
            or not all(isinstance(receipt.get(k), str) and receipt[k] for k in
                       ("review_revision", "coverage_revision"))
            or not isinstance(receipt.get("metrics"), list) or not receipt["metrics"]
            or len(set(receipt["metrics"])) != len(receipt["metrics"])
            or any(item not in METRICS for item in receipt["metrics"])
            or not isinstance(receipt.get("closed_statuses"), list)
            or any(not isinstance(v, str) or not v.strip() for v in receipt["closed_statuses"])
            or any(not isinstance(receipt.get(key), list) or len(receipt[key]) != 4
                   for key in ("base_tables", "published_tables"))):
        raise ValueError("Invalid saved work-order grid receipt.")
    bases = tuple(_table(item) for item in receipt["base_tables"])
    published = tuple(_table(item) for item in receipt["published_tables"])
    if (len({table.reference for table in published}) != 4
            or tuple(t.reference for t in bases) != tuple(t.reference for t in published)):
        raise ValueError("Invalid saved work-order grid receipt.")
    return bases, published


def _frames(draft):
    from app.monthly_report_master_tables import for_profile
    frames, metrics = [], []
    for frame in for_profile(draft.profile):
        if frame.slot != "work_orders" or len(frame.columns) != 13:
            continue
        label = " ".join(frame.columns[0].casefold().split())
        if label in _HEADINGS:
            frames.append(frame)
            metrics.append(_HEADINGS[label])
    if len(frames) != 4 or set(metrics) != set(METRICS):
        raise ValueError("The installed master needs four distinct received/closed PM and non-PM grids. Review its layout before applying source counts.")
    if not 1 <= len(draft.profile.facilities) <= 2:
        raise ValueError("This master needs an approved layout for more than two sites.")
    site_keys = tuple(site.key for site in draft.profile.facilities)
    return tuple(frames), {frame.reference: (site_keys, metric)
                           for frame, metric in zip(frames, metrics)}


def _merge_base(base, proposed, period):
    if base.reference != proposed.reference:
        raise ValueError("The master grid changed; reopen the report before applying counts.")
    if not base.rows:
        return proposed
    if base.columns != (proposed.columns[0], *rolling_labels(period)):
        raise ValueError("Existing grid month labels require review before applying counts.")
    if len(base.rows) != len(proposed.rows):
        raise ValueError("Existing grid site rows require review before applying counts.")
    rows = []
    for old, new in zip(base.rows, proposed.rows):
        if len(old) != 13 or old[0] != new[0]:
            raise ValueError("Existing grid site order requires review before applying counts.")
        row = [old[0]]
        for saved, derived in zip(old[1:], new[1:]):
            if saved and derived and saved != derived:
                raise ValueError("A saved grid value differs from the reviewed source. Keep your edit and review that month before replacing it.")
            row.append(saved or derived)
        rows.append(tuple(row))
    return replace(proposed, rows=tuple(rows))


def publish(draft, bundle, *, expected_revision, expected_block, group_index,
            metrics, closed_statuses=("Closed", "Complete"), confirmed=False, as_of=None):
    from app import monthly_report_work_order_review_flow as flow
    from app.monthly_report_row_review_receipts import decoded

    flow._validate(draft, bundle)
    as_of = config.operator_today() if as_of is None else as_of
    if type(as_of) is not date:
        raise ValueError("Choose a valid review date for source coverage.")
    if (confirmed is not True or bundle["kind"] != "workorders"
            or type(group_index) is not int or not 0 <= group_index < len(bundle["groups"])):
        raise ValueError("Confirm the selected work-order table and grid coverage first.")
    if (not isinstance(metrics, (tuple, list)) or not metrics
            or len(set(metrics)) != len(metrics) or any(v not in METRICS for v in metrics)):
        raise ValueError("Choose the received or closed measures whose source coverage you verified.")
    if (not isinstance(closed_statuses, (tuple, list))
            or any(not isinstance(v, str) or not v.strip() for v in closed_statuses)):
        raise ValueError("Closed statuses must be nonempty names.")
    group = bundle["groups"][group_index]
    if (group["omitted"] or not group["record"] or group["notes"]
            or group["unmatched"] or group["omit_unmatched"]):
        raise ValueError("Resolve the selected source group and all unmatched rows first.")
    review = flow.restored_group(bundle, group)
    if review.questions or any(row.excluded for row in review.rows):
        raise ValueError("Resolve source columns and omitted rows before claiming complete grid coverage.")
    if review.mapping.completed_date is None and any(m.endswith("_closed") for m in metrics) and not closed_statuses:
        raise ValueError("Choose at least one closed status when no completion-date column exists.")
    frame_set, bindings = _frames(draft)
    current = next((b for b in draft.blocks if b.key == "work_orders"), ResolvedBlock("work_orders", "This month"))
    if current.fingerprint != expected_block:
        raise ValueError("The report table changed. Reopen it before applying reviewed counts.")
    if current.source == "Omit":
        raise ValueError("Include the Work Orders section before applying reviewed counts.")
    existing = []
    for frame in frame_set:
        matches = [table for table in current.extra_tables if table.reference == frame.reference]
        if len(matches) != 1:
            raise ValueError("A native grid is missing or duplicated. Review the report's master tables first.")
        existing.append(matches[0])
    for raw in draft.source_row_reviews:
        other = decoded(raw)
        if other.get("kind") != "workorders" or other.get("source_id") == bundle["source_id"]:
            continue
        if other.get("grid_receipt"):
            _, other_tables = validate_receipt(other["grid_receipt"])
            if {t.reference for t in other_tables} & {f.reference for f in frame_set}:
                raise ValueError("Another saved source owns these grids. Review its published values before replacing them.")
    prior = bundle.get("grid_receipt")
    if prior:
        base, last = validate_receipt(prior)
        if tuple(existing) != last:
            raise ValueError("Published grid values changed. Your edits are retained; review the grid before applying new counts.")
    else:
        base = tuple(existing)
    covered = []
    for raw in bundle.get("coverage", ()):
        decision = restore_decision(raw)
        if decision.table_number != review.table_number:
            continue
        for month in rolling_months(draft.period):
            if decision.start_month <= month <= decision.end_month and month <= as_of.strftime('%Y-%m'):
                covered.extend(CoveredMonth(decision.site, metric, month, review.source_reference)
                               for metric in metrics)
    covered = tuple(dict.fromkeys(covered))
    if not covered:
        raise ValueError("Confirm the source's complete, nonfuture month coverage for at least one site first.")
    covered_site_months = {(item.site, item.month) for item in covered}
    for row in review.rows:
        for value in (row.work_date, row.completed_date):
            try:
                when = date.fromisoformat(value) if value else None
            except ValueError:
                continue  # The rolling tally reports malformed dates as unresolved.
            if when and when > as_of and (row.site, value[:7]) in covered_site_months:
                raise ValueError("A source event is later than the review date. Review future-dated rows before applying counts.")
    counts = tally_reviewed_months((review,), draft.period, draft.profile.facilities,
        approved_revisions={review.source_reference: review.revision},
        pm_categories=("PM",) if any(m.startswith("pm_") for m in metrics) else (),
        closed_statuses=closed_statuses, covered_months=covered,
        coverage_approvals={(c.site, c.metric, c.month): c.source_reference for c in covered})
    proposed = bind_template_grids(counts, draft.period, frame_set, bindings, draft.profile.facilities)
    published = tuple(_merge_base(old, new, draft.period) for old, new in zip(base, proposed))
    replacements = {table.reference: table for table in published}
    updated = replace(current, extra_tables=tuple(replacements.get(t.reference, t) for t in current.extra_tables),
                      references=tuple(dict.fromkeys((*current.references, review.source_reference))),
                      reviewed_fingerprint="", client_reviewed_fingerprint="")
    value = flow.decoded(flow.encoded(bundle))
    value["grid_receipt"] = {"schema": 1, "group_index": group_index,
        "review_revision": review.revision, "coverage_revision": flow.revision(bundle.get("coverage", [])),
        "metrics": list(metrics), "closed_statuses": list(closed_statuses),
        "base_tables": [asdict(t) for t in base], "published_tables": [asdict(t) for t in published]}
    result = flow.store_bundle(draft, value, expected_revision=expected_revision)
    return replace(result, blocks=tuple(updated if b.key == current.key else b for b in result.blocks))


def remove(draft, bundle, *, expected_revision, expected_block, confirmed, keep_manual=False):
    """Undo exact imported values or explicitly keep the current grid as manual."""
    from app import monthly_report_work_order_review_flow as flow

    flow._validate(draft, bundle)
    if confirmed is not True or type(keep_manual) is not bool or not bundle.get("grid_receipt"):
        raise ValueError("Confirm how to handle the source-linked grid values first.")
    base, previous = validate_receipt(bundle["grid_receipt"])
    current = next((b for b in draft.blocks if b.key == "work_orders"), None)
    if not current or current.fingerprint != expected_block:
        raise ValueError("The report table changed. Reopen it before changing the grid link.")
    if not keep_manual:
        for table in previous:
            if (sum(t.reference == table.reference for t in current.extra_tables) != 1
                    or table not in current.extra_tables):
                raise ValueError("The grids were edited. Keep your edits as manual values or restore the published values before removing source counts.")
        replacements = {table.reference: table for table in base}
        current = replace(current, extra_tables=tuple(replacements.get(t.reference, t) for t in current.extra_tables),
                          reviewed_fingerprint="", client_reviewed_fingerprint="")
    else:
        current = replace(current, reviewed_fingerprint="", client_reviewed_fingerprint="")
    value = flow.decoded(flow.encoded(bundle))
    del value["grid_receipt"]
    result = flow.store_bundle(draft, value, expected_revision=expected_revision)
    return replace(result, blocks=tuple(current if b.key == current.key else b for b in result.blocks))


def check_binding(draft):
    """Return one blocking reason when an applied grid's evidence is stale."""
    from app import monthly_report_work_order_review_flow as flow
    from app.monthly_report_row_review_receipts import decoded
    from app.monthly_report_model import used_block_keys
    block = next((b for b in draft.blocks if b.key == "work_orders"), None)
    if not block or block.source == "Omit" or "work_orders" not in used_block_keys(draft):
        return None
    for raw in draft.source_row_reviews:
        try:
            candidate = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            continue  # An unrelated damaged receipt is handled by its own review path.
        if (not isinstance(candidate, dict) or candidate.get("kind") != "workorders"
                or "grid_receipt" not in candidate):
            continue
        try:
            value = decoded(raw)
            receipt = value["grid_receipt"]
            _, tables = validate_receipt(receipt)
            flow._validate(draft, value)
            group = value["groups"][receipt["group_index"]]
            review = flow.restored_group(value, group)
            if (group["omitted"] or review.revision != receipt["review_revision"]
                    or flow.revision(value.get("coverage", [])) != receipt["coverage_revision"]
                    or any(sum(item.reference == table.reference for item in block.extra_tables) != 1
                           or table not in block.extra_tables for table in tables)):
                raise ValueError("Grid evidence changed")
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            return "The work-order grid, source or coverage review changed. Reopen the saved source and review its counts before generating."
    return None
