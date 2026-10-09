"""Explicit carry-forward decisions; a new reporting month never resolves work."""

from dataclasses import asdict, replace
import hashlib
import json
import re

from app.monthly_report_model import ReportFollowUp, STOCK_TEXTS
from app.monthly_report_sources import source_reference
from app.monthly_report_content_policy import table_price_columns

PROPOSAL_STATUSES = ("pending", "approved", "declined", "on_hold", "not_confirmed")
ISSUE_STATUSES = ("ongoing", "updated", "resolved")
_DECISIONS = {"pending": "pending", "approved": "approved", "declined": "declined",
              "rejected": "declined", "on hold": "on_hold", "not confirmed": "not_confirmed"}
_STATUS_FIELD = re.compile(r"^\s*(?:(?:proposal|approval)\s+)?(?:status|decision)\s*:\s*(.*?)\s*$", re.I)
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*•]|\d+[.)])\s+(.*)$")
_NO_EQUIPMENT_ISSUES = frozenset({
    "no equipment issues", "no current equipment issues", "no equipment issues this month",
    "no equipment performance issues", "no current equipment performance issues",
    "no equipment performance issues this month",
})


def _followup_text_items(text):
    """Keep wrapped paragraphs and indented bullet details with their item."""
    result, lines = [], []
    bullet_indent = None

    def finish():
        if lines:
            result.append("\n".join(lines))
            lines.clear()

    for line in text.splitlines():
        if not line.strip():
            finish()
            bullet_indent = None
            continue
        match = _LIST_ITEM.match(line)
        indent = len(match[1].expandtabs()) if match else None
        if match and (not lines or bullet_indent is None or indent <= bullet_indent):
            finish()
            bullet_indent = indent
            lines.append(match[2].strip())
        else:
            lines.append(line.strip())
    finish()
    return result


def _no_equipment_issues(text):
    # Match only a complete declaration, never a prefix or an embedded phrase.
    return " ".join(text.casefold().split()).removesuffix(".") in _NO_EQUIPMENT_ISSUES


def _proposal_details(text):
    """Read explicit decision fields only; ambiguous alternatives stay intact."""
    parts = re.split(r";\s*|\n", text)
    decisions, keep = [], []
    for part in parts:
        match = _STATUS_FIELD.fullmatch(part)
        decision = _DECISIONS.get(" ".join(match[1].casefold().split())) if match else None
        if decision:
            decisions.append(decision)
        else:
            keep.append(part)
    if len(set(decisions)) != 1 or not any(p.strip() for p in keep):
        return text, "not_confirmed"
    return "; ".join(p for p in keep if p.strip()), decisions[0]


def normalize_proposal(item):
    if item.category != "proposal":
        return item
    text, decision = _proposal_details(item.text)
    status = item.status if item.status in PROPOSAL_STATUSES else decision
    if (text, status) == (item.text, item.status):
        return item
    return replace(item, text=text, status=status, reviewed_fingerprint="")


def _status_label(status):
    return status.replace("_", " ").capitalize()


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def seed_followups(draft):
    result = [
        replace(
            normalize_proposal(item), carried_from=draft.period.key, reviewed_fingerprint=""
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
        texts = [text for text in _followup_text_items(block.text)
                 if text not in STOCK_TEXTS.values()
                 and not (category == "issue" and _no_equipment_issues(text))]
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
            original_text = text
            text, status = _proposal_details(text) if category == "proposal" else (text, "ongoing")
            if not text or (category, text) in seen:
                continue
            seen.add((category, text))
            result.append(
                ReportFollowUp(
                    "follow-" + _digest((category, original_text))[:20],
                    category,
                    text,
                    draft.period.key,
                    status=status,
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
        PROPOSAL_STATUSES if item.category == "proposal" else ISSUE_STATUSES
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
    if not item.included and item.category == "issue" and item.status != "resolved":
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
            "Confirm this proposal's decision and whether it belongs in this report."
            if item.category == "proposal" else
            "Confirm whether this carried item is ongoing, updated or resolved this month."
        )
    return tuple(messages)


def report_text(item):
    item = normalize_proposal(item)
    return f"{_status_label(item.status)} — {item.text}" + (
        "\n" + item.update if item.update.strip() else ""
    )


def render_followups(draft, prefix, field):
    import streamlit as st

    if not draft.follow_ups:
        return draft
    st.subheader("Check issues and proposals carried forward")
    st.caption(
        "These came from your saved report. Check equipment issues and proposal decisions separately. Approval of a proposal does not mean the work is complete. Items stay in the report until you explicitly leave them out."
    )
    options = {
        source_reference(s, n): f"{s.filename} · page {n}"
        for s in draft.sources
        for n in range(1, len(s.page_texts) + 1)
    }
    items = []
    for item in draft.follow_ups:
        item = normalize_proposal(item)
        proposal = item.category == "proposal"
        p = prefix + "_follow_" + item.key
        with st.expander(
            item.category.capitalize() + " · " + item.text[:90],
            expanded=bool(problems(item, draft)),
        ):
            st.caption("Carried from saved report: " + item.carried_from)
            text = st.text_area(
                "Item to follow up",
                key=field(p + ("_proposal_text" if proposal else "_text"), item.text),
                height=90,
                max_chars=4000,
            )
            status = st.radio(
                "Proposal decision" if proposal else "Current status",
                PROPOSAL_STATUSES if proposal else ISSUE_STATUSES,
                format_func=_status_label,
                key=field(p + ("_proposal_decision" if proposal else "_status"), item.status),
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
                    "Leave this proposal out of the report" if proposal else "Leave this resolved item out of the report",
                    key=field(p + "_excluded", not item.included),
                    disabled=not proposal and status != "resolved",
                )
                if proposal or status == "resolved"
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
