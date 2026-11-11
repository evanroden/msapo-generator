"""Exact native owner routing for chart warnings.

This module does not approve, remove, or normalize chart content. Every action
checks the currently displayed report/block and refuses stale or ambiguous
node keys. A problem with duplicate node identities is reported as a recovery
decision rather than focusing a sibling's field.
"""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from html import escape
from uuid import uuid4

import streamlit as st


def node_owner(block, message):
    """Return (position, field) of a correctable native field, or None."""
    nodes = block.org_nodes
    keys = [n.key for n in nodes]
    if not nodes or any(not key or count != 1 for key, count in
                        Counter(keys).items()):
        return None
    if message.startswith("Choose the editable chart"):
        return None
    if "name or role" in message:
        return next(((n, "name") for n, item in enumerate(nodes)
                     if not (item.name.strip() or item.role.strip())), None)
    if "under 100 characters" in message:
        return next(((n, field) for n, item in enumerate(nodes)
                     for field in ("name", "role", "team")
                     if len(getattr(item, field)) > 100), None)
    if "existing manager" in message:
        known = set(keys)
        return next(((n, "manager") for n, item in enumerate(nodes)
                     if item.reports_to and item.reports_to not in known), None)
    if "reporting lines form a loop" in message:
        by_key = {item.key: item for item in nodes}
        for index, item in enumerate(nodes):
            seen, current = set(), item
            while current and current.key not in seen:
                seen.add(current.key)
                current = by_key.get(current.reports_to)
            if current:
                return index, "manager"
    if "too much text" in message:
        index = max(range(len(nodes)), key=lambda n: sum(
            len(getattr(nodes[n], f)) for f in ("name", "role", "team")))
        field = max(("name", "role", "team"),
                    key=lambda field: len(getattr(nodes[index], field)))
        return index, field
    return None


def current_chart(draft, block_key, revision, message):
    matches = [b for b in draft.blocks if b.key == block_key]
    if len(matches) != 1 or matches[0].fingerprint != revision:
        return None
    block = matches[0]
    if block.source == "Omit":
        return None
    from app.monthly_report_checks import preflight
    if not any(c.code == "org_chart" and c.block_key == block_key
               and c.message == message and c.blocking for c in preflight(draft)):
        return None
    return block


def queue_chart(prefix, block_key, revision, message, scope):
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_organization_ui import _change_part
    state = st.session_state
    draft = state.get(prefix + "_draft")
    block = current_chart(draft, block_key, revision, message) if draft else None
    owner = node_owner(block, message) if block else None
    if scope != _rich_text_scope(prefix) or owner is None:
        state[prefix + "_chart_warning_notice"] = (
            "The exact chart field changed or cannot be uniquely identified. "
            "Review the current chart and its saved source before retrying.")
        return
    _change_part(prefix, prefix + "_organization_change", "org_chart")
    state[prefix + "_chart_warning_request"] = {
        "block": block_key, "revision": revision, "message": message,
        "index": owner[0], "field": owner[1], "scope": scope,
        "nonce": uuid4().hex}


def chart_field_markup(prefix, block, index, field, native_key):
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_correction_ui import _identity
    request = st.session_state.get(prefix + "_chart_warning_request")
    if not isinstance(request, dict) or (request.get("block"), request.get("revision"),
        request.get("index"), request.get("field"), request.get("scope")) != (
        block.key, block.fingerprint, index, field, _rich_text_scope(prefix)):
        return ""
    from app.monthly_report_correction_ui import native_warning_marker
    owner = block.key + ":node:" + str(index)
    marker = native_warning_marker(prefix, "org_chart", owner,
                                    block.fingerprint, native_key,
                                    kind="combobox" if field == "manager" else "input")
    import re
    match = re.search(r'id="(report-correction-[a-f0-9]{64})"', marker)
    if match is None:
        return ""
    st.session_state.pop(prefix + "_chart_warning_request", None)
    return marker + ('<a class="enfra-page-correction-request" data-report-identity="' +
        _identity(prefix) + '" data-token="' + escape(request["nonce"], quote=True) +
        '" href="#' + match.group(1) + '" hidden></a>')


def render_chart_links(check, draft, prefix):
    if not check.blocking or check.code != "org_chart":
        return
    from app.monthly_report_guided import _rich_text_scope
    blocks = [block for block in draft.blocks if block.key == check.block_key]
    if len(blocks) != 1:
        st.caption("This chart has no unique block identity. Restore its original scope first.")
        return
    block = current_chart(draft, check.block_key, blocks[0].fingerprint, check.message)
    if block is None:
        return
    if node_owner(block, check.message) is not None:
        n, field = node_owner(block, check.message)
        st.button("Correct chart position " + str(n + 1) + " · " + field,
                  key=prefix + "_warning_chart_" + sha256(
                      (check.message + "\\0" + block.fingerprint).encode()).hexdigest(),
                  on_click=queue_chart,
                  args=(prefix, block.key, block.fingerprint, check.message,
                        _rich_text_scope(prefix)))
        return
    if block.org_nodes and block.asset_hashes and check.message.startswith(
            "Choose the editable chart"):
        st.caption("Choose which chart representation this report should include. "
                   "Its original image remains in saved assets.")
        for choice, label in (("editable", "Use editable chart only"),
                              ("uploaded", "Use uploaded chart only")):
            st.button(label, key=prefix + "_warning_chart_choice_" + choice +
                      "_" + block.fingerprint,
                      on_click=resolve_representation,
                      args=(prefix, block.key, block.fingerprint, choice))
    else:
        keys = [node.key for node in block.org_nodes]
        if not all(key and n == 1 for key, n in Counter(keys).items()):
            st.button("Repair duplicate chart position identities",
                      key=prefix + "_warning_duplicate_chart_" + block.fingerprint,
                      on_click=queue_duplicate_chart,
                      args=(prefix, block.key, block.fingerprint,
                            check.message, _rich_text_scope(prefix)))
        else:
            st.caption("The chart identity or shape is not editable through a unique "
                       "native position. Keep both originals and restore a chart "
                       "with unique position IDs before generating.")


def resolve_representation(prefix, block_key, revision, choice):
    current = st.session_state.get(prefix + "_draft")
    if current is None:
        return
    matches = [b for b in current.blocks if b.key == block_key]
    if (len(matches) != 1 or matches[0].fingerprint != revision
            or not matches[0].org_nodes or not matches[0].asset_hashes):
        st.session_state[prefix + "_chart_warning_notice"] = (
            "The chart changed before this choice. Current content was retained.")
        return
    block = matches[0]
    if choice == "uploaded":
        updated = replace(block, org_nodes=(), client_reviewed_fingerprint="")
    elif choice == "editable":
        updated = replace(block, asset_hashes=(), asset_captions=(),
                          asset_instances=(), asset_provenance=(),
                          client_asset_reviews=(), client_reviewed_fingerprint="")
    else:
        return
    st.session_state[prefix + "_draft"] = replace(current, blocks=tuple(
        updated if b is block else b for b in current.blocks))
    st.session_state[prefix + "_period_editor_refresh"] = True


def finish_chart_notice(prefix):
    if st.session_state.pop(prefix + "_chart_warning_request", None):
        st.session_state[prefix + "_chart_warning_notice"] = (
            "The intended chart field did not mount. Current edits remain; "
            "open the chart editor and correct the existing position.")
    notice = st.session_state.pop(prefix + "_chart_warning_notice", None)
    if notice:
        st.warning(notice)


def queue_duplicate_chart(prefix, key, revision, message, scope):
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_organization_ui import _change_part
    draft = st.session_state.get(prefix + "_draft")
    block = current_chart(draft, key, revision, message) if draft else None
    if not block or scope != _rich_text_scope(prefix):
        st.session_state[prefix + "_chart_warning_notice"] = (
            "The chart identities changed before this action. Retained the current chart.")
        return
    ids = [n.key for n in block.org_nodes]
    if all(n and v == 1 for n, v in Counter(ids).items()):
        return
    _change_part(prefix, prefix + "_organization_change", "org_chart")
    st.session_state[prefix + "_duplicate_chart_recovery"] = revision


def repair_duplicate_positions(block, prefix):
    """Return (block, handled); chart fields have unique controls only afterward."""
    keys = [item.key for item in block.org_nodes]
    groups = Counter(keys)
    if all(key and count == 1 for key, count in groups.items()):
        return block, False
    st.warning("Chart position identifiers are duplicated or blank. The exact "
               "physical positions are shown below. Every person and role is retained; "
               "ambiguous reporting lines need an explicit manager selection.")
    p = prefix + "_org_identity_recovery_" + block.fingerprint
    nodes = block.org_nodes
    reserved = set(key for key, count in groups.items() if count == 1 and key)
    replacements = []
    for index, node in enumerate(nodes):
        if node.key and groups[node.key] == 1:
            replacements.append(node.key)
            continue
        candidate = "chart-position-" + str(index + 1) + "-" + sha256(
            (block.fingerprint + ":position:" + str(index)).encode()).hexdigest()[:8]
        while candidate in reserved:
            candidate += "_"
        reserved.add(candidate)
        replacements.append(candidate)
    selections = []
    unresolved = False
    for n, item in enumerate(nodes):
        st.caption("Position " + str(n + 1) + " · " +
                   (" / ".join(filter(None, (item.name, item.role))) or "Untitled") +
                   " · original ID " + (item.key or "(blank)") +
                   " · corrected ID " + replacements[n])
        candidates = [i for i in range(len(nodes)) if i != n]
        matches = [i for i, other in enumerate(nodes)
                   if other.key and other.key == item.reports_to]
        if not item.reports_to:
            chosen = -1
        elif len(matches) == 1:
            chosen = matches[0]
        else:
            chosen = "review"
        choices = ["review", -1, *candidates] if chosen == "review" else [-1, *candidates]
        selection = st.selectbox("Reports to for position " + str(n + 1),
            choices, index=choices.index(chosen),
            format_func=lambda option: ("Choose manager explicitly" if option == "review"
                else "No manager" if option == -1 else
                "Position " + str(option + 1) + " · " +
                (nodes[option].name or nodes[option].role or "(unnamed)")),
            key=p + "_manager_" + str(n))
        selections.append(selection)
        unresolved = unresolved or selection == "review"
    if st.button("Confirm unique position IDs and reviewed reporting lines",
                 disabled=unresolved, key=p + "_confirm"):
        updated = tuple(replace(node, key=replacements[n],
                          reports_to=("" if manager == -1 else replacements[manager]))
                        for n, (node, manager) in enumerate(zip(nodes, selections)))
        from app.monthly_report_visuals import validate_org
        try:
            validate_org(updated)
        except ValueError as exc:
            st.warning(str(exc) + " Reporting lines must be corrected before applying.")
            return block, True
        st.session_state.pop(prefix + "_duplicate_chart_recovery", None)
        st.session_state[prefix + "_period_editor_refresh"] = True
        return replace(block, org_nodes=updated,
                       reviewed_fingerprint="", client_reviewed_fingerprint=""), True
    return block, True
