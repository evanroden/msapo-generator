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
MAX_INCLUDED_FOLLOWUPS = 200
FOLLOWUP_PAGE_SIZE = 25
_DECISIONS = {"pending": "pending", "approved": "approved", "declined": "declined",
              "rejected": "declined", "on hold": "on_hold", "not confirmed": "not_confirmed"}
_STATUS_FIELD = re.compile(r"^\s*(?:(?:proposal|approval)\s+)?(?:status|decision)\s*:\s*(.*?)\s*$", re.I)
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*•]|\d+[.)])\s+(.*)$")
_NO_EQUIPMENT_ISSUES = frozenset({
    "no equipment issues", "no current equipment issues", "no equipment issues this month",
    "no equipment performance issues", "no current equipment performance issues",
    "no equipment performance issues this month",
    "zero equipment issues", "0 equipment issues", "zero equipment performance issues",
    "0 equipment performance issues",
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


def unique_followup_keys(draft):
    """Repair colliding saved identities without dropping either occurrence.

    Existing unique keys stay unchanged. A repaired occurrence gets a stable
    key when the working report is next saved; the historical snapshot stays
    immutable and any proposal confirmation is renewed for its actual key.
    """
    reserved = {item.key for item in draft.follow_ups}
    seen, result = set(), []
    for position, item in enumerate(draft.follow_ups):
        if item.key in seen:
            salt = 0
            key = "follow-" + _digest(("saved-collision", item.key, position, asdict(item), salt))[:20]
            while key in reserved:
                salt += 1
                key = "follow-" + _digest(("saved-collision", item.key, position, asdict(item), salt))[:20]
            reserved.add(key)
            item = replace(item, key=key, reviewed_fingerprint="")
        seen.add(item.key)
        result.append(item)
    return replace(draft, follow_ups=tuple(result)) if tuple(result) != draft.follow_ups else draft


def followup_limit_message(draft):
    count = len(output_followups(draft))
    if count > MAX_INCLUDED_FOLLOWUPS:
        return (f"This report includes {count} issues and carried proposals; the output limit is "
                f"{MAX_INCLUDED_FOLLOWUPS}. Review the numbered pages and explicitly leave out "
                "items that do not belong in this report. Every item and its history is retained; "
                "generation stays blocked until the included list is within the limit.")
    return ""


def output_followups(draft):
    from app.monthly_report_model import included_sections
    sections = {section.key for section in included_sections(draft.sections)}
    return tuple(item for item in draft.follow_ups if item.included
                 and ("issues" if item.category == "issue" else "proposals") in sections)


def _followup_choice_identity(draft, prefix, item):
    from app.monthly_report_issues import _action_scope
    values = asdict(item)
    values.pop("reviewed_fingerprint", None)
    return _digest((_action_scope(draft, prefix), values))


def _record_followup_choice(key, identity, before):
    import streamlit as st
    st.session_state[key + "_choice"] = {
        "identity": identity, "before": before, "value": st.session_state.get(key),
    }


def _followup_choice(draft, prefix, item, key, label, value, field):
    """A destructive choice belongs to this exact row and report incarnation."""
    import streamlit as st
    identity = _followup_choice_identity(draft, prefix, item)
    receipt = st.session_state.get(key + "_choice")
    captured = (isinstance(receipt, dict) and receipt.get("result") == identity
                and type(receipt.get("value")) is bool)
    if isinstance(receipt, dict) and not captured and receipt.get("identity") != identity:
        st.warning("The item changed before this choice reached it. Review the current row and repeat the choice if it still applies.")
    # Keep the completing control in this paint. Its warning can disappear
    # immediately without replacing the native target during the click.
    displayed = receipt["value"] if captured else value
    st.session_state[key] = displayed
    st.checkbox(label, key=field(key, displayed), on_change=_record_followup_choice,
                args=(key, identity, displayed))
    return displayed


def _pending_followup_key(prefix, item):
    return prefix + "_pending_followup_" + item.category + "_" + item.key


def _render_followup_recovery(key, pending):
    import streamlit as st
    earlier = pending["after"]
    with st.expander("Earlier item edit (not applied)", key=key):
        st.caption(pending.get("context", "Earlier report editor") +
                   ". Review these entered details against the current item before copying them.")
        labels = pending.get("source_labels", {})
        fields = [("Description", earlier.text), ("Status", _status_label(earlier.status)),
                  ("Update", earlier.update), ("Evidence", earlier.evidence_note)]
        fields += [("Supporting source", labels.get(ref, "Earlier source link: " + ref))
                   for ref in earlier.references]
        st.code("\n\n".join(label + ": " + value for label, value in fields if value),
                language=None, wrap_lines=True)


def _acknowledge_followup_record(key, pending):
    import streamlit as st
    for receipt_key, receipt in pending.get("receipts", {}).items():
        if st.session_state.get(receipt_key) == receipt:
            st.session_state.pop(receipt_key, None)
    st.session_state.pop(key, None)


def acknowledge_followup_controls(draft, prefix):
    """Retire only the exact edits now present in the authoritative draft.

    The full workspace calls this after assigning its canonical draft. A row
    renderer's return, preview refresh or unrelated save is not that receipt.
    """
    import streamlit as st
    for item in draft.follow_ups:
        key = _pending_followup_key(prefix, item)
        pending = st.session_state.get(key)
        if (isinstance(pending, dict) and not pending.get("conflicted")
                and pending.get("result") == _followup_choice_identity(draft, prefix, item)):
            _acknowledge_followup_record(key, pending)
    return draft


def _followup_missing_links(draft, prefix, item, options):
    import streamlit as st
    missing = tuple(ref for ref in item.references if ref not in options)
    if missing:
        return missing
    pending = st.session_state.get(_pending_followup_key(prefix, item))
    if (isinstance(pending, dict) and not pending.get("conflicted")
            and pending.get("result") == _followup_choice_identity(draft, prefix, item)):
        return pending.get("unlinked", ())
    return ()


def _visible_followup_keys(items, prefix, label):
    import streamlit as st
    if len(items) <= FOLLOWUP_PAGE_SIZE:
        return {item.key for item in items}
    pages = (len(items) + FOLLOWUP_PAGE_SIZE - 1) // FOLLOWUP_PAGE_SIZE
    key = prefix + "_page"
    if type(st.session_state.get(key)) is not int or not 1 <= st.session_state[key] <= pages:
        st.session_state[key] = 1
    page = st.selectbox(label, range(1, pages + 1), key=key)
    start = (page - 1) * FOLLOWUP_PAGE_SIZE
    st.caption(f"Showing {start + 1}–{min(start + FOLLOWUP_PAGE_SIZE, len(items))} of {len(items)}")
    return {item.key for item in items[start:start + FOLLOWUP_PAGE_SIZE]}


def _capture_followup_controls(draft, prefix, category, options):
    """Capture delivered fields before an explicit page choice retires them.

    Each callback names its original value. Stale mirrors and changed source
    option sets cannot overwrite canonical fields; untouched rows stay intact.
    """
    import streamlit as st
    result = []
    for item in draft.follow_ups:
        if item.category != category:
            result.append(item)
            continue
        pending_key = _pending_followup_key(prefix, item)
        for recovery_key in sorted(key for key in st.session_state
                                   if key.startswith(pending_key + "_recovery_")):
            _render_followup_recovery(recovery_key, st.session_state[recovery_key])
        pending = st.session_state.get(pending_key)
        current_identity = _followup_choice_identity(draft, prefix, item)
        baseline = item
        receipts, unlinked = {}, ()
        if isinstance(pending, dict):
            if not pending.get("conflicted") and pending.get("result") == current_identity:
                _acknowledge_followup_record(pending_key, pending)
            elif not pending.get("conflicted") and pending.get("identity") == current_identity:
                # The renderer finished but its enclosing report did not.
                # Reapply only this exact row in this exact report/source scope.
                item = pending["after"]
                receipts = dict(pending.get("receipts", {}))
                unlinked = pending.get("unlinked", ())
            else:
                pending = {**pending, "conflicted": True}
                st.session_state[pending_key] = pending
                st.warning("An interrupted item edit belongs to an earlier row, report or source revision. "
                           "The current item is kept; the entered details below remain available to copy.")
                _render_followup_recovery(pending_key + "_current_conflict", pending)
        p = (prefix + "_issue_" + item.key if category == "issue"
             else prefix + "_follow_" + item.key + "_compact")
        changes = {}
        identity = _followup_choice_identity(draft, prefix, item)
        for attr, suffix in (("text", "text"), ("status", "status"),
                             ("update", "update"), ("evidence_note", "note")):
            key, current = p + "_" + suffix, getattr(item, attr)
            receipt = st.session_state.get(key + "_change")
            if (isinstance(receipt, dict) and receipt.get("identity") == identity
                    and receipt.get("before") == current
                    and isinstance(receipt.get("value"), str)
                    and receipt["value"] == st.session_state.get(key)):
                changes[attr] = receipt["value"]
                receipts[key + "_change"] = receipt
        key = p + "_sources_" + _digest(list(options))
        receipt = st.session_state.get(key + "_change")
        selected = [ref for ref in item.references if ref in options]
        if (isinstance(receipt, dict) and receipt.get("identity") == identity
                and receipt.get("before") == selected
                and isinstance(receipt.get("value"), list)
                and receipt["value"] == st.session_state.get(key)
                and all(ref in options for ref in receipt["value"])):
            changes["references"] = (*receipt["value"], *(ref for ref in item.references if ref not in options))
            receipts[key + "_change"] = receipt
        missing = tuple(ref for ref in item.references if ref not in options)
        for key, before, choice in ((p + "_excluded", not item.included, "exclude"),
                                    (p + "_remove_missing_" + _digest(missing), False, "unlink")):
            receipt = st.session_state.get(key + "_choice")
            if (isinstance(receipt, dict) and receipt.get("identity") == identity
                    and receipt.get("before") == before
                    and type(receipt.get("value")) is bool
                    and receipt["value"] == st.session_state.get(key)):
                if choice == "exclude":
                    changes["included"] = not receipt["value"]
                elif receipt["value"]:
                    changes["references"] = tuple(ref for ref in changes.get("references", item.references)
                                                   if ref in options)
                    unlinked = missing
                receipts[key + "_choice"] = receipt
        revised = replace(item, **changes)
        if revised != item:
            revised = replace(revised, reviewed_fingerprint="")
        if receipts:
            after_identity = _followup_choice_identity(draft, prefix, revised)
            receipts = {key: {**receipt, "result": after_identity}
                        for key, receipt in receipts.items()}
            for receipt_key, receipt in receipts.items():
                st.session_state[receipt_key] = receipt
            if isinstance(pending, dict) and pending.get("conflicted"):
                # A later deliberate edit is not permission to discard the
                # earlier conflict. Keep each distinct version reachable.
                st.session_state[pending_key + "_recovery_" + pending["result"]] = pending
            st.session_state[pending_key] = {
                "identity": _followup_choice_identity(draft, prefix, baseline),
                "result": after_identity, "after": revised,
                "receipts": receipts, "unlinked": unlinked,
                "context": draft.profile.title + " · " + draft.period.label,
                "source_labels": {ref: options[ref] for ref in revised.references if ref in options},
            }
        result.append(revised)
    return replace(draft, follow_ups=tuple(result))


def seed_followups(draft):
    from app.monthly_report_issues import canonical_issues
    draft = canonical_issues(draft)
    result = [
        replace(
            normalize_proposal(item),
            carried_from=(item.carried_from or draft.period.key) if item.category == "issue" else draft.period.key,
            included=True, reviewed_fingerprint=""
        )
        for item in draft.follow_ups
        if (item.category == "issue" and item.text.strip()
            and (item.status != "resolved" or problems(item, draft)))
        or (item.category != "issue" and item.included)
    ]
    keys = {item.key for item in result}
    occurrences = {}
    specs = {b.key: b for s in draft.sections for b in s.blocks}
    for block in draft.blocks:
        if block.key not in ("equipment_issues", "proposals") or block.source == "Omit":
            continue
        if block.key == "equipment_issues" and (block.ai_written or block.ai_paragraphs):
            # Unreviewed source-linked issues must retain their existing gate;
            # they cannot become plain, implicitly approved carry-forward text.
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
            identity = (category, original_text)
            occurrences[identity] = occurrences.get(identity, 0) + 1
            occurrence = occurrences[identity]
            key = "follow-" + _digest(identity if occurrence == 1 else (*identity, "occurrence", occurrence))[:20]
            if not text or key in keys:
                continue
            keys.add(key)
            result.append(
                ReportFollowUp(
                    key,
                    category,
                    text,
                    draft.period.key,
                    status=status,
                )
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
    if not item.text.strip() and (item.category != "issue" or item.included):
        messages.append("Keep a description of the carried item.")
    if item.status in ("updated", "resolved") and not (
        item.evidence_note.strip() or item.references
    ):
        messages.append(
            "Add evidence for the update or resolution: a source page or an entered explanation."
        )
    valid = {
        source_reference(s, n)
        for s in draft.sources
        for n in range(1, len(s.page_texts) + 1)
    }
    if (item.included or item.status in ("updated", "resolved")) and any(ref not in valid for ref in item.references):
        messages.append(
            "A follow-up source changed or is missing. Review its current page again."
        )
    if item.category == "proposal" and item.reviewed_fingerprint != confirmation(item, draft.period):
        messages.append(
            "Confirm this proposal's decision and whether it belongs in this report."
        )
    return tuple(messages)


def report_text(item):
    item = normalize_proposal(item)
    return f"{_status_label(item.status)} — {item.text}" + (
        "\n" + item.update if item.update.strip() else ""
    )


def render_followups(draft, prefix, field, *, category=None, defer_issue_actions=False, defer_commit=False):
    """Edit carried items in their section, retaining every other category."""
    draft = unique_followup_keys(draft)
    if category is not None:
        if category not in ("issue", "proposal"):
            raise ValueError("Choose equipment issues or proposals to review.")
        if category == "issue":
            from app.monthly_report_issues import render_issue_cards
            return render_issue_cards(draft, prefix, field, defer_actions=defer_issue_actions,
                                      defer_commit=defer_commit)
        result = _render_section_followups(draft, prefix, field, category)
        return result if defer_commit else acknowledge_followup_controls(result, prefix)
    from app.monthly_report_issues import apply_issue_action, render_issue_cards
    draft = _render_all_followups(render_issue_cards(draft, prefix, field, defer_actions=True,
                                                   defer_commit=True), prefix, field)
    draft = draft if defer_issue_actions else apply_issue_action(draft, prefix)
    return draft if defer_commit else acknowledge_followup_controls(draft, prefix)


def _render_section_followups(draft, prefix, field, category, *, initially_editing=False):
    import streamlit as st
    from app.monthly_report_issues import _issue_control

    if not any(item.category == category for item in draft.follow_ups):
        return draft
    proposal = category == "proposal"
    st.markdown("**Carried proposals**" if proposal else "**Open and recently resolved issues**")
    st.caption("Confirm the current decision, or open the proposal to update it." if proposal
               else "Open an item when its details or status changed.")
    options = {
        source_reference(s, n): f"{s.filename} · page {n}"
        for s in draft.sources
        for n in range(1, len(s.page_texts) + 1)
    }
    draft = _capture_followup_controls(draft, prefix, category, options)
    message = followup_limit_message(draft)
    if message:
        st.error(message)
    visible = _visible_followup_keys([item for item in draft.follow_ups if item.category == category],
                                    prefix + "_carried_" + category, "Proposal page")
    items = []
    for original in draft.follow_ups:
        if original.category != category or original.key not in visible:
            items.append(original)
            continue
        item = normalize_proposal(original)
        p = prefix + "_follow_" + item.key + "_compact"
        edit_key = field(p + "_editing", initially_editing)
        confirmed = replace(item, reviewed_fingerprint=confirmation(item, draft.period))
        needs_correction = problems(confirmed, draft)
        if needs_correction:
            st.session_state[edit_key] = True
        with st.container():
            st.write(item.text)
            state = _status_label(item.status)
            visibility = "Included" if item.included else "Left out of this report"
            st.caption(f"{state} · {visibility} · Carried from {item.carried_from}")
            if item.update.strip():
                st.text(item.update)
            actions = st.columns(3 if not proposal and item.status != "resolved" else 2)
            keep_label = "Confirm unchanged" if proposal else "Still open" if item.status == "ongoing" else "Still correct"
            with actions[0]:
                if st.button(keep_label, key=p + "_keep", disabled=bool(needs_correction)):
                    item = confirmed
                    st.session_state[edit_key] = False
            with actions[1]:
                if st.button("Update proposal" if proposal else "Update issue", key=p + "_edit"):
                    st.session_state[edit_key] = True
            if len(actions) == 3:
                with actions[2]:
                    if st.button("Mark resolved", key=p + "_resolve"):
                        item = replace(item, status="resolved", reviewed_fingerprint="")
                        st.session_state[p + "_status"] = "resolved"
                        st.session_state[edit_key] = True
            if st.session_state[edit_key]:
                identity = _followup_choice_identity(draft, prefix, item)
                text = _issue_control(st.text_area,
                    "Proposal scope" if proposal else "Issue description",
                    p + "_text", item.text, field, identity=identity, height=90, max_chars=4000,
                )
                status = _issue_control(st.radio,
                    "Proposal decision" if proposal else "Current status",
                    p + "_status", item.status, field,
                    identity=identity,
                    options=PROPOSAL_STATUSES if proposal else ISSUE_STATUSES,
                    format_func=_status_label, horizontal=True,
                )
                update = _issue_control(st.text_area,
                    "What changed this month?", p + "_update", item.update, field,
                    identity=identity, height=90, max_chars=4000,
                )
                evidence = _issue_control(st.text_area,
                    "Evidence or explanation for the status", p + "_note", item.evidence_note, field,
                    identity=identity, height=90, max_chars=4000,
                )
                selected = _issue_control(st.multiselect,
                    "Supporting source pages (optional)", p + "_sources_" + _digest(list(options)),
                    [ref for ref in item.references if ref in options], field,
                    identity=identity, options=list(options), format_func=options.get,
                ) if options else []
                missing = _followup_missing_links(draft, prefix, item, options)
                if missing:
                    notice = st.empty()
                    if _followup_choice(draft, prefix, item, p + "_remove_missing_" + _digest(missing),
                                        "Remove unavailable source links", False, field):
                        missing = ()
                    else:
                        notice.warning("Some saved source links are unavailable. Replace them with current evidence, or explicitly remove them.")
                excluded = not item.included
                if proposal or status == "resolved":
                    excluded = _followup_choice(draft, prefix, item, p + "_excluded",
                        "Leave this proposal out of the report" if proposal else "Leave this resolved item out of the report",
                        excluded, field,
                    )
                elif excluded:
                    st.warning("An open issue must be included in the report.")
                    if st.button("Include this issue again", key=p + "_include"):
                        excluded = False
                        st.session_state[p + "_excluded"] = False
                revised = replace(
                    item, text=text, status=status, update=update, evidence_note=evidence,
                    references=(*selected, *missing), included=not excluded,
                )
                signature = confirmation(revised, draft.period)
                revised = replace(revised, reviewed_fingerprint=signature if item.reviewed_fingerprint == signature else "")
                confirmed = replace(revised, reviewed_fingerprint=signature)
                errors = problems(confirmed, draft)
                for message in errors:
                    st.warning(message)
                if st.button("Confirm update", key=p + "_confirm", disabled=bool(errors)):
                    revised = confirmed
                    st.session_state[edit_key] = False
                item = revised
            if item.reviewed_fingerprint == confirmation(item, draft.period):
                st.caption(f"Confirmed for {draft.period.label}.")
            elif not st.session_state[edit_key]:
                st.caption(f"Confirm this item for {draft.period.label}.")
            items.append(item)
    return replace(draft, follow_ups=tuple(items))


def _render_all_followups(draft, prefix, field):
    """Detailed entry uses the same bounded, receipt-aware proposal editor."""
    return _render_section_followups(draft, prefix, field, "proposal", initially_editing=True)
