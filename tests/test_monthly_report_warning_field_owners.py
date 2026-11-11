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
