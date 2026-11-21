"""Visible source-row mapping, corrections, omissions and explicit report inclusion."""
from dataclasses import replace
import streamlit as st

from app.config import operator_today
from app.monthly_report_model import ResolvedBlock
from app import monthly_report_work_order_review_flow as flow
from app.monthly_report_work_order_coverage import (
    month_window, restore_decision, summarize_coverage,
)
from app.monthly_report_work_order_counts import count_reviewed_work_orders

LABELS = {"work_order": "Work-order ID", "work_date": "Work date", "completed_date": "Completion date",
          "status": "Recorded status", "site": "Site", "work_type": "PM / Non-PM", "trade": "Trade",
          "wo": "Work-order ID", "finished": "Finish date", "area": "Area", "task": "Work performed", "tag": "Equipment tag"}


def _coverage_as_of():
    """Use the operator's calendar day when identifying future source rows."""
    return operator_today(getattr(getattr(st, "context", None), "timezone", None))


def _queue(key, request, fields=()):
    st.session_state[key] = {**request, "values": {name: st.session_state.get(widget)
                                                  for name, widget in fields}}


def apply_request(draft, content, request):
    if request["scope"] != flow.scope(draft) or request["source"] != content.source.fingerprint:
        raise ValueError("The report or source changed. Your saved work is unchanged; review the current file.")
    kind = request["kind"]
    old = flow.saved_bundle(draft, content.source.id, kind)
    if (flow.revision(old) if old else "") != request["expected"]:
        raise ValueError("The row review changed. Reopen the current rows before editing.")
    action, values = request["action"], request.get("values", {})
    if action == "start":
        if old:
            return draft
        value = flow.prepare_bundle(draft, content, kind=kind)
    elif action == "row":
        fields = flow.FIELDS if kind == "workorders" else flow.CALL_FIELDS
        value = flow.change_row(old, request["group"], request["row"],
            {name: values[name] for name in fields}, excluded=bool(values["excluded"]))
    elif action == "decisions":
        value = flow.group_decisions(old, request["group"], **values)
    elif action == "coverage":
        value = flow.confirm_coverage(draft, old, table_number=request["table_number"], site=values["site"],
            start_month=values["start_month"], end_month=values["end_month"],
            evidence=values["evidence"], confirmed=values["confirmed"])
    elif action == "coverage_revoke":
        value = flow.revoke_coverage(draft, old, site=values["site"], table_number=request["table_number"])
    elif action == "mapping":
        if not values.pop("confirmed", False):
            raise ValueError("Confirm rebuilding this table's mapping before replacing row corrections.")
        date_order = values.pop("date_order", "")
        value = flow.remap_group(draft, content, old, request["group"], values, date_order)
    elif action == "reconcile":
        winner = {"Keep existing source": "existing", "Use incoming source": "incoming"}.get(
            values.get("winner"))
        return flow.record_cross_source_decision(draft, old, request["binding"], winner,
            expected_revision=request["expected"])
    elif action == "publish":
        return flow.publish_bundle(draft, old, expected_revision=request["expected"],
            expected_block=request["block"], include_trades=bool(values.get("include_trades")),
            include_omitted=bool(values.get("include_omitted")))
    elif action == "publish_grid":
        from app.monthly_report_rolling_workflow import publish
        from app.monthly_report_work_order_rolling import METRICS
        metrics = tuple(name for name in METRICS if values.get(name) is True)
        statuses = tuple(value.strip() for value in str(values.get("closed_statuses", "")).split(",") if value.strip())
        return publish(draft, old, expected_revision=request["expected"],
            expected_block=request["block"], group_index=request["group"], metrics=metrics,
            closed_statuses=statuses, confirmed=values.get("confirmed") is True,
            as_of=_coverage_as_of())
    elif action == "remove_grid":
        from app.monthly_report_rolling_workflow import remove
        return remove(draft, old, expected_revision=request["expected"],
            expected_block=request["block"], confirmed=values.get("confirmed") is True,
            keep_manual=values.get("keep_manual") is True)
    elif action == "maintenance_correct":
        from app.monthly_report_maintenance_workflow import correct
        value = correct(draft, old, index=request["group"], row_key=request["row"], changes=values)
    elif action == "maintenance_classify":
        from app.monthly_report_maintenance_workflow import classify_unknown
        value = classify_unknown(draft, old, index=request["group"], site=values["site"],
            performer=values["performer"], confirmed=values.get("confirmed") is True)
    elif action == "maintenance_publish":
        from app.monthly_report_maintenance_workflow import publish
        return publish(draft, old, expected_revision=request["expected"],
            expected_blocks=request["blocks"], index=request["group"],
            confirmed=values.get("confirmed") is True)
    elif action == "maintenance_remove":
        from app.monthly_report_maintenance_workflow import remove
        return remove(draft, old, expected_revision=request["expected"],
            expected_blocks=request["blocks"], index=request["group"],
            confirmed=values.get("confirmed") is True, keep_manual=values.get("keep_manual") is True)
    else:
        raise ValueError("Unknown row-review action.")
    return flow.store_bundle(draft, value, expected_revision=request["expected"])


def render_reviewed_rows(draft, blocks, prefix, content):
    if content.source.suffix not in (".csv", ".xlsx", ".pdf", ".docx"):
        return draft, blocks
    draft = replace(draft, blocks=tuple(blocks.values()))
    key = prefix + "_normalized_rows_" + content.source.id[:16]
    request_key = prefix + "_normalized_row_action"
    pending = st.session_state.pop(request_key, None)
    if pending:
        try:
            draft = apply_request(draft, content, pending)
            blocks = {b.key: b for b in draft.blocks}
            if pending.get("action") in ("publish", "publish_grid", "remove_grid", "maintenance_publish", "maintenance_remove"):
                from app.monthly_report_guided import _forget_block_widgets
                keys = ({"work_orders", "service_calls"} if pending["action"] in ("maintenance_publish", "maintenance_remove")
                        else {"work_orders" if pending["kind"] == "workorders" else "service_calls"})
                _forget_block_widgets(prefix, keys)
            st.session_state[prefix + "_period_editor_refresh"] = True
        except (ValueError, OSError, KeyError) as exc:
            st.warning(str(exc))
    st.markdown("**Review imported work-order rows**")
    choices = ["Activity work orders"]
    if content.source.suffix != ".pdf" and any(s.key == "maintenance" and s.included for s in draft.sections):
        choices.append("Completed in-house maintenance calls")
    selected_kind = st.selectbox("Use these records for", choices, key=key + "_kind") if len(choices) > 1 else choices[0]
    kind = "workorders" if selected_kind == choices[0] else "maintenance"
    key += "_" + kind
    try:
        bundle = flow.saved_bundle(draft, content.source.id, kind)
    except (ValueError, KeyError) as exc:
        st.warning(str(exc))
        return draft, blocks
    base = {"scope": flow.scope(draft), "source": content.source.fingerprint,
            "kind": kind, "expected": flow.revision(bundle) if bundle else ""}
    if not bundle:
        st.caption("Review original values, choose uncertain columns and correct rows before adding them to this report.")
        st.button("Review and correct imported rows", key=key + "_start",
                  on_click=_queue, args=(request_key, {**base, "action": "start"}))
        return draft, blocks
    labels = [f"{group['label']} · {len(flow.restored_group(bundle, group).rows) if group['record'] else 0} candidate rows"
              for group in bundle["groups"]]
    index = st.selectbox("Source rows to review", range(len(labels)), format_func=lambda n: labels[n],
                         key=key + "_group") if len(labels) > 1 else 0
    group = bundle["groups"][index]
    local = key + "_" + str(index) + "_" + base["expected"][:12]
    st.caption(content.source.filename + " · " + labels[index])
    for note in group["notes"]:
        st.warning(note)
    for note in group["unmatched"]:
        st.caption("Unmatched source row: " + note)
    record = flow.restored_group(bundle, group) if group["record"] else None
    fields = flow.FIELDS if kind == "workorders" else flow.CALL_FIELDS
    if record:
        for note in (record.questions if kind == "workorders" else record.notes):
            st.warning(note)
        if (content.source.suffix in (".csv", ".xlsx")
                or (kind == "workorders" and content.source.suffix == ".docx")):
            unresolved = tuple(LABELS[name] for name in fields
                if name in record.mapping.ambiguous
                or (name in ("work_order", "site", "work_date", "status")
                    and getattr(record.mapping, name) is None)) if kind == "workorders" else ()
            with st.expander(
                "Resolve CSV source columns: " + ", ".join(unresolved)
                if content.source.suffix == ".csv" and unresolved
                else "Change source columns or date interpretation",
                expanded=content.source.suffix == ".csv" and bool(unresolved),
            ):
                if content.source.suffix == ".csv":
                    st.caption("Detected column positions are preselected. Change only "
                               "unresolved or incorrect positions; no original source cell is discarded.")
                with st.form(local + "_mapping"):
                    pairs = []
                    for name in fields:
                        widget = local + "_map_" + name
                        options = (None, *range(len(record.original_columns)))
                        current = getattr(record.mapping, name)
                        st.selectbox(LABELS[name] + " column", options, index=options.index(current),
                            format_func=lambda n: "Not mapped" if n is None else f"{n + 1}: {record.original_columns[n]}", key=widget)
                        pairs.append((name, widget))
                    if kind == "workorders" and content.source.suffix in (".csv", ".xlsx"):
                        widget = local + "_date_order"
                        orders = ("", "MDY", "DMY")
                        st.selectbox("Numeric date order", orders, index=orders.index(group.get("date_order", "")),
                            format_func=lambda x: {"": "Leave ambiguous dates for review", "MDY": "Month / day / year", "DMY": "Day / month / year"}[x], key=widget)
                        pairs.append(("date_order", widget))
                    widget = local + "_confirm_mapping"
                    st.checkbox("Rebuild this table's mapping and replace its row corrections", key=widget)
                    pairs.append(("confirmed", widget))
                    st.form_submit_button("Apply source mapping", on_click=_queue,
                        args=(request_key, {**base, "action": "mapping", "group": index}, pairs))
        if record.rows:
            st.dataframe([{"Source row": row.origin.native_row_number or row.origin.row_number,
                **{LABELS[n]: getattr(row, n) for n in fields},
                "Review needed": "; ".join(row.issues), "Omitted": row.excluded} for row in record.rows], hide_index=True)
            if kind == "workorders":
                evidence = count_reviewed_work_orders(record, approved_revision=record.revision,
                    period=draft.period, selected_sites=tuple(s.key for s in draft.profile.facilities))
                withheld = [item for item in evidence.dispositions
                            if item.disposition in ("needs_review", "excluded")]
                st.caption(f"Row-derived candidate total: {evidence.overall.total}. "
                           f"{len(withheld)} rows withheld pending review or deliberate exclusion. "
                           "These are not published counts or proof of complete CMMS coverage.")
                if withheld:
                    by_key = {row.key: row for row in record.rows}
                    st.dataframe([{"Source row": by_key[item.row_key].origin.row_number,
                        "Work order": by_key[item.row_key].work_order,
                        "Site": by_key[item.row_key].site,
                        "Work date": by_key[item.row_key].work_date,
                        "Count effect": "Withheld (not in totals)",
                        "Action": "Confirm exclusion or correct row" if item.disposition == "excluded"
                                  else "; ".join(item.reasons)}
                        for item in withheld], hide_index=True)
            selected = st.selectbox("Row to correct", range(len(record.rows)),
                format_func=lambda n: f"Source row {record.rows[n].origin.native_row_number or record.rows[n].origin.row_number} · {getattr(record.rows[n], fields[0]) or 'Missing ID'}",
                key=local + "_row")
            row = record.rows[selected]
            st.caption("Original cells: " + " | ".join(row.origin.cells))
            with st.form(local + "_row_" + row.key):
                pairs = []
                for name in fields:
                    widget = local + "_" + row.key + "_" + name
                    value = getattr(row, name)
                    if kind == "workorders" and name == "status" and record.mapping.status is not None:
                        # Preserve the original status spelling when an unrelated field is edited.
                        value = dict(row.corrections).get(name, row.origin.cells[record.mapping.status])
                    if not value:
                        position = getattr(record.mapping, name)
                        value = dict(row.corrections).get(name,
                            row.origin.cells[position] if position is not None else "")
                    if kind == "maintenance" and name in ("task", "area", "tag"):
                        st.text_area(LABELS[name], value=value, key=widget)
                    else:
                        st.text_input(LABELS[name], value=value, key=widget)
                    pairs.append((name, widget))
                widget = local + "_omit_" + row.key
                st.checkbox("Omit this source row", value=row.excluded, key=widget)
                pairs.append(("excluded", widget))
                st.form_submit_button("Save row correction", on_click=_queue,
                    args=(request_key, {**base, "action": "row", "group": index, "row": row.key}, pairs))
        if kind == "workorders" and content.source.suffix in (".csv", ".xlsx"):
            with st.expander("Verify export month coverage (unknown is not zero)"):
                site_options = tuple(site.key for site in draft.profile.facilities)
                selected_key = local + "_coverage_site"
                chosen = st.selectbox("Site covered by this export", site_options, key=selected_key,
                    format_func=lambda key: next((site.title for site in draft.profile.facilities
                                                  if site.key == key), key))
                confirmations = tuple(restore_decision(item) for item in bundle.get("coverage", ())
                    if item.get("site") == chosen and item.get("table_number") == record.table_number)
                months = summarize_coverage(record, confirmations,
                    contract=draft.profile.contract, profile_key=draft.profile.key,
                    site=chosen, months=month_window(draft.period.key), as_of=_coverage_as_of())
                st.caption("A row's earliest/latest date does not prove complete export coverage. "
                           "Blank means missing or unresolved coverage; zero requires a confirmed covered month.")
                st.dataframe([{"Month": item.month,
                    "Coverage": "Confirmed" if item.covered else "Unknown",
                    "Reviewed source rows": item.total,
                    "PM": item.pm, "Non-PM": item.non_pm,
                    "Review needed": "; ".join(item.issues)}
                    for item in months], hide_index=True)
                for evidence in confirmations:
                    st.caption(f"Confirmed {evidence.start_month}–{evidence.end_month}: {evidence.evidence}")
                with st.form(local + "_coverage_form"):
                    form_fields = [("site", selected_key)]
                    for name, label in (("start_month", "Export covers months from (YYYY-MM)"),
                                        ("end_month", "Export covers months through (YYYY-MM)"),
                                        ("evidence", "How was full export coverage verified?")):
                        widget = local + "_coverage_" + name
                        st.text_input(label, value=draft.period.key if name != "evidence" else "",
                                      key=widget)
                        form_fields.append((name, widget))
                    widget = local + "_coverage_confirmed"
                    st.checkbox("I confirmed this export covers the entire range for the selected site",
                                key=widget)
                    form_fields.append(("confirmed", widget))
                    st.form_submit_button("Save confirmed coverage", on_click=_queue,
                        args=(request_key, {**base, "action": "coverage", "table_number": record.table_number}, form_fields))
                st.button("Revoke this site's coverage confirmations", key=local + "_coverage_revoke",
                    on_click=_queue, args=(request_key,
                        {**base, "action": "coverage_revoke", "table_number": record.table_number}, (("site", selected_key),)))
                st.caption("Apply the same reviewed export to the installed master's monthly grids. "
                           "Only confirmed site/month ranges and selected measures receive values; future and other unconfirmed months remain blank. "
                           "For closed counts, confirm the export includes work closed in the range even if received earlier.")
                if draft.profile.facilities:
                    locations = "; ".join(f"Location {index}: {site.title}"
                                          for index, site in enumerate(draft.profile.facilities, 1))
                    st.caption(f"Grid locations follow the selected site order: {locations}.")
                with st.form(local + "_grid_form"):
                    grid_fields = []
                    for name, label, default in (
                        ("non_pm_received", "Non-PM received", True),
                        ("non_pm_closed", "Non-PM closed", True),
                        ("pm_received", "PM received", False),
                        ("pm_closed", "PM closed", False),
                    ):
                        widget = local + "_grid_" + name
                        st.checkbox(label, value=default, key=widget)
                        grid_fields.append((name, widget))
                    widget = local + "_grid_closed_statuses"
                    st.text_input("Closed statuses when no completion-date column exists", value="Closed, Complete", key=widget)
                    grid_fields.append(("closed_statuses", widget))
                    widget = local + "_grid_confirmed"
                    st.checkbox("I reviewed the rows and confirmed coverage for the selected measures", key=widget)
                    grid_fields.append(("confirmed", widget))
                    grid_block = blocks.get("work_orders", ResolvedBlock("work_orders", "This month"))
                    st.form_submit_button("Apply verified monthly grid counts", on_click=_queue,
                        args=(request_key, {**base, "action": "publish_grid", "group": index,
                                            "block": grid_block.fingerprint}, grid_fields))
                if bundle.get("grid_receipt"):
                    with st.form(local + "_remove_grid_form"):
                        manual_key = local + "_grid_keep_manual"
                        confirm_key = local + "_grid_remove_confirm"
                        st.checkbox("Keep the current grid values as manual entries", key=manual_key,
                            help="Leave this unchecked to restore the values from before this source was applied. Edited values are never overwritten.")
                        st.checkbox("I confirm how to handle these grid values", key=confirm_key)
                        grid_block = blocks.get("work_orders", ResolvedBlock("work_orders", "This month"))
                        st.form_submit_button("Remove the source link", on_click=_queue,
                            args=(request_key, {**base, "action": "remove_grid", "block": grid_block.fingerprint},
                                  (("keep_manual", manual_key), ("confirmed", confirm_key))))
        if kind == "workorders" and any(s.key == "maintenance" and s.included for s in draft.sections):
            from app.monthly_report_maintenance_workflow_ui import render as render_maintenance
            render_maintenance(draft, blocks, bundle, index, local, base, request_key, _queue)
        if kind == "maintenance":
            for unmatched in record.unmatched:
                st.caption(f"Unmatched source row {unmatched.number}: {unmatched.reason} — " + " | ".join(unmatched.cells))
    with st.form(local + "_decisions"):
        pairs = []
        for name, label, checked in (("omitted", "Omit this entire source group", group["omitted"]),
                                    ("omit_unmatched", "Omit the unmatched rows shown above", group["omit_unmatched"])):
            widget = local + "_decision_" + name
            st.checkbox(label, value=checked, key=widget)
            pairs.append((name, widget))
        if kind == "maintenance" and record:
            for name, label, checked in (("financial", "Exclude source financial columns from this client report", record.financial_exclusion_confirmed),
                                        ("layout", "I reviewed this source's native row layout", record.native_layout_confirmed)):
                widget = local + "_decision_" + name
                st.checkbox(label, value=checked, key=widget)
                pairs.append((name, widget))
        st.form_submit_button("Save source-group decisions", on_click=_queue,
            args=(request_key, {**base, "action": "decisions", "group": index}, pairs))
    trades = st.checkbox("Include optional trade subtotals", value=bundle.get("include_trades", False), key=key + "_trades") if kind == "workorders" else False
    ready = True
    try:
        tables = flow.reviewed_tables(draft, bundle, include_trades=trades)
        st.caption("Reviewed uploaded rows only; this does not establish complete CMMS coverage.")
        with st.expander("Preview reviewed report tables"):
            for table in tables:
                st.dataframe([dict(zip(table.columns, row)) for row in table.rows], hide_index=True)
    except ValueError as exc:
        ready = False
        st.info(str(exc))
    if kind == "workorders" and ready:
        try:
            candidates = flow.cross_source_candidates(draft, bundle)
            decisions = {item["binding"]: item["winner"] for item in bundle.get("cross_source_decisions", ())}
            for collision in candidates:
                older, newer = collision.existing, collision.incoming
                if collision.kind == "duplicate":
                    st.caption(
                        f"Matching source rows: {older.locator} and {newer.locator}. "
                        "Counted once; both originals remain available for review.")
                    continue
                st.warning(
                    f"Conflicting source claims for {newer.site} work order {newer.work_order}: "
                    f"{older.locator} records {older.status or 'unknown'} "
                    f"({older.work_date or 'unknown date'}); "
                    f"{newer.locator} records {newer.status or 'unknown'} "
                    f"({newer.work_date or 'unknown date'}). Neither was silently preferred.")
                selected = {"existing": "Keep existing source",
                            "incoming": "Use incoming source"}.get(decisions.get(collision.binding), "Review needed")
                widget = local + "_collision_" + collision.binding
                options = ("Review needed", "Keep existing source", "Use incoming source")
                st.radio("Correct which source to use for this report", options,
                         index=options.index(selected), key=widget)
                st.button("Save this conflict choice", key=widget + "_save",
                          disabled=st.session_state.get(widget) == "Review needed",
                          on_click=_queue, args=(request_key,
                              {**base, "action": "reconcile", "binding": collision.binding},
                              (("winner", widget),)))
                # An unsaved change in the native radio is never misrepresented
                # as the prior saved choice. Switching winners remains possible.
                if selected == "Review needed" or st.session_state.get(widget) != selected:
                    ready = False
                else:
                    st.caption(f"Saved report-only choice: {selected.lower()}. "
                               "Both original claims and previous choices remain in report history.")
        except ValueError as exc:
            st.warning(str(exc))
            ready = False
    destination = "work_orders" if kind == "workorders" else "service_calls"
    block = blocks.get(destination, ResolvedBlock(destination, "This month"))
    publish_fields = [("include_trades", key + "_trades")] if kind == "workorders" else []
    if block.source == "Omit":
        include_key = local + "_include_omitted"
        include = st.checkbox("Include " + ("Work Orders" if kind == "workorders" else "Maintenance calls") + " in this report", key=include_key)
        ready = ready and include
        publish_fields.append(("include_omitted", include_key))
    st.button("Include reviewed rows in " + ("Activity" if kind == "workorders" else "Maintenance"),
        disabled=not ready, key=local + "_publish", on_click=_queue,
        args=(request_key, {**base, "action": "publish", "block": block.fingerprint},
              publish_fields))
    return draft, blocks
