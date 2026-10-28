"""Visible source-row mapping, corrections, omissions and explicit report inclusion."""
from dataclasses import replace

import streamlit as st

from app.monthly_report_model import ResolvedBlock
from app import monthly_report_work_order_review_flow as flow

LABELS = {"work_order": "Work-order ID", "work_date": "Work date", "completed_date": "Completion date",
          "status": "Recorded status", "site": "Site", "work_type": "PM / Non-PM", "trade": "Trade",
          "wo": "Work-order ID", "finished": "Finish date", "area": "Area", "task": "Work performed", "tag": "Equipment tag"}


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
    elif action == "mapping":
        if not values.pop("confirmed", False):
            raise ValueError("Confirm rebuilding this table's mapping before replacing row corrections.")
        date_order = values.pop("date_order", "")
        value = flow.remap_group(draft, content, old, request["group"], values, date_order)
    elif action == "publish":
        return flow.publish_bundle(draft, old, expected_revision=request["expected"],
            expected_block=request["block"], include_trades=bool(values.get("include_trades")),
            include_omitted=bool(values.get("include_omitted")))
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
            if pending.get("action") == "publish":
                from app.monthly_report_guided import _forget_block_widgets
                _forget_block_widgets(prefix, {"work_orders" if pending["kind"] == "workorders" else "service_calls"})
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
        if content.source.suffix in (".csv", ".xlsx"):
            with st.expander("Change source columns or date interpretation"):
                with st.form(local + "_mapping"):
                    pairs = []
                    for name in fields:
                        widget = local + "_map_" + name
                        options = (None, *range(len(record.original_columns)))
                        current = getattr(record.mapping, name)
                        st.selectbox(LABELS[name] + " column", options, index=options.index(current),
                            format_func=lambda n: "Not mapped" if n is None else f"{n + 1}: {record.original_columns[n]}", key=widget)
                        pairs.append((name, widget))
                    if kind == "workorders":
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
            st.dataframe([{"Source row": row.origin.row_number,
                **{LABELS[n]: getattr(row, n) for n in fields},
                "Review needed": "; ".join(row.issues), "Omitted": row.excluded} for row in record.rows], hide_index=True)
            selected = st.selectbox("Row to correct", range(len(record.rows)),
                format_func=lambda n: f"Source row {record.rows[n].origin.row_number} · {getattr(record.rows[n], fields[0]) or 'Missing ID'}",
                key=local + "_row")
            row = record.rows[selected]
            st.caption("Original cells: " + " | ".join(row.origin.cells))
            with st.form(local + "_row_" + row.key):
                pairs = []
                for name in fields:
                    widget = local + "_" + row.key + "_" + name
                    value = getattr(row, name)
                    if not value:
                        position = getattr(record.mapping, name)
                        value = dict(row.corrections).get(name,
                            row.origin.cells[position] if position is not None else "")
                    st.text_input(LABELS[name], value=value, key=widget)
                    pairs.append((name, widget))
                widget = local + "_omit_" + row.key
                st.checkbox("Omit this source row", value=row.excluded, key=widget)
                pairs.append(("excluded", widget))
                st.form_submit_button("Save row correction", on_click=_queue,
                    args=(request_key, {**base, "action": "row", "group": index, "row": row.key}, pairs))
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
