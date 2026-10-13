"""One report-scoped issue list; omission is not resolution or history deletion."""

from dataclasses import replace
from uuid import uuid4

from app.monthly_report_content_policy import table_price_columns
from app.monthly_report_followups import (
    ISSUE_STATUSES, _digest, _followup_text_items, _no_equipment_issues,
    _status_label, problems,
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
        references = tuple(dict.fromkeys(ref for ref in references
                            if not ref.startswith(("report-period:", "report-origin:", "docx:", _REMOVED_STATEMENT))))
        items.append(ReportFollowUp(key, "issue", text, draft.period.key,
                                    references=references))
    if len(items) > 200:
        raise ValueError("More than 200 issues/proposals need review; no items were discarded.")
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


def _issue_changed(key, before):
    import streamlit as st
    st.session_state[key + "_change"] = {"before": before, "value": st.session_state.get(key)}


def _issue_control(widget, label, key, value, field, **kwargs):
    """An untouched widget mirror cannot undo a replaced canonical issue."""
    import streamlit as st
    receipt = st.session_state.get(key + "_change")
    submitted = (isinstance(receipt, dict) and receipt.get("before") == value
                 and receipt.get("value") == st.session_state.get(key))
    if st.session_state.get(key, value) != value and not submitted:
        st.session_state[key] = value
    result = widget(label, key=field(key, value), on_change=_issue_changed,
                    args=(key, value), **kwargs)
    if submitted and result != value:
        return result
    st.session_state.pop(key + "_change", None)
    return value


def render_issue_cards(draft, prefix, field):
    import streamlit as st

    draft = canonical_issues(draft)
    options = {source_reference(source, n): f"{source.filename} · page {n}"
               for source in draft.sources for n in range(1, len(source.page_texts) + 1)}
    issues = [item for item in draft.follow_ups if item.category == "issue"]
    if st.button("Add issue", key=prefix + "_issue_add", disabled=len(draft.follow_ups) >= 200):
        item = ReportFollowUp("issue-" + uuid4().hex, "issue", "", draft.period.key)
        draft = replace(draft, follow_ups=(*draft.follow_ups, item))
        issues.append(item)
    if any(item.included for item in issues):
        if st.button("Clear issues from this report", key=prefix + "_issue_clear"):
            draft = clear_issues(draft)
            st.caption("Issue list cleared for this report. Their status and history are retained.")
    block = next((b for b in draft.blocks if b.key == "equipment_issues"), None)
    if block and block.text and not block.ai_written and not block.ai_paragraphs:
        st.text(block.text)
        if st.button("Remove no-issues statement", key=prefix + "_issue_statement_remove"):
            draft = remove_issue_statement(draft)
    items = []
    for original in draft.follow_ups:
        if original.category != "issue" or not original.included:
            items.append(original)
            continue
        item = original
        p = prefix + "_issue_" + item.key
        surface = st.empty()
        with surface.container(border=True):
            text = _issue_control(st.text_area, "Issue description", p + "_text", item.text,
                                  field, height=90, max_chars=4000)
            status = _issue_control(st.selectbox, "Issue status", p + "_status", item.status,
                                    field, options=ISSUE_STATUSES, format_func=_status_label)
            update, note, references = item.update, item.evidence_note, item.references
            with st.expander("Details and evidence", expanded=status in ("updated", "resolved")):
                update = _issue_control(st.text_area, "Issue update", p + "_update", update,
                                        field, height=90, max_chars=4000)
                if status in ("updated", "resolved") or note:
                    note = _issue_control(st.text_area, "Evidence or explanation for the status",
                                          p + "_note", note, field, height=90, max_chars=4000)
                if options or references:
                    selected = _issue_control(st.multiselect, "Supporting source pages",
                        p + "_sources_" + _digest(list(options)),
                        [ref for ref in references if ref in options], field,
                        options=list(options), format_func=options.get) if options else []
                    missing = tuple(ref for ref in references if ref not in options)
                    if missing:
                        st.warning("A supporting source changed or is missing.")
                        if st.checkbox("Remove unavailable source links",
                                       key=field(p + "_remove_missing_" + _digest(missing), False)):
                            missing = ()
                    references = (*selected, *missing)
                if item.carried_from != draft.period.key:
                    st.caption("Carried from " + item.carried_from)
            item = replace(item, text=text, status=status, update=update,
                           evidence_note=note, references=references)
            for message in problems(item, draft):
                st.warning(message)
            removed = st.button("Remove from this report", key=p + "_remove")
            if removed:
                item = replace(item, included=False)
        if removed:
            surface.empty()
        items.append(item)
    draft = replace(draft, follow_ups=tuple(items))
    omitted = [item for item in items if item.category == "issue" and not item.included]
    if omitted:
        with st.expander(f"Removed from this report ({len(omitted)})"):
            st.caption("Unresolved issues remain available for future reports.")
            for item in omitted:
                st.write(item.text or "Unfinished issue")
                st.caption(_status_label(item.status))
                if st.button("Include again", key=prefix + "_issue_restore_" + item.key):
                    draft = issue_visibility(draft, item.key, True)
    return draft
