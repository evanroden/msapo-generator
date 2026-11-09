"""Review explicit source-table instructions without guessing ambiguous facts."""
from dataclasses import replace
import hashlib
import json

from app.monthly_report_model import ReportTable
from app.monthly_report_source_content_roles import source_stamp, text_role


def source_table_role(item):
    if item.kind != "table" or item.section in ("", "cover"):
        return ""
    return next((role for row in item.rows for cell in row if (role := text_role(cell))), "")


def _stamp(source_sha, item):
    return hashlib.sha256(json.dumps((source_stamp(source_sha, item), item.rows),
                                     ensure_ascii=False).encode()).hexdigest()


def _value(table):
    return {"columns": list(table.columns), "rows": [list(row) for row in table.rows]}


def _role(table):
    return next((role for row in (table.columns, *table.rows) for cell in row
                 if (role := text_role(cell))), "")


def validate_table_role_reviews(plan, items, source_sha):
    if plan.get("omit"):
        return
    by_id = {item.id: item for item in items}
    selected = set(plan.get("selected", ()))
    required = set(plan.get("table_role_required", ()))
    required.update(identity for identity in selected
                    if identity in by_id and source_table_role(by_id[identity]))
    for identity in required:
        item = by_id.get(identity)
        receipt = plan.get("table_role_reviews", {}).get(identity, {})
        if (item is None or not source_table_role(item)
                or receipt.get("stamp") != _stamp(source_sha, item)
                or receipt.get("action") not in ("include", "exclude")):
            raise ValueError("Review the source table instructions or examples again before continuing.")
        if receipt["action"] == "exclude":
            if identity in selected:
                raise ValueError("An excluded source table cannot be included in the report.")
            continue
        table = plan.get("tables", {}).get(identity)
        if (identity not in selected or not isinstance(table, ReportTable)
                or _value(table) != receipt.get("table") or _role(table)
                or not all(table.columns) or len(set(table.columns)) != len(table.columns)):
            raise ValueError("Use the verified table edits or review the source table again before continuing.")


def review_source_table(item, table, number, inspection, prefix, field, old, plan, blocking):
    """One exact table choice; preserve edits when temporarily excluding it."""
    import streamlit as st
    from app.monthly_report_content_policy import table_has_pricing
    from app.monthly_report_editor import _grid, _signature
    from app.monthly_report_ui_text import literal

    stamp = _stamp(inspection.sha256, item)
    prior = old.get("table_role_reviews", {}).get(item.id, {})
    if prior.get("stamp") != stamp:
        prior = {}
    if table is not None and prior.get("table"):
        stored = prior["table"]
        table = replace(table, columns=tuple(stored["columns"]),
                        rows=tuple(tuple(row) for row in stored["rows"]))
    key = prefix + "_role_table_" + stamp
    plan.setdefault("table_role_required", [])
    if item.id not in plan["table_role_required"]:
        plan["table_role_required"].append(item.id)
    plan["questions"] = tuple(dict.fromkeys((*plan.get("questions", ()), "Review source table instructions or examples.")))
    st.caption(literal(source_table_role(item)) + " · source table " + str(number))
    if table is not None:
        st.dataframe([dict(zip(table.columns, row)) for row in table.rows[:300]], hide_index=True)
    else:
        st.info("No client-facing columns remain after removing pricing. Leave this table out; the original stays in your uploaded report.")
    choices = {"": "Choose how to use this table", "exclude": "Leave out of this report",
               "include": "Use verified table edits"}
    if table is None:
        choices.pop("include")
    choice = st.radio("Use source table " + str(number), tuple(choices), format_func=choices.get,
                      key=field(key + "_choice", prior.get("action", "") if prior.get("action", "") in choices else ""))
    if choice == "include":
        st.caption("Replace marked instructions, examples and placeholders with verified report values below. Original cells remain in the uploaded report.")
        columns = tuple(st.text_input(f"Verified column {n + 1} heading", key=field(key + f"_heading_{n}", title)).strip()
                        for n, title in enumerate(table.columns))
        if not all(columns) or len(set(columns)) != len(columns):
            blocking.append("Give each verified table column a different, nonempty heading.")
        else:
            rows = [dict(zip(columns, row)) for row in table.rows]
            rows = _grid(key + "_cells_" + _signature(columns), rows, num_rows="dynamic", hide_index=True)
            table = replace(table, columns=columns,
                            rows=tuple(tuple("" if row.get(c) is None else str(row[c]) for c in columns) for row in rows))
        if _role(table):
            blocking.append("Replace the table instruction, placeholder or example with verified values, or leave the table out.")
        if table_has_pricing(table.columns, table.rows):
            blocking.append("Remove pricing from the verified table before continuing.")
    elif not choice:
        blocking.append("Choose how to use the marked source table before continuing.")
    plan.setdefault("table_role_reviews", {})[item.id] = {
        "stamp": stamp, "action": choice, "table": _value(table) if table is not None else None,
    }
    return table if choice == "include" else None
