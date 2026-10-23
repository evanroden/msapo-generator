"""Real guided save/reload integration; Word is real, PDF conversion is stubbed.

These synthetic AppTest cases are not native-browser or served acceptance.
"""
from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_docx import ReportPackage, assemble_docx
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from test_monthly_report_ui import ROOT, monthly, choose_report


PERIOD = ReportPeriod(2026, 9)


def button(app, label):
    return next(item for item in app.button if item.label == label)


def saved():
    return library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD)


def setup(monkeypatch, tmp_path):
    generated = []

    def generate(draft, **kwargs):
        files = ReportPackage(assemble_docx(draft, **kwargs), b"%PDF-synthetic-caption-test",
                              "synthetic-caption.docx", "synthetic-caption.pdf", draft.fingerprint)
        generated.append(files)
        return files

    monkeypatch.setattr(guided, "generate_report", generate)
    app = monthly(monkeypatch, tmp_path)
    next(item for item in app.text_input if item.label == "Prepared by").set_value("Synthetic Caption Editor").run()
    next(item for item in app.text_area if item.label == "Activity summary").set_value("Synthetic inspection completed.").run()
    button(app, "Save shared version").click().run()
    button(app, "Save shared version").click().run()
    assert not app.exception
    before = saved()
    assert before.revision == 2
    assert not button(app, "Create Word and PDF").disabled
    return app, before, generated


def assert_version(app, revision):
    assert not app.exception
    assert f"[Shared version {revision}](#shared-report-history) · September 2026" in [item.value for item in app.caption]
    assert any(f"Version {revision} is saved" in item.value for item in app.markdown)
    assert not any("this version was not saved" in item.value for item in app.warning)
    assert [item.label for item in app.get("download_button")] == ["Download DOCX", "Download PDF"]


def assert_retained(before, generated):
    assert len(generated) == 1, "Saving/retrying/displaying must not generate good output again."
    assert library.load_snapshot_version(RRH_CONTRACT, "synthetic-guided", PERIOD, 2) == before
    assert saved().revision == 3
    assert saved().draft.fingerprint == before.draft.fingerprint


def test_first_generation_render_matches_saved_badge_before_history_refresh(monkeypatch, tmp_path):
    app, before, generated = setup(monkeypatch, tmp_path)
    button(app, "Create Word and PDF").click().run()
    # Do not rerun/open history before this assertion: that hid the defect.
    assert_version(app, 3)
    assert_retained(before, generated)
    app.run()
    assert_version(app, 3)
    assert_retained(before, generated)
    reopened = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    reopened.segmented_control[0].set_value("Monthly report").run()
    choose_report(reopened, synthetic_profiles()[0].facilities[0].title)
    assert not reopened.exception
    assert next(item for item in reopened.text_area if item.label == "Activity summary").value == "Synthetic inspection completed."
    assert_retained(before, generated)


def fail_generation_save(monkeypatch, app, before):
    real_save = library.save_snapshot

    def unavailable(*args, **kwargs):
        raise OSError("Synthetic shared write unavailable")

    monkeypatch.setattr(library, "save_snapshot", unavailable)
    button(app, "Create Word and PDF").click().run()
    assert not app.exception
    assert saved() == before
    assert any("Synthetic shared write unavailable" in item.value for item in app.warning)
    assert not any(item.value.startswith("[Shared version ") for item in app.caption)
    assert not button(app, "Retry saving this version").disabled
    assert [item.label for item in app.get("download_button")] == ["Download DOCX", "Download PDF"]
    monkeypatch.setattr(library, "save_snapshot", real_save)


def test_failed_save_remains_visible_and_retry_preserves_generated_files(monkeypatch, tmp_path):
    app, before, generated = setup(monkeypatch, tmp_path)
    fail_generation_save(monkeypatch, app, before)
    original = generated[0]
    button(app, "Retry saving this version").click().run()
    assert_version(app, 3)
    assert_retained(before, generated)
    assert generated[0] == original
    app.run()
    assert_version(app, 3)
    assert_retained(before, generated)


def test_explicit_later_manual_checkpoint_reconciles_failed_package_save(monkeypatch, tmp_path):
    app, before, generated = setup(monkeypatch, tmp_path)
    fail_generation_save(monkeypatch, app, before)
    button(app, "Save shared version").click().run()
    assert_version(app, 3)
    assert_retained(before, generated)
