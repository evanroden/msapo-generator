"""One report-scoped issue list; omission is not resolution or history deletion."""

from dataclasses import asdict, replace
from uuid import uuid4

from app.monthly_report_content_policy import table_price_columns
from app.monthly_report_followups import (
    ISSUE_STATUSES, _digest, _followup_text_items, _no_equipment_issues,
    _status_label, problems, unique_followup_keys, followup_limit_message,
    _capture_followup_controls, _visible_followup_keys, MAX_INCLUDED_FOLLOWUPS,
    FOLLOWUP_PAGE_SIZE, _followup_choice, _followup_choice_identity, output_followups,
    confirmation, needs_issue_period_confirmation,
    acknowledge_followup_controls, _followup_missing_links,
)
from app.monthly_report_model import ReportFollowUp
from app.monthly_report_sources import source_reference

_REMOVED_STATEMENT = "issue-statement-removed:"


def issue_key(text):
    # Match the existing carry-forward identity. Editing or omitting an issue
    # retains this key, so importing its original wording cannot recreate it.
    return "follow-" + _digest(("issue", text))[:20]


def canonical_issues(draft):
    """Migrate legacy issue prose/rows once without mutating a saved snapshot.

    Supporting artwork and its review/provenance stay in the section block.
    Explicit no-issue declarations stay statements, rather than false issues.
    A source-linked draft remains in its evidence editor until reviewed there.
    """
    draft = unique_followup_keys(draft)
    block = next((b for b in draft.blocks if b.key == "equipment_issues"), None)
    if block is None or block.source == "Omit":
        return draft
    if block.ai_written or block.ai_paragraphs:
        from app.monthly_report_ai import reviewed_block
        if not block.reviewed:
            return draft
        try:
            reviewed_block(block, draft.sources)
        except ValueError:
            return draft
    specs = {b.key: b for s in draft.sections for b in s.blocks}
    texts = _followup_text_items(block.text)
    spec = specs.get(block.key)
    tables = [(tuple(c.title for c in spec.columns) if spec else (), block.rows, "")]
    tables += [(table.columns, table.rows, table.reference) for table in block.extra_tables]
    candidates = [(text, block.references) for text in texts]
    for columns, rows, reference in tables:
        width = max((len(row) for row in rows), default=len(columns))
        columns = (*columns, *(f"Detail {n + 1}" for n in range(len(columns), width)))
        prices = table_price_columns(columns, rows)
        for row in rows:
            text = "; ".join(f"{columns[n]}: {value}" for n, value in enumerate(row)
                             if n not in prices and value.strip())
            if text:
                candidates.append((text, (*block.references, *((reference,) if reference else ()))))
    items = list(draft.follow_ups)
    keys = {item.key for item in items if item.category == "issue"}
    seen = {item.text.strip() for item in items if item.category == "issue"}
    statements = []
    for text, references in candidates:
        if _no_equipment_issues(text):
            if _REMOVED_STATEMENT + _digest(text) not in block.references:
                statements.append(text)
            continue
        key = issue_key(text)
        if key in keys or text.strip() in seen:
            continue
        keys.add(key)
        seen.add(text.strip())
        # Report-period tags describe the old document, not supporting pages.
        # A source-linked draft remains in its evidence editor until reviewed.
        references = tuple(dict.fromkeys(ref for ref in references
                            if not ref.startswith(("report-period:", "report-origin:", "docx:", _REMOVED_STATEMENT))))
        items.append(ReportFollowUp(key, "issue", text, draft.period.key,
                                    references=references))
    revised = replace(block, text="\n\n".join(dict.fromkeys(statements)), rows=(),
                      extra_tables=(), ai_paragraphs=(), ai_written=False,
                      ai_evidence_fingerprint="", reviewed_fingerprint="",
                      references=block.references if block.asset_hashes else
                      tuple(ref for ref in block.references
                            if not ref.startswith(("report-period:", "report-origin:"))))
    from app.monthly_report_asset_review import preserve_asset_reviews
    revised = replace(preserve_asset_reviews(block, revised), asset_provenance=block.asset_provenance)
    sections = tuple(replace(section, blocks=tuple(
        replace(spec, required=False) if spec.key == "equipment_issues" else spec
        for spec in section.blocks)) for section in draft.sections)
    if revised == block and tuple(items) == draft.follow_ups and sections == draft.sections:
        return draft
    return replace(draft, blocks=tuple(revised if b.key == block.key else b for b in draft.blocks),
                   follow_ups=tuple(items), sections=sections)


def remove_issue_statement(draft):
    """Keep a source-wording omission receipt without creating a fake issue."""
    from app.monthly_report_asset_review import normalize_asset_reviews, preserve_asset_reviews
    blocks = []
    for block in draft.blocks:
        if block.key == "equipment_issues":
            block = normalize_asset_reviews(block)
            excluded = tuple(_REMOVED_STATEMENT + _digest(text)
                             for text in _followup_text_items(block.text) if _no_equipment_issues(text))
            block = preserve_asset_reviews(block, replace(block, text="",
                references=tuple(dict.fromkeys((*block.references, *excluded)))))
        blocks.append(block)
    return replace(draft, blocks=tuple(blocks))


def issue_visibility(draft, key, included):
    """Retain the original item and status as a report-only omission receipt."""
    return replace(draft, follow_ups=tuple(
        replace(item, included=included) if item.category == "issue" and item.key == key else item
        for item in draft.follow_ups))


def clear_issues(draft):
    draft = canonical_issues(draft)
    return replace(draft, follow_ups=tuple(
        replace(item, included=False) if item.category == "issue" else item
        for item in draft.follow_ups))


def _action_scope(draft, prefix):
    """A delayed list action cannot cross a reset, source or report identity."""
    import streamlit as st
    epoch = st.session_state.setdefault(prefix + "_rich_text_epoch", uuid4().hex)
    return _digest((prefix, epoch, st.session_state.get("_monthly_qa_generation", ""),
                    asdict(draft.profile), draft.period.key,
                    tuple(source.fingerprint for source in draft.sources),
                    tuple(item.key for item in draft.follow_ups if item.category == "issue")))


def _queue_issue_action(prefix, scope, action, expected=""):
    import streamlit as st
    st.session_state[prefix + "_pending_issue_action"] = {
        "scope": scope, "action": action, "expected": expected,
    }


def _action_cycle(prefix, scope):
    """One local cycle token, plus an optional exact-report Undo receipt."""
    import streamlit as st
    key = prefix + "_issue_clear_undo"
    cycle = st.session_state.get(key)
    if not isinstance(cycle, dict) or cycle.get("scope") != scope:
        cycle = {"scope": scope, "token": uuid4().hex}
    elif not isinstance(cycle.get("token"), str) or not cycle["token"]:
        cycle = {**cycle, "token": uuid4().hex}
    st.session_state[key] = cycle
    return cycle


def apply_issue_action(draft, prefix):
    """Apply after native edits, so Clear retains them and Undo cannot replace them.

    The ordered workspace calls this only after every section's delivered
    values have reached the draft, including tables rendered after Issues.
    A receipt contains inclusion flags, never another copy of source bytes.
    """
    import streamlit as st
    request = st.session_state.pop(prefix + "_pending_issue_action", None)
    if not request:
        return draft
    scope = _action_scope(draft, prefix)
    undo_key = prefix + "_issue_clear_undo"
    if request.get("scope") != scope:
        st.warning("The report or its sources changed. Review the issue list before trying that action again.")
        return draft
    cycle = st.session_state.get(undo_key)
    if (not isinstance(cycle, dict) or cycle.get("scope") != scope
            or cycle.get("token") != request.get("expected")):
        st.warning("That issue action was replaced. Review the current issue selection and try again.")
        return draft
    if request.get("action") == "clear":
        inclusion = tuple((item.key, item.included) for item in draft.follow_ups
                          if item.category == "issue")
        if not any(included for _, included in inclusion):
            return draft
        draft = clear_issues(draft)
        st.session_state[undo_key] = {"scope": scope, "after": draft.fingerprint,
                                      "token": uuid4().hex, "inclusion": inclusion}
        notice = "Issues left out of this report. Their wording, status and history are retained."
    elif request.get("action") == "undo":
        if draft.fingerprint != cycle.get("after"):
            st.warning("The report changed after Clear. Your edits are kept; use Include again for individual issues.")
            return draft
        inclusion = dict(cycle["inclusion"])
        draft = replace(draft, follow_ups=tuple(
            replace(item, included=inclusion[item.key])
            if item.category == "issue" and item.key in inclusion else item
            for item in draft.follow_ups))
        st.session_state[undo_key] = {"scope": scope, "token": uuid4().hex}
        notice = "The previous issue selection is restored in this report."
    else:
        return draft
    st.session_state[prefix + "_issue_action_notice"] = (scope, notice)
    # The authoritative draft and recovery journal must commit before the
    # normal workspace refreshes its controls. Never rerun mid-editor.
    st.session_state[prefix + "_period_editor_refresh"] = True
    return draft


def _render_issue_actions(draft, prefix):
    import streamlit as st
    scope = _action_scope(draft, prefix)
    notice = st.session_state.pop(prefix + "_issue_action_notice", None)
    if notice and notice[0] == scope:
        st.caption(notice[1])
    cycle = _action_cycle(prefix, scope)
    token = cycle["token"]
    receipt = cycle if "after" in cycle else None
    included = any(item.category == "issue" and item.included for item in draft.follow_ups)
    if not included and not receipt:
        return
    with st.popover("Issue actions", key=prefix + "_issue_actions_" + scope):
        st.caption("Changes only this report's issue selection. Saved versions, source files and issue history stay intact.")
        # Both native IDs and callback arguments carry the action cycle.
        # Completing Clear or Undo retires the preceding native buttons even
        # when the report has identical content in the same incarnation.
        st.button("Clear issues from this report", key=prefix + "_issue_clear_" + scope + "_" + token,
                  disabled=not included, on_click=_queue_issue_action,
                  args=(prefix, scope, "clear", token))
        if receipt:
            unchanged = receipt["after"] == draft.fingerprint
            # Equal content after a reset is still another native action.
            # Scope in callback arguments alone is insufficient: reusing the
            # native ID would bind an old click to the NEW callback arguments.
            st.button("Undo Clear issues", key=prefix + "_issue_undo_clear_" + scope + "_" + token + "_" + receipt["after"],
                      disabled=not unchanged, on_click=_queue_issue_action,
                      args=(prefix, scope, "undo", token))
            if not unchanged:
                st.caption("The report changed after Clear. Use Include again for individual issues.")


def _issue_changed(key, before, identity):
    import streamlit as st
    st.session_state[key + "_change"] = {
        "identity": identity, "before": before, "value": st.session_state.get(key),
    }


def _queue_issue_period_confirmation(prefix, row_key, identity):
    import streamlit as st
    st.session_state[prefix + "_pending_issue_period_confirmation"] = {
        "row_key": row_key, "identity": identity,
    }


def _apply_issue_period_confirmation(before, captured, prefix):
    """Approve only the rendered row, after its delivered native edits land."""
    import streamlit as st
    key = prefix + "_pending_issue_period_confirmation"
    request = st.session_state.get(key)
    if not request:
        return captured
    original = next((item for item in before.follow_ups
                     if item.category == "issue" and item.key == request.get("row_key")), None)
    if (original is None
            or _followup_choice_identity(before, prefix, original)
            not in (request.get("identity"), request.get("result"))):
        st.session_state.pop(key, None)
        st.warning("The issue or report changed before this confirmation arrived. Review the current issue and confirm again if the update still applies.")
        return captured
    current = next((item for item in captured.follow_ups if item.key == original.key), None)
    if (current is None or (request.get("result")
            and request["result"] != _followup_choice_identity(captured, prefix, current))):
        st.session_state.pop(key, None)
        st.warning("The entered issue changed after the earlier confirmation. Its current details are kept; confirm the current update if it still applies.")
        return captured
    if not needs_issue_period_confirmation(current, captured.period):
        if not request.get("result"):
            st.session_state.pop(key, None)
        return captured
    confirmed = replace(current, reviewed_fingerprint=confirmation(current, captured.period))
    remaining = problems(confirmed, captured)
    if remaining:
        st.session_state.pop(key, None)
        st.warning("The update has not been confirmed: " + " ".join(remaining))
        return captured
    st.session_state[key] = {
        **request, "result": _followup_choice_identity(captured, prefix, current),
        "reviewed_fingerprint": confirmed.reviewed_fingerprint,
    }
    return replace(captured, follow_ups=tuple(
        confirmed if item.key == current.key else item for item in captured.follow_ups))


def _issue_control(widget, label, key, value, field, *, identity, **kwargs):
    """An untouched widget mirror cannot undo a replaced canonical issue."""
    import streamlit as st
    receipt = st.session_state.get(key + "_change")
    submitted = (isinstance(receipt, dict) and receipt.get("identity") == identity
                 and receipt.get("before") == value
                 and receipt.get("value") == st.session_state.get(key))
    captured = (isinstance(receipt, dict) and receipt.get("result") == identity
                and receipt.get("value") == value)
    if isinstance(receipt, dict) and not submitted and not captured:
        st.warning(f"An earlier {label.lower()} edit belongs to a changed item or report. "
                   "The current value is kept. The entered value below has not been applied or saved.")
        if receipt.get("value") in ("", []):
            st.caption("The earlier edit cleared this field.")
        else:
            st.code(str(receipt.get("value", "")), language=None, wrap_lines=True)
    if st.session_state.get(key, value) != value and not submitted:
        st.session_state[key] = value
    if widget == st.text_area:
        # The first native mount needs the same wording as the canonical
        # issue, not the textarea's implicit empty default. Keep the existing
        # receipt guard and honor an explicitly submitted clear/update.
        kwargs["value"] = receipt["value"] if submitted else value
    elif widget == st.multiselect:
        # The Python mirror alone does not set a newly mounted native default.
        # Keep real selection and explicit clear consistent in both protocols.
        kwargs["default"] = receipt["value"] if submitted else value
    result = widget(label, key=field(key, value), on_change=_issue_changed,
                    args=(key, value, identity), **kwargs)
    if submitted and not captured:
        st.session_state.pop(key + "_change", None)
    if submitted and result != value:
        return result
    return value


def _render_issue_evidence(item, draft, options, p, field, prefix):
    import streamlit as st
    identity = _followup_choice_identity(draft, prefix, item)
    update = _issue_control(st.text_area, "Issue update", p + "_update", item.update,
                            field, identity=identity, height=90, max_chars=4000)
    note, references = item.evidence_note, item.references
    if item.status in ("updated", "resolved") or note:
        note = _issue_control(st.text_area, "Evidence or explanation for the status",
                              p + "_note", note, field, identity=identity, height=90, max_chars=4000)
    if options or references:
        selected = _issue_control(st.multiselect, "Supporting source pages",
            p + "_sources_" + _digest(list(options)),
            [ref for ref in references if ref in options], field,
            identity=identity, options=list(options), format_func=options.get) if options else []
        missing = _followup_missing_links(draft, prefix, item, options)
        if missing:
            notice = st.empty()
            if _followup_choice(draft, prefix, item, p + "_remove_missing_" + _digest(missing),
                                "Remove unavailable source links", False, field):
                missing = ()
            else:
                notice.warning("A supporting source changed or is missing.")
        references = (*selected, *missing)
    if item.carried_from != draft.period.key:
        st.caption("Carried from " + item.carried_from)
    if needs_issue_period_confirmation(item, draft.period):
        st.button("Confirm update for " + draft.period.label,
                  key=p + "_confirm_period_" + identity,
                  on_click=_queue_issue_period_confirmation,
                  args=(prefix, item.key, identity))
    return replace(item, update=update, evidence_note=note, references=references)


def render_issue_cards(draft, prefix, field, *, defer_actions=False, evidence_pages=None, defer_commit=False):
    import streamlit as st

    draft = canonical_issues(draft)
    options = {source_reference(source, n): f"{source.filename} · page {n}"
               for source in draft.sources for n in range(1, len(source.page_texts) + 1)}
    before = draft
    draft = _capture_followup_controls(draft, prefix, "issue", options)
    draft = _apply_issue_period_confirmation(before, draft, prefix)
    message = followup_limit_message(draft)
    if message:
        st.error(message)
    issues = [item for item in draft.follow_ups if item.category == "issue"]
    if st.button("Add issue", key=prefix + "_issue_add",
                 disabled=len(output_followups(draft)) >= MAX_INCLUDED_FOLLOWUPS):
        item = ReportFollowUp("issue-" + uuid4().hex, "issue", "", draft.period.key)
        draft = replace(draft, follow_ups=(*draft.follow_ups, item))
        issues.append(item)
        st.session_state[prefix + "_issues_page"] = (
            sum(issue.included for issue in issues) + FOLLOWUP_PAGE_SIZE - 1) // FOLLOWUP_PAGE_SIZE
    _render_issue_actions(draft, prefix)
    visible = _visible_followup_keys([item for item in issues if item.included],
                                    prefix + "_issues", "Issue page")
    block = next((b for b in draft.blocks if b.key == "equipment_issues"), None)
    if block and block.text and not block.ai_written and not block.ai_paragraphs:
        st.text(block.text)
        if st.button("Remove no-issues statement", key=prefix + "_issue_statement_remove"):
            draft = remove_issue_statement(draft)
    items, evidence_controls = [], {}
    for original in draft.follow_ups:
        if original.category != "issue" or not original.included or original.key not in visible:
            items.append(original)
            continue
        item = original
        p = prefix + "_issue_" + item.key
        identity = _followup_choice_identity(draft, prefix, item)
        surface = st.empty()
        with surface.container(border=True):
            text = _issue_control(st.text_area, "Issue description", p + "_text", item.text,
                                  field, identity=identity, height=90, max_chars=4000)
            status = _issue_control(st.selectbox, "Issue status", p + "_status", item.status,
                                    field, identity=identity, options=ISSUE_STATUSES, format_func=_status_label)
            item = replace(item, text=text, status=status)
            warnings = st.empty()
            removed = st.button("Remove from this report", key=p + "_remove")
            if removed:
                item = replace(item, included=False)
        if removed:
            surface.empty()
        evidence_controls[len(items)] = (p, warnings)
        items.append(item)
    if evidence_controls or evidence_pages:
        needs_evidence = any(items[n].included and items[n].status in ("updated", "resolved")
                             for n in evidence_controls)
        with st.expander("Evidence", expanded=needs_evidence):
            for n, (p, warnings) in evidence_controls.items():
                item = items[n]
                evidence_surface = st.empty()
                with evidence_surface.container(border=True):
                    label = " ".join(item.text.split()) or "Unfinished issue"
                    st.caption("Issue: " + (label if len(label) <= 120 else label[:117] + "…"))
                    # A Remove click can deliver the last native evidence edit
                    # in the same packet. Read it before retiring the controls;
                    # omission must preserve that wording and its source links.
                    item = _render_issue_evidence(item, draft, options, p, field, prefix)
                if not item.included:
                    evidence_surface.empty()
                else:
                    with warnings.container():
                        for message in problems(item, draft):
                            st.warning(message)
                items[n] = item
            draft = replace(draft, follow_ups=tuple(items))
            if evidence_pages:
                draft = evidence_pages(draft)
    else:
        draft = replace(draft, follow_ups=tuple(items))
    omitted = [item for item in draft.follow_ups if item.category == "issue" and not item.included]
    if omitted:
        with st.expander(f"Removed from this report ({len(omitted)})"):
            st.caption("Unresolved issues remain available for future reports.")
            visible = _visible_followup_keys(omitted, prefix + "_omitted_issues", "Removed issue page")
            for item in omitted:
                if item.key not in visible:
                    continue
                st.write(item.text or "Unfinished issue")
                st.caption(_status_label(item.status))
                if st.button("Include again", key=prefix + "_issue_restore_" + item.key):
                    draft = issue_visibility(draft, item.key, True)
    draft = draft if defer_actions else apply_issue_action(draft, prefix)
    return draft if defer_commit else acknowledge_followup_controls(draft, prefix)
