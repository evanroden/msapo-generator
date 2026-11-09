"""Saved chart page numerals cannot escape or weaken the publication gate."""

from dataclasses import asdict, replace
import json

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_org_chart_defaults as charts
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import OrgChartNode, ReportSource, ResolvedBlock
from test_monthly_report_org_chart_defaults import scopes, fresh, with_chart, chart
from test_monthly_report_org_chart_defaults_ui import WRAPPER, button
from test_monthly_report_org_chart_source_scope import storage_bytes


INVALID_PAGES = [
    pytest.param("²", id="superscript"),
    pytest.param("١", id="arabic-decimal"),
    pytest.param("１", id="fullwidth-decimal"),
    pytest.param("1" * 4301, id="integer-conversion-limit"),
    pytest.param("0000001", id="beyond-historical-padding-bound"),
    pytest.param("1000000", id="seven-digits"),
    pytest.param("", id="missing"),
    pytest.param("0", id="zero"),
    pytest.param("-1", id="negative"),
    pytest.param("+1", id="explicit-plus"),
    pytest.param("1.0", id="decimal-point"),
    pytest.param(" 1", id="leading-space"),
    pytest.param("1 ", id="trailing-space"),
]


def saved_chart(profile, page, *, approved=True):
    source = ReportSource("a" * 64, "synthetic-chart.txt", "b" * 64, ".txt", facility="A1",
                          page_texts=("Synthetic maintenance reporting chart.",), selected_pages=(1,))
    if approved:
        source = replace(source, client_page_reviews=((1, page_fingerprint(source, 1)),))
    block = ResolvedBlock("org_chart", "This month", references=(f"{source.id}:{page}:{source.fingerprint}",),
                          org_nodes=(OrgChartNode("lead", "Synthetic Lead", "Lead"),))
    assert library.source_from_dict(json.loads(json.dumps(asdict(source)))) == source
    assert library.block_from_dict(json.loads(json.dumps(asdict(block)))) == block
    draft = replace(with_chart(fresh(profile), block), sources=(source,))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic editor")
    restored = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert restored == saved
    return restored.draft


def publish(draft):
    block = chart(draft)
    return charts.save_default(draft, block, {}, scope="contract", expected_revision=0,
                               expected_fingerprint=block.fingerprint, confirmed=True)


@pytest.mark.parametrize("page", INVALID_PAGES)
def test_bad_saved_page_number_is_refused_without_writing(scopes, page):
    draft = saved_chart(scopes[0], page)
    block = chart(draft)
    assert charts.eligible(block)
    before = storage_bytes()
    assert charts.source_pages_allowed(block, draft.sources, draft.profile) is False
    with pytest.raises(library.LibraryError, match="Include and review the chart"):
        publish(draft)
    assert charts.load_defaults(draft.profile.contract).revision == 0
    assert storage_bytes() == before


@pytest.mark.parametrize("page", ["1", "000001"])
def test_canonical_and_historically_padded_pages_still_publish(scopes, page):
    draft = saved_chart(scopes[0], page)
    before = storage_bytes()
    assert charts.source_pages_allowed(chart(draft), draft.sources, draft.profile)
    assert publish(draft).revision == 1
    saved = charts.load_defaults(draft.profile.contract)
    assert saved.revision == 1
    assert charts.selected_default(draft.profile, saved).block.org_nodes == chart(draft).org_nodes
    after = storage_bytes()
    assert all(after[name] == raw for name, raw in before.items())
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft == draft


@pytest.mark.parametrize("condition", [
    "missing-source", "unselected", "unapproved", "stale-review", "outside-page-range",
    "foreign-site", "bad-digest", "uppercase-digest", "extra-component",
])
def test_existing_page_digest_approval_and_scope_checks_stay_closed(scopes, condition):
    draft = saved_chart(scopes[0], "1")
    source, block = draft.sources[0], chart(draft)
    if condition == "missing-source":
        draft = replace(draft, sources=())
    elif condition == "unselected":
        draft = replace(draft, sources=(replace(source, selected_pages=()),))
    elif condition == "unapproved":
        draft = replace(draft, sources=(replace(source, client_page_reviews=()),))
    elif condition == "stale-review":
        draft = replace(draft, sources=(replace(source, client_page_reviews=((1, "old"),)),))
    elif condition == "outside-page-range":
        block = replace(block, references=(f"{source.id}:2:{source.fingerprint}",))
        draft = replace(draft, sources=(replace(source, selected_pages=(1, 2)),))
    elif condition == "foreign-site":
        draft = replace(draft, sources=(replace(source, facility="Foreign Site"),))
    elif condition == "bad-digest":
        block = replace(block, references=(f"{source.id}:1:" + "c" * 63,))
    elif condition == "uppercase-digest":
        block = replace(block, references=(f"{source.id}:1:" + "C" * 64,))
    else:
        block = replace(block, references=(block.references[0] + ":extra",))
    draft = with_chart(draft, block)
    before = storage_bytes()
    assert charts.source_pages_allowed(block, draft.sources, draft.profile) is False
    with pytest.raises(library.LibraryError, match="Include and review the chart"):
        publish(draft)
    assert storage_bytes() == before


@pytest.mark.parametrize("reference", [
    "docx:synthetic-original:org-chart",
    "contract-org-chart:v1:" + "c" * 64,
    "asset-source-context:v1:" + "d" * 64,
])
def test_existing_non_page_reference_exemptions_remain_unchanged(scopes, reference):
    draft = saved_chart(scopes[0], "1")
    block = replace(chart(draft), references=(reference,))
    assert charts.source_pages_allowed(block, (), draft.profile)


@pytest.mark.parametrize("page,approved,allowed", [
    pytest.param("²", True, False, id="superscript"),
    pytest.param("1" * 4301, True, False, id="integer-conversion-limit"),
    pytest.param("١", True, False, id="arabic-decimal"),
    pytest.param("１", True, False, id="fullwidth-decimal"),
    pytest.param("0000001", True, False, id="oversized-padding"),
    pytest.param("1", False, False, id="unapproved"),
    pytest.param("1", True, True, id="approved"),
    pytest.param("000001", True, True, id="approved-padded"),
])
def test_real_chart_confirmation_keeps_invalid_pages_blocked_and_editor_usable(scopes, page, approved, allowed):
    draft = saved_chart(scopes[0], page, approved=approved)
    before = storage_bytes()
    app = AppTest.from_string(WRAPPER, default_timeout=20)
    app.session_state["draft"] = draft
    app.session_state["assets"] = {}
    app.run()
    assert not app.exception
    button(app, "Edit chart").click().run()
    assert not app.exception and button(app, "Publish chart default").disabled
    next(item for item in app.checkbox if item.label.startswith("Make this reviewed")).check().run()
    assert not app.exception
    assert button(app, "Publish chart default").disabled is (not allowed)
    assert charts.load_defaults(draft.profile.contract).revision == 0
    assert chart(app.session_state["draft"]) == chart(draft)
    assert storage_bytes() == before
    if allowed:
        button(app, "Publish chart default").click().run()
        assert not app.exception
        saved = charts.load_defaults(draft.profile.contract)
        assert saved.revision == 1
        assert charts.selected_default(draft.profile, saved).block.org_nodes == chart(draft).org_nodes
        after = storage_bytes()
        assert all(after[name] == raw for name, raw in before.items())
    else:
        next(item for item in app.text_input if item.label == "Name").set_value("Still editing this chart").run()
        assert not app.exception
        assert chart(app.session_state["draft"]).org_nodes[0].name == "Still editing this chart"
        assert button(app, "Publish chart default").disabled
        assert charts.load_defaults(draft.profile.contract).revision == 0
        assert storage_bytes() == before
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft == draft
