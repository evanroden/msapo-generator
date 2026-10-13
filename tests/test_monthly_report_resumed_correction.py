"""Fresh-session source date/site corrections remain canonical and singular."""
from dataclasses import replace
from datetime import date

from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from test_monthly_report_ui import ROOT, choose_report, monthly


def test_saved_source_date_site_correction_on_resumed_report(monkeypatch, tmp_path):
    monthly(monkeypatch, tmp_path)
    profile = library.list_profiles(RRH_CONTRACT)[0]
    period = ReportPeriod(2026, 9)
    original = b"Vendor: Example Mechanical QA Services\nInspected motor. Replacement pending."
    content, _ = sources.ingest(profile, "service-note.txt", original)
    unresolved = replace(
        content.source, service_date="", facility="", classification="Vendor service"
    )
    state = library.load_profile(profile.contract, profile.key)
    draft = guided._initial_draft(state, period, "Synthetic Editor")
    library.save_snapshot(replace(draft, sources=(unresolved,)),
                          expected_revision=0, entered_editor="Synthetic Editor")

    # A fresh Streamlit session has no upload widget or native/completed-source
    # flags. Its saved original must still expose the SAME canonical resolver.
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, synthetic_profiles()[0].facilities[0].title)
    review = next(w for w in app.checkbox
                  if w.label == "Review source dates and sites from saved files")
    assert review.value
    assert len([w for w in app.date_input if w.label == "Source date"]) == 1
    site = next(w for w in app.selectbox if w.label == "Source facility")
    app.date_input[0].set_value(date(2026, 9, 20))
    site.set_value(profile.facilities[0].key)
    next(w for w in app.button if w.label == "Save corrected details").click().run()
    assert not app.exception
    prefix = "report_guided_" + guided._signature((RRH_CONTRACT, profile.key, period.key))
    revised, = app.session_state[prefix + "_draft"].sources
    assert revised.id == unresolved.id
    assert revised.sha256 == unresolved.sha256
    assert revised.service_date == "2026-09-20"
    assert revised.facility == profile.facilities[0].key
    assert sources.source_bytes(profile, revised) == original

    # A duplicate route or a rerun must never create a second correction form.
    app.run()
    assert not app.exception
    assert len([w for w in app.date_input if w.label == "Source date"]) == 1
    assert app.session_state[prefix + "_draft"].sources == (revised,)
