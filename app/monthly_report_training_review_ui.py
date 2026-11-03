"""Native controls for retained Training originals, corrections and inclusion."""
from dataclasses import replace
from hashlib import sha256

import streamlit as st

from app import monthly_report_training_review_flow as flow
from app import monthly_report_sources as sources
from app.monthly_report_training_import import (
    training_tables, restore_training_review, training_review_record,
    confirm_training_word_layout,
)
from app.monthly_report_training import is_matrix_reference


def _queue(key, request, fields=()):
    st.session_state[key] = {**request, "values": {name: st.session_state.get(widget)
                                                  for name, widget in fields}}


def apply_request(draft, request):
    if request["scope"] != flow.scope(draft):
        raise ValueError("This Training action belongs to a different report or month.")
    source = next((s for s in draft.sources if s.id == request["source_id"]), None)
    if source is None or source.fingerprint != request["source"]:
        raise ValueError("The source changed. Reopen the current Training review.")
    value = flow.saved_review(draft, source, request["table"])
    if (flow.revision(value) if value else "") != request["expected"]:
        raise ValueError("The Training review changed. Your saved corrections are unchanged.")
    fields = request.get("values", {})
    action = request["action"]
    if action == "prepare":
        year = str(fields.get("year", "")).strip()
        if year and (len(year) != 4 or not year.isdigit()):
            raise ValueError("Enter a four-digit requirements source year, or leave it unknown.")
        value = flow.prepare_review(draft, source, request["table"], int(year) if year else None)
    elif action == "row":
        if (any(not isinstance(fields.get(name), str) for name in request["columns"])
                or type(fields.get("excluded")) is not bool
                or "historical" in fields and type(fields["historical"]) is not bool):
            raise ValueError("The Training fields were not delivered. Your saved source review is unchanged.")
        value = flow.change_row(draft, value, request["row"],
            {name: fields[name] for name in request["columns"]},
            excluded=bool(fields["excluded"]), historical=bool(fields.get("historical")))
    elif action == "year":
        year = str(fields.get("year", "")).strip()
        if len(year) != 4 or not year.isdigit():
            raise ValueError("Confirm a four-digit requirements source year.")
        old = restore_training_review(value["record"])
        if old.kind != "requirements" or value["published"]:
            raise ValueError("An included source year cannot be relabeled. Review a separate source instead.")
        rebuilt = flow.prepare_review(draft, source, request["table"], int(year))
        from app.monthly_report_training_import import correct_training_row
        review = restore_training_review(rebuilt["record"])
        review = replace(review, rows=tuple(replace(row, excluded=next(r.excluded for r in old.rows if r.key == row.key))
                                            for row in review.rows))
        for row in old.rows:
            changes = dict(row.corrections) or dict(zip(old.normalized_columns, row.values))
            review = correct_training_row(review, row.key, changes,
                expected_revision=review.revision, profile=draft.profile, period=draft.period)
        if old.native_layout_confirmed:
            review = confirm_training_word_layout(review, expected_revision=review.revision)
        value = {**value, "record": training_review_record(review)}
    elif action == "layout":
        if not fields.get("confirmed"):
            raise ValueError("Confirm the original Word table's layout before including its normalized rows.")
        review = restore_training_review(value["record"])
        review = confirm_training_word_layout(review, expected_revision=review.revision)
        value = {**value, "record": training_review_record(review)}
    elif action == "publish":
        return flow.publish_review(draft, value, expected_revision=request["expected"],
            expected_block=request["block"], carry_prior=bool(fields.get("carry_prior")),
            replace_source=bool(fields.get("replace_source")), replace_matrix=bool(fields.get("replace_matrix")))
    else:
        raise ValueError("Unknown Training source action.")
    return flow.store_review(draft, value, request["expected"])


def render_training_import(draft, blocks, prefix):
    if not draft.prepared_by.strip():
        return draft, blocks
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_editor import _signature
    draft = replace(draft, blocks=tuple(blocks.values()))
    key = prefix + "_training_import_" + flow.scope(draft)[:16]
    action_key = key + "_action"
    pending = st.session_state.pop(action_key, None)
    if pending:
        try:
            if pending["incarnation"] != _rich_text_scope(prefix):
                raise ValueError("The Training editor was reopened. Review this source again.")
            draft = apply_request(draft, pending)
            blocks = {b.key: b for b in draft.blocks}
            if pending["action"] == "publish":
                matrix_key = prefix + "_training_" + _signature((draft.profile.contract,
                    tuple(f.key for f in draft.profile.facilities), draft.period.key))
                st.session_state.pop(matrix_key + "_matrix_draft", None)
                st.session_state[matrix_key + "_generation"] = st.session_state.get(matrix_key + "_generation", 0) + 1
            st.session_state[prefix + "_period_editor_refresh"] = True
        except (ValueError, OSError, KeyError) as exc:
            st.warning(str(exc))
    with st.expander("Import Training from a saved source", expanded=False, key=key + "_open"):
        st.caption("Review original dates, people and known hours before including rows. Annual requirements and completed sessions remain separate.")
        with st.expander("Add a prior Training file", key=key + "_upload_open"):
            upload = st.file_uploader("Prior Training report or table", type=["docx", "csv", "xlsx"], key=key + "_file")
            confirmed = st.checkbox("This Training source belongs to the selected report sites", key=key + "_scope")
            if st.button("Add Training source", key=key + "_add", disabled=not upload or not confirmed):
                try:
                    raw = upload.getvalue()
                    if len(raw) > sources.MAX_FILE_BYTES:
                        raise ValueError("Choose a Training file within 30 MB.")
                    # Use the established decoder boundary, aggregate budgets,
                    # duplicate repair and rejected-byte cleanup. Malformed ZIP,
                    # CSV and document input must not tear down the current form.
                    contents, messages = sources.ingest_batch(draft.profile, ((upload.name, raw),),
                        tuple(sources.SourceContent(source) for source in draft.sources))
                    content = next((item for item in contents if item.source.sha256 == sha256(raw).hexdigest()), None)
                    if content is None:
                        raise ValueError(" ".join(messages) or "This Training source could not be read.")
                    from app.monthly_report_source_scope import correct_scope
                    source = correct_scope(content.source, draft.profile, tuple(site.key for site in draft.profile.facilities))
                    if not any(s.id == source.id for s in draft.sources):
                        draft = replace(draft, sources=(*draft.sources, source))
                    st.session_state[prefix + "_period_editor_refresh"] = True
                except (ValueError, OSError) as exc:
                    st.warning(str(exc))
        choices = [s for s in draft.sources if s.suffix in (".docx", ".csv", ".xlsx")]
        if not choices:
            st.info("Add a prior Training file above, or use an original already saved with this report.")
            return draft, blocks
        selected = st.selectbox("Training original", range(len(choices)),
            format_func=lambda n: choices[n].filename, key=key + "_source")
        source = choices[selected]
        try:
            tables = training_tables(flow.source_content(draft, source), draft.profile)
            if not tables:
                st.info("No eligible Training tables were found in this saved original.")
                return draft, blocks
            selected_table = st.selectbox("Source table", range(len(tables)),
                format_func=lambda n: f"Table {tables[n].number} · {len(tables[n].rows)} source rows",
                key=key + "_table_" + source.id)
            table = tables[selected_table]
            value = flow.saved_review(draft, source, table.number)
            base = {"scope": flow.scope(draft), "incarnation": _rich_text_scope(prefix),
                    "source_id": source.id, "source": source.fingerprint, "table": table.number,
                    "expected": flow.revision(value) if value else ""}
            local = key + "_" + source.id[:12] + "_" + str(table.number)
            if value is None:
                st.text("Original columns: " + " | ".join(table.columns))
                with st.form(local + "_prepare"):
                    year = local + "_year"
                    st.text_input("Requirements source year (leave unknown if unconfirmed)", value="", key=year)
                    st.form_submit_button("Review this Training table", on_click=_queue,
                        args=(action_key, {**base, "action": "prepare"}, (("year", year),)))
                return draft, blocks
            review = restore_training_review(value["record"])
            st.caption({"events": "Dated Training sessions", "requirements": "Annual staff requirements"}.get(review.kind, "Source mapping needs review"))
            for issue in review.issues:
                st.info(issue)
            if review.kind == "requirements" and not value["published"]:
                with st.form(local + "_year_review_" + review.revision[:12]):
                    year = local + "_confirmed_year_" + review.revision[:12]
                    st.text_input("Confirmed requirements source year", value=str(review.source_year or ""), key=year)
                    st.form_submit_button("Confirm requirements year", on_click=_queue,
                        args=(action_key, {**base, "action": "year"}, (("year", year),)))
            for number, cells, reason in review.unmatched:
                st.text(f"Unmatched source row {number}: {reason} · " + " | ".join(cells))
            if review.rows:
                st.dataframe([{"Source row": row.origin.row_number, **dict(zip(review.normalized_columns, row.values)),
                    "Completion evidence": row.status, "Review needed": "; ".join(row.issues), "Omitted": row.excluded,
                    "Historical": row.key in value["history"]} for row in review.rows], hide_index=True)
                chosen = st.selectbox("Training row to review", range(len(review.rows)),
                    format_func=lambda n: f"Source row {review.rows[n].origin.row_number} · {review.rows[n].values[0] or 'Unknown topic/person'}",
                    key=local + "_selected_row")
                row = review.rows[chosen]
                st.text("Original cells: " + " | ".join(row.origin.cells))
                fields = (*review.normalized_columns, "Completion status") if review.kind == "events" else review.normalized_columns
                with st.form(local + "_row_" + row.key + "_" + review.revision[:12]):
                    pairs = []
                    for n, name in enumerate(fields):
                        widget = local + "_cell_" + row.key + "_" + review.revision[:12] + "_" + str(n)
                        st.text_input(name, value=row.status if name == "Completion status" else row.values[n], key=widget)
                        pairs.append((name, widget))
                    omitted = local + "_omit_" + row.key + "_" + review.revision[:12]
                    st.checkbox("Omit this Training source row", value=row.excluded, key=omitted)
                    pairs.append(("excluded", omitted))
                    if review.kind == "events":
                        history = local + "_history_" + row.key + "_" + review.revision[:12]
                        st.checkbox("Include this older dated session as historical", value=row.key in value["history"], key=history)
                        pairs.append(("historical", history))
                    st.form_submit_button("Save Training row review", on_click=_queue,
                        args=(action_key, {**base, "action": "row", "row": row.key, "columns": fields}, pairs))
            if review.source.native_word and not review.native_layout_confirmed:
                with st.form(local + "_layout"):
                    checked = local + "_layout_checked"
                    st.checkbox("I reviewed the original Word table's merged cells and layout", key=checked)
                    st.form_submit_button("Confirm Training source layout", on_click=_queue,
                        args=(action_key, {**base, "action": "layout"}, (("confirmed", checked),)))
            block = blocks.get("training_summary")
            if block is not None:
                with st.form(local + "_include_" + flow.revision(value)[:12]):
                    pairs = []
                    decisions = []
                    if review.kind == "requirements" and review.source_year != draft.period.year:
                        decisions.append(("carry_prior", "Use older requirement names for this year; reset recorded statuses"))
                    if review.kind == "requirements" and any(is_matrix_reference(t.reference) for t in block.extra_tables):
                        st.caption("Current report requirements remain unchanged unless replacement is deliberately selected. Shared records stay unchanged.")
                        for t in block.extra_tables:
                            if is_matrix_reference(t.reference):
                                st.dataframe([dict(zip(t.columns, r)) for r in t.rows], hide_index=True)
                        decisions.append(("replace_matrix", "Replace this report's existing requirements with the reviewed requirements"))
                    raw_refs = (review.source.reference, "docx:" + review.source.source_sha256 + ":" + review.source.word_item_id)
                    if any(t.reference in raw_refs for t in block.extra_tables):
                        decisions.append(("replace_source", "Replace the existing source table with these reviewed rows once"))
                    for name, label in decisions:
                        widget = local + "_decision_" + name
                        st.checkbox(label, key=widget)
                        pairs.append((name, widget))
                    st.form_submit_button("Include reviewed Training rows", disabled=block.source == "Omit",
                        on_click=_queue, args=(action_key, {**base, "action": "publish", "block": block.fingerprint}, pairs))
                if value["published"]:
                    st.caption("These reviewed rows were included. Repeated inclusion preserves subsequent report edits and deletions.")
        except (ValueError, OSError, KeyError) as exc:
            st.warning(str(exc))
    return draft, blocks
