"""Synthetic AppTest coverage for Section 9's explicit capital approvals."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_capital_master import (
    CapitalItem, load_capital_master, save_capital_master,
)
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock,
    default_sections,
)


SCRIPT = """
import streamlit as st
from app.monthly_report_capital_ui import render_capital_master
st.session_state["block"] = render_capital_master(
    st.session_state["draft"], st.session_state["block"], "capital_test")
"""
PERIOD = ReportPeriod(2026, 9)


def profile(contract, facilities=("north",)):
    sites = tuple(Facility(key, f"Synthetic {contract[-1]} {key.title()}")
                  for key in facilities)
    return ReportProfile(contract, "-".join(facilities),
                         "Synthetic report", sites,
                         scope_type="individual" if len(sites) == 1 else "multi_site")


def draft(profile, block=None):
    section = next(s for s in default_sections() if s.key == "capital")
    return ReportDraft(profile, PERIOD, "Synthetic Reviewer", (section,),
                       (block,) if block else (), synthetic=True)


def start(profile, block=None):
    current = block or ResolvedBlock("capital_renewal", "This month")
    app = AppTest.from_string(SCRIPT, default_timeout=20)
    app.session_state["draft"] = draft(profile, current)
    app.session_state["block"] = current
    return app.run()


def button(app, label):
    return next(item for item in app.button if item.label == label)


def check(app, label):
    return next(item for item in app.checkbox if item.label == label)


def approve(profile, items, revision=0):
    return save_capital_master(
        profile, items, expected_revision=revision,
        actor="Synthetic Approver", confirmed=True)


def test_two_contracts_only_offer_their_own_approved_list(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    a = profile("Synthetic Contract A")
    b = profile("Synthetic Contract B")
    first = approve(a, (CapitalItem("a-pump", "High", "Replace north pump",
                                    site_keys=("north",)),))
    app_a = start(a)
    app_b = start(b)
    assert not app_a.exception and not app_b.exception
    assert load_capital_master(b.contract).revision == 0
    assert button(app_a, "Use approved Capital Renewal in this report")
    assert all(item.label != "Use approved Capital Renewal in this report"
               for item in app_b.button)
    assert any("version 1" in item.value for item in app_a.caption)
    assert all("Replace north pump" not in item.value for item in app_b.caption)
    assert not app_a.session_state["block"].rows
    assert load_capital_master(a.contract) == first

    button(app_a, "Use approved Capital Renewal in this report").click().run()
    assert not app_a.exception
    used = app_a.session_state["block"]
    assert used.rows == (("Synthetic A North", "High", "Replace north pump"),)
    assert used.references == (first.reference,)
    assert used.source == "Library"
    assert load_capital_master(a.contract) == first
    assert not app_b.session_state["block"].rows


def test_explicit_promotion_records_actor_and_never_changes_report(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    b = profile("Synthetic Contract B")
    rows = ResolvedBlock("capital_renewal", "This month",
                         rows=(("Synthetic B North", "Medium", "Renew roof"),))
    app = start(b, rows)
    assert not app.exception and load_capital_master(b.contract).revision == 0
    action = button(app, "Save approved Capital Renewal version")
    assert action.disabled
    app.run()
    assert load_capital_master(b.contract).revision == 0
    check(app, "I reviewed these capital recommendations and approve a new contract version").check().run()
    button(app, "Save approved Capital Renewal version").click().run()
    assert not app.exception
    saved = load_capital_master(b.contract)
    assert saved.revision == 1 and saved.actor == "Synthetic Reviewer"
    assert saved.items[0].recommendation == "Renew roof"
    assert saved.items[0].site_keys == ("north",)
    assert app.session_state["block"] == rows
    assert app.session_state["block"].references == ()
    app.run()
    assert load_capital_master(b.contract) == saved


def test_approval_changes_only_the_reviewed_site_and_preserves_previous_revision(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    both = profile("Synthetic Contract A", ("north", "south"))
    north = profile("Synthetic Contract A")
    initial = approve(both, (
        CapitalItem("north-pump", "High", "Original north pump", site_keys=("north",)),
        CapitalItem("south-roof", "Medium", "Original south roof", site_keys=("south",)),
    ))
    current = ResolvedBlock("capital_renewal", "This month",
                            rows=(("Synthetic A North", "Critical", "Replace north pump now"),))
    app = start(north, current)
    check(app, "I reviewed these capital recommendations and approve a new contract version").check().run()
    button(app, "Save approved Capital Renewal version").click().run()
    assert not app.exception
    updated = load_capital_master(north.contract)
    assert updated.revision == 2
    assert [(item.key, item.recommendation) for item in updated.items if item.site_keys == ("south",)] == [
        ("south-roof", "Original south roof")]
    assert [(item.recommendation, item.site_keys) for item in updated.items if item.site_keys == ("north",)] == [
        ("Replace north pump now", ("north",))]
    assert load_capital_master(north.contract, 1) == initial
    assert app.session_state["block"] == current


def test_reuse_requires_explicit_replacement_and_reports_stay_pinned(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    north = profile("Synthetic Contract A")
    version1 = approve(north, (
        CapitalItem("pump", "High", "Original pump", site_keys=("north",)),))
    manual = ResolvedBlock("capital_renewal", "This month",
                           rows=(("Synthetic A North", "Low", "Keep manual review"),),
                           text="Report-specific observations")
    app = start(north, manual)
    assert button(app, "Use approved Capital Renewal in this report").disabled
    assert app.session_state["block"] == manual
    check(app, "Replace this report's existing capital tables (keep notes and pages)").check().run()
    button(app, "Use approved Capital Renewal in this report").click().run()
    assert not app.exception
    pinned = app.session_state["block"]
    assert pinned.rows[0][2] == "Original pump"
    assert pinned.references == (version1.reference,)
    assert pinned.text == manual.text

    saved = library.save_snapshot(draft(north, pinned), expected_revision=0)
    version2 = approve(north, (
        replace(version1.items[0], recommendation="Updated pump"),), revision=1)
    assert version2.revision == 2
    assert library.load_snapshot(north.contract, north.key, PERIOD).draft.blocks == (pinned,)
    assert saved.draft.blocks == (pinned,)
    assert app.session_state["block"] == pinned
    app.run()
    assert any("changed" in item.value for item in app.warning)
    button(app, "Reload approved capital").click().run()
    assert not app.exception
    assert app.session_state["block"] == pinned
    check(app, "I reviewed these capital recommendations and approve a new contract version").check().run()
    button(app, "Save approved Capital Renewal version").click().run()
    assert any("earlier approved version" in item.value for item in app.warning)
    assert load_capital_master(north.contract) == version2


def test_approval_rejects_prices_without_publishing(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    p = profile("Synthetic Contract B")
    block = ResolvedBlock("capital_renewal", "This month",
                          rows=(("Synthetic B North", "High", "Replace chiller for $900"),))
    app = start(p, block)
    check(app, "I reviewed these capital recommendations and approve a new contract version").check().run()
    button(app, "Save approved Capital Renewal version").click().run()
    assert not app.exception
    assert load_capital_master(p.contract).revision == 0
    assert app.session_state["block"] == block
    assert any("monetary" in item.value.lower() for item in app.warning)
