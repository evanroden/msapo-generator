"""Scoped warning owner regressions; synthetic report data only.

Native pointer, keyboard, reload and real output remain separate hosted checks.
"""
from dataclasses import replace
from types import SimpleNamespace
import re

from app.monthly_report_checks import ReportCheck
from app.monthly_report_model import ReportTable, ResolvedBlock
from app import monthly_report_correction_ui as correction
from app import monthly_report_table_column_recovery as columns
from tests.test_monthly_report_native_layout import draft as synthetic_draft


def _capture(monkeypatch, module, *, pressed=False, typed=None):
    seen = {"markup": [], "buttons": [], "captions": [], "inputs": []}
    monkeypatch.setattr(module.st, "markdown",
                        lambda value, **kwargs: seen["markup"].append(value))
    monkeypatch.setattr(module.st, "caption",
                        lambda value, **kwargs: seen["captions"].append(value))
    def button(label, **kwargs):
        seen["buttons"].append((label, kwargs))
        return pressed
    monkeypatch.setattr(module.st, "button", button)
    if typed is not None:
        def input_value(label, **kwargs):
            seen["inputs"].append((label, kwargs))
            return typed[len(seen["inputs"]) - 1]
        monkeypatch.setattr(module.st, "text_input", input_value)
    return seen


def _link_target(markup):
    matches = re.findall(r'href="#(report-correction-[a-f0-9]{64})"', markup)
    assert len(matches) == 1
    return matches[0]


def _marker_target(markup):
    matches = re.findall(r'id="(report-correction-[a-f0-9]{64})"', markup)
    assert len(matches) == 1
    return matches[0]


def test_prepared_by_links_only_to_exact_native_input(monkeypatch):
    report = replace(synthetic_draft(), prepared_by="")
    seen = _capture(monkeypatch, correction)
    check = ReportCheck("prepared_by", "Enter who prepared this report.", True)
    correction.render_native_warning_links(check, report, "synthetic")
    target = _link_target("".join(seen["markup"]))
    from app.monthly_report_correction_targets import report_identity
    marker = correction.native_warning_marker("synthetic", "prepared_by", "report",
                                               report_identity(report), "prepared-native",
                                               kind="input")
    assert _marker_target(marker) == target
    assert 'data-field-kind="input"' in marker
    assert 'data-field-key="prepared-native"' in marker
    seen["markup"].clear()
    correction.render_native_warning_links(check, replace(report, prepared_by="Ready"), "synthetic")
    assert not seen["markup"]


def test_stale_revisions_or_different_owner_do_not_reuse_marker():
    first = correction.native_warning_marker("s", "carried_period", "activity_summary",
                                              "old-revision", "old-widget")
    newer = correction.native_warning_marker("s", "carried_period", "activity_summary",
                                              "new-revision", "new-widget")
    sibling = correction.native_warning_marker("s", "carried_period", "training_summary",
                                                "old-revision", "sibling-widget")
    assert len({_marker_target(first), _marker_target(newer), _marker_target(sibling)}) == 3


def test_explicit_report_only_action_preserves_omission_and_does_not_auto_approve(monkeypatch):
    block = ResolvedBlock("work_orders", "Omit", text="Retained original",
                          pending_library_save=True, rows=(("A", "B"),))
    spec = SimpleNamespace(allowed_sources=("Omit", "This month", "Replace once"))
    no_click = _capture(monkeypatch, correction)
    assert correction.render_inline_block_repairs(spec, block, "sample") == block
    assert len(no_click["buttons"]) == 1
    clicked = _capture(monkeypatch, correction, pressed=True)
    result = correction.render_inline_block_repairs(spec, block, "sample")
    assert result.source == "Omit"
    assert result.pending_library_save is False
    assert result.text == block.text and result.rows == block.rows
    assert result.reviewed_fingerprint == block.reviewed_fingerprint
    assert clicked["buttons"][0][1]["key"].endswith(block.fingerprint)


def test_source_choice_and_photo_density_require_explicit_click(monkeypatch):
    block = ResolvedBlock("work_orders", "Unsupported", rows=(("extreme", "2099-12-31"),),
                          photos_per_page=19)
    spec = SimpleNamespace(allowed_sources=("This month",))
    _capture(monkeypatch, correction, pressed=False)
    assert correction.render_inline_block_repairs(spec, block, "sample") == block
    _capture(monkeypatch, correction, pressed=True)
    fixed = correction.render_inline_block_repairs(spec, block, "sample")
    assert fixed.source == "This month" and fixed.photos_per_page == 3
    assert fixed.rows == block.rows
    assert fixed.reviewed_fingerprint == block.reviewed_fingerprint


def test_missing_table_headings_are_positional_not_inferred(monkeypatch):
    table = ReportTable((), (("v1", "", "v3"), ("v4", "v5")), "source:first")
    block = ResolvedBlock("work_orders", "This month", extra_tables=(table,))
    assert columns.missing_positions(table) == (0, 1, 2)
    seen = _capture(monkeypatch, columns, typed=("A", "", "A"))
    unchanged = columns.edit_missing_positions(table, block, 0, "scope", lambda key, value: key)
    assert unchanged == table
    assert len(seen["inputs"]) == 3
    assert all(str(index + 1) in seen["inputs"][index][0] for index in range(3))
    _capture(monkeypatch, columns, pressed=True, typed=("A", "", "A"))
    repaired = columns.edit_missing_positions(table, block, 0, "scope", lambda key, value: key)
    assert repaired.columns == ("A", "", "A")
    assert repaired.rows == table.rows and repaired.reference == table.reference
    assert table.columns == ()


def test_duplicate_imported_tables_have_distinct_native_correction_owners(monkeypatch):
    table = ReportTable(("Name",), (("pump", "2027-01-01", "99999999999999999.999"),),
                        "same-name-and-bytes")
    block = ResolvedBlock("work_orders", "This month", extra_tables=(table, table))
    report = synthetic_draft(block)
    seen = _capture(monkeypatch, correction)
    for n in (1, 2):
        check = ReportCheck("table_columns",
                            f"Imported table {n}, row 1 in work orders has 3 cells but 1 columns.",
                            True, block.key)
        correction.render_imported_table_warning_links(check, report, "scope")
    links = [_link_target(markup) for markup in seen["markup"]]
    assert len(links) == 2 and links[0] != links[1]
    stamps = []
    for index in (0, 1):
        rows = _capture(monkeypatch, columns, typed=("Added", ""))
        columns.edit_missing_positions(table, block, index, "scope", lambda key, value: key)
        stamps.append(_marker_target("".join(rows["markup"])))
    assert links == stamps


def test_source_recovery_names_duplicate_filenames_but_preserves_source_ids(monkeypatch):
    report = synthetic_draft()
    first = SimpleNamespace(id="source-a", filename="same-name.pdf")
    second = SimpleNamespace(id="source-b", filename="same-name.pdf")
    report = replace(report, sources=(first, second))
    seen = _capture(monkeypatch, correction)
    warning = ReportCheck("unavailable_source", "Saved source unavailable", True,
                          targets=(SimpleNamespace(source_id=first.id),
                                   SimpleNamespace(source_id=second.id)))
    correction.render_source_recovery_links(warning, report, "scope")
    assert len(seen["buttons"]) == 2
    assert seen["buttons"][0][1]["key"] != seen["buttons"][1][1]["key"]
    assert seen["buttons"][0][1]["args"][-1] == "source-a"
    assert seen["buttons"][1][1]["args"][-1] == "source-b"
    assert all("same-name.pdf" in caption for caption in seen["captions"])


def test_nonblocking_or_noneditable_cases_do_not_get_false_native_target(monkeypatch):
    report = synthetic_draft(ResolvedBlock("work_orders", "This month"))
    seen = _capture(monkeypatch, correction)
    for code in ("duplicate_blocks", "title", "follow_up_identity",
                 "table_missing_columns", "org_chart"):
        correction.render_native_warning_links(ReportCheck(code, code, True, "work_orders"),
                                               report, "scope")
    correction.render_native_warning_links(ReportCheck("prepared_by", "", False),
                                           replace(report, prepared_by=""), "scope")
    assert not seen["markup"]


def test_unique_blank_section_title_has_direct_native_field_but_existing_literal_is_preserved(monkeypatch):
    from app.monthly_report_model import SectionSpec
    section = SectionSpec("activity", "2", "", ())
    original = synthetic_draft()
    report = replace(original, sections=(section,))
    seen = _capture(monkeypatch, correction)
    correction.render_native_warning_links(ReportCheck("title", "", True, "activity"),
                                           report, "scope")
    token = _link_target("".join(seen["markup"]))
    seen = _capture(monkeypatch, correction, typed=("Literal heading",))
    revised = correction.edit_missing_section_title(section, "scope", lambda key, value: key)
    assert token == _marker_target("".join(seen["markup"]))
    assert revised.title == "Literal heading"
    assert revised.number == section.number and revised.blocks == section.blocks
    seen = _capture(monkeypatch, correction)
    assert correction.edit_missing_section_title(revised, "scope", lambda key, value: key) == revised
    assert not seen["markup"]


def test_duplicate_section_keys_refuse_title_link(monkeypatch):
    from app.monthly_report_model import SectionSpec
    a = SectionSpec("activity", "2", "", ())
    b = SectionSpec("activity", "3", "", ())
    report = replace(synthetic_draft(), sections=(a, b))
    seen = _capture(monkeypatch, correction)
    correction.render_native_warning_links(ReportCheck("title", "", True, "activity"),
                                           report, "scope")
    assert not seen["markup"]


def test_duplicate_followup_recovery_requires_click_and_preserves_each_item(monkeypatch):
    from app.monthly_report_model import ReportFollowUp
    first = ReportFollowUp("collision", "issue", "Pump 1", "2026-09",
                           update="Exact update 1")
    second = ReportFollowUp("collision", "issue", "Pump 2", "2026-09",
                            update="Exact update 2")
    report = replace(synthetic_draft(), follow_ups=(first, second))
    prefix = "repair-duplicate"
    monkeypatch.setattr(correction.st, "session_state", {prefix + "_draft": report})
    seen = _capture(monkeypatch, correction, pressed=False)
    check = ReportCheck("follow_up_identity", "Rows collide", True)
    correction.render_followup_identity_recovery(check, report, prefix)
    assert correction.st.session_state[prefix + "_draft"] == report
    assert seen["buttons"][0][1]["key"].endswith(report.fingerprint)

    def interrupted():
        raise RuntimeError("Expected current-draft rerun")
    monkeypatch.setattr(correction.st, "rerun", interrupted)
    _capture(monkeypatch, correction, pressed=True)
    import pytest
    with pytest.raises(RuntimeError, match="Expected current-draft rerun"):
        correction.render_followup_identity_recovery(check, report, prefix)
    updated = correction.st.session_state[prefix + "_draft"]
    assert [item.text for item in updated.follow_ups] == ["Pump 1", "Pump 2"]
    assert [item.update for item in updated.follow_ups] == ["Exact update 1", "Exact update 2"]
    assert updated.follow_ups[0].key == "collision"
    assert updated.follow_ups[1].key != "collision"
    assert updated.follow_ups[1].reviewed_fingerprint == ""


def test_duplicate_followup_recovery_refuses_stale_draft(monkeypatch):
    from app.monthly_report_model import ReportFollowUp
    first = ReportFollowUp("collision", "issue", "Pump A", "2026-09")
    second = ReportFollowUp("collision", "issue", "Pump B", "2026-09")
    warning_report = replace(synthetic_draft(), follow_ups=(first, second))
    later = replace(warning_report, prepared_by="Later updated preparer")
    prefix = "repair-stale"
    monkeypatch.setattr(correction.st, "session_state", {prefix + "_draft": later})
    _capture(monkeypatch, correction, pressed=True)
    monkeypatch.setattr(correction.st, "warning", lambda message: None)
    correction.render_followup_identity_recovery(
        ReportCheck("follow_up_identity", "Rows collide", True), warning_report, prefix)
    assert correction.st.session_state[prefix + "_draft"] == later


def test_section_and_item_recovery_is_explicit_and_positional(monkeypatch):
    from app.monthly_report_model import SectionSpec, ReportFollowUp
    from types import SimpleNamespace
    empty = SectionSpec("activity", "2", "Activity", (), included=False)
    issue = ReportFollowUp("issue-a", "issue", "First issue", "2026-09")
    other = ReportFollowUp("issue-b", "issue", "Second issue", "2026-09")
    report = replace(synthetic_draft(), sections=(empty,), follow_ups=(issue, other))
    state = {"p_draft": report}
    monkeypatch.setattr(correction, "st", SimpleNamespace(session_state=state))
    correction._apply_review_recovery("p", report, "include_section", target="activity")
    included = state["p_draft"]
    assert included.sections[0].included and included.follow_ups == (issue, other)
    correction._apply_review_recovery("p", included, "omit_followup",
                                      target="issue-b", position=1)
    revised = state["p_draft"]
    assert revised.follow_ups[0] == issue
    assert not revised.follow_ups[1].included
    assert revised.follow_ups[1].text == "Second issue"
    assert revised.follow_ups[1].reviewed_fingerprint == ""


def test_structural_recovery_never_discards_distinct_duplicate_records(monkeypatch):
    from app.monthly_report_model import SectionSpec
    from types import SimpleNamespace
    a = SectionSpec("activity", "2", "Activity A", ())
    b = SectionSpec("activity", "3", "Activity B", ())
    report = replace(synthetic_draft(), sections=(a, b))
    state = {"p_draft": report}
    monkeypatch.setattr(correction, "st", SimpleNamespace(session_state=state))
    correction._apply_review_recovery("p", report, "dedupe_sections")
    assert state["p_draft"] == report
    duplicate = replace(report, sections=(a, a))
    state["p_draft"] = duplicate
    correction._apply_review_recovery("p", duplicate, "dedupe_sections")
    assert state["p_draft"].sections == (a,)


def test_later_draft_refuses_stale_followup_omit(monkeypatch):
    from app.monthly_report_model import ReportFollowUp
    from types import SimpleNamespace
    a = ReportFollowUp("a", "proposal", "Original", "2026-09")
    old = replace(synthetic_draft(), follow_ups=(a,))
    newer = replace(old, follow_ups=(replace(a, text="Newer retained edit"),))
    state = {"p_draft": newer}
    monkeypatch.setattr(correction, "st", SimpleNamespace(session_state=state))
    correction._apply_review_recovery("p", old, "omit_followup", target="a", position=0)
    assert state["p_draft"] == newer


def test_fixed_table_width_correction_retains_physical_columns_and_all_source_cells(monkeypatch):
    from types import SimpleNamespace
    from app.monthly_report_model import BlockSpec, ColumnSpec, SectionSpec
    table = ResolvedBlock("work_orders", "This month", rows=(("A", "", "C"),))
    spec = BlockSpec("work_orders", "table", columns=(ColumnSpec("original", ""),))
    section = SectionSpec("activity", "2", "Activity", (spec,))
    report = replace(synthetic_draft(table), sections=(section,))
    state = {"p_draft": report}
    fields = []
    def text_input(label, **kwargs):
        fields.append((label, kwargs))
        return ["", "Replacement"][len(fields) - 1]
    monkeypatch.setattr(columns, "st", SimpleNamespace(
        session_state=state, markdown=lambda *a, **kw: None, warning=lambda *a: None,
        text_input=text_input, button=lambda *a, **kw: True, rerun=lambda: None))
    assert columns.fixed_width_defect(spec, table) == 2
    columns.edit_fixed_column_schema(
        ReportCheck("table_columns", "Row 1 in work orders has 3 cells but only 1 columns.",
                    True, "work_orders"), report, "p", lambda k,v: k)
    revised = state["p_draft"]
    assert revised.blocks == (table,)
    assert revised.sections[0].blocks[0].columns[0] == spec.columns[0]
    assert [c.title for c in revised.sections[0].blocks[0].columns] == ["", "", "Replacement"]
    assert len({c.key for c in revised.sections[0].blocks[0].columns}) == 3


def test_non_narrative_unsafe_captions_route_by_exact_picture_occurrence(monkeypatch):
    from types import SimpleNamespace
    from app.monthly_report_model import AssetInstance
    from app.monthly_report_checks import preflight
    from app.monthly_report_correction_targets import resolve_target
    image = "d" * 64 + ".png"
    block = ResolvedBlock("improvements", "This month",
        asset_hashes=(image, image),
        asset_instances=(AssetInstance("picture-one", image), AssetInstance("picture-two", image)),
        asset_captions=("Quoted cost $100", "Quoted cost $100"))
    report = synthetic_draft(block)
    checks = [check for check in preflight(report) if check.code == "pricing" and check.targets]
    assert len(checks) == 2
    targets = [check.targets[0] for check in checks]
    assert targets[0] != targets[1]
    assert [resolve_target(report, target)[1] for target in targets] == [0, 1]
    state = {"p_draft": report}
    callbacks = []
    monkeypatch.setattr(correction, "st", SimpleNamespace(
        session_state=state, button=lambda label, **kw: callbacks.append(kw),
        caption=lambda *a: None))
    from app import monthly_report_guided as guided
    monkeypatch.setattr(guided, "_rich_text_scope", lambda prefix: "editor-epoch")
    for check in checks:
        correction.render_photo_caption_links(check, report, "p")
    assert len(callbacks) == 2
    assert callbacks[0]["key"] != callbacks[1]["key"]
    callbacks[1]["on_click"](*callbacks[1]["args"])
    correction.consume_photo_caption("p", report, "editor-epoch")
    assert correction.photo_caption_request("p", report, block, 0) == ""
    assert 'enfra-page-correction-request' in correction.photo_caption_request(
        "p", report, block, 1)


def test_chart_warning_owner_is_position_specific():
    from app.monthly_report_model import OrgChartNode
    from app.monthly_report_org_warning import node_owner
    block = ResolvedBlock("org_chart", "This month",
        org_nodes=(OrgChartNode("a", "Ready", "Lead"),
                   OrgChartNode("b", "", "", "a")))
    assert node_owner(block, "Enter a name or role for each chart position.") == (1, "name")
    assert node_owner(replace(block, org_nodes=(
        OrgChartNode("a", "Ready", "Lead", "b"),
        OrgChartNode("b", "Helper", "Support", "a"))),
        "The reporting lines form a loop. A person cannot report back to themselves.") is not None
    assert node_owner(replace(block, org_nodes=(
        OrgChartNode("a", "Ready", "Lead"),
        OrgChartNode("a", "Other", "Support"))),
        "Each chart position needs its own identity.") is None


def test_exact_table_cell_recovery_preserves_duplicate_bytes_and_neighbouring_rows(monkeypatch):
    from app import monthly_report_non_narrative_recovery as cells
    from types import SimpleNamespace
    from app.monthly_report_model import ReportTable
    raw = ReportTable(("Description", "Amount"),
        (("Part", "$120"), ("Part", "$120")), "source:same.pdf")
    block = ResolvedBlock("work_orders", "This month", extra_tables=(raw,))
    report = synthetic_draft(block)
    targets = cells.candidates(report, "work_orders", "pricing")
    assert len(targets) == 2 and targets[0].token != targets[1].token
    assert [cells.resolve(report, target) for target in targets] == [block, block]
    state = {"p_draft": report}
    monkeypatch.setattr(cells, "st", SimpleNamespace(session_state=state))
    from app import monthly_report_guided as guided
    monkeypatch.setattr(guided, "_rich_text_scope", lambda prefix: "scope")
    cells.queue("p", targets[1], "scope")
    assert state["p_table_cell_repair"]["target"] == targets[1]
    cells.queue("p", targets[0], "scope")
    assert state["p_table_cell_repair"]["target"] == targets[1]
    assert "Finish or cancel" in state["p_table_cell_repair_notice"]
    assert cells.resolve(replace(report, blocks=(replace(block, extra_tables=(
        replace(raw, rows=(("Part", "$200"), raw.rows[1])),)),)),
        targets[0]) is None
    assert state["p_draft"] == report


def test_exact_table_cell_apply_changes_only_selected_cell_and_clears_review(monkeypatch):
    from app import monthly_report_non_narrative_recovery as cells
    from types import SimpleNamespace
    raw = ReportTable(("Item", "Cost"), (("First", "$100"), ("Second", "$100")),
                      "same-imported-table")
    block = ResolvedBlock("work_orders", "This month", extra_tables=(raw,))
    report = synthetic_draft(block)
    target = cells.candidates(report, "work_orders", "pricing")[1]
    state = {"p_draft": report}
    from app import monthly_report_guided as guided
    monkeypatch.setattr(guided, "_rich_text_scope", lambda prefix: "scope")
    monkeypatch.setattr(cells, "st", SimpleNamespace(session_state=state))
    cells.queue("p", target, "scope")
    controls = []
    import streamlit as real_st
    def button(label, **kwargs):
        controls.append(label)
        return label.startswith("Apply")
    monkeypatch.setattr(cells, "st", SimpleNamespace(
        session_state=state, caption=lambda *a: None,
        markdown=lambda *a, **kw: None,
        text_area=lambda *a, **kw: "Price removed",
        button=button))
    updated, editing = cells.edit_active_cell(
        report, block, "p", lambda key, default: key)
    assert editing
    assert updated.extra_tables[0].rows == (("First", "$100"), ("Second", "Price removed"))
    assert updated.extra_tables[0].columns == raw.columns
    assert updated.extra_tables[0].reference == raw.reference
    assert updated.client_reviewed_fingerprint == ""
    assert updated.reviewed_fingerprint == ""
    assert "p_table_cell_repair" not in state
    assert state["p_period_editor_refresh"]


def test_cell_recovery_after_source_change_never_substitutes_sibling(monkeypatch):
    from app import monthly_report_non_narrative_recovery as cells
    from types import SimpleNamespace
    raw = ReportTable(("Item",), (("$200",), ("$200",)), "same-original")
    block = ResolvedBlock("work_orders", "This month", extra_tables=(raw,))
    report = synthetic_draft(block)
    target = cells.candidates(report, "work_orders", "pricing")[0]
    changed = replace(block, extra_tables=(replace(raw, reference="different-source"),))
    state = {"p_draft": report, "p_table_cell_repair": {
        "target": target, "scope": "scope", "nonce": "one", "reveal": True}}
    monkeypatch.setattr(cells, "st", SimpleNamespace(session_state=state))
    from app import monthly_report_guided as guided
    monkeypatch.setattr(guided, "_rich_text_scope", lambda prefix: "scope")
    updated, editing = cells.edit_active_cell(replace(report, blocks=(changed,)),
                                              changed, "p", lambda k,v:k)
    assert not editing and updated == changed
    assert "p_table_cell_repair" not in state
    assert "No other row" in state["p_table_cell_repair_notice"]


def test_org_chart_field_markup_is_one_use_and_invalidates_changed_chart(monkeypatch):
    from types import SimpleNamespace
    from app.monthly_report_org_warning import chart_field_markup
    from app.monthly_report_model import OrgChartNode
    from app import monthly_report_guided as guided
    block = ResolvedBlock("org_chart", "This month",
        org_nodes=(OrgChartNode("a", name="A", role="Role"),))
    request = {"block": "org_chart", "revision": block.fingerprint,
               "index": 0, "field": "name", "scope": "scope", "nonce": "one"}
    state = {"p_chart_warning_request": request.copy()}
    import app.monthly_report_org_warning as org
    monkeypatch.setattr(org, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided, "_rich_text_scope", lambda prefix: "scope")
    marker = chart_field_markup("p", block, 0, "name", "p_org_person_a_name")
    assert 'data-field-key="p_org_person_a_name"' in marker
    assert 'enfra-page-correction-request' in marker
    assert not chart_field_markup("p", block, 0, "name", "p_org_person_a_name")
    state["p_chart_warning_request"] = request
    later = replace(block, org_nodes=(OrgChartNode("a", name="Newer name", role="Role"),))
    assert not chart_field_markup("p", later, 0, "name", "p_org_person_a_name")
    assert state["p_chart_warning_request"] == request
