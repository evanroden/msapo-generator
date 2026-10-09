"""Regression coverage for saved-name collisions and resumed report identities."""

from dataclasses import replace
from io import BytesIO
from unittest.mock import patch

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_docx import _build_docx
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, profile_sections, synthetic_profiles
from app.monthly_report_start import refresh_profile_identity
from test_monthly_report_ui import ROOT, choose_report, monthly


CONTRACT_APP = """
import streamlit as st
from app.monthly_report_start_ui import choose_contract
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
choose_contract('', field)
"""

SITES_APP = """
import streamlit as st
from app.monthly_report_start_ui import select_sites
from app.contracts import RRH_CONTRACT
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
candidate, existing = select_sites(RRH_CONTRACT, (), '', field)
st.session_state['candidate'] = candidate
"""

IMPORT_SITES_APP = """
import streamlit as st
from app.monthly_report_section_ui import _identity
from app.contracts import RRH_CONTRACT
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
candidate, actor, missing = _identity(RRH_CONTRACT, 'Synthetic Editor', 'test_import', field, None)
st.session_state['candidate'] = candidate
"""


def test_lowercase_saved_contract_does_not_crash_landing_page(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    directory.save_directory("rochester regional health", (directory.DirectorySite("synthetic-site", "Synthetic Site"),),
                             expected_revision=0, actor="Synthetic Editor", confirmed=True)
    app = AppTest.from_string(CONTRACT_APP).run()
    assert not app.exception
    # Directory and catalog spelling represent one choice after normalization.
    assert sum(b.label.casefold() == RRH_CONTRACT.casefold() for b in app.button) == 1


def test_contract_cards_survive_display_slug_collisions(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    names = ["Synthetic A&B", "Synthetic A-B", "Synthetic " + "x" * 65 + "1", "Synthetic " + "x" * 65 + "2"]
    with patch("app.monthly_report_start_ui.contract_choices", return_value=names):
        app = AppTest.from_string(CONTRACT_APP).run()
        assert not app.exception
        assert {b.label for b in app.button} == set(names)
        assert len({b.key for b in app.button}) == len(names)


@pytest.mark.parametrize("custom", ["Unity", "Unity Hospital", "New Site; New Site", "A&B; A-B", "---"])
def test_duplicate_or_invalid_custom_site_is_recoverable_on_rerun(monkeypatch, tmp_path, custom):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(SITES_APP).run()
    next(w for w in app.checkbox if w.label == "Unity Hospital").check().run()
    next(w for w in app.text_input if w.label == "Site name").set_value(custom).run()
    assert not app.exception
    assert app.warning
    assert app.session_state["candidate"] is None
    # The still-populated value must not turn a reload into a widget exception.
    app.run()
    assert not app.exception
    next(w for w in app.text_input if w.label == "Site name").set_value("").run()
    assert not app.exception
    assert tuple(f.title for f in app.session_state["candidate"].facilities) == ("Unity Hospital",)


def test_current_profile_identity_refresh_preserves_draft_design_and_membership():
    profile = synthetic_profiles()[1]
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", profile_sections(profile), ())
    current = replace(profile, title="Renamed Region", scope_type="regional", excluded_sections=("activity",))
    refreshed = refresh_profile_identity(draft, current)
    assert refreshed.profile.title == "Renamed Region"
    assert refreshed.profile.scope_type == "regional"
    assert refreshed.profile.excluded_sections == profile.excluded_sections
    assert refreshed.sections == draft.sections
    assert draft.profile.title == profile.title
    other_sites = replace(current, facilities=(Facility("different", "Different site"),), scope_type="individual")
    assert refresh_profile_identity(draft, other_sites) is draft
    assert refresh_profile_identity(draft, replace(current, key="different")) is draft


@pytest.mark.parametrize("custom", ["Unity", "Unity Hospital", "---"])
def test_standalone_import_site_identity_recovers_from_duplicate_name(monkeypatch, tmp_path, custom):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(IMPORT_SITES_APP).run()
    app.multiselect[0].set_value(["unity"]).run()
    next(w for w in app.text_input if w.label == "Site not listed? Add its name here").set_value(custom).run()
    assert not app.exception
    assert app.warning
    app.run()
    assert not app.exception
    next(w for w in app.text_input if w.label == "Site not listed? Add its name here").set_value("").run()
    assert not app.exception
    assert tuple(f.title for f in app.session_state["candidate"].facilities) == ("Unity Hospital",)


@pytest.mark.parametrize("source", ["snapshot", "imported"])
def test_resumed_saved_report_uses_current_group_name_on_docx_cover(monkeypatch, tmp_path, source):
    from app.monthly_report_guided import _initial_draft
    from app.monthly_report_start import save_design_start

    monthly(monkeypatch, tmp_path, saved=False)
    profile = replace(synthetic_profiles()[1], contract=RRH_CONTRACT, key="synthetic-rename",
                      title="Former group name")
    if source == "snapshot":
        state = library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
        initial = _initial_draft(state, ReportPeriod(2026, 9), "Synthetic Editor")
        library.save_snapshot(initial, expected_revision=0, entered_editor="Synthetic Editor")
    else:
        initial = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", profile_sections(profile), ())
        state = save_design_start(initial, {}, actor="Synthetic Editor", confirmed=True)
    renamed = replace(profile, title="Current group name")
    library.save_profile(renamed, expected_revision=state.revision, actor="Synthetic Editor", confirmed=True)

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app)
    for facility in profile.facilities:
        next(w for w in app.checkbox if w.label == facility.title).check().run()
    assert not app.exception
    working = next(v for k, v in app.session_state.filtered_state.items()
                   if k.endswith("_draft") and isinstance(v, ReportDraft))
    assert working.profile.title == "Current group name"
    # Assert the actual generated document title, not just the UI heading.
    document = Document(BytesIO(_build_docx(working)))
    cover_text = "\n".join(p.text for p in document.paragraphs)
    assert "Current group name" in cover_text
    assert "Former group name" not in cover_text
    saved = library.load_snapshot(profile.contract, profile.key, initial.period).draft if source == "snapshot" else library.load_imported_draft(profile.contract, profile.key)
    assert saved.profile.title == "Former group name"
