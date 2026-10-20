"""A small monthly workspace around the versioned report model."""

from dataclasses import asdict, replace
from contextlib import nullcontext
import re
from uuid import uuid4

import streamlit as st

from app import monthly_report_library as library
from app import monthly_report_active_work as active_work
from app.config import operator_today
from app.memory import (record_report_preferences, record_report_preparer,
                        remembered_report_preferences, remembered_report_preparer)
from app.monthly_report_checks import preflight
from app.monthly_report_docx import estimate_bytes, generate_report, normalize_report_image
from app.monthly_report_editor import _grid, _signature, _typed_table
from app.monthly_report_model import (ReportDraft, ResolvedBlock, STOCK_TEXTS,
                                     layout_blocks, profile_sections)
from app.monthly_report_setup import MONTHLY_BLOCKS, merge_blocks, month_selector, new_month_draft, suggested_period
from app.monthly_report_section_help import section_help

# UI location is separate from next-month clearing: issues and renewal plans carry forward.
MONTHLY_EDIT_KEYS = MONTHLY_BLOCKS | {"equipment_issues", "utility_analysis", "capital_renewal", "end_of_life", "proposals", "rfi_matrix", "mbcx_status"}

STEPS = ("1 · Report", "2 · This month’s work", "3 · Site information", "4 · Review & download")


def _monthly_specs(section):
    # Capacity is standing data but belongs beside utility results in the UI.
    # This routing must not change rollover or standing-review semantics.
    return tuple(b for b in section.blocks if b.key in MONTHLY_EDIT_KEYS or section.key == "scorecards")


def _standing_specs(section):
    monthly = {b.key for b in _monthly_specs(section)}
    return tuple(b for b in section.blocks if b.key not in monthly)


def _rich_text_scope(prefix):
    """Bind callbacks to this report incarnation, including isolated resets."""
    epoch = st.session_state.setdefault(prefix + "_rich_text_epoch", uuid4().hex)
    # The durable journal receives its first generation *after* widgets render,
    # and a successful export can rotate that journal while keeping this editor.
    # Its save generation is therefore not an editor incarnation. The local
    # epoch rotates on import/restart, and a QA reset also clears that epoch.
    return _signature((prefix, epoch, st.session_state.get("_monthly_qa_generation", "")))


def _edited_rich_text(block, text):
    return replace(block, source="This month", text=text,
                   reviewed_fingerprint="", client_reviewed_fingerprint="")


def _rich_text_editor_key(prefix, block):
    # Callback arguments alone cannot identify a delayed browser value: the
    # framework applies incoming widget state BEFORE invoking its currently
    # registered callback. Give a reset/import a distinct native widget ID.
    # Ordinary edits, journal writes, preview reruns and geometry keep this key.
    return (prefix + "_edit_" + block.key + "_text_" +
            _signature((block.references, _rich_text_scope(prefix))))


def _mark_explicit_rich_text_edit(marker, widget_key, block, scope, *, preserve_clear_undo=False):
    """Capture the exact submission and the version the operator edited.

    A string alone cannot distinguish an interrupted edit from a stale edit
    after an import or reset. Replay is allowed only against this baseline.
    """
    text = st.session_state.get(widget_key)
    if (block.key == "activity_summary"
            and st.session_state.get("_monthly_report_storage_mode") == "isolated"):
        # Only the explicitly synthetic route emits these bounded metadata
        # receipts. A failed live regression must show what the callback saw,
        # not merely that the final draft unexpectedly became empty.
        from hashlib import sha256
        events = list(st.session_state.get("monthly_qa_activity_callbacks", ()))
        events.append({"widget": _signature(widget_key), "scope": scope,
                       "baseline": block.fingerprint,
                       "before": sha256(block.text.encode()).hexdigest(),
                       "after": sha256(text.encode()).hexdigest() if isinstance(text, str) else "missing"})
        st.session_state["monthly_qa_activity_callbacks"] = tuple(events[-8:])
    if not isinstance(text, str):
        # A removed/uninitialized widget is not an intentional empty edit.
        return
    undo = st.session_state.get(marker + "_clear_undo")
    if not preserve_clear_undo and isinstance(undo, dict) and undo.get("scope") == scope:
        # The same empty fingerprint can recur after deliberate later edits.
        # Equality must not resurrect an earlier destructive-action receipt.
        st.session_state.pop(marker + "_clear_undo", None)
    previous = st.session_state.get(marker)
    receipt = {
        "text": text, "baseline": block.fingerprint,
        "result": _edited_rich_text(block, text).fingerprint, "scope": scope,
    }
    if (isinstance(previous, dict) and previous.get("scope") == scope
            and previous.get("result") == block.fingerprint
            and isinstance(previous.get("baseline"), str)):
        # The shown edit can receive another native action before the full
        # render commits it. Retain only its exact uncommitted parent, never
        # permission to replace an unrelated newer canonical revision.
        receipt["previous_baseline"] = previous["baseline"]
    st.session_state[marker] = receipt


def _rich_text_receipt_matches(receipt, block):
    return block.fingerprint in (receipt.get("baseline"), receipt.get("previous_baseline"))


def _clear_rich_text_for_this_report(marker, widget_key, block, scope, prefix):
    """Explicit report-only empty edit; obey the same revision/epoch receipt guard.

    The native multiline widget can require an explicit apply gesture after
    editing. This separate action gives the operator a deliberate one-click
    clear without touching original evidence or saved shared report history.
    """
    if _rich_text_scope(prefix) != scope:
        return  # A stale tab cannot clear a different imported/reset report.
    prior_text = st.session_state.get(widget_key, block.text)
    if isinstance(prior_text, str) and prior_text:
        st.session_state[marker + "_clear_undo"] = {
            "text": prior_text, "scope": scope, "token": uuid4().hex,
            "cleared": _edited_rich_text(block, "").fingerprint,
        }
    st.session_state[widget_key] = ""
    _mark_explicit_rich_text_edit(marker, widget_key, block, scope, preserve_clear_undo=True)
    if isinstance(prior_text, str) and prior_text:
        st.session_state[marker]["clear_previous"] = prior_text


def _undo_rich_text_clear(marker, widget_key, block, scope, prefix, token):
    undo = st.session_state.get(marker + "_clear_undo")
    if (not isinstance(undo, dict) or undo.get("token") != token
            or undo.get("scope") != scope or _rich_text_scope(prefix) != scope
            or undo.get("cleared") != block.fingerprint
            or st.session_state.get(widget_key) != block.text):
        return
    st.session_state[widget_key] = undo["text"]
    _mark_explicit_rich_text_edit(marker, widget_key, block, scope)
    st.session_state.pop(marker + "_clear_undo", None)


def _pending_rich_text_edit(prefix, block):
    """A delivered callback is newer input before the final draft assignment."""
    key = _rich_text_editor_key(prefix, block)
    receipt = st.session_state.get(key + "_explicitly_edited")
    if (isinstance(receipt, dict)
            and receipt.get("scope") == _rich_text_scope(prefix)
            and _rich_text_receipt_matches(receipt, block)
            and isinstance(receipt.get("text"), str)
            and receipt["text"] != block.text
            and receipt["text"] == st.session_state.get(key)):
        return _edited_rich_text(block, receipt["text"])
    return None


def _recover_rich_text_edit(marker, widget_key, block, scope):
    recovered = st.session_state.get(marker + "_recovery")
    if isinstance(recovered, dict) and recovered.get("scope") == scope:
        if recovered.get("text") == "" and recovered.get("clear_previous"):
            # Applying a refused Clear is a new, explicit operation against
            # the current wording. Its Undo must restore what this choice
            # removes, not the older wording from the refused operation.
            current_text = st.session_state.get(widget_key, block.text)
            if isinstance(current_text, str) and current_text:
                st.session_state[marker + "_clear_undo"] = {
                    "text": current_text, "scope": scope, "token": uuid4().hex,
                    "cleared": _edited_rich_text(block, "").fingerprint,
                }
        st.session_state[widget_key] = recovered["text"]
        _mark_explicit_rich_text_edit(marker, widget_key, block, scope,
                                     preserve_clear_undo=recovered.get("text") == "" and bool(recovered.get("clear_previous")))
        st.session_state.pop(marker + "_recovery", None)


def _dismiss_rich_text_recovery(key):
    st.session_state.pop(key, None)


def _render_rich_text_recovery(marker, widget_key, block, scope):
    recovery_key = marker + "_recovery"
    recovered = st.session_state.get(recovery_key)
    if not isinstance(recovered, dict):
        return
    if recovered.get("scope") != scope:
        st.session_state.pop(recovery_key, None)
        return
    # A stale full-render or import can leave a genuine interrupted draft
    # edit. Put the conflict beside its actual editor, never inside a collapsed
    # disclosure where a busy operator would miss a refused replacement.
    # Both values are read-only until an explicit revision-bound choice.
    with st.container(border=True):
        st.warning("Your earlier edit was interrupted by a newer version of this section. "
                   "Both versions are available here; nothing has been overwritten.")
        st.markdown("**Current wording (kept in this report)**")
        if block.text:
            st.code(block.text, language=None, wrap_lines=True)
        else:
            st.caption("The current section is empty.")
        st.markdown("**Interrupted wording (not applied)**")
        if recovered["text"]:
            st.code(recovered["text"], language=None, wrap_lines=True)
        else:
            st.caption("Your interrupted edit cleared this section.")
            if recovered.get("clear_previous"):
                st.markdown("**Wording retained from before Clear**")
                st.code(recovered["clear_previous"], language=None, wrap_lines=True)
        st.button("Apply interrupted edit", key=marker + "_apply_recovery",
                  on_click=_recover_rich_text_edit,
                  args=(marker, widget_key, block, scope))
        st.button("Keep current wording", key=marker + "_dismiss_recovery",
                  on_click=_dismiss_rich_text_recovery, args=(recovery_key,))


def _forget_block_widgets(prefix, keys):
    starts = tuple(prefix + "_edit_" + key + "_" for key in keys)
    for key in list(st.session_state):
        if key.startswith(starts):
            del st.session_state[key]
    st.session_state["report_draft_mirror"] = {
        key: value for key, value in st.session_state.get("report_draft_mirror", {}).items()
        if not key.startswith(starts)
    }


def _apply_prepared(draft, blocks, additions, incoming_specs, prefix):
    """Apply one reviewed batch atomically; leave the draft intact on conflict."""
    from app.monthly_report_setup import merge_report_block
    specs = {b.key: b for s in draft.sections for b in s.blocks}
    proposed = dict(blocks)
    try:
        for key, block in additions.items():
            incoming = incoming_specs.get(key, specs.get(key))
            if block.rows and blocks.get(key) and blocks[key].rows and specs.get(key) != incoming:
                raise ValueError("The existing table has different columns. Match the uploaded table headings to the current section and try again; nothing was replaced.")
            proposed[key] = merge_report_block(blocks.get(key), block, specs.get(key), incoming)
    except ValueError as exc:
        st.error(str(exc))
        st.caption("Nothing was added. Your current draft is retained; correct the source and try again.")
        return draft, blocks
    changed = {key for key in additions if proposed.get(key) != blocks.get(key)}
    _forget_block_widgets(prefix, changed)
    sections = tuple(replace(s, included=s.included or any(b.key in additions for b in s.blocks),
                             blocks=tuple(incoming_specs.get(b.key, b) if b.key in additions else b for b in s.blocks))
                     for s in draft.sections)
    return replace(draft, sections=sections), proposed


def review_destination(draft, block_key):
    follow_up = next((item for item in draft.follow_ups if item.key == block_key), None)
    if follow_up:
        block_key = "proposals" if follow_up.category == "proposal" else "equipment_issues"
    if block_key in {"cover", *(b.key for b in layout_blocks())}:
        return STEPS[0], None
    if block_key == "issues":
        block_key = "equipment_issues"
    section = next((s for s in draft.sections if any(b.key == block_key for b in s.blocks)), None)
    if section:
        if not section.included:
            return STEPS[0], None
        monthly = any(b.key == block_key for b in _monthly_specs(section))
        return STEPS[1] if monthly else STEPS[2], section.key
    return None, None


def review_message(check, draft):
    """Tell a manager what to do and where, without exposing model field IDs."""
    from app.monthly_report_sections import readable_label
    key = check.block_key
    source = next((source for source in draft.sources if source.id == key), None)
    if source is not None and check.code.startswith("source_"):
        target = "site" if check.code == "source_facility" else "date"
        label = "Correct site" if target == "site" else "Correct date"
        return check.message + f" [{label}](#source-details-{source.id}--{target})."
    follow_up = next((item for item in draft.follow_ups if item.key == key), None)
    if follow_up:
        category = "proposals" if follow_up.category == "proposal" else "equipment issues"
        return check.message.replace(key, category) + f" Check this item in {category.capitalize()} above."
    label = readable_label(key) if key else "this report"
    section = next((s.title for s in draft.sections if any(b.key == key for b in s.blocks)), "")
    location = section or "the report fields above"
    if key and not section:
        location = label
    if key in {"issues", "proposals"} and draft.follow_ups:
        location = "Equipment Performance Issues" if key == "issues" else "Pending & Declined Proposals"
    if check.code == "required":
        return f"Add {label.lower()} in {location}."
    if check.code in {"review", "ai_evidence", "ai_number"}:
        return f"Check the wording and linked evidence for {label.lower()} above, then confirm its review." + (" Correct any unsupported numbers." if check.code == "ai_number" else "")
    if check.code == "client_pages":
        return f"Review the new or changed pictures in {label} above and confirm they are relevant and have no prices. Unchanged reviewed pictures stay ready."
    if check.code == "library_save":
        return f"The shared replacement for {label.lower()} needs confirmation before it can be saved. Keep the existing saved content to continue."
    message = check.message
    if check.code == "carried_period":
        return f"{location} — {label}: {message} [Edit this section](#report-section-{review_destination(draft, key)[1] or 'cover'})."
    if key:
        message = message.replace(key, label).replace(key.replace("_", " "), label.lower())
    if check.code in {"placeholder", "pricing", "period"} and key:
        message += " Correct it in " + ("the cover details" if key == "cover" else location) + " above."
    return message


def generation_block_reason(*, conflict, checks, warnings_ok):
    """Explain the existing export gate without weakening it."""
    if conflict:
        return "Another version was saved. Compare the saved changes above and accept the current revision before generating."
    count = sum(bool(check.blocking) for check in checks)
    if count:
        noun = "item" if count == 1 else "items"
        return f"Resolve the {count} required {noun} listed above to enable Create Word and PDF."
    if not warnings_ok:
        return "Read the specific warnings above, then check ‘I checked these specific warnings’ to enable Create Word and PDF."
    return ""


def monthly_entries_by_section(draft):
    """Count substantive monthly inputs, not corporate furniture or blank grids.

    This is an advisory signal, not a content-approval or completion check.
    Contract defaults and old library text do not establish work this month.
    """
    from app.monthly_report_model import included_sections
    blocks = {block.key: block for block in draft.blocks}
    present = []
    for section in included_sections(draft.sections):
        for spec in section.blocks:
            if spec.key not in MONTHLY_EDIT_KEYS:
                continue
            block = blocks.get(spec.key)
            if block is None or block.source in ("Omit", "Library", "Stock text"):
                continue
            if (block.text.strip() or block.rows or block.asset_hashes
                    or block.org_nodes or any(table.rows for table in block.extra_tables)):
                present.append(section.key)
                break
    return tuple(present)


def _standing_signature(blocks, included):
    keys = included | {b.key for b in layout_blocks()}
    return _signature(sorted((b.key, b.fingerprint) for b in blocks
                             if b.key not in MONTHLY_EDIT_KEYS and b.key in keys))


def _initial_draft(state, period, prepared):
    blocks = []
    for spec in (*[b for s in profile_sections(state.profile) for b in s.blocks], *layout_blocks()):
        saved = state.block(spec.key)
        if saved:
            blocks.append(saved)
        elif spec.stock_text_keys:
            blocks.append(ResolvedBlock(spec.key, "Stock text", text=STOCK_TEXTS[spec.stock_text_keys[0]]))
        else:
            blocks.append(ResolvedBlock(spec.key, "This month" if spec.required else "Omit"))
    return ReportDraft(state.profile, period, prepared, profile_sections(state.profile), tuple(blocks))


def complete_guided_sections(draft):
    """Keep every standard section, including intentionally blank sections.

    Existing order, titles, imported schemas and content remain authoritative.
    Older partial designs gain the missing sections and standard block slots;
    this guided working copy never requires content just to retain a heading.
    """
    from app.monthly_report_model import default_sections, optional_sections
    native_order = (draft.profile.section_order if draft.profile.template.startswith(
        ("enfra_native:", "enfra_master:")) else ())
    optional_keys = {"rfi", *(section.key for section in optional_sections())}
    allowed = {section.key for section in default_sections() if section.key not in optional_keys}
    allowed.update(key for key in native_order if key in optional_keys)
    if not native_order:
        allowed.add("rfi")
        allowed.update(section.key for section in draft.sections if section.key in optional_keys)
    # The design owns optional sections and their position. Missing core
    # sections still remain available, including deliberately blank sections.
    order = tuple(dict.fromkeys((*native_order, *(section.key for section in draft.sections),
                                 *(section.key for section in default_sections()))))
    order = tuple(key for key in order if key in allowed)
    full_profile = replace(draft.profile, section_order=order, section_block_order=(), excluded_sections=())
    standard = {section.key: section for section in profile_sections(full_profile)}
    existing = {section.key: section for section in draft.sections}
    sections = []
    for key in order:
        section = existing.get(key, standard[key])
        present = {block.key for block in section.blocks}
        additions = tuple(block for block in standard[key].blocks if block.key not in present)
        sections.append(replace(section, included=True,
                                blocks=tuple(replace(block, required=False) for block in (*section.blocks, *additions))))
    return replace(draft, sections=tuple(sections))


def _review_carried_update(block, period, prefix):
    from app.monthly_report_setup import carried_period, confirm_current_period
    previous = carried_period(block, period)
    if previous is None:
        return block
    st.info(f"This update was carried from {previous.label}. Check its wording and any charts for {period.label} before including it.")
    if st.button(f"This update is correct for {period.label}", key=prefix + "_current_period_" + block.key + "_" + block.fingerprint):
        return confirm_current_period(block, period)
    return block


def _period_editor_transition(prefix, block, period):
    """Replay only an exact item decision if its full draft commit was interrupted."""
    key = prefix + "_period_transition_" + block.key
    pending = st.session_state.get(key)
    if not isinstance(pending, dict):
        return block
    if pending.get("scope") != (_rich_text_scope(prefix), period.key):
        st.session_state.pop(key, None)
        return block
    result = pending["result"]
    if result.fingerprint == block.fingerprint:
        st.session_state.pop(key, None)
        return block
    if block.fingerprint in pending.get("baselines", ()):
        st.session_state[prefix + "_period_editor_refresh"] = True
        return result
    st.session_state.pop(key, None)
    st.info("This dated item changed before its earlier choice finished. Review the current wording again.")
    return block


def _record_period_editor_transition(prefix, canonical_before, before, after, period, editor_key):
    if before == after:
        return after
    st.session_state[prefix + "_period_transition_" + before.key] = {
        "scope": (_rich_text_scope(prefix), period.key),
        "baselines": (canonical_before.fingerprint, before.fingerprint), "result": after,
    }
    # The item operation includes the current manual edit. Its former text
    # callback must not restore the pre-decision value if this editor key returns.
    st.session_state.pop(editor_key + "_explicitly_edited", None)
    st.session_state[prefix + "_period_editor_refresh"] = True
    return after


def _refresh_period_editors_after_commit(prefix):
    # Business actions may change visible wording; refresh only after the whole
    # canonical draft and its recovery attempt completed, never mid-editor.
    if st.session_state.pop(prefix + "_period_editor_refresh", False):
        st.rerun()


def _has_request_rows(block):
    from app.monthly_report_table_entry_ui import has_rows
    return has_rows(block)


def _edit_content(spec, block, state, prefix, assets, field, draft=None, *, edit_text=True,
                  manage_saved_pictures=True, inline_photo_intake=False):
    if draft is not None and spec.type == "image_grid":
        from app.monthly_report_visual_ui import edit_photos
        return edit_photos(draft, block, prefix, assets, field, show_preview=False)
    key = prefix + "_edit_" + spec.key
    edit_tables = True
    request_notice = None
    from app.monthly_report_table_entry_ui import EMPTY_TABLES, empty_text_seed, entry_open, has_values
    optional_table = spec.key in EMPTY_TABLES
    if optional_table and (spec.type in ("table", "work_order_grid") or block.extra_tables):
        # A fresh report shows an honest empty state. Add opens the
        # existing native grid; an empty editor slot is never report content.
        # Reset/import/source replacement receives different native IDs while
        # ordinary row edits keep the same mounted editor and input seed.
        key += "_" + _signature((_rich_text_scope(prefix), block.references,
                                 tuple(table.reference for table in block.extra_tables)))
        request_notice = st.empty()
        edit_tables = entry_open(block, key)
    # Source-linked text has its own evidence-aware editor above. Do not echo a
    # competing read-only copy below that editor or add a second text control.
    if spec.type not in ("rich_text", "stock_text") and block.text.strip() and not block.ai_paragraphs:
        retained_mbcx = spec.key == "mbcx_report"
        notes_label = ("Retained page notes (left out)" if block.source == "Omit"
                       else "Page notes included in this report") if retained_mbcx else "Notes included in this section"
        notes_scope = (block.references, _rich_text_scope(prefix)) if retained_mbcx else block.references
        notes = st.text_area(notes_label, key=field(key + "_notes_" + _signature(notes_scope), block.text),
                             height=120, **({"value": block.text} if retained_mbcx else {}))
        if notes != block.text:
            source = "Omit" if retained_mbcx and block.source == "Omit" else "This month"
            block = replace(block, source=source, text=notes, reviewed_fingerprint="", client_reviewed_fingerprint="")
    if block.extra_tables and edit_tables:
        from app.monthly_report_editor import _cell_text
        tables = []
        for n, table in enumerate(block.extra_tables):
            from app.monthly_report_table_review_ui import review_table_headings
            table = review_table_headings(table, key + f"_imported_{n}", field)
            if len(block.extra_tables) > 1:
                st.write(f"Table {n+1}")
            seed = [dict(zip(table.columns, r)) for r in table.rows] or [dict.fromkeys(table.columns)]
            if optional_table:
                seed = empty_text_seed(seed)
            rows = _grid(key + f"_imported_{n}_" + _signature(table.columns), seed, num_rows="dynamic", hide_index=True)
            # Opening a blank imported frame must retain its original
            # structure/reference without pretending its editor slot is data.
            edited_rows = tuple(tuple(_cell_text(r.get(c)) for c in table.columns) for r in rows
                                if any(v is not None and (str(v).strip() if optional_table else v != "") for v in r.values()))
            tables.append(table if optional_table and (rows == seed or not edited_rows and not has_values(table.rows))
                          else replace(table, rows=edited_rows))
        if optional_table and tuple(tables) != block.extra_tables:
            block = replace(block, source="This month", extra_tables=tuple(tables),
                            reviewed_fingerprint="", client_reviewed_fingerprint="")
        else:
            block = replace(block, extra_tables=tuple(tables))
    if spec.type in ("rich_text", "stock_text") and block.ai_paragraphs:
        # The authoritative source-linked text editor is rendered earlier.
        pass
    elif spec.type in ("rich_text", "stock_text") and edit_text:
        canonical_before = block
        if draft is not None and not block.ai_written:
            block = _period_editor_transition(prefix, block, draft.period)
        editor_key = _rich_text_editor_key(prefix, block)
        changed_marker = editor_key + "_explicitly_edited"
        scope = _rich_text_scope(prefix)
        displayed = st.session_state.get(editor_key, block.text)
        receipt = st.session_state.get(changed_marker)
        valid = (isinstance(receipt, dict) and isinstance(receipt.get("text"), str)
                 and receipt.get("scope") == scope)
        if valid and receipt.get("result") == block.fingerprint:
            # Acknowledge the exact resulting block, not merely equal wording.
            st.session_state.pop(changed_marker, None)
            receipt = None
            valid = False
        submitted = (valid and _rich_text_receipt_matches(receipt, block)
                     and receipt["text"] == displayed)
        if valid and not submitted:
            # Do not overwrite newer content or lose the interrupted operator
            # input. Recovery is report-scoped and requires an explicit choice.
            st.session_state[changed_marker + "_recovery"] = receipt
        if displayed != block.text and not submitted:
            # A rerun after generation, preview or browser hydration can mount
            # obsolete text. Only an unacknowledged exact on_change receipt
            # permits changing canonical text. A genuine clear has a receipt
            # and therefore remains a valid edit.
            st.session_state[editor_key] = block.text
        if submitted:
            # Bind every control below to the wording actually being shown.
            # Registering against the pre-edit block makes the next Clear or
            # textarea callback look stale even after this edit is committed.
            # Keep an exact receipt until the authoritative draft agrees, and
            # collapse any delivered parent chain to this canonical baseline.
            receipt = {**receipt, "baseline": block.fingerprint}
            receipt.pop("previous_baseline", None)
            st.session_state[changed_marker] = receipt
            block = _edited_rich_text(block, receipt["text"])
        else:
            # A mismatched/old receipt never authorizes a later overwrite.
            st.session_state.pop(changed_marker, None)
        editor_anchor = "report-editor-" + spec.key
        if draft is not None:
            from html import escape
            st.markdown('<span id="' + escape(editor_anchor, quote=True) + '"></span>', unsafe_allow_html=True)
        from app.monthly_report_native_loading import reserve_text_area
        reserve_text_area(editor_key, 140)
        st.text_area(
            spec.key.replace("_", " ").capitalize(),
            # The native protocol default must agree with the actual draft.
            # A new browser mount initially reads this field; relying solely
            # on a one-shot set_value leaves an empty value it can echo on a
            # later unrelated button/fragment request. In pinned 1.61.1 a keyed
            # text area's ID excludes value (only max_chars is whitelisted),
            # so changing this default does not remount or reset current input.
            value=block.text,
            key=field(editor_key, block.text), height=140,
            on_change=_mark_explicit_rich_text_edit,
            args=(changed_marker, editor_key, block, scope))
        if spec.key == "activity_summary":
            st.button(
                "Clear Activity for this report",
                # A reused native button ID can retain an obsolete widget
                # action after multiple edit/clear/re-entry reruns. Bind the
                # control to the exact current block as well as report epoch,
                # just as shared fixture actions bind their original SHA.
                key=prefix + "_clear_activity_report_" + _signature((scope, block.fingerprint)),
                disabled=(not block.text and not displayed),
                help="Clears only this working report's Activity wording, not source files, older report versions or standing information.",
                on_click=_clear_rich_text_for_this_report,
                args=(changed_marker, editor_key, block, scope, prefix),
            )
            undo = st.session_state.get(changed_marker + "_clear_undo")
            if (isinstance(undo, dict) and undo.get("scope") == scope
                    and undo.get("cleared") == block.fingerprint):
                st.button("Undo Clear Activity", key=changed_marker + "_undo_clear_" + undo["token"],
                          help="Restores the wording removed by this Clear in this report only. Later edits are kept.",
                          on_click=_undo_rich_text_clear,
                          args=(changed_marker, editor_key, block, scope, prefix, undo["token"]))
        _render_rich_text_recovery(changed_marker, editor_key, block, scope)
        if draft is not None and not block.ai_written:
            from app.monthly_report_period_items_ui import render_period_items
            section_title = next((section.title for section in draft.sections
                                  if any(item.key == spec.key for item in section.blocks)),
                                 spec.key.replace("_", " ").capitalize())
            resolved = render_period_items(block, draft.period, draft.sources, prefix,
                section_title=section_title, editor_anchor=editor_anchor)
            block = _record_period_editor_transition(prefix, canonical_before, block, resolved, draft.period, editor_key)
    elif edit_tables and spec.type in ("table", "work_order_grid") and (block.rows or not block.extra_tables):
        seed, config = _typed_table(spec, block.rows)
        if optional_table:
            seed = empty_text_seed(seed, spec)
        rows = _grid(key + "_table_" + _signature(asdict(spec)), seed, num_rows="dynamic", hide_index=True, column_config=config)
        from app.monthly_report_editor import _cell_text
        columns = [c.title for c in spec.columns] or ["Facility", "Item", "Status"]
        edited_rows = tuple(tuple(_cell_text(row.get(c)) for c in columns) for row in rows
                            if any(v is not None and (str(v).strip() if optional_table else v != "") for v in row.values()))
        if (rows != seed and edited_rows != block.rows
                and (not optional_table or edited_rows or has_values(block.rows))):
            block = replace(block, source="This month", rows=edited_rows, reviewed_fingerprint="", client_reviewed_fingerprint="")
    if (request_notice is not None and not edit_tables and not _has_request_rows(block)
            and not (block.text.strip() or block.asset_hashes or block.org_nodes or block.ai_paragraphs)):
        # A deliberately opened draft slot replaces the empty-state sentence;
        # its blank cells are still not report content.
        request_notice.caption(EMPTY_TABLES[spec.key][0])
    if block.asset_hashes and manage_saved_pictures:
        from app.monthly_report_saved_pictures_ui import edit_saved_pictures
        block = edit_saved_pictures(block, key, lambda ref: assets.get(ref) or library.read_asset(state.profile.contract, state.profile.key, ref), show_preview=False)
    if spec.type in ("rich_text", "stock_text", "table", "work_order_grid"):
        if spec.key in ("training_summary", "equipment_issues"):
            with nullcontext() if inline_photo_intake else st.expander("Add a supporting photo (optional)"):
                photo = st.file_uploader("Photo to add to this section", type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_add_photo")
                if photo and st.button("Add this photo", key=key + "_add_photo_save"):
                    from pathlib import Path
                    try:
                        normalized = normalize_report_image(photo.getvalue(), Path(photo.name).suffix)
                        reference = library.asset_reference(normalized.data, normalized.extension)
                        assets[reference] = normalized.data
                        from app.monthly_report_asset_instances import append_human_asset
                        block = append_human_asset(block, reference)
                    except (ValueError, OSError):
                        st.error("This photo could not be read. Choose another image; the existing section is retained.")
        return block
    from app.monthly_report_sections import readable_label
    if spec.type == "pdf_pages":
        replacing_pages = bool(block.asset_hashes)
        with st.expander("Replace this section’s attached pages" if replacing_pages else "Add report pages"):
            if replacing_pages:
                st.caption(f"Replaces {len(block.asset_hashes)} attached {'page' if len(block.asset_hashes) == 1 else 'pages'} in {readable_label(spec.key)} with one image. Other sections and saved originals stay unchanged.")
            upload = st.file_uploader(("Replacement image for " if replacing_pages else "Image page for ") + readable_label(spec.key), type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_image")
    else:
        upload = st.file_uploader("Upload a new " + readable_label(spec.key).lower(), type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_image")
    adding_page = spec.type == "pdf_pages" and not block.asset_hashes
    if upload and st.button("Add page to this report" if adding_page else "Use this replacement in this report", key=key + "_replace"):
        from pathlib import Path
        image = normalize_report_image(upload.getvalue(), Path(upload.name).suffix,
                                       line_art=spec.key in ("org_chart", "contact_matrix", "business_hours_workflow", "after_hours_workflow"))
        reference = library.asset_reference(image.data, image.extension)
        assets[reference] = image.data
        previous = block
        from app.monthly_report_asset_instances import new_asset_instance, with_asset_instances
        block = with_asset_instances(replace(block, source="Replace once", asset_hashes=(reference,),
            asset_captions=(), references=(), client_asset_reviews=(), reviewed_fingerprint="",
            client_reviewed_fingerprint=""), (new_asset_instance(reference),))
        if spec.type == "pdf_pages":
            st.session_state[key + "_replacement_undo"] = (block.fingerprint, previous)
        st.image(image.data, width="stretch", caption="Added page in this report" if adding_page else "Updated image in this report")
    undo = st.session_state.get(key + "_replacement_undo") if spec.type == "pdf_pages" else None
    if undo:
        unchanged = block.fingerprint == undo[0]
        if st.button("Undo attached-page replacement" if undo[1].asset_hashes else "Undo added page", key=key + "_undo_replacement_" + undo[0],
                     disabled=not unchanged,
                     help="Restores this section’s previous pages. Unavailable after another edit changes this section."):
            block = undo[1]
            st.session_state.pop(key + "_replacement_undo", None)
    return block


def activity_from_sources(sources, existing):
    """Append reviewed action fields only. Recommendations are not completed work."""
    from app.monthly_report_sources import action_evidence, source_reference
    text, references = [], []
    for source in sources:
        if source.classification not in ("Vendor service", "Water treatment"):
            continue
        accepted, _ = action_evidence(source)
        for line, pages in accepted:
            refs = tuple(source_reference(source, n) for n in pages)
            action = ": ".join(v for v in (source.vendor, line) if v)
            action = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[contact omitted]", action)
            action = re.sub(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)", "[contact omitted]", action)
            rendered = "- " + action.strip()
            if rendered in existing.text.splitlines() and all(r in existing.references for r in refs):
                continue
            text.append(rendered)
            references.extend(refs)

    return merge_blocks(existing, ResolvedBlock("activity_summary", "This month", text="\n".join(text), references=tuple(references)))


def client_table_draft(draft):
    """Edit a price-free copy; saved history and non-table wording stay intact."""
    from app.monthly_report_content_policy import price_free_table
    blocks = {b.key: b for b in draft.blocks}
    sections, removed = [], []
    for section in draft.sections:
        specs = []
        for spec in section.blocks:
            if spec.key in blocks:
                spec, blocks[spec.key], labels = price_free_table(spec, blocks[spec.key])
                removed.extend(labels)
            specs.append(spec)
        sections.append(replace(section, blocks=tuple(specs)))
    return replace(draft, sections=tuple(sections), blocks=tuple(blocks.values())), tuple(dict.fromkeys(removed))


def _render_ordered_section(draft, section, blocks, specs, state, prefix, assets, field):
    """Edit one report section without splitting standing and monthly content."""
    # Reserve the writing position before source tools. Populate it after
    # source callbacks have been reconciled so one native editor sees the
    # current result without changing the established mutation order.
    writing = st.container(key=prefix + "_activity_writing") if section.key == "activity" else None
    if section.key in {"organization", "subcontractors", "training"} and not draft.prepared_by.strip():
        st.info("Enter Prepared by above to view or edit saved contact and team information.")
        return draft, blocks
    # A source-acceptance callback is delivered before widgets redraw. Use
    # this report's identity + the exact block revision the user reviewed;
    # stale clicks from another month/site or changed manual edits cannot
    # overwrite newer content.
    if section.key == "activity":
        request = st.session_state.pop(prefix + "_pending_accepted_workorders", None)
        if request:
            current = blocks.get("activity_summary", ResolvedBlock("activity_summary", "This month"))
            matches = (request["contract"] == draft.profile.contract
                       and request["profile"] == draft.profile.key
                       and request["month"] == draft.period.key
                       and any(source.id == request["source_id"]
                               and request["reference"].split(":")[-1] == source.fingerprint
                               for source in draft.sources))
            if (matches and request["expected"] == current.fingerprint
                    and not _pending_rich_text_edit(prefix, current)):
                if request["text"] not in current.text:
                    updated = replace(current, source="This month",
                        text="\n\n".join(filter(None, (current.text.strip(), request["text"]))),
                        references=tuple(dict.fromkeys((*current.references, request["reference"],
                                                        *([request["scope_receipt"]] if request.get("scope_receipt") else [])))),
                        reviewed_fingerprint="", client_reviewed_fingerprint="")
                    blocks["activity_summary"] = updated
                    _forget_block_widgets(prefix, {"activity_summary"})
            else:
                st.warning("The report changed after you reviewed the work-order totals. "
                           "Your edits are unchanged. Review the file and select Add again.")
    from app.monthly_report_sections import readable_label
    draft = replace(draft, blocks=tuple(blocks.values()))
    profile, period = draft.profile, draft.period
    destination = {"activity": "activity_summary", "capital": "capital_renewal", "proposals": "proposals"}.get(section.key)
    if destination:
        from app.monthly_report_upload_ui import render_structured_uploads
        from app.monthly_report_structured_uploads import COLUMNS as STANDARD_COLUMNS
        native_spec = next((b for s in draft.sections for b in s.blocks if b.key == destination), None)
        selected_columns = tuple(c.title for c in native_spec.columns) if native_spec and native_spec.columns else ()
        custom_columns = selected_columns if selected_columns and selected_columns != STANDARD_COLUMNS[destination] else None
        sources, additions, incoming_specs = render_structured_uploads(
            profile, period, prefix, field, destination, blocks=blocks, assets=assets,
            table_columns=custom_columns)
        draft = replace(draft, sources=_keep_missing_sources(prefix, sources))
        if additions:
            # Structured readers return the updated destination block; their
            # attachment assets alone are incremental. Never append the prior
            # text/table a second time when applying a later upload.
            for key, block in additions.items():
                blocks[key] = merge_blocks(blocks.get(key), block) if key == "improvements" else block
            _forget_block_widgets(prefix, additions)
    local_destination = {"water": "water_reports", "mbcx": "mbcx_report", "scorecards": "utility_analysis"}.get(section.key)
    if local_destination:
        from app.monthly_report_upload_ui import render_section_uploads
        sources, additions, incoming_specs = render_section_uploads(
            profile, period, prefix, field, local_destination, blocks=blocks, assets=assets)
        draft = replace(draft, sources=_keep_missing_sources(prefix, sources))
        if additions:
            draft, blocks = _apply_prepared(draft, blocks, additions, incoming_specs, prefix)
            if local_destination == "water_reports":
                # A completed page-review receipt is consumed only after the
                # additions are present in the current draft. This prevents
                # an intentionally removed page from silently reappearing.
                from app.monthly_report_upload_ui import acknowledge_autoincluded_water_pages
                acknowledge_autoincluded_water_pages(prefix, blocks)
    if section.key == "activity":
        from app.monthly_report_source_manager_ui import render_guided_source_manager
        # Vendor originals use this existing page-by-page manager. A second
        # section-upload panel would expose competing controls for the same
        # source and caption. The manager keeps the Activity destination and
        # its atomic, repeat-safe preparation path.
        draft, blocks = render_guided_source_manager(
            draft, blocks, prefix, field, _apply_prepared, _keep_missing_sources)
        from app.monthly_report_ai_ui import render_drafting
        # One shared evidence workspace: rendering this once avoids duplicated
        # source/job widget identities when every report section is visible.
        draft, blocks = render_drafting(draft, blocks, prefix, field,
            allowed_keys={spec.key for spec in section.blocks}, editor_container=writing)
    if section.key != "activity":
        from app.monthly_report_ai_ui import edit_linked_paragraphs
        blocks = edit_linked_paragraphs(draft, blocks, prefix, field, {spec.key for spec in section.blocks})
    specs.update({b.key: b for current in draft.sections for b in current.blocks})
    handled = set()
    if section.key == "issues":
        from app.monthly_report_issues import render_issue_cards
        def edit_issue_pages(current):
            current_blocks = {block.key: block for block in current.blocks}
            for block_key, label in (("equipment_issues", "Section photos"),
                                     ("equipment_issues_evidence", "Attached section evidence pages")):
                if block_key not in specs:
                    continue
                block = current_blocks.get(block_key, ResolvedBlock(block_key, "This month"))
                st.markdown("**" + label + "**")
                if block_key == "equipment_issues":
                    st.caption("These photos belong to the section. Supporting source links above belong to the named issue.")
                block = _review_carried_update(block, period, prefix)
                current_blocks[block_key] = _edit_content(specs[block_key], block, state,
                    prefix, assets, field, current, edit_text=False, inline_photo_intake=True)
            return replace(current, blocks=tuple(current_blocks.values()))
        draft = render_issue_cards(replace(draft, blocks=tuple(blocks.values())), prefix, field,
                                   defer_actions=True, evidence_pages=edit_issue_pages, defer_commit=True)
        blocks = {block.key: block for block in draft.blocks}
        handled.update(("equipment_issues", "equipment_issues_evidence"))
    elif section.key == "proposals":
        from app.monthly_report_followups import render_followups
        draft = replace(draft, blocks=tuple(blocks.values()))
        draft = render_followups(draft, prefix, field, category="proposal", defer_commit=True)
    if section.key == "training":
        from app.monthly_report_training_ui import render_training
        blocks = render_training(draft, blocks, prefix, field)
        handled.add("training_summary")
    if section.key == "organization":
        from app.monthly_report_organization_ui import render_organization
        blocks = render_organization(draft, blocks, specs, prefix, assets, field,
            lambda spec, block: _edit_content(spec, block, state, prefix, assets, field, draft), show_preview=False)
        handled.update(spec.key for spec in _standing_specs(section))
    if section.key == "mbcx":
        from app.monthly_report_mbcx_ui import render_mbcx
        status = blocks.get("mbcx_status", ResolvedBlock("mbcx_status", "This month"))
        pages = blocks.get("mbcx_report", ResolvedBlock("mbcx_report", "This month"))
        blocks["mbcx_status"], blocks["mbcx_report"] = render_mbcx(
            status, pages, prefix, field,
            lambda block: _edit_content(specs["mbcx_report"], block, state, prefix, assets, field, draft))
        blocks["mbcx_status"] = _review_carried_update(blocks["mbcx_status"], period, prefix)
        handled.update(("mbcx_status", "mbcx_report"))
    for original_spec in section.blocks:
        if original_spec.key in handled:
            continue
        spec = specs[original_spec.key]
        block = blocks.get(spec.key, ResolvedBlock(spec.key, "This month"))
        if spec.key == "vendor_reports" and not block.asset_hashes:
            # Keep genuine legacy content accessible; an empty compatibility
            # slot does not need its own explanatory monthly report caption.
            continue
        from app.monthly_report_page_controls import source_managed_pages
        page_managed = (spec.key == "water_reports" and source_managed_pages(
            block, st.session_state.get(prefix + "_evidence", ())))
        if not page_managed and spec.key not in {"proposals", "rfi_matrix", "utility_analysis", "activity_summary"}:
            st.markdown("**" + readable_label(spec.key) + "**")
        if spec.key == "thermal_capacity":
            from app.monthly_report_capacity_ui import render_capacity
            before = block
            draft, block = render_capacity(draft, block, prefix, field)
            if block != before:
                _forget_block_widgets(prefix, {spec.key})
            spec = next((item for current in draft.sections for item in current.blocks if item.key == spec.key), spec)
            specs[spec.key] = spec
        if spec.key in ("contact_matrix", "subcontractor_matrix"):
            from app.monthly_report_visual_ui import edit_contacts
            block = edit_contacts(draft, spec, block, prefix, assets, field, show_preview=False)
        else:
            with writing if writing is not None and spec.key == "activity_summary" else nullcontext():
                block = _edit_content(spec, block, state, prefix, assets, field, draft,
                                      manage_saved_pictures=not page_managed)
        if spec.key in MONTHLY_EDIT_KEYS:
            block = _review_carried_update(block, period, prefix)
        blocks[spec.key] = block
    return draft, blocks


def _keep_missing_sources(prefix, sources):
    from app.monthly_report_source_recovery import retain_unavailable
    identifiers = {source.id for source in sources}
    missing = tuple(source for source in st.session_state.get(prefix + "_unavailable_sources", ())
                    if source.id not in identifiers)
    st.session_state[prefix + "_unavailable_sources"] = missing
    return retain_unavailable(sources, missing)


def _render_report_details_action(candidate, existing, period, browser_token):
    """An explicit scoped profile save beside the identity fields it changes."""
    if existing is None:
        return
    contract, selected = existing.contract, existing.key
    prefix = "report_guided_" + _signature((contract, selected, period.key))
    prepared_key = prefix + "_prepared"
    actor = (st.session_state[prepared_key] if prepared_key in st.session_state else
             remembered_report_preparer(browser_token, contract, selected))
    state = library.load_profile(contract, selected)
    if state.profile != existing:
        st.warning("These saved report details changed while you were editing. Reload the current details before saving; your report text has not been changed.")
        return
    baseline_key = prefix + "_identity_details_base"
    baseline = st.session_state.setdefault(baseline_key, state.revision)
    if candidate == existing:
        st.session_state[baseline_key] = state.revision
        return
    st.caption("Saves this report group's name, site aliases and regional scope for future reports for these sites. Completed report versions keep their original details.")
    if not actor.strip():
        st.caption("[Enter Prepared by](#report-prepared-by) to save these report details.")
    if baseline != state.revision:
        st.warning("The saved report details changed while your changes were pending. Compare both versions before continuing. Nothing has been overwritten.")
        def aliases(profile):
            return "; ".join(site.title + ": " + (", ".join(site.aliases) or "None") for site in profile.facilities)
        st.table([
            {"Detail": "Group name", "Current saved": existing.title, "Your change": candidate.title},
            {"Detail": "Report scope", "Current saved": existing.scope_type.replace("_", " "),
             "Your change": candidate.scope_type.replace("_", " ")},
            {"Detail": "Site aliases", "Current saved": aliases(existing), "Your change": aliases(candidate)},
        ])
        st.caption("Continuing keeps your proposed details against this newer version. Save report details applies them afterward.")
        if st.button("Continue with these report details", disabled=not actor.strip(),
                     key=prefix + f"_details_accept_{state.revision}"):
            st.session_state[baseline_key] = state.revision
            st.rerun()
        return
    if st.button("Save report details", disabled=not actor.strip(),
                 key=prefix + f"_rename_save_{state.revision}"):
        try:
            library.save_profile(candidate, expected_revision=state.revision, actor=actor, confirmed=True)
            if prefix + "_draft" in st.session_state:
                from app.monthly_report_start import refresh_profile_identity
                st.session_state[prefix + "_draft"] = refresh_profile_identity(
                    st.session_state[prefix + "_draft"], candidate)
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error("Report details could not be saved: " + str(exc))


def _current_source_detail(source, contents):
    """Use this report's delivered source changes before drawing its form.

    Page actions commit evidence before requesting a full rerun; the report
    snapshot may still be one render behind. An ambiguous or different
    original is never substituted, and the form keeps its revision guard.
    """
    matches = tuple(content.source for content in contents if content.source.id == source.id)
    if (len(matches) == 1 and matches[0].sha256 == source.sha256
            and matches[0].suffix == source.suffix):
        return matches[0]
    return source


def render_guided_workflow(browser_token, browser_timezone, field, move):
    st.session_state["_monthly_source_detail_anchors"] = set()
    st.session_state["_monthly_source_detail_forms"] = {}
    last_contract, last_profile = remembered_report_preferences(browser_token)
    recovery_available = active_work.enabled(browser_token)
    with st.expander("Help"):
        st.write("1. Choose sites and month.\n2. Update the sections below; sections without a new update can stay blank.\n3. Review source pages that need attention, then create and download Word/PDF.")
        st.caption("Selecting several sites combines them in one report. For separate reports, select each site individually.")
        st.write("Saved site details carry forward. Monthly files and progress photos start fresh. Browser drafts and shared report versions are separate.")
        st.caption("MBCx means monitoring-based commissioning: reviewing equipment performance for operating issues and improvements. ENFRA Connect refers to the monitoring platform. Include only verified findings and savings; otherwise record the current status.")
        st.caption("Training covers hospital/client staff. ENFRA employees, asset managers and vendor personnel are outside its scope. Record only confirmed completed training in the monthly list. Enter hours only when known.")
        st.caption("Draft recovery keeps edits after they reach the app. Text still being typed may not be recoverable. Check the save status before leaving. Saving or creating files adds a shared version. Prepared by is report attribution, not a sign-in.")
    from app.monthly_report_admin_ui import render_administration_links
    render_administration_links()
    from app.monthly_report_start_ui import choose_contract, select_sites, starting_choice, identity_summary
    with st.container(key="monthly_report_identity"):
        contract = choose_contract(last_contract, field)
        if contract:
            period = month_selector(field, "report", suggested_period(operator_today(browser_timezone)))
            # Keep the prior identity line while the native site choices are
            # being read. st.empty() clears it immediately on every rerun,
            # shifting checkbox rows during a second pointer press.
            identity_slot = st.container(key="monthly_report_identity_sites")
    if not contract:
        return
    profiles = library.list_profiles(contract)
    completed_setup = st.session_state.pop("report_setup_done", None)
    remembered = last_profile if last_contract == contract else ""
    returning = any(p.key == remembered for p in profiles) and not completed_setup
    initial_sites_open = st.session_state.setdefault("report_sites_initially_open_" + _signature(contract), not returning)
    # Always use the same container/label. Remembering this report after its
    # first acknowledged edit must not move existing native editors.
    site_box = st.expander("Change report sites", expanded=initial_sites_open)
    with site_box:
        candidate, existing = select_sites(contract, profiles, remembered, field, completed_setup,
            render_details_action=lambda candidate, existing: _render_report_details_action(
                candidate, existing, period, browser_token))
    identity_slot.caption(identity_summary(existing or candidate) if candidate else "Select report sites.")
    if not candidate:
        return
    if not existing:
        starting_choice(candidate, profiles, period, "", field)
        return
    selected = existing.key
    state = library.load_profile(contract, selected)
    profile = state.profile
    prefix = "report_guided_" + _signature((contract, selected, period.key))
    assets = st.session_state.setdefault(prefix + "_assets", {})
    snapshot = library.load_snapshot(contract, selected, period)
    imported = library.load_imported_draft(contract, selected)
    if completed_setup == selected:
        record_report_preferences(browser_token, contract, selected)
        if imported:
            record_report_preparer(browser_token, contract, selected, imported.prepared_by)
    from app.monthly_report_start import latest_snapshot, latest_saved_draft, refresh_profile_identity
    prior = latest_snapshot(contract, selected, period)
    prior_draft = latest_saved_draft(contract, selected, period, before=True)
    draft_key = prefix + "_draft"
    resume = st.session_state.get("report_resume_import") == (contract, selected, period.key)
    # Keep this status slot on every render. Removing a one-shot root element
    # after recovery shifts the workspace's delta path and replaces its native
    # editors on the first edit, even when their widget keys and text agree.
    recovery_notice = st.empty()
    if draft_key not in st.session_state or resume:
        # A replacement import/restart must not inherit unacknowledged text
        # callbacks even when the same sites, month and widget key are reused.
        st.session_state[prefix + "_rich_text_epoch"] = uuid4().hex
        st.session_state.pop(prefix + "_pending_browser_save", None)
        active = None
        active_generation = ""
        if recovery_available:
            try:
                active = active_work.load(browser_token, contract, selected, period)
                active_generation = (active.generation if active else
                                     active_work.current_generation(browser_token, contract, selected, period))
            except (library.LibraryError, OSError):
                st.warning("Unfinished browser work could not be restored. Your saved reports are unchanged.")
        active_sequence = active.revision if active else 0
        current_head_revision = snapshot.revision if snapshot else 0
        if active and active.base_snapshot_revision != current_head_revision and not (resume or completed_setup == selected):
            if snapshot and snapshot.draft.fingerprint == active.draft.fingerprint:
                # Already published as a completed version; no stale recovery.
                active_generation = active_work.discard(browser_token, contract, selected, period,
                    expected_revision=active.revision, expected_generation=active_generation)
                active = None
                active_sequence = 0
            elif st.session_state.get(prefix + "_recover_previous") is not True:
                st.warning("This browser has unfinished changes based on an older saved version. Nothing has been overwritten.")
                if st.button("Review my unfinished work", key=prefix + "_restore_active"):
                    st.session_state[prefix + "_recover_previous"] = True
                    st.rerun()
                if st.button("Use the current saved version instead", key=prefix + "_discard_stale_active"):
                    try:
                        active_work.discard(browser_token, contract, selected, period,
                            expected_revision=active.revision, expected_generation=active_generation)
                        st.rerun()
                    except (library.LibraryError, OSError):
                        st.error("Unfinished work could not be discarded. Your saved reports remain available.")
                return
        prepared = remembered_report_preparer(browser_token, contract, selected)
        using_import = False
        preserve_saved_defaults = False
        recovered_work = False
        pending_import = imported and imported.period == period and (not snapshot or snapshot.revision == library.imported_snapshot_revision(contract, selected))
        if active and not (resume or completed_setup == selected):
            draft = active.draft
            recovered_work = True
            preserve_saved_defaults = True
            assets.update(active.assets)
        elif imported and (resume or pending_import):
            draft = imported
            using_import = True
            st.session_state.pop("report_resume_import", None)
        elif snapshot:
            draft = snapshot.draft
            preserve_saved_defaults = True
        elif imported and imported.period == period:
            draft = imported
            using_import = True
        elif prior_draft:
            draft = replace(new_month_draft(prior_draft, period), profile=profile)
            preserve_saved_defaults = True
        else:
            draft = _initial_draft(state, period, prepared)
        # A shared report's author is not the identity of a new visitor.
        # Only a setup/import just completed in this session can seed that name.
        current_actor = (draft.prepared_by if recovered_work else
                         prepared or (draft.prepared_by if completed_setup == selected or resume else ""))
        draft = complete_guided_sections(replace(draft, prepared_by=current_actor))
        from app.monthly_report_designs import pin
        draft = replace(draft, profile=pin(draft.profile,
            latest_master=not bool(snapshot) and not recovered_work,
            preserve_legacy=bool(snapshot) or recovered_work))
        if not preserve_saved_defaults:
            from app.monthly_report_capacity import resolve_capacity
            from app.monthly_report_workflow_standards import apply_defaults as apply_workflow_defaults
            draft = apply_workflow_defaults(resolve_capacity(draft), assets)
        st.session_state[draft_key] = draft
        # A saved empty standing block is an intentional report choice, not a
        # first-use gap. Preserve it on reopen and next-month rollover alike.
        st.session_state[prefix + "_directory_defaults_attempted"] = preserve_saved_defaults
        st.session_state[prefix + "_revision"] = (active.base_snapshot_revision if recovered_work else
            library.imported_snapshot_revision(contract, selected) if using_import else snapshot.revision if snapshot else 0)
        st.session_state[prefix + "_active_sequence"] = active_sequence
        st.session_state[prefix + "_active_generation"] = active_generation
        if recovered_work:
            recovery_notice.success("Recovered your unfinished changes from this browser. Completed report history is unchanged.")
    from app import monthly_report_recovery_save as recovery_save
    recovery_scope = (contract, selected, period.key, st.session_state[prefix + "_rich_text_epoch"],
                      st.session_state.get("_monthly_qa_generation", ""))
    recovery_ack_error = None
    recovery_acknowledged = None
    if recovery_available:
        try:
            recovery_acknowledged = recovery_save.acknowledge(st.session_state, prefix, recovery_scope, browser_token)
        except (library.LibraryError, OSError) as exc:
            # Keep rendering delivered edits; the ordinary save-status branch
            # below reports this exact failure without adopting a newer head.
            recovery_ack_error = exc
    from app.monthly_report_setup import normalize_mbcx
    draft, removed_prices = client_table_draft(complete_guided_sections(normalize_mbcx(refresh_profile_identity(st.session_state[draft_key], profile))))
    if removed_prices:
        st.info("Price columns were left out of this working report: " + ", ".join(removed_prices) + ". The saved original remains available. Check the remaining wording and images for prices before download.")
    # A missing preparer must never strand someone in a distant section with
    # only a generic instruction. This stable in-page anchor identifies the
    # actual native text input immediately below it (not a fake proxy field).
    st.markdown('<span id="report-prepared-by"></span>', unsafe_allow_html=True)
    prepared = st.text_input("Prepared by", key=field(prefix + "_prepared", draft.prepared_by),
                             help="Shown on this report; not a sign-in.")
    draft = replace(draft, prepared_by=prepared)
    if prepared.strip() and not st.session_state.get(prefix + "_directory_defaults_attempted"):
        from app.monthly_report_directory import apply_defaults
        draft = apply_defaults(draft)
        st.session_state[prefix + "_directory_defaults_attempted"] = True
    from app.monthly_report_directory import refresh_directory_contacts
    refreshed = refresh_directory_contacts(draft)
    if refreshed != draft:
        from app.monthly_report_directory_ui import _resume_contacts
        # Discard only this editor's obsolete widget delta before the next draw.
        _resume_contacts(refreshed, prefix)
    from app.monthly_report_directory_ui import render_selected_directory
    # Shared contact maintenance belongs to the administration surface, not
    # a competing report editor above Organizational Chart. Keep the same
    # explicit shared-save scope, contact widget identity and return value.
    with st.sidebar:
        updated_contacts = render_selected_directory(contract, profile.facilities, prepared, prefix)
    if updated_contacts is not None:
        from app.monthly_report_directory import apply_contacts
        from app.monthly_report_directory_ui import _resume_contacts
        draft = apply_contacts(draft, updated_contacts)
        _resume_contacts(draft, prefix)
    from app.monthly_report_save_status import SaveStatus
    save_status = SaveStatus(prefix, recovery_available=recovery_available)
    from app.monthly_report_asset_review import refresh_asset_source_context
    from app.monthly_report_section_preview_ui import render_section_preview
    blocks = {b.key: refresh_asset_source_context(b, draft.sources) for b in draft.blocks}
    specs = {b.key: b for s in draft.sections for b in s.blocks} | {b.key: b for b in layout_blocks()}
    from app.monthly_report_source_recovery import restore_sources, used_missing_sources, safe_source_name
    if prefix + "_evidence" not in st.session_state and draft.sources:
        contents, failed = restore_sources(profile, draft.sources)
        st.session_state[prefix + "_evidence"] = contents
        st.session_state[prefix + "_unavailable_sources"] = failed
        # The original upload widgets are intentionally not restored by a new
        # Streamlit session. Retain a canonical date/site correction path for
        # every saved source, even if the upload was already processed.
        st.session_state[prefix + "_source_details_on_resume"] = True
    available_ids = {content.source.id for content in st.session_state.get(prefix + "_evidence", ())}
    missing = tuple(source for source in st.session_state.get(prefix + "_unavailable_sources", ())
                    if source.id not in available_ids)
    st.session_state[prefix + "_unavailable_sources"] = missing
    if missing:
        names = ", ".join(safe_source_name(source) for source in missing)
        st.warning(f"Could not read saved file: {names}. Other sections remain editable. "
                   "Re-upload a good copy or remove linked content before downloading.")
        if st.button("Retry reading saved files", key=prefix + "_retry_missing_source"):
            st.session_state.pop(prefix + "_evidence", None)
            st.session_state.pop(prefix + "_unavailable_sources", None)
            st.rerun()
        unused = tuple(source for source in missing if source not in used_missing_sources(draft, missing))
        if unused:
            selected_missing = st.selectbox("Unused file to remove from this working report",
                unused, format_func=safe_source_name, key=prefix + "_unused_source")
            if st.button("Remove this unused file", key=prefix + "_remove_unused_source"):
                draft = replace(draft, sources=tuple(source for source in draft.sources
                                                     if source.id != selected_missing.id))
                st.session_state[prefix + "_unavailable_sources"] = tuple(
                    source for source in missing if source.id != selected_missing.id)
                st.session_state[draft_key] = draft
                st.rerun()
    # Source metadata can appear after the first upload. Keep its subtree at
    # one fixed root position so native section controls below it retain their
    # delta paths while that first source is committed and reviewed.
    with st.container(key=prefix + "_source_metadata_corrections"):
        # This stable sibling precedes the workspace so native widget paths
        # do not move when a source appears. Bind navigation to the same
        # hashed report identity used by workspace_layout.workspace.
        from hashlib import sha256
        st.markdown('<span class="enfra-source-correction-owner" data-report-identity="' +
                    sha256(prefix.encode()).hexdigest()[:24] + '" aria-hidden="true"></span>',
                    unsafe_allow_html=True)
        if draft.sources:
            from app.monthly_report_source_details import detail_problems
            from app.monthly_report_upload_ui import render_source_details
            from app.monthly_report_model import used_source_ids
            # A resumed report needs an exact-item correction path, not every
            # source form expanded above the report. Valid or unused reference-only
            # sources remain available through Manage source files. Keep each unresolved
            # source's anchor outside its quiet disclosure so review links land on
            # a visible, named action. Opening it does not approve or change facts.
            corrections = {}
            included_sources = used_source_ids(draft)
            resumed = st.session_state.get(prefix + "_source_details_on_resume")
            for source in draft.sources:
                source = _current_source_detail(source, st.session_state.get(prefix + "_evidence", ()))
                in_report = source.id in included_sources
                problems = detail_problems(source, profile, period, in_report=in_report, draft=draft)
                if in_report and not source.facility:
                    from app.monthly_report_source_scope import included_scope_valid
                    if not included_scope_valid(draft, source) and not any("scope" in p or "site" in p for p in problems):
                        problems = (*problems, "source scope needs review")
                # Keep one quiet return location even when this exact correction
                # removes its warning/form. The display adapter reveals it only
                # during a deliberate trip from final review.
                with st.container(key="monthly_source_correction_" + source.id):
                    from html import escape
                    st.markdown('<a class="enfra-source-review-return" data-source-id="' +
                                escape(source.id, quote=True) + '" href="#report-review" hidden>Return to review</a>',
                                unsafe_allow_html=True)
                    if problems and (resumed or in_report):
                        from app.monthly_report_source_scope import artwork_scope_keys
                        corrections[source.id] = render_source_details(
                            source, profile, prefix + "_resumed_" + source.id, field,
                            compact_problems=problems, artwork_keys=artwork_scope_keys(draft, source.id))
            if any(corrections.get(source.id, source) != source for source in draft.sources):
                draft = replace(draft, sources=tuple(corrections.get(source.id, source) for source in draft.sources))
                st.session_state[prefix + "_evidence"] = tuple(
                    replace(content, source=corrections.get(content.source.id, content.source))
                    for content in st.session_state.get(prefix + "_evidence", ()))
                # A metadata correction does not restore missing original bytes.
                # Keep the corrected record in that retained set as well, or the
                # next source renderer would restore its pre-correction metadata.
                st.session_state[prefix + "_unavailable_sources"] = tuple(
                    corrections.get(source.id, source)
                    for source in st.session_state.get(prefix + "_unavailable_sources", ()))
    from app.monthly_report_model import included_sections
    short_links = {
        "organization": "Contacts", "activity": "Activity", "scorecards": "Scorecards",
        "mbcx": "MBCx", "maintenance": "Onsite calls", "subcontractors": "Subcontractors",
        "water": "Water", "issues": "Issues", "capital": "Capital",
        "proposals": "Proposals", "training": "Training", "rfi": "RFI",
        "accounts_receivable": "A/R",
    }
    from app.workspace_layout import workspace, workspace_section, workspace_columns
    with workspace("monthly", prefix, navigation_key="monthly_report_navigation"):
        with st.container(key="monthly_report_navigation"):
            links = [f"[{short_links.get(section.key, section.title)}](#report-section-{section.key})"
                     for section in included_sections(draft.sections)]
            st.markdown("**Jump to:** " + " · ".join((*links, "[Review & download](#report-review)")))
        st.markdown(
            '<style>.st-key-monthly_report_navigation{position:sticky;top:3rem;z-index:15;'
            'background:var(--background-color,#fff);border-bottom:1px solid rgba(128,128,128,.25);'
            'padding:.25rem .5rem;max-height:6rem;overflow-y:auto;}</style>',
            unsafe_allow_html=True,
        )
        with workspace_section("monthly_cover", "Cover"):
            editor_column, preview_column = workspace_columns("monthly_cover")
            with editor_column:
                # Contract, period, sites and preparer were already chosen at Start.
                # Keep report-only photo changes reachable independently from the
                # starting-report gallery and shared design administration.
                from app.monthly_report_cover_ui import render_cover_photograph
                blocks = render_cover_photograph(
                    blocks, prefix, assets,
                    lambda ref: assets[ref] if ref in assets else library.read_asset(contract, selected, ref),
                    scope=_rich_text_scope(prefix),
                )
                from app.monthly_report_section_ui import render_section_setup
                render_section_setup(contract, period, prepared, field, state=state,
                                     working_draft=replace(draft, blocks=tuple(blocks.values())),
                                     working_assets=tuple(assets.items()), working_revision=st.session_state[prefix + "_revision"])
                with st.expander("About this report"):
                    from app.monthly_report_designs_ui import render_design_status, render_apply_master_design
                    render_design_status(draft)
                    render_apply_master_design(replace(draft, blocks=tuple(blocks.values())), prefix)
            with preview_column:
                with st.container(key="monthly_cover_preview_sticky"):
                    from app.monthly_report_section_ui import render_pending_cover_selection
                    proposed_draft, proposed_assets = render_pending_cover_selection(
                        replace(draft, blocks=tuple(blocks.values())), assets, contract, period, state)
                    render_section_preview(proposed_draft, "cover", proposed_assets, prefix, deferred=True)
        from app.monthly_report_section_help import editor_section_title
        for section in draft.sections:
            title = editor_section_title(section)
            with workspace_section("monthly_" + section.key, title):
                st.divider()
                st.subheader(title, anchor="report-section-" + section.key)
                st.caption(section_help(section.key).guidance)
                editor_column, preview_column = workspace_columns("monthly_" + section.key)
                with editor_column:
                    draft, blocks = _render_ordered_section(draft, section, blocks, specs, state, prefix, assets, field)
                with preview_column:
                    if section.key in {"organization", "subcontractors", "training"} and not prepared.strip():
                        st.caption("Saved team and contact pages are kept. "
                                   "[Enter Prepared by](#report-prepared-by) above to view them.")
                    else:
                        render_section_preview(replace(draft, blocks=tuple(blocks.values())), section.key, assets, prefix, deferred=True)
    blocks = {key: refresh_asset_source_context(block, draft.sources) for key, block in blocks.items()}
    draft = complete_guided_sections(replace(draft, blocks=tuple(blocks.values())))
    footer = blocks.get("footer_text")
    if footer:
        draft = replace(draft, address_line=footer.text if footer.source != "Omit" else "")
    from app.monthly_report_issues import apply_issue_action
    draft = apply_issue_action(draft, prefix)
    st.session_state[draft_key] = draft
    from app.monthly_report_followups import acknowledge_followup_controls
    acknowledge_followup_controls(draft, prefix)
    current_revision = snapshot.revision if snapshot else 0
    conflict = current_revision != st.session_state[prefix + "_revision"]
    if conflict:
        st.warning("Another version was saved. Your working draft is preserved. Compare it with the saved report before creating another version.")
        with st.expander("Compare saved content"):
            from app.monthly_report_compare_ui import render_conflict_comparison
            render_conflict_comparison(draft, snapshot,
                working_asset_loader=lambda ref: assets.get(ref) or library.read_asset(contract, selected, ref),
                saved_asset_loader=lambda ref: library.read_asset(contract, selected, ref))
        accept = st.checkbox("I compared the saved version and want to save my draft as the next version", key=prefix + f"_accept_{current_revision}")
        st.caption("Continuing keeps your draft and uses the newer shared version as its starting revision. It does not save; your next save creates another shared version.")
        if st.button("Continue with my draft", key=prefix + "_accept_revision", disabled=not accept):
            st.session_state[prefix + "_revision"] = current_revision
            st.rerun()
    st.markdown('<span id="shared-report-history"></span>', unsafe_allow_html=True)
    history = st.expander("Shared report history", expanded=False,
                          key=prefix + "_history_open", on_change="rerun")
    with history:
        st.caption("Saving a version adds it to shared report history. Browser draft recovery is separate.")
        from app.monthly_report_history_ui import render_snapshot_history
        if history.open:
            render_snapshot_history(draft, prefix, assets, snapshot)
        if st.button("Save shared version", key=prefix + "_save", disabled=conflict or not prepared.strip()):
            try:
                saved = library.save_snapshot(draft, expected_revision=current_revision, assets=tuple(assets.items()), entered_editor=prepared,
                                              open_issues=snapshot.open_issues if snapshot else prior.open_issues if prior else (),
                                              pending_proposals=snapshot.pending_proposals if snapshot else prior.pending_proposals if prior else ())
            except (ValueError, OSError) as exc:
                st.error("Shared version could not be saved: " + str(exc))
                st.caption("Your draft remains on this page. Check its recovery status before leaving, then retry saving.")
            else:
                st.session_state[prefix + "_revision"] = saved.revision
                if recovery_available:
                    try:
                        st.session_state[prefix + "_active_generation"] = active_work.discard(
                            browser_token, contract, selected, period,
                            expected_revision=st.session_state.get(prefix + "_active_sequence", 0),
                            expected_generation=st.session_state.get(prefix + "_active_generation", ""))
                        st.session_state[prefix + "_active_sequence"] = 0
                    except (library.LibraryError, OSError):
                        st.warning("The report version was saved, but its older browser copy still needs review.")
                record_report_preferences(browser_token, contract, selected)
                record_report_preparer(browser_token, contract, selected, prepared)
                st.success("Report version saved in the shared history.")
                st.rerun()
    with st.expander("Report actions"):
        if snapshot:
            st.caption(f"Opened shared version {snapshot.revision} · {period.label}. Current edits use the save status above.")
        elif prior_draft:
            st.caption(f"Starting report: saved {prior_draft.period.label} for these sites. Monthly updates start fresh; site information carries forward.")
        st.markdown("**Start over on this browser**")
        st.caption(f"Discard this browser's unfinished changes for {profile.title} · {period.label}. "
                   "Sites: " + "; ".join(site.title for site in profile.facilities) + ". "
                   "Completed report versions, original files, standing site information and other browsers stay unchanged.")
        forget = st.checkbox("Discard my unfinished changes for this report", key=prefix + "_discard_work_confirm")
        if st.button("Start this report over", key=prefix + "_discard_work", disabled=not forget):
            try:
                if recovery_available:
                    active_work.discard(browser_token, contract, selected, period,
                        expected_revision=st.session_state.get(prefix + "_active_sequence", 0),
                        expected_generation=st.session_state.get(prefix + "_active_generation", ""))
                for key in list(st.session_state):
                    if key.startswith(prefix):
                        del st.session_state[key]
                st.session_state["report_draft_mirror"] = {
                    key: val for key, val in st.session_state.get("report_draft_mirror", {}).items()
                    if not key.startswith(prefix)
                }
                st.rerun()
            except (library.LibraryError, OSError):
                st.error("Unfinished work could not be discarded. Your current edits remain on this page.")
    from app.monthly_report_output_ui import take_retries
    output_retries = take_retries(prefix)
    package = st.session_state.get(prefix + "_package")
    if package and package.fingerprint != draft.fingerprint:
        st.session_state.pop(prefix + "_package", None)
        package = None
    st.divider()
    with st.container():
        st.subheader("Review and download", anchor="report-review")
        from app.monthly_report_editor import review_client_images
        if prepared.strip():
            from app.monthly_report_asset_review import pending_asset_indexes
            before_review = tuple((block.key, block.asset_hashes, pending_asset_indexes(block))
                                  for block in draft.blocks)
            draft = review_client_images(draft, assets, prefix, field)
            after_review = tuple((block.key, block.asset_hashes, pending_asset_indexes(block))
                                 for block in draft.blocks)
            if after_review != before_review:
                # Ordered section controls were rendered before these image
                # decisions. Refresh them only after the complete draft and
                # its recovery attempt below, never before delivered edits.
                st.session_state[prefix + "_period_editor_refresh"] = True
        st.session_state[draft_key] = draft
        if recovery_available and snapshot and snapshot.draft.fingerprint == draft.fingerprint:
            # The complete current version already exists in immutable history;
            # no new browser journal is necessary after Generate/Save.
            save_status.shared_saved(snapshot.revision)
        elif recovery_available:
            try:
                if recovery_ack_error is not None:
                    raise recovery_ack_error
                previous_sequence = st.session_state.get(prefix + "_active_sequence", 0)
                recovered = recovery_save.save(st.session_state, prefix, recovery_scope,
                                               browser_token, draft, assets)
                save_status.browser_saved(recovered.updated_at)
                if recovered.revision != previous_sequence or recovery_acknowledged is not None:
                    record_report_preferences(browser_token, contract, selected)
                    if prepared.strip():
                        record_report_preparer(browser_token, contract, selected, prepared)
            except active_work.ActiveWorkConflict:
                save_status.failed()
                st.error("Another tab or a new working copy has newer changes. "
                                  "These edits are still on this page but were not kept for recovery. "
                                  "Reload and compare before trying again.")
            except (library.LibraryError, OSError):
                save_status.failed()
                st.error("Automatic recovery could not keep these edits. "
                                  "Your current text remains on this page, but is not saved for a refresh. "
                                  "Retry the browser save, or save a shared report version before leaving.")
                # Native button activation starts one full render, whose
                # persistence attempt above retries the current draft once.
                st.button("Retry browser save", key=prefix + "_retry_browser_save")
        else:
            if snapshot and snapshot.draft.fingerprint == draft.fingerprint:
                # A completed/saved version is still saved, even when cookies
                # prevent separately retaining unfinished browser changes.
                save_status.shared_saved(snapshot.revision)
                st.caption("Automatic recovery for new edits is unavailable in this browser.")
            else:
                st.warning("Automatic recovery is unavailable in this browser. Save a report version before leaving.")
        if package and package.fingerprint != draft.fingerprint:
            st.session_state.pop(prefix + "_package", None)
            package = None
        from app.monthly_report_model import included_sections
        monthly_entry_sections = monthly_entries_by_section(draft)
        # Lack of a new update is not an error or a completion score. Only
        # monthly-editable sections belong in this quiet optional disclosure.
        included = included_sections(draft.sections)
        without_new_monthly = [
            section for section in included
            if section.key not in monthly_entry_sections
            and any(spec.key in MONTHLY_EDIT_KEYS for spec in section.blocks)
        ]
        if without_new_monthly:
            with st.expander("Sections without new updates (optional)", expanded=False):
                st.caption("Blank or unchanged sections are allowed; saved standing details remain.")
                st.markdown(" · ".join(
                    f"[{short_links.get(section.key, section.title)}](#report-section-{section.key})"
                    for section in without_new_monthly))
        # Pre-generation page/size estimates are not client deliverables.
        # Actual sizes and the >15 MB warning are shown after generation.
        loader = lambda ref: assets[ref] if ref in assets else library.read_asset(contract, selected, ref)
        estimated = estimate_bytes(draft, loader)
        checks = [check for check in preflight(draft, estimated) if check.code != "empty"]
        from app.monthly_report_checks import ReportCheck
        dependent = used_missing_sources(draft, st.session_state.get(prefix + "_unavailable_sources", ()))
        if dependent:
            missing_names = ", ".join(safe_source_name(source) for source in dependent)
            checks.append(ReportCheck("unavailable_source",
                f"Cannot safely generate while {missing_names} is missing. "
                "Replace the source or remove the content linked to it first.", True))
        if checks:
            count = len(checks)
            st.markdown(f"**{count} {'item needs' if count == 1 else 'items need'} attention**")
        from app.monthly_report_source_review_ui import render_source_check
        for check in checks:
            if not render_source_check(check, draft, prefix):
                (st.error if check.blocking else st.warning)(review_message(check, draft))
        warnings_ok = not any(not c.blocking for c in checks)
        if not warnings_ok:
            warnings_ok = st.checkbox("I checked these specific warnings", key=prefix + "_warnings_" + draft.fingerprint)
        blocked_reason = generation_block_reason(conflict=conflict, checks=checks, warnings_ok=warnings_ok)
        if blocked_reason:
            st.caption(blocked_reason)
        # Re-confirm only a completely empty monthly input set. This is a
        # soft editorial guard, never a way around mandatory preflight gates.
        empty_confirmation_key = prefix + "_empty_generation_confirmation"
        if st.session_state.get(empty_confirmation_key) not in (None, draft.fingerprint):
            st.session_state.pop(empty_confirmation_key, None)
        st.caption("Creating files also saves a version in Shared report history.")
        pressed = st.button("Create Word and PDF", key=prefix + "_generate",
                            type="secondary" if blocked_reason else "primary", disabled=bool(blocked_reason))
        if pressed and not monthly_entry_sections:
            st.session_state[empty_confirmation_key] = draft.fingerprint
        generate_anyway = False
        if not blocked_reason and not monthly_entry_sections and (
                st.session_state.get(empty_confirmation_key) == draft.fingerprint):
            st.warning("No new monthly information was entered in the section editors. "
                       "This draft may contain mostly dividers and saved standing material. "
                       "Check the report before sending it to a client.")
            generate_anyway = st.button("Create anyway", key=prefix + "_empty_generate_anyway")
        if (pressed and bool(monthly_entry_sections)) or generate_anyway:
            st.session_state.pop(empty_confirmation_key, None)
            try:
                with st.spinner("Preparing the Word and PDF downloads…"):
                    package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=loader)
            except ValueError as exc:
                st.error(str(exc))
                st.caption("Your edits and saved versions are unchanged. Retry generation when the service is ready.")
                return
            st.session_state[prefix + "_package"] = package
            from app.monthly_report_output_ui import record_shared_save
            record_shared_save(prefix, package)
            try:
                saved = library.save_snapshot(draft, expected_revision=current_revision, assets=tuple(assets.items()), entered_editor=prepared,
                                              open_issues=snapshot.open_issues if snapshot else prior.open_issues if prior else (),
                                              pending_proposals=snapshot.pending_proposals if snapshot else prior.pending_proposals if prior else ())
                st.session_state[prefix + "_revision"] = saved.revision
                if recovery_available:
                    try:
                        st.session_state[prefix + "_active_generation"] = active_work.discard(
                            browser_token, contract, selected, period,
                            expected_revision=st.session_state.get(prefix + "_active_sequence", 0),
                            expected_generation=st.session_state.get(prefix + "_active_generation", ""))
                        st.session_state[prefix + "_active_sequence"] = 0
                    except (library.LibraryError, OSError):
                        st.warning("Your finished report was saved, but a browser working copy could not be cleared.")
                record_report_preferences(browser_token, contract, selected)
                record_report_preparer(browser_token, contract, selected, prepared)
                record_shared_save(prefix, package, saved=saved)
                save_status.shared_saved(saved.revision)
            except (ValueError, OSError) as exc:
                record_shared_save(prefix, package, error=str(exc))
        if package:
            from app.monthly_report_output_ui import render_output_status, record_shared_save, package_identity, queue_retry, matches_retry
            needs_shared_save = render_output_status(package, draft, snapshot, prefix)
            retry_identity = package_identity(package)
            retry_scope = _rich_text_scope(prefix)
            retry_revision = st.session_state[prefix + "_revision"]
            retry_key = _signature((retry_identity, retry_scope, retry_revision))
            if needs_shared_save:
                if conflict:
                    st.caption("Compare the newer shared version above and continue with your draft before retrying this save.")
                st.button("Retry saving this version", key=prefix + "_retry_package_save_" + retry_key,
                          disabled=conflict or not prepared.strip(), on_click=queue_retry,
                          args=(prefix, "save", retry_identity, retry_scope, retry_revision))
                if matches_retry(output_retries["save"], package, retry_scope, retry_revision) and not conflict and prepared.strip():
                    try:
                        saved = library.save_snapshot(draft, expected_revision=current_revision, assets=tuple(assets.items()), entered_editor=prepared,
                            open_issues=snapshot.open_issues if snapshot else prior.open_issues if prior else (),
                            pending_proposals=snapshot.pending_proposals if snapshot else prior.pending_proposals if prior else ())
                        st.session_state[prefix + "_revision"] = saved.revision
                        record_shared_save(prefix, package, saved=saved)
                    except (ValueError, OSError) as exc:
                        record_shared_save(prefix, package, error=str(exc))
                    st.rerun()
            if package.pdf is None and package.pdf_error:
                st.button("Retry PDF", key=prefix + "_retry_pdf_" + retry_key, on_click=queue_retry,
                          args=(prefix, "pdf", retry_identity, retry_scope, retry_revision))
                if matches_retry(output_retries["pdf"], package, retry_scope, retry_revision):
                    from app.monthly_report_docx import retry_report_pdf
                    try:
                        with st.spinner("Retrying PDF conversion…"):
                            package = retry_report_pdf(draft, package)
                        st.session_state[prefix + "_package"] = package
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            from app.monthly_report_storage import readable_bytes
            sizes = "DOCX " + readable_bytes(len(package.docx))
            if package.pdf:
                sizes += " · PDF " + readable_bytes(len(package.pdf))
            st.caption(sizes)
            if max(len(package.docx), len(package.pdf or b"")) > 15 * 1024 * 1024:
                st.warning("The finished report exceeds the 15 MB target. You can reduce selected attachment pages or use denser photo layouts, then generate it again.")
            st.download_button("Download DOCX", package.docx, file_name=package.docx_name,
                               key=prefix + "_docx", on_click="ignore")
            if package.pdf:
                st.download_button("Download PDF", package.pdf, file_name=package.pdf_name,
                                   mime="application/pdf", key=prefix + "_pdf", on_click="ignore")
            if package.pdf_error:
                st.warning(package.pdf_error)

    _refresh_period_editors_after_commit(prefix)
