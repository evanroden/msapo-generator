"""Two independent Streamlit sessions using one synthetic browser recovery identity."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import synthetic_profiles
from test_monthly_report_active_recovery_ui import _visit, _value, TOKEN, ROOT, PERIOD
from test_monthly_report_ui import monthly, choose_report


def button(app, label):
    return next(item for item in app.button if item.label == label)


def two_sessions(monkeypatch, tmp_path):
    _visit(monkeypatch)
    first = monthly(monkeypatch, tmp_path)
    _value(first, "Prepared by", "text_input").set_value("Synthetic editor").run()
    _value(first, "Activity summary").set_value("Accepted base summary").run()
    assert not first.exception
    second = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    second.segmented_control[0].set_value("Monthly report").run()
    choose_report(second, synthetic_profiles()[0].facilities[0].title)
    assert not second.exception
    return first, second


def test_disjoint_tabs_merge_by_deliberate_one_click_and_reopen(monkeypatch, tmp_path):
    first, second = two_sessions(monkeypatch, tmp_path)
    _value(second, "Prepared by", "text_input").set_value("Synthetic newer editor").run()
    latest = active.load(TOKEN, RRH_CONTRACT, "synthetic-guided", PERIOD)
    _value(first, "Activity summary").set_value("Synthetic unsaved first-tab correction").run()
    assert not first.exception and not second.exception
    assert active.load(TOKEN, RRH_CONTRACT, "synthetic-guided", PERIOD) == latest
    button(first, "Compare browser copies").click().run()
    assert not first.exception
    assert not button(first, "Merge independent changes").disabled
    button(first, "Merge independent changes").click().run()
    assert not first.exception
    saved = active.load(TOKEN, RRH_CONTRACT, "synthetic-guided", PERIOD)
    assert saved.revision > latest.revision
    assert saved.draft.prepared_by == "Synthetic newer editor"
    assert next(b.text for b in saved.draft.blocks if b.key == "activity_summary") == "Synthetic unsaved first-tab correction"
    reopened = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    reopened.segmented_control[0].set_value("Monthly report").run()
    choose_report(reopened, synthetic_profiles()[0].facilities[0].title)
    assert not reopened.exception
    assert _value(reopened, "Activity summary").value == "Synthetic unsaved first-tab correction"


def test_same_field_requires_narrow_choice_and_stale_save_rejects_race(monkeypatch, tmp_path):
    first, second = two_sessions(monkeypatch, tmp_path)
    _value(second, "Activity summary").set_value("Second-tab accepted correction").run()
    latest = active.load(TOKEN, RRH_CONTRACT, "synthetic-guided", PERIOD)
    _value(first, "Activity summary").set_value("First-tab unsaved correction").run()
    button(first, "Compare browser copies").click().run()
    assert not first.exception
    choice = next(w for w in first.radio if "blocks[activity_summary].text" in w.label)
    assert button(first, "Save resolved field choices").disabled
    choice.set_value("Use this page value").run()
    assert not first.exception
    assert not button(first, "Save resolved field choices").disabled
    original = active.save
    raced = []

    def concurrent_save(token, draft, **kwargs):
        if kwargs.get("expected_revision") == latest.revision and not raced:
            raced.append(original(token, replace(latest.draft, prepared_by="Third synthetic editor"),
                                  expected_revision=latest.revision,
                                  expected_generation=latest.generation,
                                  base_snapshot_revision=latest.base_snapshot_revision))
        return original(token, draft, **kwargs)

    monkeypatch.setattr(active, "save", concurrent_save)
    button(first, "Save resolved field choices").click().run()
    assert not first.exception and len(raced) == 1
    assert active.load(TOKEN, RRH_CONTRACT, "synthetic-guided", PERIOD) == raced[0]
    assert any("A browser version changed" in item.value for item in first.error)
    assert _value(first, "Activity summary").value == "First-tab unsaved correction"
    monkeypatch.setattr(active, "save", original)
