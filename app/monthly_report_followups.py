"""Explicit carry-forward decisions; a new reporting month never resolves work."""

from dataclasses import asdict, replace
import hashlib
import json

from app.monthly_report_model import ReportFollowUp, STOCK_TEXTS
from app.monthly_report_sources import source_reference
from app.monthly_report_content_policy import table_price_columns


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def seed_followups(draft):
    result = [
        replace(
            item, carried_from=draft.period.key, references=(), reviewed_fingerprint=""
        )
        for item in draft.follow_ups
        if item.included
    ]
    seen = {(item.category, item.text.strip()) for item in result}
    specs = {b.key: b for s in draft.sections for b in s.blocks}
    for block in draft.blocks:
        if block.key not in ("equipment_issues", "proposals") or block.source == "Omit":
            continue
        category = "issue" if block.key == "equipment_issues" else "proposal"
        texts = [
            line.lstrip("- •").strip()
            for line in block.text.splitlines()
            if line.strip() and line.strip() not in STOCK_TEXTS.values()
        ]
        tables = (
            [(tuple(c.title for c in specs[block.key].columns), block.rows)]
            if block.key in specs and block.rows
            else []
        )
        tables += [(t.columns, t.rows) for t in block.extra_tables]
        for columns, rows in tables:
            width = max((len(row) for row in rows), default=len(columns))
            columns = (*columns, *(f"Detail {n+1}" for n in range(len(columns), width)))
            prices = table_price_columns(columns, rows)
            texts += [
                "; ".join(
                    f"{columns[n]}: {value}"
                    for n, value in enumerate(row)
                    if n < len(columns) and n not in prices and value.strip()
                )
                for row in rows
            ]
        for text in texts:
            if not text or (category, text) in seen:
                continue
            seen.add((category, text))
            result.append(
                ReportFollowUp(
                    "follow-" + _digest((category, text))[:20],
                    category,
                    text,
                    draft.period.key,
                )
            )
    if len(result) > 200:
        raise ValueError(
            "More than 200 carried issues/proposals need review. Resolve or consolidate the prior report first; no items were discarded."
        )
    return tuple(result)


def confirmation(item, period):
    values = asdict(item)
    values.pop("reviewed_fingerprint")
    return _digest((values, period.key))


def problems(item, draft):
    messages = []
    if item.category not in ("issue", "proposal") or item.status not in (
        "ongoing",
        "updated",
        "resolved",
    ):
        messages.append("Choose a valid item type and current status.")
    if not item.text.strip():
        messages.append("Keep a description of the carried item.")
    if item.status in ("updated", "resolved") and not (
        item.evidence_note.strip() or item.references
    ):
        messages.append(
            "Add evidence for the update or resolution: a source page or an entered explanation."
        )
    if not item.included and item.status != "resolved":
        messages.append(
            "Only explicitly resolved items can be left out. Ongoing work remains in the report."
        )
    valid = {
        source_reference(s, n)
        for s in draft.sources
        for n in range(1, len(s.page_texts) + 1)
    }
    if any(ref not in valid for ref in item.references):
        messages.append(
            "A follow-up source changed or is missing. Review its current page again."
        )
    if item.reviewed_fingerprint != confirmation(item, draft.period):
        messages.append(
            "Confirm whether this carried item is ongoing, updated or resolved this month."
        )
    return tuple(messages)


def report_text(item):
    return f"{item.status.capitalize()} — {item.text}" + (
        "\n" + item.update if item.update.strip() else ""
    )


def render_followups(draft, prefix, field):
    import streamlit as st

    if not draft.follow_ups:
        return draft
    st.subheader("Check issues and proposals carried forward")
    st.caption(
        "These came from your saved report. Keep open work, explain changes, or mark an item resolved. Resolved items stay in the report until you choose to leave them out."
    )
    options = {
        source_reference(s, n): f"{s.filename} · page {n}"
        for s in draft.sources
        for n in range(1, len(s.page_texts) + 1)
    }
    items = []
    for item in draft.follow_ups:
        p = prefix + "_follow_" + item.key
        with st.expander(
            item.category.capitalize() + " · " + item.text[:90],
            expanded=bool(problems(item, draft)),
        ):
            st.caption("Carried from saved report: " + item.carried_from)
            text = st.text_area(
                "Item to follow up",
                key=field(p + "_text", item.text),
                height=90,
                max_chars=4000,
            )
            status = st.radio(
                "Current status",
                ["ongoing", "updated", "resolved"],
                format_func=str.capitalize,
                key=field(p + "_status", item.status),
                horizontal=True,
            )
            update = st.text_area(
                "What changed this month?",
                key=field(p + "_update", item.update),
                height=90,
                max_chars=4000,
            )
            evidence = st.text_area(
                "Evidence or explanation for the status",
                key=field(p + "_note", item.evidence_note),
                height=90,
                max_chars=4000,
            )
            selected = st.multiselect(
                "Supporting source pages (optional)",
                list(options),
                format_func=options.get,
                key=field(
                    p + "_sources_" + _digest(list(options)),
                    [r for r in item.references if r in options],
                ),
            )
            excluded = (
                st.checkbox(
                    "Leave this resolved item out of the report",
                    key=field(p + "_excluded", not item.included),
                    disabled=status != "resolved",
                )
                if status == "resolved"
                else False
            )
            revised = replace(
                item,
                text=text,
                status=status,
                update=update,
                evidence_note=evidence,
                references=tuple(selected),
                included=not excluded,
                reviewed_fingerprint="",
            )
            signature = confirmation(revised, draft.period)
            checked = st.checkbox(
                "I confirmed this item’s status and supporting information",
                key=field(
                    p + "_checked_" + signature, item.reviewed_fingerprint == signature
                ),
            )
            if checked:
                revised = replace(revised, reviewed_fingerprint=signature)
            for message in problems(revised, draft):
                st.warning(message)
            items.append(revised)
    return replace(draft, follow_ups=tuple(items))
