"""A61: the first native DOCX selection produces one truthful loaded-file card.

All sources are synthetic DOCX fixtures. AppTest observes Streamlit controls,
not a deployed browser, mouse/touch hit geometry or Word page rasterization.
"""
import hashlib

from app import monthly_report_library as library
from app import monthly_report_section_ui as section_ui
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from test_monthly_report_start_import import report_file, save_start
from test_monthly_report_starting_import_failure_ui import _start


def _card_text(app):
    return "\n".join([*(item.value for item in app.markdown),
                      *(item.value for item in app.caption)]).replace("\\", "")


def test_first_upload_loads_single_source_card_without_analyze_click(monkeypatch, tmp_path):
    original = report_file(tmp_path, activity=("September 2026 completed synthetic work.",))
    raw = original.read_bytes()
    selected = {"raw": raw}
    app = _start(monkeypatch, tmp_path, selected)

    display = _card_text(app)
    assert "Loaded file:" in display and "synthetic-starting.docx" in display
    assert "Recognized source sites:" in display and "Source month: 2026-09" in display
    assert "Target sites:" in display and "Target month:" in display
    # AppTest does not expose file_uploader elements. Observe the intercepted
    # native upload function on a settled rerun instead of counting DOM nodes.
    import test_monthly_report_starting_import_failure_ui as fixture
    original_uploaded = fixture._uploaded
    upload_calls = []

    def observed_upload(data):
        upload_calls.append(data)
        return original_uploaded(data)

    monkeypatch.setattr(fixture, "_uploaded", observed_upload)
    app.run()
    assert upload_calls == [raw], "Exactly one Starting report picker was invoked."
    assert not app.exception
    # F12: no diagnostic preview or generic review reminder on the card.
    assert not any(w.label == "Preview recognized content" for w in app.expander)
    assert "File read; report sections" not in display
    assert any(w.label == "Remove loaded file" for w in app.button)
    assert not any(w.label == "Analyze report" for w in app.button)
    assert any(b.label == "Continue to this month’s updates" and not b.disabled for b in app.button)
    assert raw == original.read_bytes()
    assert not app.exception

    draft = save_start(app)
    assert draft.profile.facilities == synthetic_profiles()[0].facilities
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == raw
    assert (library.load_imported_draft(draft.profile.contract, draft.profile.key)
            .profile.facilities == draft.profile.facilities)
    assert hashlib.sha256(library.imported_original(
        draft.profile.contract, draft.profile.key).read_bytes()).hexdigest() == hashlib.sha256(raw).hexdigest()


def test_replace_and_remove_loaded_source_do_not_retain_stale_identity(monkeypatch, tmp_path):
    first = report_file(tmp_path, month="August 2026",
                        activity=("August 2026 initial work.",)).read_bytes()
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second = report_file(second_dir, month="September 2026",
                         activity=("September 2026 replacement work.",)).read_bytes()
    chosen = {"raw": first, "name": "first-month.docx"}
    import test_monthly_report_starting_import_failure_ui as fixture
    native_uploaded = fixture._uploaded

    def named_upload(raw):
        upload = native_uploaded(raw)
        upload.name = chosen["name"]
        return upload

    monkeypatch.setattr(fixture, "_uploaded", named_upload)
    app = _start(monkeypatch, tmp_path, chosen)
    assert "first-month.docx" in _card_text(app)
    assert "Source month: 2026-08" in _card_text(app)
    stage_key = next(k for k in app.session_state.filtered_state if k.endswith("_stage"))
    before = app.session_state[stage_key]

    chosen["raw"] = second
    chosen["name"] = "replacement-month.docx"
    app.run()
    assert not app.exception
    after = app.session_state[stage_key]
    assert after[2].sha256 != before[2].sha256
    assert "Source month: 2026-09" in _card_text(app)
    assert "replacement-month.docx" in _card_text(app)
    assert "first-month.docx" not in _card_text(app)
    assert "Source month: 2026-08" not in _card_text(app)
    assert first != second and after[1].read_bytes() == second

    # Simulate the browser's cleared picker before using the explicit Remove.
    chosen["raw"] = None
    next(b for b in app.button if b.label == "Remove loaded file").click().run()
    assert not app.exception
    assert stage_key not in app.session_state.filtered_state
    assert "Loaded file:" not in _card_text(app)
    assert not any(b.label == "Continue to this month’s updates" for b in app.button)



def test_bad_replacement_keeps_previous_loaded_card_and_source_bytes(monkeypatch, tmp_path):
    first = report_file(tmp_path, month="August 2026",
                        activity=("August 2026 retained source.",)).read_bytes()
    chosen = {"raw": first}
    app = _start(monkeypatch, tmp_path, chosen)
    stage_key = next(k for k in app.session_state.filtered_state if k.endswith("_stage"))
    original_stage = app.session_state[stage_key]
    chosen["raw"] = b"not-a-word-document"
    app.run()
    assert not app.exception
    assert app.session_state[stage_key] is original_stage
    assert original_stage[1].read_bytes() == first
    assert "Loaded file:" in _card_text(app)
    assert "synthetic-starting.docx" in _card_text(app)
    assert any("newly selected file has not been analyzed" in x.value for x in app.info)
    assert any(b.label == "Remove loaded file" for b in app.button)


def test_unknown_source_and_questionable_month_stay_visibly_unconfirmed(monkeypatch, tmp_path):
    path = report_file(tmp_path, title="Unrecognized Synthetic Site",
                       month="undated", activity=("Unscheduled maintenance details.",))
    chosen = {"raw": path.read_bytes()}
    app = _start(monkeypatch, tmp_path, chosen)
    display = _card_text(app)
    assert "Loaded file:" in display
    assert "Unknown" in display or "Not checked yet" in display
    assert "Source month: Unconfirmed" in display
    assert not any(b.label == "Continue to this month’s updates" for b in app.button)
    assert any(b.label == "Remove loaded file" for b in app.button)
    # Source membership remains a real, reachable human correction, not an
    # inferred approval from an unknown cover or a questionable period.
    target_name = synthetic_profiles()[0].facilities[0].title
    next(w for w in app.checkbox if w.label == target_name).check().run()
    assert target_name in _card_text(app)
    assert not app.exception


def test_foreign_source_identity_stays_distinct_from_target(monkeypatch, tmp_path):
    target, other = synthetic_profiles()[1].facilities
    source = report_file(tmp_path, title=other.title, month="August 2026",
                         activity=("August 2026 foreign work.",))
    chosen = {"raw": source.read_bytes()}
    monkeypatch.setattr(section_ui, "_site_options", lambda contract: (target, other))
    app = _start(monkeypatch, tmp_path, chosen)
    display = _card_text(app)
    assert "Recognized source sites:" in display and other.title in display
    assert "Target sites:" in display and target.title in display
    assert "Source month: 2026-08" in display
    assert not app.exception

def test_conflicting_cover_months_keep_loaded_card_unconfirmed_until_chosen(monkeypatch, tmp_path):
    source = report_file(tmp_path, month="August 2026 / September 2026")
    selected = {"raw": source.read_bytes()}
    app = _start(monkeypatch, tmp_path, selected)
    assert "Loaded file:" in _card_text(app)
    assert "Source month: Unconfirmed — choose the source reporting month" in _card_text(app)
    assert not any(b.label == "Continue to this month’s updates" for b in app.button)
    choice = next(w for w in app.selectbox
                  if w.label == "Reporting month shown by the uploaded source cover")
    choice.set_value((2026, 9)).run()
    assert not app.exception
    assert "Source month: 2026-09" in _card_text(app)
