"""Exact ordinary-photo caption warning navigation, with identical picture bytes.

Only synthetic pictures and report identities. These tests do not approve content
or call a browser; native pointer/keyboard behavior is in qa_warning_routes.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app import monthly_report_correction_ui as ui
from app import monthly_report_guided as guided
from app import monthly_report_layout_checks as layout
from app.monthly_report_correction_targets import picture_target, resolve_target
from app.monthly_report_model import AssetInstance, ResolvedBlock
from tests.test_monthly_report_native_layout import draft as synthetic_draft

PREFIX = "caption-warning"
SCOPE = "synthetic-editor-epoch"
ASSET = "a" * 64 + ".png"


def report_and_targets(monkeypatch):
    # The same bytes in two independent occurrences must never be conflated.
    block = ResolvedBlock(
        "improvements", "This month", asset_hashes=(ASSET, ASSET),
        asset_instances=(AssetInstance("synthetic-one", ASSET),
                         AssetInstance("synthetic-two", ASSET)),
        asset_provenance=((ASSET, ()),),
        asset_captions=("Overlong A " * 70, "Overlong B " * 70),
        photos_per_page=2,
    )
    report = synthetic_draft(block)
    monkeypatch.setattr(layout, "_renders_photo_pages", lambda profile: True)
    from app import monthly_report_visuals
    monkeypatch.setattr(monthly_report_visuals, "photo_caption_problems",
                        lambda run: (0, 1))
    checks = tuple(check for check in layout.layout_checks(report)
                   if check.code == "photo_caption")
    assert len(checks) == 2
    return report, block, tuple(check.targets[0] for check in checks)


def test_each_blocking_caption_names_one_exact_picture_occurrence(monkeypatch):
    report, block, targets = report_and_targets(monkeypatch)
    assert targets[0] != targets[1]
    assert targets[0].asset == targets[1].asset == ASSET
    assert targets[0].occurrence != targets[1].occurrence
    for number, target in enumerate(targets):
        assert resolve_target(report, target) == (block, number, None)
        assert target == picture_target(report, block, number)
    swapped = replace(block, asset_instances=tuple(reversed(block.asset_instances)))
    stale = replace(report, blocks=(swapped,))
    assert all(resolve_target(stale, target) is None for target in targets)


def test_click_unfolds_existing_editor_then_routes_only_to_requested_caption(monkeypatch):
    report, block, targets = report_and_targets(monkeypatch)
    state = {PREFIX + "_draft": report,
             PREFIX + "_unrelated_text": "Synthetic unfinished typed input"}
    monkeypatch.setattr(ui, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided, "_rich_text_scope", lambda prefix: SCOPE)
    target = targets[1]
    ui.queue_photo_caption(PREFIX, target, SCOPE)
    assert PREFIX + "_photo_caption_navigation_pending" in state
    ui.consume_photo_caption(PREFIX, report, SCOPE)
    assert state[PREFIX + "_photos_improvements_editing"] is True
    assert ui.photo_caption_request(PREFIX, report, block, 0) == ""
    request = ui.photo_caption_request(PREFIX, report, block, 1)
    assert 'class="enfra-page-correction-request"' in request
    assert 'href="#' + ui.marker_id(PREFIX, target) + '"' in request
    assert 'data-report-identity="' + ui._identity(PREFIX) + '"' in request
    assert PREFIX + "_photo_caption_navigation_open" not in state
    assert ui.photo_caption_request(PREFIX, report, block, 1) == ""
    assert state[PREFIX + "_unrelated_text"] == "Synthetic unfinished typed input"
    # The ordinary native correction adapter creates Return to Review only
    # after confirming the exact mounted field; no receipt grants approval.
    from app.monthly_report_correction_ui import picture_marker
    marker = picture_marker(report, block, 1, PREFIX, "synthetic_caption_widget")
    assert ui.marker_id(PREFIX, target) in marker
    assert "synthetic_caption_widget" in marker


@pytest.mark.parametrize("kind", ("scope", "changed-caption", "removed", "reordered",
                                   "other-report", "omitted"))
def test_stale_or_wrong_owner_never_opens_another_editor(monkeypatch, kind):
    report, block, targets = report_and_targets(monkeypatch)
    state = {PREFIX + "_draft": report,
             PREFIX + "_photos_improvements_editing": False,
             PREFIX + "_unrelated_text": "Synthetic pending input"}
    monkeypatch.setattr(ui, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided, "_rich_text_scope", lambda prefix: SCOPE)
    target = targets[1]
    ui.queue_photo_caption(PREFIX, target, SCOPE)
    scope = SCOPE
    if kind == "scope":
        scope = "different-editor-epoch"
    elif kind == "changed-caption":
        report = replace(report, blocks=(replace(block, asset_captions=("Original", "New caption")),))
    elif kind == "removed":
        report = replace(report, blocks=(replace(block, asset_hashes=(ASSET,),
                                                  asset_instances=(block.asset_instances[0],),
                                                  asset_captions=(block.asset_captions[0],)),))
    elif kind == "reordered":
        report = replace(report, blocks=(replace(block, asset_instances=tuple(reversed(block.asset_instances))),))
    elif kind == "other-report":
        report = replace(report, period=replace(report.period, month=9))
    elif kind == "omitted":
        report = replace(report, blocks=(replace(block, source="Omit"),))
    ui.consume_photo_caption(PREFIX, report, scope)
    assert state[PREFIX + "_photos_improvements_editing"] is False
    assert PREFIX + "_photo_caption_navigation_open" not in state
    assert "changed or is unavailable" in state[PREFIX + "_photo_caption_navigation_notice"]
    assert state[PREFIX + "_unrelated_text"] == "Synthetic pending input"


def test_unmatched_visible_editor_reports_recovery_instead_of_retargeting(monkeypatch):
    report, block, targets = report_and_targets(monkeypatch)
    warnings = []
    state = {PREFIX + "_draft": report}
    monkeypatch.setattr(ui, "st", SimpleNamespace(session_state=state, warning=warnings.append))
    monkeypatch.setattr(guided, "_rich_text_scope", lambda prefix: SCOPE)
    ui.queue_photo_caption(PREFIX, targets[0], SCOPE)
    ui.consume_photo_caption(PREFIX, report, SCOPE)
    assert ui.photo_caption_request(PREFIX, report, block, 1) == ""
    ui.finish_photo_caption(PREFIX)
    assert len(warnings) == 1 and "changed or is unavailable" in warnings[0]
    assert PREFIX + "_photo_caption_navigation_open" not in state


@pytest.mark.parametrize("code,text", (
    ("required", ""),
    ("review", "Unreviewed synthetic text"),
    ("placeholder", "Insert image in this synthetic report section"),
    ("pricing", "Synthetic quoted price: $125"),
    ("text_character", "Synthetic bad character " + chr(1)),
))
def test_text_only_warning_points_to_the_exact_native_field(monkeypatch, code, text):
    from app.monthly_report_checks import ReportCheck
    block = ResolvedBlock("activity_summary", "This month", text=text)
    report = synthetic_draft(block)
    rendered = []
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        markdown=lambda value, **kwargs: rendered.append(value)))
    marker = ui.text_warning_marker(report, block, PREFIX, "synthetic-editor-field")
    assert marker.count('class="enfra-picture-correction"') == 1
    assert 'data-field-key="synthetic-editor-field"' in marker
    ui.render_text_warning_links(ReportCheck(code, "Synthetic correction", True, block.key),
                                 report, PREFIX)
    assert len(rendered) == 1
    assert 'class="enfra-picture-correction-link"' in rendered[0]
    assert ('href="#report-correction-' +
            marker.split('id="report-correction-', 1)[1].split('"', 1)[0] + '"') in rendered[0]
    changed = replace(block, text=text + " changed")
    updated = replace(report, blocks=(changed,))
    assert ui.text_warning_marker(updated, changed, PREFIX, "synthetic-editor-field") != marker


def test_unrelated_table_or_photo_warning_never_advertises_a_text_field(monkeypatch):
    from app.monthly_report_checks import ReportCheck
    block = ResolvedBlock("improvements", "This month", asset_hashes=(ASSET,))
    report = synthetic_draft(block)
    rendered = []
    monkeypatch.setattr(ui, "st", SimpleNamespace(
        markdown=lambda value, **kwargs: rendered.append(value)))
    assert ui.text_warning_marker(report, block, PREFIX, "not-text") == ""
    ui.render_text_warning_links(ReportCheck("pricing", "Price in photo", True, block.key),
                                 report, PREFIX)
    assert rendered == []
