"""Exact, bounded correction of unsafe table cells in the native report owner.

The normal table grid is withheld *only* while one exact cell is being
corrected. No parallel copy is rendered, no edit is applied on navigation,
and an obsolete report/source/row cannot be replaced by a sibling.
"""
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from html import escape
import json
import re
from uuid import uuid4

import streamlit as st

from app.monthly_report_correction_targets import report_identity


INVALID = re.compile(r"[\x00-\x08\x0e-\x1b\x1f\ud800-\udfff\ufffe\uffff]")
TYPES = ("pricing", "placeholder", "text_character")


@dataclass(frozen=True)
class CellTarget:
    report: str
    block: str
    revision: str
    table: int  # -1 for primary rows, otherwise imported table index
    table_reference: str
    row: int
    column: int
    value: str
    code: str

    @property
    def token(self):
        return sha256(json.dumps(asdict(self), sort_keys=True,
                                 ensure_ascii=True).encode()).hexdigest()


def unsafe(text, code):
    if code == "pricing":
        from app.monthly_report_content_policy import contains_price
        return contains_price(text)
    if code == "placeholder":
        from app.monthly_report_checks import placeholder_matches
        return bool(placeholder_matches(text))
    if code == "text_character":
        return bool(INVALID.search(text))
    return False


def candidates(draft, key, code):
    if code not in TYPES:
        return ()
    matches = [b for b in draft.blocks if b.key == key]
    if len(matches) != 1:
        return ()
    block = matches[0]
    if block.source == "Omit":
        return ()
    targets = []
    primary_specs = [spec for section in draft.sections if section.included
                     for spec in section.blocks if spec.key == key]
    primary = primary_specs[0] if len(primary_specs) == 1 else None
    if len(primary_specs) > 1:
        return ()  # Duplicate owners must be resolved before editing any row.
    from app.monthly_report_content_policy import (
        ambiguous_price_columns, table_price_columns, table_has_pricing)
    for number, table in ((-1, None), *enumerate(block.extra_tables)):
        rows = block.rows if table is None else table.rows
        reference = "" if table is None else table.reference
        headings = (tuple(spec.title for spec in primary.columns) if table is None
                    and primary is not None else () if table is None else table.columns)
        price_columns = set(table_price_columns(headings, rows)) if code == "pricing" else set()
        ambiguous = set(ambiguous_price_columns(headings, rows)) if code == "pricing" else set()
        for n, row in enumerate(rows):
            direct = {c for c, value in enumerate(row) if unsafe(value, code)}
            flagged = set(direct)
            if code == "pricing":
                # The existing price gate can detect an amount spread across
                # separate table cells (e.g. Total | 500) even if neither cell
                # alone matches contains_price. Bind the exact physical amount
                # position rather than asking to edit unrelated report text.
                row_flagged = table_has_pricing(headings, (row,),
                    work_orders=bool(primary and table is None
                                    and primary.type == "work_order_grid"))
                if row_flagged:
                    flagged.update(c for c in price_columns | ambiguous
                                   if c < len(row) and str(row[c]).strip())
                    if not flagged:
                        numeric = [c for c, value in enumerate(row)
                                   if re.search(r"\\d", str(value))]
                        if numeric:
                            flagged.add(numeric[-1])
            for column in sorted(flagged):
                targets.append(CellTarget(report_identity(draft), key, block.fingerprint,
                    number, reference, n, column, row[column], code))
    return tuple(targets)


def resolve(draft, target):
    if not isinstance(target, CellTarget) or target.report != report_identity(draft):
        return None
    blocks = [block for block in draft.blocks if block.key == target.block]
    if len(blocks) != 1 or blocks[0].fingerprint != target.revision:
        return None
    block = blocks[0]
    if block.source == "Omit":
        return None
    if target.table == -1:
        rows, reference = block.rows, ""
    elif 0 <= target.table < len(block.extra_tables):
        table = block.extra_tables[target.table]
        rows, reference = table.rows, table.reference
    else:
        return None
    if reference != target.table_reference or not 0 <= target.row < len(rows):
        return None
    row = rows[target.row]
    if not 0 <= target.column < len(row) or row[target.column] != target.value:
        return None
    if target not in candidates(draft, target.block, target.code):
        return None
    return block


def queue(prefix, target, scope):
    from app.monthly_report_guided import _rich_text_scope
    state = st.session_state
    draft = state.get(prefix + "_draft")
    current = state.get(prefix + "_table_cell_repair")
    if (isinstance(current, dict) and current.get("target") != target
            and current.get("scope") == scope):
        state[prefix + "_table_cell_repair_notice"] = (
            "Finish or cancel the current exact cell correction before choosing another. "
            "Your typed value has not been discarded.")
        return
    if (draft is None or scope != _rich_text_scope(prefix)
            or resolve(draft, target) is None):
        state[prefix + "_table_cell_repair_notice"] = (
            "That table cell changed or is unavailable. Existing edits remain; "
            "review the current warning.")
        return
    state[prefix + "_table_cell_repair"] = {
        "target": target, "scope": scope, "nonce": uuid4().hex,
        "reveal": True}


def render_links(check, draft, prefix):
    if not check.blocking or check.code not in TYPES:
        return
    from app.monthly_report_guided import _rich_text_scope
    # Photo captions and source-page evidence already have their own owner.
    if check.targets:
        return
    matches = candidates(draft, check.block_key, check.code)
    if not matches:
        return
    # One rendered control for a potentially large imported file. The native
    # selectbox lists exact physical positions; changing selection never edits.
    if len(matches) > 12:
        choice = st.selectbox("Affected " + check.code + " table cell",
            list(range(len(matches))),
            format_func=lambda n: ("Imported " + str(matches[n].table + 1)
                if matches[n].table >= 0 else "Primary") +
                " · row " + str(matches[n].row + 1) +
                " · column " + str(matches[n].column + 1),
            key=prefix + "_unsafe_cell_select_" + check.block_key + "_" +
                check.code + "_" + draft.fingerprint)
        matches = (matches[choice],)
    for target in matches:
        source_label = ("table rows" if target.table == -1 else
                        "imported table " + str(target.table + 1))
        label = ("Correct " + source_label + " · row " + str(target.row + 1) +
                 " · column " + str(target.column + 1))
        st.button(label, key=prefix + "_unsafe_cell_" + target.token,
                  on_click=queue, args=(prefix, target, _rich_text_scope(prefix)))


def edit_active_cell(draft, block, prefix, field):
    """Return (block, editing). Editing blocks only the competing grid."""
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_correction_ui import native_warning_marker, _identity
    state = st.session_state
    request = state.get(prefix + "_table_cell_repair")
    if not isinstance(request, dict):
        return block, False
    target = request.get("target")
    if not isinstance(target, CellTarget) or target.block != block.key:
        return block, False
    if (request.get("scope") != _rich_text_scope(prefix)
            or resolve(draft, target) != block):
        state.pop(prefix + "_table_cell_repair", None)
        state[prefix + "_table_cell_repair_notice"] = (
            "The selected table cell changed. No other row or cell was edited.")
        return block, False
    key = prefix + "_table_cell_" + target.token
    st.caption(("Primary table" if target.table == -1 else
                "Imported table " + str(target.table + 1)) +
               " · row " + str(target.row + 1) + " · column " +
               str(target.column + 1) +
               ". Edit the unsafe value below; all other source cells are retained.")
    marker = native_warning_marker(prefix, target.code,
                                   target.block + ":table:" + str(target.table) +
                                   ":row:" + str(target.row) + ":column:" + str(target.column),
                                   target.revision, key, kind="textarea")
    if request.get("reveal"):
        match = re.search(r'id="(report-correction-[a-f0-9]{64})"', marker)
        if match:
            marker += ('<a class="enfra-page-correction-request" data-report-identity="' +
                _identity(prefix) + '" data-token="' +
                escape(request["nonce"], quote=True) + '" href="#' +
                match.group(1) + '" hidden></a>')
        state[prefix + "_table_cell_repair"] = {**request, "reveal": False}
    st.markdown(marker, unsafe_allow_html=True)
    edited = st.text_area("Exact report table cell",
                          value=target.value, key=field(key, target.value), height=100)
    if st.button("Apply correction to this exact cell",
                 key=prefix + "_apply_table_cell_" + target.token):
        if edited == target.value:
            st.warning("The value is unchanged; correct or explicitly clear it first.")
            return block, True
        if target.table == -1:
            rows = [list(row) for row in block.rows]
            rows[target.row][target.column] = edited
            changed = replace(block, rows=tuple(tuple(row) for row in rows),
                              reviewed_fingerprint="", client_reviewed_fingerprint="")
        else:
            tables = list(block.extra_tables)
            rows = [list(row) for row in tables[target.table].rows]
            rows[target.row][target.column] = edited
            tables[target.table] = replace(tables[target.table],
                                           rows=tuple(tuple(row) for row in rows))
            changed = replace(block, extra_tables=tuple(tables),
                              reviewed_fingerprint="", client_reviewed_fingerprint="")
        state.pop(prefix + "_table_cell_repair", None)
        state[prefix + "_period_editor_refresh"] = True
        return changed, True
    if st.button("Cancel this cell correction without applying",
                 key=prefix + "_cancel_table_cell_" + target.token):
        state.pop(prefix + "_table_cell_repair", None)
        state[prefix + "_period_editor_refresh"] = True
    return block, True


def finish_notice(prefix):
    notice = st.session_state.pop(prefix + "_table_cell_repair_notice", None)
    if notice:
        st.warning(notice)
