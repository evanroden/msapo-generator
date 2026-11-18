"""Apply independently confirmed source coverage to the report's native grids.

One explicit action binds one reviewed export table to the four metric frames.
It preserves other report content, and a receipt lets preflight detect a
changed review, coverage decision, source, or manually edited published grid.
"""
from dataclasses import asdict, replace
from datetime import date
import json

from app import config
from app.monthly_report_model import BandedWorkOrderTable, ReportTable, ResolvedBlock
from app.monthly_report_work_order_coverage import restore_decision
from app.monthly_report_work_order_rolling import (
    METRICS, CoveredMonth, bind_six_month_bands, bind_template_grids, rolling_labels, rolling_months,
    tally_reviewed_months,
)


_HEADINGS = {
    "pm received": "pm_received", "pm closed": "pm_closed",
    "non-pm received": "non_pm_received", "non-pm closed": "non_pm_closed",
    "non pm received": "non_pm_received", "non pm closed": "non_pm_closed",
}


def _table(value):
    if (not isinstance(value, dict) or not isinstance(value.get("reference"), str)
            or not isinstance(value.get("columns"), list) or len(value["columns"]) not in (7, 13)
            or any(not isinstance(cell, str) for cell in value["columns"])
            or not isinstance(value.get("rows"), list)
            or len(value["rows"]) > (7 if len(value["columns"]) == 7 else 2)
            or any(not isinstance(row, list) or len(row) != len(value["columns"])
                   or any(not isinstance(cell, str) for cell in row) for row in value["rows"])):
        raise ValueError("Invalid saved work-order grid receipt.")
    columns, rows, reference = tuple(value["columns"]), tuple(tuple(row) for row in value["rows"]), value["reference"]
    if "band_site_key" in value or "band_category" in value:
        site, category = value.get("band_site_key"), value.get("band_category")
        if (len(columns) != 7 or not reference.startswith("master-table:")
                or not isinstance(site, str) or not site.strip() or category not in ("pm", "non_pm")):
            raise ValueError("Invalid saved work-order grid receipt.")
        return BandedWorkOrderTable(columns, rows, reference, site, category)
    return ReportTable(columns, rows, reference)


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
            or tuple(t.reference for t in bases) != tuple(t.reference for t in published)
            or any(len(table.columns) == 7 and table.rows and not isinstance(table, BandedWorkOrderTable)
                   for table in published)):
        raise ValueError("Invalid saved work-order grid receipt.")
    return bases, published


def _frames(draft):
    from app.monthly_report_master_tables import for_profile
    frames, metrics = [], []
    available = for_profile(draft.profile)
    if not 1 <= len(draft.profile.facilities) <= 2:
        raise ValueError("This master needs an approved layout for more than two sites.")
    for frame in available:
        if frame.slot != "work_orders" or len(frame.columns) != 13:
            continue
        label = " ".join(frame.columns[0].casefold().split())
        if label in _HEADINGS:
            frames.append(frame)
            metrics.append(_HEADINGS[label])
    seven_column = [frame for frame in available
                    if frame.slot == "work_orders" and len(frame.columns) == 7]
    recognized_bands = [frame for frame in seven_column
                        if frame.band_site_index is not None or frame.band_category]
    if len(frames) == 4 and set(metrics) == set(METRICS):
        if recognized_bands:
            raise ValueError("The master contains competing work-order grid layouts; review its mapping.")
        site_keys = tuple(site.key for site in draft.profile.facilities)
        return tuple(frames), {frame.reference: (site_keys, metric)
                               for frame, metric in zip(frames, metrics)}
    if seven_column:
        identities = [(frame.band_site_index, frame.band_category) for frame in seven_column]
        required = {(site, category) for site in (0, 1) for category in ("pm", "non_pm")}
        if (frames or len(seven_column) != 4 or len(set(identities)) != 4
                or set(identities) != required):
            raise ValueError("The master grid location and PM category mapping is missing or ambiguous.")
        return tuple(seven_column), {}
    if len(frames) != 4 or set(metrics) != set(METRICS):
        raise ValueError("The installed master needs four distinct received/closed PM and non-PM grids. Review its layout before applying source counts.")


def _merge_base(base, proposed, period):
    if base.reference != proposed.reference:
        raise ValueError("The master grid changed; reopen the report before applying counts.")
    if not base.rows:
        return proposed
    if len(base.columns) == 7:
        if not proposed.rows or len(base.rows) != 7 or len(proposed.rows) != 7:
            raise ValueError("Existing location grid values need review before applying counts.")
        if (not isinstance(base, BandedWorkOrderTable) or not isinstance(proposed, BandedWorkOrderTable)
                or (base.band_site_key, base.band_category) != (proposed.band_site_key, proposed.band_category)):
            raise ValueError("Existing location grid identity needs review before applying counts.")
        if base.columns != proposed.columns or any(
                base.rows[index] != proposed.rows[index] for index in (1, 3, 5)):
            raise ValueError("Existing grid month labels require review before applying counts.")
        merged = []
        for index, (old, new) in enumerate(zip(base.rows, proposed.rows)):
            if len(old) != 7 or len(new) != 7:
                raise ValueError("Existing grid rows require review before applying counts.")
            if index in (1, 3, 5):
                merged.append(new)
                continue
            if old[0] != new[0] or any(before and after and before != after
                                       for before, after in zip(old[1:], new[1:])):
                raise ValueError("A saved grid value differs from the reviewed source. Keep your edit and review that month before replacing it.")
            merged.append((new[0], *(before or after for before, after in zip(old[1:], new[1:]))))
        return replace(proposed, rows=tuple(merged))
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
    if bundle.get("published"):
        raise ValueError("This source already supplies a published work-order list and totals. Remove those source-linked tables before publishing its annual grid.")
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
        if (other.get("scope") == bundle["scope"] and other.get("published")
                and {t["reference"] for t in other["published"]}
                    & {t.reference for t in current.extra_tables}):
            incoming = {(row.site, row.work_date, row.work_order.casefold())
                        for row in review.rows if not row.excluded and not row.issues}
            prior = {(row.site, row.work_date, row.work_order.casefold())
                for item in other["groups"] if item["record"] and not item["omitted"]
                for row in flow.restored_group(other, item).rows if not row.excluded and not row.issues}
            if incoming & prior:
                raise ValueError("Another source already publishes these work orders in its detailed list. Compare or omit overlapping source rows before applying the annual grid.")
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
    proposed = (bind_six_month_bands(counts, draft.period, frame_set, draft.profile.facilities)
                if len(frame_set[0].columns) == 7 else
                bind_template_grids(counts, draft.period, frame_set, bindings, draft.profile.facilities))
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
