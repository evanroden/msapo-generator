"""A small monthly workspace around the versioned report model."""

from dataclasses import asdict, replace
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


def _mark_explicit_rich_text_edit(marker, widget_key, block, scope):
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
    st.session_state[marker] = {
        "text": text, "baseline": block.fingerprint,
        "result": _edited_rich_text(block, text).fingerprint, "scope": scope,
    }


def _clear_rich_text_for_this_report(marker, widget_key, block, scope, prefix):
    """Explicit report-only empty edit; obey the same revision/epoch receipt guard.

    The native multiline widget can require an explicit apply gesture after
    editing. This separate action gives the operator a deliberate one-click
    clear without touching original evidence or saved shared report history.
    """
    if _rich_text_scope(prefix) != scope:
        return  # A stale tab cannot clear a different imported/reset report.
    st.session_state[widget_key] = ""
    _mark_explicit_rich_text_edit(marker, widget_key, block, scope)


def _pending_rich_text_edit(prefix, block):
    """A delivered callback is newer input before the final draft assignment."""
    key = _rich_text_editor_key(prefix, block)
    receipt = st.session_state.get(key + "_explicitly_edited")
    if (isinstance(receipt, dict)
            and receipt.get("scope") == _rich_text_scope(prefix)
            and receipt.get("baseline") == block.fingerprint
            and isinstance(receipt.get("text"), str)
            and receipt["text"] != block.text
            and receipt["text"] == st.session_state.get(key)):
        return _edited_rich_text(block, receipt["text"])
    return None


def _recover_rich_text_edit(marker, widget_key, block, scope):
    recovered = st.session_state.get(marker + "_recovery")
    if isinstance(recovered, dict) and recovered.get("scope") == scope:
        st.session_state[widget_key] = recovered["text"]
        _mark_explicit_rich_text_edit(marker, widget_key, block, scope)
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
    with st.expander("Review interrupted edit"):
        st.caption("This section changed before your earlier edit finished. "
                   "The current wording is unchanged; your interrupted edit is kept here for this session.")
        if recovered["text"]:
            st.code(recovered["text"], language=None, wrap_lines=True)
        else:
            st.caption("The interrupted edit cleared this section.")
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
        return check.message + f" [Correct source details](#source-details-{source.id})."
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


def _edit_content(spec, block, state, prefix, assets, field, draft=None, *, edit_text=True):
    if draft is not None and spec.type == "image_grid":
        from app.monthly_report_visual_ui import edit_photos
        return edit_photos(draft, block, prefix, assets, field, show_preview=False)
    key = prefix + "_edit_" + spec.key
    # Source-linked text has its own evidence-aware editor above. Do not echo a
    # competing read-only copy below that editor or add a second text control.
    if spec.type not in ("rich_text", "stock_text") and block.text.strip() and not block.ai_paragraphs:
        notes = st.text_area("Notes included in this section", key=field(key + "_notes_" + _signature(block.references), block.text), height=120)
        if notes != block.text:
            block = replace(block, source="This month", text=notes, reviewed_fingerprint="", client_reviewed_fingerprint="")
    if block.extra_tables:
        from app.monthly_report_editor import _cell_text
        tables = []
        for n, table in enumerate(block.extra_tables):
            from app.monthly_report_table_review_ui import review_table_headings
            table = review_table_headings(table, key + f"_imported_{n}", field)
            st.write(f"Table {n+1}")
            rows = _grid(key + f"_imported_{n}_" + _signature(table.columns), [dict(zip(table.columns, r)) for r in table.rows] or [dict.fromkeys(table.columns)], num_rows="dynamic", hide_index=True)
            tables.append(replace(table, rows=tuple(tuple(_cell_text(r.get(c)) for c in table.columns) for r in rows if any(v is not None and v != "" for v in r.values()))))
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
        submitted = (valid and receipt.get("baseline") == block.fingerprint
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
        editor_anchor = "report-editor-" + spec.key
        if draft is not None:
            from html import escape
            st.markdown('<span id="' + escape(editor_anchor, quote=True) + '"></span>', unsafe_allow_html=True)
        text = st.text_area(
            spec.key.replace("_", " ").capitalize(),
            # The native protocol default must agree with the actual draft.
            # A new browser mount initially reads this field; relying solely
            # on a one-shot set_value leaves an empty value it can echo on a
            # later unrelated button/fragment request. In pinned 1.61.1 a keyed
            # text area's ID excludes value (only max_chars is whitelisted),
            # so changing this default does not remount or reset current input.
            value=receipt["text"] if submitted else block.text,
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
        if submitted and text != block.text:
            block = _edited_rich_text(block, text)
            # Do not consume yet. Preview/fragment work can interrupt a full
            # rerun before the edited block reaches the authoritative draft.
            # Replay only this exact submitted value until that draft agrees.
        else:
            # A mismatched/old receipt is never a license to overwrite a
            # newer draft on the next rerun.
            st.session_state.pop(changed_marker, None)
        _render_rich_text_recovery(changed_marker, editor_key, block, scope)
        if draft is not None and not block.ai_written:
            from app.monthly_report_period_items_ui import render_period_items
            section_title = next((section.title for section in draft.sections
                                  if any(item.key == spec.key for item in section.blocks)),
                                 spec.key.replace("_", " ").capitalize())
            resolved = render_period_items(block, draft.period, draft.sources, prefix,
                section_title=section_title, editor_anchor=editor_anchor)
            block = _record_period_editor_transition(prefix, canonical_before, block, resolved, draft.period, editor_key)
    elif spec.type in ("table", "work_order_grid") and (block.rows or not block.extra_tables):
        seed, config = _typed_table(spec, block.rows)
        rows = _grid(key + "_table_" + _signature(asdict(spec)), seed, num_rows="dynamic", hide_index=True, column_config=config)
        from app.monthly_report_editor import _cell_text
        columns = [c.title for c in spec.columns] or ["Facility", "Item", "Status"]
        edited_rows = tuple(tuple(_cell_text(row.get(c)) for c in columns) for row in rows
                            if any(v is not None and v != "" for v in row.values()))
        if rows != seed and edited_rows != block.rows:
            block = replace(block, source="This month", rows=edited_rows, reviewed_fingerprint="", client_reviewed_fingerprint="")
    if block.asset_hashes:
        from app.monthly_report_saved_pictures_ui import edit_saved_pictures
        block = edit_saved_pictures(block, key, lambda ref: assets.get(ref) or library.read_asset(state.profile.contract, state.profile.key, ref), show_preview=False)
    if spec.type in ("rich_text", "stock_text", "table", "work_order_grid"):
        if spec.key in ("training_summary", "equipment_issues"):
            with st.expander("Add a supporting photo (optional)"):
                photo = st.file_uploader("Photo to add to this section", type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_add_photo")
                if photo and st.button("Add this photo", key=key + "_add_photo_save"):
                    from pathlib import Path
                    try:
                        normalized = normalize_report_image(photo.getvalue(), Path(photo.name).suffix)
                        reference = library.asset_reference(normalized.data, normalized.extension)
                        assets[reference] = normalized.data
                        if reference not in block.asset_hashes:
                            captions = (*block.asset_captions, *("" for _ in range(len(block.asset_hashes) - len(block.asset_captions))), "")
                            block = replace(block, source="This month", asset_hashes=(*block.asset_hashes, reference), asset_captions=captions,
                                            reviewed_fingerprint="", client_reviewed_fingerprint="")
                    except (ValueError, OSError):
                        st.error("This photo could not be read. Choose another image; the existing section is retained.")
        return block
    from app.monthly_report_sections import readable_label
    if spec.type == "pdf_pages":
        with st.expander("Replace all report pages with one image (optional)"):
            upload = st.file_uploader("Replacement image for all pages in this part", type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_image")
    else:
        upload = st.file_uploader("Upload a new " + readable_label(spec.key).lower(), type=["png", "jpg", "jpeg", "heic", "heif", "webp"], key=key + "_image")
    if upload and st.button("Use this replacement in this report", key=key + "_replace"):
        from pathlib import Path
        image = normalize_report_image(upload.getvalue(), Path(upload.name).suffix,
                                       line_art=spec.key in ("org_chart", "contact_matrix", "business_hours_workflow", "after_hours_workflow"))
        reference = library.asset_reference(image.data, image.extension)
        assets[reference] = image.data
        block = replace(block, source="Replace once", asset_hashes=(reference,), asset_captions=(), references=())
        st.image(image.data, width="stretch", caption="Updated image in this report")
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
                       and request["month"] == draft.period.key)
            if (matches and request["expected"] == current.fingerprint
                    and not _pending_rich_text_edit(prefix, current)):
                if request["text"] not in current.text:
                    updated = replace(current, source="This month",
                        text="\n\n".join(filter(None, (current.text.strip(), request["text"]))),
                        references=tuple(dict.fromkeys((*current.references, request["reference"]))),
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
    if section.key == "activity" and st.checkbox(
            "Add reviewed vendor service pages", key=field(prefix + "_vendor_pages_open", False)):
        # Optional page-by-page inclusion after the primary upload-first text
        # path. Avoid two simultaneous review widgets for the same source.
        from app.monthly_report_upload_ui import render_section_uploads
        sources, additions, incoming_specs = render_section_uploads(
            profile, period, prefix, field, "improvements", blocks=blocks, assets=assets)
        draft = replace(draft, sources=_keep_missing_sources(prefix, sources))
        if additions:
            draft, blocks = _apply_prepared(draft, blocks, additions, incoming_specs, prefix)
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
        if st.checkbox("Add work-order spreadsheets", key=field(prefix + "_batch_files_open", False)):
            from app.monthly_report_upload_ui import render_uploads
            sources, additions, incoming_specs = render_uploads(profile, period, prefix, field)
            draft = replace(draft, sources=_keep_missing_sources(prefix, sources))
            if additions and st.button("Add prepared pages and tables to this draft", key=prefix + "_apply_uploads"):
                draft, blocks = _apply_prepared(draft, blocks, additions, incoming_specs, prefix)
        from app.monthly_report_ai_ui import render_drafting
        # One shared evidence workspace: rendering this once avoids duplicated
        # source/job widget identities when every report section is visible.
        draft, blocks = render_drafting(draft, blocks, prefix, field, allowed_keys={spec.key for spec in section.blocks})
    if section.key != "activity":
        from app.monthly_report_ai_ui import edit_linked_paragraphs
        blocks = edit_linked_paragraphs(draft, blocks, prefix, field, {spec.key for spec in section.blocks})
    specs.update({b.key: b for current in draft.sections for b in current.blocks})
    if section.key in ("issues", "proposals"):
        from app.monthly_report_followups import render_followups
        draft = replace(draft, blocks=tuple(blocks.values()))
        draft = render_followups(draft, prefix, field, category="issue" if section.key == "issues" else "proposal")
        if section.key == "issues":
            blocks = {block.key: block for block in draft.blocks}
    handled = set()
    if section.key == "issues" and "equipment_issues" in specs:
        block = blocks.get("equipment_issues", ResolvedBlock("equipment_issues", "This month"))
        blocks["equipment_issues"] = _edit_content(specs["equipment_issues"], block, state,
            prefix, assets, field, draft, edit_text=False)
        handled.add("equipment_issues")
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
            block = _edit_content(spec, block, state, prefix, assets, field, draft)
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


def _render_storage_maintenance():
    """Administrative tools kept out of ordinary monthly authoring."""
    if st.button("Check available storage", key="report_storage_check"):
        from app.monthly_report_storage import storage_summary
        try:
            st.session_state["report_storage_summary"] = storage_summary()
        except OSError:
            st.session_state.pop("report_storage_summary", None)
            st.warning("Storage could not be measured right now. Your saved reports were not changed.")
    if storage := st.session_state.get("report_storage_summary"):
        from app.monthly_report_storage import readable_bytes
        st.write(f"Disk capacity: {readable_bytes(storage['total'])} · Available: {readable_bytes(storage['free'])} · Monthly report files: {'at least ' if not storage['complete'] else ''}{readable_bytes(storage['monthly'])}")
        st.caption("Measured when you click Check available storage. The disk is also used by other app workflows. Originals are retained. Identical new assets and source files share one stored copy across all contracts and sites. Monthly history keeps references, so changing one site's selection does not change another report. Existing files can be consolidated below.")
        if storage["free"] < max(512 * 1024 * 1024, storage["total"] * .05):
            st.warning("Storage is running low. Keep space available before importing more large reports. This check does not delete anything.")
    if st.button("Consolidate duplicate stored files", key="report_storage_consolidate"):
        from app.monthly_report_objects import consolidate_existing
        from app.monthly_report_storage import storage_summary, readable_bytes
        try:
            with st.spinner("Sharing identical stored files; originals and history remain available…"):
                result = consolidate_existing()
            st.session_state["report_storage_summary"] = storage_summary()
            st.success(f"Consolidated {result['changed']} files; released {readable_bytes(result['reclaimed'])} from duplicate copies.")
            if not result["complete"]:
                st.info("This batch is complete. Run consolidation again to continue through the remaining files.")
        except (ValueError, OSError):
            st.warning("Consolidation stopped. Original paths and report history remain available; completed files can safely be reused when you retry.")


def render_guided_workflow(browser_token, browser_timezone, field, move):
    st.session_state["_monthly_source_detail_anchors"] = set()
    st.session_state["_monthly_source_detail_forms"] = {}
    last_contract, last_profile = remembered_report_preferences(browser_token)
    recovery_available = active_work.enabled(browser_token)
    with st.expander("How to use this page"):
        st.write("1. Choose sites and month.\n2. Update the sections below; sections without a new update can stay blank.\n3. Review source pages that need attention, then create and download Word/PDF.")
        st.caption("Selecting several sites combines them in one report. For separate reports, select each site individually.")
    with st.expander("Saving and recovery"):
        st.write("Saved site details carry forward. Monthly files and progress photos start fresh. Browser drafts and shared report versions are separate.")
        st.caption("Draft recovery uses a browser cookie and acknowledged server working copies; it may not recover when cookies are disabled or edits have not reached the app. Saving or generating a version shares it. Prepared by records attribution, not verified identity.")
    with st.sidebar.expander("Storage maintenance — all contracts", expanded=False):
        _render_storage_maintenance()
    from app.monthly_report_start_ui import choose_contract, select_sites, starting_choice
    contract = choose_contract(last_contract, field)
    if not contract:
        return
    period = month_selector(field, "report", suggested_period(operator_today(browser_timezone)))
    profiles = library.list_profiles(contract)
    completed_setup = st.session_state.pop("report_setup_done", None)
    remembered = last_profile if last_contract == contract else ""
    returning = any(p.key == remembered for p in profiles) and not completed_setup
    site_box = st.expander("Report sites — expand to change", expanded=False) if returning else st.container()
    with site_box:
        candidate, existing = select_sites(contract, profiles, remembered, field, completed_setup)
    if not candidate:
        return
    if not existing:
        starting_choice(candidate, profiles, period, "", field)
        return
    selected = existing.key
    state = library.load_profile(contract, selected)
    profile = state.profile
    st.subheader(profile.title)
    st.caption(profile.scope_type.replace("_", " ").capitalize() + " · " + "; ".join(f.title for f in profile.facilities))
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
    if draft_key not in st.session_state or resume:
        # A replacement import/restart must not inherit unacknowledged text
        # callbacks even when the same sites, month and widget key are reused.
        st.session_state[prefix + "_rich_text_epoch"] = uuid4().hex
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
        draft = replace(draft, profile=pin(draft.profile, latest_master=not bool(snapshot) and not recovered_work))
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
            st.success("Recovered your unfinished changes from this browser. Completed report history is unchanged.")
    from app.monthly_report_setup import normalize_mbcx
    draft, removed_prices = client_table_draft(complete_guided_sections(normalize_mbcx(refresh_profile_identity(st.session_state[draft_key], profile))))
    if removed_prices:
        st.info("Price columns were left out of this working report: " + ", ".join(removed_prices) + ". The saved original remains available. Check the remaining wording and images for prices before download.")
    if snapshot:
        st.info(f"{period.label} saved report loaded.")
    elif prior_draft:
        st.info(f"{period.label} started from the saved {prior_draft.period.label} report for these sites.")
    else:
        st.info("Site details are ready. Update this month’s work below.")
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
    if candidate != profile:
        st.caption("The updated group name/scope will be remembered after you save it.")
        if st.button("Save group name", disabled=not prepared.strip(), key=prefix + "_rename_save"):
            library.save_profile(candidate, expected_revision=state.revision, actor=prepared, confirmed=True)
            st.session_state[draft_key] = replace(draft, profile=candidate)
            st.rerun()
    save_status = st.empty()
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
    if st.session_state.get(prefix + "_source_details_on_resume") and draft.sources:
        from app.monthly_report_source_details import facility_choice, source_date, KEEP_FACILITY
        from app.monthly_report_upload_ui import render_source_details
        needs_correction = any(
            source_date(source.service_date) is None
            or facility_choice(source, profile) in ("", KEEP_FACILITY)
            for source in draft.sources
        )
        review_key = field(prefix + "_review_saved_source_details", needs_correction)
        if st.checkbox("Review source dates and sites from saved files", key=review_key):
            st.caption("Correct the date or site beside each saved source. Original files and reviewed page decisions are retained.")
            corrections = {}
            for source in draft.sources:
                corrections[source.id] = render_source_details(
                    source, profile, prefix + "_resumed_" + source.id, field)
            if any(corrections[source.id] != source for source in draft.sources):
                draft = replace(draft, sources=tuple(corrections[source.id] for source in draft.sources))
                st.session_state[prefix + "_evidence"] = tuple(
                    replace(content, source=corrections.get(content.source.id, content.source))
                    for content in st.session_state.get(prefix + "_evidence", ()))
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
            st.caption(f"{contract} · {period.label} · " +
                       ", ".join(f.title for f in profile.facilities))
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
                # Do not repeat a "Cover and report details" step or a hidden
                # appearance/settings form. The starting-report photo gallery below
                # handles an imported cover image when its identity is uncertain.
                from app.monthly_report_section_ui import render_section_setup
                render_section_setup(contract, period, prepared, field, state=state,
                                     working_draft=replace(draft, blocks=tuple(blocks.values())),
                                     working_assets=tuple(assets.items()), working_revision=st.session_state[prefix + "_revision"])
                with st.expander("Report design and version"):
                    from app.monthly_report_designs_ui import render_design_status
                    render_design_status(draft)
                # Global design installation changes *future reports across all
                # contracts*. It is not a monthly report field or routine approval.
                with st.sidebar.expander("Master design administration — all contracts", expanded=False):
                    from app.monthly_report_designs_ui import render_design_settings
                    render_design_settings(replace(draft, blocks=tuple(blocks.values())), prefix)
            with preview_column:
                with st.container(key="monthly_cover_preview_sticky"):
                    from app.monthly_report_section_ui import render_pending_cover_selection
                    proposed_draft, proposed_assets = render_pending_cover_selection(
                        replace(draft, blocks=tuple(blocks.values())), assets, contract, period, state)
                    render_section_preview(proposed_draft, "cover", proposed_assets, prefix, deferred=True)
        for section in draft.sections:
            with workspace_section("monthly_" + section.key, section.title):
                st.divider()
                st.subheader(section.title, anchor="report-section-" + section.key)
                st.caption(section_help(section.key).guidance)
                editor_column, preview_column = workspace_columns("monthly_" + section.key)
                with editor_column:
                    draft, blocks = _render_ordered_section(draft, section, blocks, specs, state, prefix, assets, field)
                with preview_column:
                    if section.key in {"organization", "subcontractors", "training"} and not prepared.strip():
                        st.caption("Enter Prepared by above to view saved contact and team pages.")
                    else:
                        render_section_preview(replace(draft, blocks=tuple(blocks.values())), section.key, assets, prefix, deferred=True)
    blocks = {key: refresh_asset_source_context(block, draft.sources) for key, block in blocks.items()}
    draft = complete_guided_sections(replace(draft, blocks=tuple(blocks.values())))
    footer = blocks.get("footer_text")
    if footer:
        draft = replace(draft, address_line=footer.text if footer.source != "Omit" else "")
    st.session_state[draft_key] = draft
    if snapshot and snapshot.draft.fingerprint == draft.fingerprint:
        save_status.success(f"Saved · version {snapshot.revision} · {period.label}")
    elif prior_draft:
        save_status.info(f"Starting from the saved {prior_draft.period.label} report. Monthly work and attachments start fresh; site information carries forward.")
    else:
        save_status.info("Your selected design is ready. Changes are kept for this browser when automatic recovery is available.")
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
        if st.button("Accept current revision", key=prefix + "_accept_revision", disabled=not accept):
            st.session_state[prefix + "_revision"] = current_revision
            st.rerun()
    with st.expander("Shared report history", expanded=False):
        st.caption("Saving a version adds it to shared report history. Browser draft recovery is separate.")
        if st.button("Save shared version", key=prefix + "_save", disabled=conflict or not prepared.strip()):
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
                    st.warning("The report version was saved, but its older browser copy still needs review.")
            record_report_preferences(browser_token, contract, selected)
            record_report_preparer(browser_token, contract, selected, prepared)
            st.success("Report version saved in the shared history.")
            st.rerun()
    with st.expander("Start over on this browser"):
        st.caption("Discard only this browser's unfinished changes for these sites and this month. Existing report versions, contract information and other browsers stay unchanged.")
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
    package = st.session_state.get(prefix + "_package")
    if package and package.fingerprint != draft.fingerprint:
        st.session_state.pop(prefix + "_package", None)
        package = None
    st.divider()
    with st.container():
        st.subheader("Review and download", anchor="report-review")
        from app.monthly_report_editor import review_client_images
        if prepared.strip():
            draft = review_client_images(draft, assets, prefix, field)
        st.session_state[draft_key] = draft
        if recovery_available and snapshot and snapshot.draft.fingerprint == draft.fingerprint:
            # The complete current version already exists in immutable history;
            # no new browser journal is necessary after Generate/Save.
            save_status.success(f"Saved · version {snapshot.revision} · {period.label}")
        elif recovery_available:
            try:
                previous_sequence = st.session_state.get(prefix + "_active_sequence", 0)
                recovered = active_work.save(browser_token, draft,
                    expected_revision=previous_sequence,
                    base_snapshot_revision=st.session_state[prefix + "_revision"],
                    expected_generation=st.session_state.get(prefix + "_active_generation", ""),
                    assets=assets)
                st.session_state[prefix + "_active_sequence"] = recovered.revision
                st.session_state[prefix + "_active_generation"] = recovered.generation
                save_status.success("Current edits kept for this browser. Completed report versions remain unchanged.")
                if recovered.revision != previous_sequence:
                    record_report_preferences(browser_token, contract, selected)
                    if prepared.strip():
                        record_report_preparer(browser_token, contract, selected, prepared)
            except active_work.ActiveWorkConflict:
                save_status.error("Another tab or a new working copy has newer changes. "
                                  "These edits are still on this page but were not kept for recovery. "
                                  "Reload and compare before trying again.")
            except (library.LibraryError, OSError):
                save_status.error("Automatic recovery could not keep these edits. "
                                  "Your current text remains on this page, but is not saved for a refresh. "
                                  "Try another edit to retry, or save a report version before leaving.")
        else:
            if snapshot and snapshot.draft.fingerprint == draft.fingerprint:
                # A completed/saved version is still saved, even when cookies
                # prevent separately retaining unfinished browser changes.
                save_status.success(f"Saved · version {snapshot.revision} · {period.label}")
                st.caption("Automatic recovery for new edits is unavailable in this browser.")
            else:
                save_status.warning("Automatic recovery is unavailable in this browser. Save a report version before leaving.")
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
        for check in checks:
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
        st.caption("Creating files also saves a shared report version. Any save failure will be shown.")
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
            except (ValueError, OSError) as exc:
                st.warning(f"Downloads are ready, but this version could not be saved: {exc}")
        if package:
            st.success("Ready to download")
            sizes = f"DOCX {len(package.docx) / (1024 * 1024):.1f} MB"
            if package.pdf:
                sizes += f" · PDF {len(package.pdf) / (1024 * 1024):.1f} MB"
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
