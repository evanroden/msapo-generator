"""Native defaults must agree with canonical text, not only Python state.

AppTest's value alone missed the served empty-hydration regression. Assert
protobuf defaults as well; keep genuine clear/re-entry and issue receipt guards.
All content is invented and stores are disposable.
"""
from dataclasses import replace

import pytest
from streamlit.delta_generator import DeltaGenerator
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


def repeat_issue_app(tmp_path, monkeypatch):
    from app.monthly_report_model import ReportSource
    from app.monthly_report_sources import source_reference

    value = app(tmp_path, monkeypatch)
    draft = value.session_state["report_test_draft"]
    source = ReportSource("synthetic-repeat-evidence", "synthetic-evidence.pdf", "a" * 64, ".pdf",
                          page_texts=("Synthetic first inspection.", "Synthetic second inspection."))
    value.session_state["report_test_draft"] = replace(draft, sources=(source,), follow_ups=tuple(
        replace(item, status="updated", evidence_note="Initial synthetic evidence.") if item.category == "issue" else item
        for item in draft.follow_ups))
    value.run()  # Establish the fixture before the consecutive native edits.
    assert not value.exception
    return value, [source_reference(source, page) for page in (1, 2)]


@pytest.mark.parametrize("label,kind,attribute", [
    ("Issue description", "text_area", "text"),
    ("Issue update", "text_area", "update"),
    ("Evidence or explanation for the status", "text_area", "evidence_note"),
    ("Issue status", "selectbox", "status"),
    ("Supporting source pages", "multiselect", "references"),
])
def test_consecutive_issue_edits_accept_the_previous_result_without_a_settling_run(
        tmp_path, monkeypatch, label, kind, attribute):
    value, references = repeat_issue_app(tmp_path, monkeypatch)
    changes = {
        "text": ("", "Synthetic repeated issue wording.", "", "Synthetic final issue wording."),
        "update": ("Synthetic inspection completed on October 20, 2026.", "", "Synthetic next inspection."),
        "evidence_note": ("", "Synthetic reviewed evidence.", "", "Synthetic final evidence."),
        "status": ("resolved", "ongoing", "updated", "resolved"),
        "references": ([references[0]], [references[1]], [], references),
    }[attribute]

    def control():
        return next(widget for widget in getattr(value, kind) if widget.label == label)

    identity = control().proto.id
    for expected in changes:
        assert control().value != expected
        control().set_value(expected).run()
        assert not value.exception
        item = next(item for item in value.session_state["report_test_draft"].follow_ups
                    if item.category == "issue")
        assert getattr(item, attribute) == (tuple(expected) if attribute == "references" else expected)
        assert control().value == expected
        assert control().proto.id == identity
        if kind == "text_area":
            assert control().proto.default == expected
        # The next edit is the next run. A neutral run here would register a
        # fresh callback baseline and hide rejection of an immediate edit.


@pytest.mark.parametrize("label,attribute", [("Issue description", "text"), ("Issue update", "update")])
@pytest.mark.parametrize("delivered", ["", "Stale native correction."])
def test_consecutive_issue_edit_cannot_replace_a_newer_canonical_value(
        tmp_path, monkeypatch, label, attribute, delivered):
    value, _ = repeat_issue_app(tmp_path, monkeypatch)
    area(value, label).set_value("Accepted native wording.").run()
    assert not value.exception
    draft = value.session_state["report_test_draft"]
    newer = "Newer canonical wording from another operation."
    value.session_state["report_test_draft"] = replace(draft, follow_ups=tuple(
        replace(item, **{attribute: newer}) if item.category == "issue" else item
        for item in draft.follow_ups))
    # Deliver through the still-rendered control, with no intervening run to
    # rebind its callback to the externally replaced canonical value.
    area(value, label).set_value(delivered).run()
    assert not value.exception
    current = next(item for item in value.session_state["report_test_draft"].follow_ups
                   if item.category == "issue")
    assert getattr(current, attribute) == area(value, label).value == newer
    assert area(value, label).key + "_change" not in value.session_state.filtered_state


@pytest.mark.parametrize("label,attribute,initial", [
    ("Issue description", "text", ISSUE),
    ("Issue update", "update", "Synthetic inspection scheduled."),
])
@pytest.mark.parametrize("operation", ["clear", "reentry"])
def test_retained_issue_edit_never_clears_a_native_editor_ancestor(
        tmp_path, monkeypatch, label, attribute, initial, operation):
    value = app(tmp_path, monkeypatch)
    if area(value, label).value != initial:
        area(value, label).set_value(initial).run()
    if operation == "reentry":
        area(value, label).set_value("").run()
    value.run()
    assert not value.exception
    identity = area(value, label).proto.id
    wording = "" if operation == "clear" else "Synthetic reentered issue wording."
    assert area(value, label).value != wording
    messages = []
    enqueue = DeltaGenerator._enqueue

    def observed(self, delta_type, element_proto, *args, **kwargs):
        result = enqueue(self, delta_type, element_proto, *args, **kwargs)
        messages.append((tuple(result._cursor.delta_path), delta_type,
                         getattr(element_proto, "label", "")))
        return result

    monkeypatch.setattr(DeltaGenerator, "_enqueue", observed)
    area(value, label).set_value(wording).run()
    for phase in ("delivered edit", "acknowledged rerender"):
        assert not value.exception
        item = next(item for item in value.session_state["report_test_draft"].follow_ups
                    if item.category == "issue")
        assert item.included and getattr(item, attribute) == wording
        assert area(value, label).proto.id == identity
        assert area(value, label).proto.default == area(value, label).value == wording
        paths = [path for path, kind, native_label in messages
                 if kind == "text_area" and native_label == label]
        assert len(paths) == 1
        editor_path = paths[0]
        # Streamlit may flush after any enqueue. Its final widget tree and ID
        # can agree even when an earlier empty ancestor removed the input node.
        cleared_ancestors = [path for path, kind, _ in messages if kind == "empty"
                             and len(path) < len(editor_path)
                             and editor_path[:len(path)] == path]
        assert not cleared_ancestors, (label, operation, phase, editor_path, cleared_ancestors)
        if phase == "delivered edit":
            messages.clear()
            value.run()


def test_guided_remove_and_include_again_refresh_controls_after_committing_same_packet_text(monkeypatch, tmp_path):
    from app import monthly_report_active_work as active
    from app import monthly_report_library as library
    from app import monthly_report_qa_fixture as fixture
    from app import monthly_report_testing as qa
    from app.monthly_report_editor import _signature
    from test_monthly_report_qa_ui import ACTOR_COOKIE, visit

    value = visit(monkeypatch, tmp_path)
    next(button for button in value.button if button.label == "Load known-value report").click().run()
    assert not value.exception
    prefix = "report_guided_" + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
    draft = value.session_state[prefix + "_draft"]
    target = next(item for item in draft.follow_ups if item.category == "issue")
    sibling = replace(target, key="synthetic-retained-issue", text="Separate synthetic valve issue.",
                      update="Keep the sibling update.")
    value.session_state[prefix + "_draft"] = replace(draft, follow_ups=(*draft.follow_ups, sibling))
    value.run()
    assert not value.exception
    before = value.session_state[prefix + "_draft"]
    with qa.isolated(ACTOR_COOKIE):
        shared = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)

    def control(kind, label, issue_key=target.key):
        return next(widget for widget in kind if widget.label == label and issue_key in widget.key)

    control(value.text_area, "Issue description").set_value("Delivered description before removal.")
    control(value.text_area, "Issue update").set_value("Delivered evidence update before removal.")
    control(value.button, "Remove from this report").click().run()
    assert not value.exception
    after = value.session_state[prefix + "_draft"]
    removed = next(item for item in after.follow_ups if item.key == target.key)
    assert not removed.included
    assert removed.text == "Delivered description before removal."
    assert removed.update == "Delivered evidence update before removal."
    assert removed.references == target.references
    assert next(item for item in after.follow_ups if item.key == sibling.key) == sibling
    assert after.blocks == before.blocks and after.sources == before.sources
    # The ordinary guided hook already performed its post-commit rerender;
    # no second test action may be needed to retire only the omitted controls.
    assert [widget.value for widget in value.text_area if widget.label == "Issue description"] == [sibling.text]
    assert [widget.value for widget in value.text_area if widget.label == "Issue update"] == [sibling.update]
    assert prefix + "_period_editor_refresh" not in value.session_state.filtered_state
    with qa.isolated(ACTOR_COOKIE):
        assert active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD).draft == after
        assert library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD) == shared

    assert [widget.label for widget in value.expander
            if widget.label.startswith("Removed from this report")] == ["Removed from this report (1)"]
    # A delivered update is this month's review of it (#281).
    revised_sibling = replace(sibling, text="Delivered sibling description during restore.",
                              update="Delivered sibling update during restore.",
                              update_period=after.period.key)
    control(value.text_area, "Issue description", sibling.key).set_value(revised_sibling.text)
    control(value.text_area, "Issue update", sibling.key).set_value(revised_sibling.update)
    control(value.button, "Include again").click().run()
    assert not value.exception
    restored = value.session_state[prefix + "_draft"]
    # The restored item's text/status/history and sources stay intact; the
    # sibling's edits delivered with the same click must commit as well.
    expected_items = {target.key: replace(removed, included=True), sibling.key: revised_sibling}
    assert restored == replace(after, follow_ups=tuple(
        expected_items.get(item.key, item) for item in after.follow_ups))
    with qa.isolated(ACTOR_COOKIE):
        assert active.load(ACTOR_COOKIE, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD).draft == restored
        assert library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD) == shared
    # No neutral run/reload may be needed after Include again. The guided
    # post-commit hook must mount the restored controls and retire its old row.
    for label, expected in (("Issue description", [removed.text, revised_sibling.text]),
                            ("Issue update", [removed.update, revised_sibling.update])):
        widgets = [widget for widget in value.text_area if widget.label == label]
        assert [widget.value for widget in widgets] == expected
        assert [widget.proto.default for widget in widgets] == expected
    assert not any(widget.label == "Include again" for widget in value.button)
    assert not any(widget.label.startswith("Removed from this report") for widget in value.expander)
    assert prefix + "_period_editor_refresh" not in value.session_state.filtered_state


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
