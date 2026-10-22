"""One report-scoped issue list; omission is not resolution or history deletion."""

from dataclasses import asdict, replace
from uuid import uuid4

from app.monthly_report_content_policy import table_price_columns
from app.monthly_report_followups import (
    ISSUE_STATUSES, _digest, _followup_text_items, _no_equipment_issues,
    _status_label, problems, unique_followup_keys, followup_limit_message,
    _visible_followup_keys, MAX_INCLUDED_FOLLOWUPS, FOLLOWUP_PAGE_SIZE, output_followups,
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


def _issue_identity(draft, prefix, item):
    values = asdict(item)
    values.pop("reviewed_fingerprint", None)
    return _digest((_action_scope(draft, prefix), values))


def _issue_pending_key(prefix, item):
    return prefix + "_pending_issue_delivery_" + item.key


def _issue_fields(item, options):
    return (("text", item.text), ("status", item.status), ("update", item.update),
            ("note", item.evidence_note),
            ("sources_" + _digest(list(options)), [ref for ref in item.references if ref in options]))


def _acknowledge_issue_delivery(key, pending):
    import streamlit as st
    for receipt_key, receipt in pending["receipts"].items():
        if st.session_state.get(receipt_key) == receipt:
            st.session_state.pop(receipt_key, None)
    st.session_state.pop(key, None)


def acknowledge_issue_controls(draft, prefix):
    """Only the authoritative caller may acknowledge a just-rendered draft."""
    import streamlit as st
    for item in draft.follow_ups:
        key = _issue_pending_key(prefix, item)
        pending = st.session_state.get(key)
        if (item.category == "issue" and isinstance(pending, dict)
                and not pending.get("conflicted")
                and (pending["result"] == _issue_identity(draft, prefix, item)
                     or (replace(pending["after"], included=item.included) == item
                         and _issue_identity(draft, prefix, pending["after"]) == pending["result"]))):
            # A deferred Clear/Undo may change only inclusion after the issue
            # renderer. The authoritative row still contains every entered field.
            _acknowledge_issue_delivery(key, pending)


def _show_issue_delivery(key, pending):
    import streamlit as st
    with st.expander("Earlier issue edit (not applied)", key=key):
        st.caption("These entered details were not applied to the changed item or saved. "
                   "Compare them with the current issue before copying them.")
        item = pending["after"]
        labels = pending["source_labels"]
        details = [("Description", item.text), ("Status", _status_label(item.status)),
                   ("Update", item.update), ("Evidence", item.evidence_note)]
        details += [("Supporting source", labels.get(ref, ref)) for ref in item.references]
        st.code("\n\n".join(label + ": " + value for label, value in details if value),
                language=None, wrap_lines=True)


def _recover_rejected_source_deliveries(prefix, captured):
    """Keep a real delivered choice when its row changed before first capture.

    A retired/forged receipt token is never recovered as a new user action.
    These source-only records cannot apply anything to the canonical report.
    """
    import streamlit as st
    recovery_prefix = prefix + "_source_delivery_recovery_"
    for key in list(st.session_state):
        if (key in captured or not key.startswith(prefix + "_issue_")
                or "_sources_" not in key or not key.endswith("_change")):
            continue
        receipt = st.session_state.get(key)
        registration = st.session_state.get(key.removesuffix("_change") + "_delivery", {})
        if (isinstance(receipt, dict) and isinstance(receipt.get("token"), str)
                and receipt["token"] == registration.get("token")
                and isinstance(receipt.get("value"), list)
                and receipt["value"] == st.session_state.get(key.removesuffix("_change"))):
            st.session_state[recovery_prefix + _digest((key, receipt["identity"], receipt["value"]))] = receipt
            st.session_state.pop(key, None)
    for key in sorted(k for k in st.session_state if k.startswith(recovery_prefix)):
        receipt = st.session_state[key]
        with st.expander("Earlier source selection (not applied)", key=key):
            st.caption("The issue, report or sources changed before this choice arrived. "
                       "These entered links were not applied or saved; compare them before selecting them again.")
            labels = receipt.get("source_labels", {})
            st.code("\n".join(labels.get(ref, ref) for ref in receipt["value"])
                    or "The earlier choice cleared the supporting source selection.",
                    language=None, wrap_lines=True)


def _capture_issue_controls(draft, prefix, options):
    """Project delivered edits without mistaking a widget render for a commit.

    A source callback can advance from A to A+B before the enclosing workspace
    assigns A. Keep its exact before/after row until canonical acknowledgement,
    including co-delivered issue fields needed by the row identity guard.
    """
    import streamlit as st
    items, captured = [], set()
    current_keys = {_issue_pending_key(prefix, item) for item in draft.follow_ups if item.category == "issue"}
    for key in sorted(k for k in st.session_state if k.startswith(prefix + "_pending_issue_delivery_")):
        if key in current_keys or "_recovery_" in key:
            continue
        pending = st.session_state[key]
        if isinstance(pending, dict) and "after" in pending:
            pending = {**pending, "conflicted": True}
            st.session_state[key] = pending
            _show_issue_delivery(key + "_missing_row", pending)
    for original in draft.follow_ups:
        if original.category != "issue":
            items.append(original)
            continue
        item = original
        key = _issue_pending_key(prefix, item)
        for recovery_key in sorted(k for k in st.session_state if k.startswith(key + "_recovery_")):
            _show_issue_delivery(recovery_key, st.session_state[recovery_key])
        pending = st.session_state.get(key)
        receipts, reapplied = {}, False
        identity = _issue_identity(draft, prefix, item)
        if isinstance(pending, dict):
            captured.update(receipt_key for receipt_key, receipt in pending["receipts"].items()
                            if st.session_state.get(receipt_key) == receipt)
            if not pending.get("conflicted") and pending["result"] == identity:
                # The caller's INPUT now contains the edit, not merely a local
                # renderer return. Never retire a newer callback with it.
                _acknowledge_issue_delivery(key, pending)
                pending = None
            elif not pending.get("conflicted") and pending["identity"] == identity:
                item = pending["after"]
                receipts = dict(pending["receipts"])
                reapplied = True
            else:
                pending = {**pending, "conflicted": True}
                st.session_state[key] = pending
                _show_issue_delivery(key + "_conflict", pending)
        identity = _issue_identity(draft, prefix, item)
        changes = {}
        original_fields = dict(_issue_fields(original, options))
        original_identity = _issue_identity(draft, prefix, original)
        p = prefix + "_issue_" + item.key
        for suffix, current in _issue_fields(item, options):
            control = p + "_" + suffix
            receipt = st.session_state.get(control + "_change")
            registration = st.session_state.get(control + "_delivery", {})
            if not (isinstance(receipt, dict) and isinstance(receipt.get("token"), str)
                    and receipt["token"] == registration.get("token")
                    and receipt.get("value") == st.session_state.get(control)):
                continue
            matches = receipt.get("identity") == identity and receipt.get("before") == current
            # If interruption preceded this widget's registration, its live
            # callback still names the original row. Accept that exact baseline
            # too, never a retired token or an independently changed row.
            if not (matches or (reapplied and receipt.get("identity") == original_identity
                                and receipt.get("before") == original_fields[suffix])):
                continue
            value = receipt["value"]
            if suffix.startswith("sources_"):
                if not isinstance(value, list) or any(ref not in options for ref in value):
                    continue
                changes["references"] = (*value, *(ref for ref in item.references if ref not in options))
            elif isinstance(value, str):
                changes["evidence_note" if suffix == "note" else suffix] = value
            else:
                continue
            receipts[control + "_change"] = receipt
            captured.add(control + "_change")
        revised = replace(item, **changes)
        if receipts:
            captured.update(receipts)
            result = _issue_identity(draft, prefix, revised)
            receipts = {receipt_key: {**receipt, "result": result}
                        for receipt_key, receipt in receipts.items()}
            for receipt_key, receipt in receipts.items():
                st.session_state[receipt_key] = receipt
            if isinstance(pending, dict) and pending.get("conflicted"):
                st.session_state[key + "_recovery_" + pending["result"]] = pending
            st.session_state[key] = {
                "identity": _issue_identity(draft, prefix, original), "result": result,
                "after": revised, "receipts": receipts,
                "source_labels": dict(options),
            }
        items.append(revised)
    _recover_rejected_source_deliveries(prefix, captured)
    return replace(draft, follow_ups=tuple(items))


def _finish_issue_controls(draft, prefix, options, cycle):
    """Include deliberate unlink/omit actions without changing native IDs.

    These actions occur after their row's native fields. Finalize only callback
    registrations whose displayed before-value still equals the returned row;
    an interrupted earlier registration retains its already captured baseline.
    """
    import streamlit as st
    for item in draft.follow_ups:
        if item.category != "issue":
            continue
        identity = _issue_identity(draft, prefix, item)
        p = prefix + "_issue_" + item.key
        for suffix, current in _issue_fields(item, options):
            control = p + "_" + suffix
            registration = st.session_state.get(control + "_delivery")
            if (isinstance(registration, dict) and registration.get("cycle") == cycle
                    and registration.get("before") == current):
                st.session_state[control + "_delivery"] = {**registration, "identity": identity}
        key = _issue_pending_key(prefix, item)
        pending = st.session_state.get(key)
        if isinstance(pending, dict) and not pending.get("conflicted"):
            st.session_state[key] = {**pending, "after": item, "result": identity}
    return draft


def _issue_changed(key, before, identity, token):
    import streamlit as st
    registration = st.session_state.get(key + "_delivery", {})
    if registration.get("token") != token:
        return  # A retired callback cannot reopen an acknowledged receipt.
    st.session_state[key + "_change"] = {
        "identity": registration.get("identity", identity), "token": token,
        "before": before, "value": st.session_state.get(key),
        "source_labels": registration.get("source_labels", {}),
    }


def _issue_control(widget, label, key, value, field, *, identity, cycle, **kwargs):
    """An untouched widget mirror cannot undo a replaced canonical issue."""
    import streamlit as st
    receipt = st.session_state.get(key + "_change")
    registration = st.session_state.get(key + "_delivery", {})
    submitted = (isinstance(receipt, dict) and receipt.get("identity") == identity
                 and receipt.get("token") == registration.get("token")
                 and receipt.get("before") == value
                 and receipt.get("value") == st.session_state.get(key))
    captured = (isinstance(receipt, dict) and receipt.get("result") == identity
                and receipt.get("value") == value)
    if st.session_state.get(key, value) != value and not submitted:
        st.session_state[key] = value
    accepted_value = receipt["value"] if submitted else value
    if widget == st.text_area:
        kwargs["value"] = accepted_value
    elif widget == st.multiselect:
        # The Python mirror alone does not set a newly mounted native default.
        # Keep real selection and explicit clear consistent in both protocols.
        kwargs["default"] = accepted_value
    # A render is not acknowledgement. Capture is durable before registration,
    # so even interruption before the native delta is queued keeps this value.
    token = uuid4().hex
    st.session_state[key + "_delivery"] = {
        "identity": identity, "before": accepted_value, "token": token, "cycle": cycle,
        "source_labels": ({ref: kwargs["format_func"](ref) for ref in kwargs["options"]}
                          if widget == st.multiselect else {}),
    }
    result = widget(label, key=field(key, value), on_change=_issue_changed,
                    args=(key, accepted_value, identity, token), **kwargs)
    if submitted and result != value:
        return result
    if not captured:
        st.session_state.pop(key + "_change", None)
    return value


def _render_issue_evidence(item, draft, options, p, field, prefix, cycle):
    import streamlit as st
    identity = _issue_identity(draft, prefix, item)
    update = _issue_control(st.text_area, "Issue update", p + "_update", item.update,
                            field, identity=identity, cycle=cycle, height=90, max_chars=4000)
    note, references = item.evidence_note, item.references
    if item.status in ("updated", "resolved") or note:
        note = _issue_control(st.text_area, "Evidence or explanation for the status",
                              p + "_note", note, field, identity=identity, cycle=cycle, height=90, max_chars=4000)
    if options or references:
        selected = _issue_control(st.multiselect, "Supporting source pages",
            p + "_sources_" + _digest(list(options)),
            [ref for ref in references if ref in options], field,
            identity=identity, cycle=cycle, options=list(options), format_func=options.get) if options else []
        missing = tuple(ref for ref in references if ref not in options)
        if missing:
            notice = st.empty()
            if st.checkbox("Remove unavailable source links",
                           key=field(p + "_remove_missing_" + _digest(missing), False)):
                missing = ()
            else:
                notice.warning("A supporting source changed or is missing.")
        references = (*selected, *missing)
    if item.carried_from != draft.period.key:
        st.caption("Carried from " + item.carried_from)
    return replace(item, update=update, evidence_note=note, references=references)


def render_issue_cards(draft, prefix, field, *, defer_actions=False, evidence_pages=None):
    import streamlit as st

    draft = canonical_issues(draft)
    options = {source_reference(source, n): f"{source.filename} · page {n}"
               for source in draft.sources for n in range(1, len(source.page_texts) + 1)}
    draft = _capture_issue_controls(draft, prefix, options)
    cycle = uuid4().hex
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
        identity = _issue_identity(draft, prefix, item)
        # A placeholder emits an empty ancestor before rebuilding this card.
        # A queue flush between those messages replaces the native input node,
        # even when its widget key and acknowledged text have not changed.
        with st.container(border=True, key=p + "_card"):
            text = _issue_control(st.text_area, "Issue description", p + "_text", item.text,
                                  field, identity=identity, cycle=cycle, height=90, max_chars=4000)
            status = _issue_control(st.selectbox, "Issue status", p + "_status", item.status,
                                    field, identity=identity, cycle=cycle, options=ISSUE_STATUSES, format_func=_status_label)
            item = replace(item, text=text, status=status)
            warnings = st.empty()
            removed = st.button("Remove from this report", key=p + "_remove")
            if removed:
                item = replace(item, included=False)
                # Read the evidence edits delivered with this click below.
                # The normal post-commit refresh retires the controls only
                # after the complete draft and its recovery save were tried.
                st.session_state[prefix + "_period_editor_refresh"] = True
        evidence_controls[len(items)] = (p, warnings)
        items.append(item)
    if evidence_controls or evidence_pages:
        needs_evidence = any(items[n].included and items[n].status in ("updated", "resolved")
                             for n in evidence_controls)
        with st.expander("Evidence", expanded=needs_evidence):
            for n, (p, warnings) in evidence_controls.items():
                item = items[n]
                with st.container(border=True, key=p + "_evidence"):
                    label = " ".join(item.text.split()) or "Unfinished issue"
                    st.caption("Issue: " + (label if len(label) <= 120 else label[:117] + "…"))
                    # A Remove click can deliver the last native evidence edit
                    # in the same packet. Read it before retiring the controls;
                    # omission must preserve that wording and its source links.
                    item = _render_issue_evidence(item, draft, options, p, field, prefix, cycle)
                if item.included:
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
                    # Cards were drawn before this restoration. Use the normal
                    # post-commit refresh after the complete recovery attempt.
                    st.session_state[prefix + "_period_editor_refresh"] = True
    draft = draft if defer_actions else apply_issue_action(draft, prefix)
    return _finish_issue_controls(draft, prefix, options, cycle)
