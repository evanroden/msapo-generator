"""Extreme saved source dates stay explicitly correctable without a calendar crash."""
from dataclasses import replace
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_source_details import detail_problems


SCRIPT = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_upload_ui import render_source_details
from app.monthly_report_ui import _field
st.button("Neutral rerun")
st.session_state["source"] = render_source_details(
    st.session_state["source"], st.session_state["profile"], "date_recovery", _field)
'''
EXTREMES = ("0001-01-01", "0004-02-29", "0010-12-31", "0011-01-01", "0999-12-31", "1009-12-31", "9990-01-01", "9996-02-29", "9999-12-31")


@pytest.fixture
def saved(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic editor", confirmed=True)
    raw = b"Synthetic service note. Source metadata needs explicit date review."
    content, _ = sources.ingest(profile, "synthetic-date.txt", raw)
    source = replace(content.source, service_date=EXTREMES[0], classification="Vendor service",
                     facility=profile.facilities[0].key,
                     actions="Independent reviewed wording.",
                     captions=((1, "Retained source caption"),),
                     client_page_reviews=((1, "existing-review"),),
                     client_page_exclusions=((2, "existing-exclusion"),))
    draft = replace(synthetic_draft(profile, ReportPeriod(2026, 9)), sources=(source,),
                    blocks=(ResolvedBlock("activity_summary", "This month", text="Human-authored note."),))
    snapshot = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic editor")
    return profile, source, raw, snapshot


def app_for(saved, value=EXTREMES[0]):
    profile, source, _, _ = saved
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    app.session_state["profile"] = profile
    app.session_state["source"] = replace(source, service_date=value)
    app.run()
    assert not app.exception
    return app


def text_date(app):
    return next(item for item in app.text_input if item.label == "Source date (YYYY-MM-DD)")


def submit(app):
    next(item for item in app.button if item.label == "Use these source details").click().run()
    assert not app.exception


@pytest.mark.parametrize("value", EXTREMES)
def test_extreme_dates_remain_exact_and_editable_without_passive_mutation(saved, value):
    app = app_for(saved, value)
    before = app.session_state["source"]
    assert not app.date_input
    assert text_date(app).value == value
    key = text_date(app).key
    next(item for item in app.button if item.label == "Neutral rerun").click().run()
    assert not app.exception
    assert text_date(app).key == key
    assert app.session_state["source"] == before
    assert "date outside this report month" in detail_problems(before, saved[0], ReportPeriod(2026, 9))


@pytest.mark.parametrize("value", ("2026-09-19", ""))
def test_explicit_correction_or_clear_survives_rerun_and_fresh_editor(saved, value):
    app = app_for(saved)
    before = app.session_state["source"]
    text_date(app).set_value(value).run()
    assert app.session_state["source"] == before
    assert text_date(app).value == value
    submit(app)
    corrected = app.session_state["source"]
    assert corrected.service_date == value
    assert replace(corrected, service_date=before.service_date, scope_review=before.scope_review) == before
    app.run()
    assert not app.exception and not app.text_input
    assert app.date_input[0].value == (date.fromisoformat(value) if value else None)
    assert app.session_state["source"] == corrected
    reopened = AppTest.from_string(SCRIPT, default_timeout=15)
    reopened.session_state["profile"] = saved[0]
    reopened.session_state["source"] = corrected
    reopened.run()
    assert not reopened.exception and reopened.session_state["source"] == corrected
    assert reopened.date_input[0].value == (date.fromisoformat(value) if value else None)


@pytest.mark.parametrize("value", ("not a date", "2026-02-30", "10000-01-01", "2026-09-01 to 2026-09-02"))
def test_invalid_correction_does_not_clear_date_or_apply_other_fields(saved, value):
    app = app_for(saved)
    before = app.session_state["source"]
    text_date(app).set_value(value)
    app.selectbox[0].set_value("")
    submit(app)
    assert app.session_state["source"] == before
    assert text_date(app).value == value
    assert any("YYYY-MM-DD" in item.value for item in app.error)
    app.run()
    assert not app.exception and text_date(app).value == value
    text_date(app).set_value("2026-09-20")
    submit(app)
    assert app.session_state["source"].service_date == "2026-09-20"
    assert app.session_state["source"].facility == ""


@pytest.mark.parametrize("value", ("2026-09-12", "", "1010-01-01", "9989-12-31"))
def test_normal_calendar_and_unknown_defaults_are_unchanged(saved, value):
    app = app_for(saved, value)
    assert not app.text_input
    assert len(app.date_input) == 1
    assert app.date_input[0].label == "Source date"
    assert app.date_input[0].value == (date.fromisoformat(value) if value else None)
    assert app.session_state["source"].service_date == value


def test_changing_only_site_never_silently_replaces_the_extreme_date(saved):
    app = app_for(saved)
    before = app.session_state["source"]
    app.selectbox[0].set_value("")
    submit(app)
    after = app.session_state["source"]
    assert after.service_date == before.service_date and after.facility == ""
    assert replace(after, facility=before.facility, scope_review=before.scope_review) == before
    app.run()
    assert not app.exception and text_date(app).value == before.service_date


@pytest.mark.parametrize("new_date", ("2026-09-22", "9999-12-31"))
def test_external_correction_retires_pending_text_before_stale_submit(saved, new_date):
    app = app_for(saved)
    text_date(app).set_value("2026-09-19")
    external = replace(app.session_state["source"], service_date=new_date, findings="A newer correction.")
    app.session_state["source"] = external
    submit(app)
    assert app.session_state["source"] == external
    assert any("corrected elsewhere" in item.value for item in app.info)
    if new_date.startswith("9999"):
        assert text_date(app).value == new_date
    else:
        assert not app.text_input and app.date_input[0].value == date(2026, 9, 22)
    app.run()
    assert not app.exception and app.session_state["source"] == external


def test_corrected_source_saves_and_reopens_without_rewriting_original_or_history(saved):
    profile, original, raw, prior = saved
    app = app_for(saved)
    text_date(app).set_value("2026-09-23")
    submit(app)
    corrected = app.session_state["source"]
    draft = replace(prior.draft, sources=(corrected,))
    new = library.save_snapshot(draft, expected_revision=prior.revision, entered_editor="Synthetic editor")
    reopened = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert reopened == new and reopened.draft == draft
    assert library.load_snapshot_version(profile.contract, profile.key, draft.period, prior.revision) == prior
    assert draft.blocks == prior.draft.blocks
    assert sources.source_bytes(profile, corrected) == raw
    other_profile = replace(profile, key="other-date-profile", contract="Synthetic other contract")
    other, _ = sources.ingest(other_profile, "synthetic-date.txt", raw)
    assert other.source.service_date == ""
    assert sources.source_bytes(other_profile, other.source) == raw


def test_multisite_date_correction_keeps_explicit_site_review(saved):
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    profile = synthetic_profiles()[1]
    source = replace(saved[1], facility="", scope_review="")
    app.session_state["profile"] = profile
    app.session_state["source"] = source
    app.run()
    assert not app.exception
    text_date(app).set_value("2026-09-21")
    app.multiselect[0].set_value([site.key for site in profile.facilities])
    submit(app)
    corrected = app.session_state["source"]
    from app.monthly_report_source_scope import reviewed_scope
    assert set(reviewed_scope(corrected, profile)["facilities"]) == {site.key for site in profile.facilities}
    assert corrected.service_date == "2026-09-21"
    assert replace(corrected, service_date=source.service_date, scope_review=source.scope_review) == source
    app.run()
    assert not app.exception and app.session_state["source"] == corrected


def test_sibling_source_remains_usable_with_an_extreme_date_in_another_form(saved):
    script = SCRIPT + '''
st.session_state["sibling"] = render_source_details(
    st.session_state["sibling"], st.session_state["profile"], "sibling_date", _field)
'''
    app = AppTest.from_string(script, default_timeout=15)
    app.session_state["profile"] = saved[0]
    app.session_state["source"] = saved[1]
    sibling = replace(saved[1], id="b" * 64, sha256="b" * 64,
                      filename="synthetic-sibling.txt", service_date="2026-09-10")
    app.session_state["sibling"] = sibling
    app.run()
    assert not app.exception
    text_date(app).set_value("2026-09-18")
    next(item for item in app.button if item.label == "Use these source details").click().run()
    assert not app.exception
    assert app.session_state["source"].service_date == "2026-09-18"
    assert app.session_state["sibling"] == sibling
    app.run()
    assert not app.exception
    dates = [item for item in app.date_input if item.label == "Source date"]
    assert [item.value for item in dates] == [date(2026, 9, 18), date(2026, 9, 10)]
