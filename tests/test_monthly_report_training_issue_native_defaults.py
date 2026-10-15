"""Native defaults must agree with canonical text, not only Python state.

AppTest's value alone missed the served empty-hydration regression. Assert
protobuf defaults as well; keep genuine clear/re-entry and issue receipt guards.
All content is invented and stores are disposable.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

TRAINING = "Hospital staff completed a synthetic training exercise."
ISSUE = "Synthetic actuator feedback follow-up."


APP = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles, profile_sections
from app.monthly_report_training_ui import render_training
from app.monthly_report_issues import render_issue_cards
from app.monthly_report_ui import _field
profile = synthetic_profiles()[0]
initial = replace(synthetic_draft(profile, ReportPeriod(2026, 9)),
    sections=profile_sections(profile), blocks=(
      ResolvedBlock("training_summary", "This month", text="Hospital staff completed a synthetic training exercise."),
      ResolvedBlock("equipment_issues", "This month", text="Synthetic actuator feedback follow-up.")))
draft = st.session_state.setdefault("report_test_draft", initial)
blocks = render_training(draft, {b.key:b for b in draft.blocks}, "report_defaults", _field)
draft = render_issue_cards(replace(draft, blocks=tuple(blocks.values())), "report_defaults", _field)
st.session_state["report_test_draft"] = draft
st.button("Unrelated display rerun")
'''


def app(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SMARTSHEET_API_MODE", "disabled")
    value = AppTest.from_string(APP).run(timeout=30)
    assert not value.exception
    return value


def area(value, label):
    return next(widget for widget in value.text_area if widget.label == label)


def canonical(value, label):
    draft = value.session_state["report_test_draft"]
    if label == "Training notes":
        return next(b.text for b in draft.blocks if b.key == "training_summary")
    return next(item.text for item in draft.follow_ups if item.category == "issue")


def test_actual_training_and_issue_native_defaults_match_initial_canonical_text(tmp_path, monkeypatch):
    value = app(tmp_path, monkeypatch)
    for label, expected in (("Training notes", TRAINING), ("Issue description", ISSUE)):
        widget = area(value, label)
        assert widget.value == expected
        assert widget.proto.default == expected, "Python state is not a native first-mount default."
    before = value.session_state["report_test_draft"]
    next(b for b in value.button if b.label == "Unrelated display rerun").click().run()
    assert not value.exception
    assert value.session_state["report_test_draft"] == before


@pytest.mark.parametrize("label,initial", [("Training notes", TRAINING), ("Issue description", ISSUE)])
def test_deliberate_clear_reentry_and_noop_keep_canonical_values_without_remount(tmp_path, monkeypatch, label, initial):
    value = app(tmp_path, monkeypatch)
    identity = area(value, label).proto.id
    for wording in ("", "Synthetic explicit correction", initial):
        area(value, label).set_value(wording).run()
        assert not value.exception
        assert canonical(value, label) == wording
        value.run()
        assert not value.exception
        assert canonical(value, label) == wording
        assert area(value, label).value == wording
        assert area(value, label).proto.default == wording
        assert area(value, label).proto.id == identity, "Editing must not remount the native textarea."


def test_issue_stale_mirror_without_receipt_does_not_replace_canonical_wording(tmp_path, monkeypatch):
    value = app(tmp_path, monkeypatch)
    before = value.session_state["report_test_draft"]
    widget_key = area(value, "Issue description").key
    value.session_state[widget_key] = "Stale browser mirror"
    value.run()
    assert not value.exception
    assert canonical(value, "Issue description") == ISSUE
    assert area(value, "Issue description").proto.default == ISSUE
    assert value.session_state["report_test_draft"] == before


def test_served_failure_hashes_identify_only_training_notes_and_issue_description():
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_qa_fixture import _training_tables, profile, PERIOD
    from app.monthly_report_model import ReportDraft, profile_sections
    from app.monthly_report_issues import canonical_issues
    from app.monthly_report_testing_ui import _hash_generation_part

    training = ResolvedBlock("training_summary", "This month", text=TRAINING,
                             extra_tables=_training_tables())
    draft = canonical_issues(ReportDraft(profile(), PERIOD, "Synthetic QA Operator",
        profile_sections(profile()), (ResolvedBlock("equipment_issues", "This month", text=ISSUE),)))
    # Prefixes independently read from the first failed exact-served screenshot,
    # run 38658716013. This does not simulate or claim the browser event cause.
    assert _hash_generation_part(training).startswith("1d69729694ef")
    assert _hash_generation_part(replace(training, text="")).startswith("01619e358244")
    assert _hash_generation_part(draft.follow_ups).startswith("db5b9df3c0ca")
    assert _hash_generation_part(tuple(replace(item, text="") for item in draft.follow_ups)).startswith("54b322afba69")
