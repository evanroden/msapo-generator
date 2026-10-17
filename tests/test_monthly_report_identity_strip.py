"""Site details have one scoped save while the report keeps its pinned design."""

from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided, monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_designs import MASTER_PREFIX
from app.monthly_report_model import ReportDraft, ReportPeriod, profile_sections, synthetic_profiles
from test_monthly_report_ui import monthly


DETAILS_APP = """
import streamlit as st
from app import monthly_report_guided as guided
old, candidate, working, actor = guided._test_report_details
prefix = 'report_guided_' + guided._signature((old.contract, old.key, working.period.key))
st.session_state.setdefault(prefix + '_prepared', actor)
st.session_state.setdefault(prefix + '_draft', working)
guided._render_report_details_action(candidate, old, working.period, 'd' * 32)
"""


def details_app(monkeypatch, tmp_path, *, actor="Current editor"):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    old = synthetic_profiles()[1]
    library.save_profile(old, expected_revision=0, actor="Original editor", confirmed=True)
    pinned = replace(old, template=MASTER_PREFIX + "a" * 64)
    working = ReportDraft(pinned, ReportPeriod(2026, 9), actor, profile_sections(pinned), ())
    candidate = replace(old, title="Current region", scope_type="regional", facilities=(
        replace(old.facilities[0], aliases=("North alternate name",)), old.facilities[1]))
    monkeypatch.setattr(guided, "_test_report_details", (old, candidate, working, actor), raising=False)
    return AppTest.from_string(DETAILS_APP).run(), old, candidate, working


def test_one_details_disclosure_and_exact_identity_replace_repeated_site_prose(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    assert not app.exception
    labels = [item.label for item in app.expander]
    assert labels.count("More report details") == 1
    assert "Add a site that is not listed" not in labels
    assert "Other names for these sites (optional)" not in labels
    assert labels.count("Change report sites") == 1
    first = next(item for item in app.checkbox if item.key.startswith("report_sites_"))
    first.check().run()
    assert not app.exception
    assert any(item.value == "Site: " + first.label for item in app.caption)
    assert not any("Sites selected (" in item.value for item in app.caption)
    assert not any(item.value == "Sites in this report" for item in app.subheader)
    # Month and year remain independently editable native controls together.
    assert app.selectbox("report_month_number").value == 9
    assert app.selectbox("report_year").value == 2026
    assert library.list_profiles(RRH_CONTRACT) == ()


def test_explicit_details_save_preserves_working_design_content_and_immutable_history(monkeypatch, tmp_path):
    app, old, candidate, working = details_app(monkeypatch, tmp_path)
    previous = library.save_snapshot(working, expected_revision=0, entered_editor="Original editor")
    assert not app.exception
    assert library.load_profile(old.contract, old.key).profile == old
    next(item for item in app.button if item.label == "Save report details").click().run()
    assert not app.exception
    saved_profile = library.load_profile(old.contract, old.key)
    assert saved_profile.profile == candidate and saved_profile.revision == 2
    current = next(value for value in app.session_state.filtered_state.values() if isinstance(value, ReportDraft))
    assert current.profile.title == candidate.title and current.profile.scope_type == "regional"
    assert current.profile.facilities == candidate.facilities
    assert current.profile.template == working.profile.template
    assert current.sections == working.sections and current.blocks == working.blocks
    assert library.load_snapshot(old.contract, old.key, working.period) == previous


def test_cleared_current_attribution_does_not_reuse_remembered_name_for_details_save(monkeypatch, tmp_path):
    monkeypatch.setattr(guided, "remembered_report_preparer", lambda *args: "Remembered editor")
    app, old, candidate, working = details_app(monkeypatch, tmp_path, actor="")
    assert not app.exception
    assert next(item for item in app.button if item.label == "Save report details").disabled
    assert library.load_profile(old.contract, old.key).profile == old


def test_failed_scoped_details_save_preserves_edits_and_existing_profile(monkeypatch, tmp_path):
    app, old, candidate, working = details_app(monkeypatch, tmp_path)

    def fail(*args, **kwargs):
        raise OSError("Synthetic profile disk unavailable")

    monkeypatch.setattr(library, "save_profile", fail)
    next(item for item in app.button if item.label == "Save report details").click().run()
    assert not app.exception
    assert any("Report details could not be saved" in item.value for item in app.error)
    assert library.load_profile(old.contract, old.key).profile == old
    assert next(value for value in app.session_state.filtered_state.values() if isinstance(value, ReportDraft)) == working


def test_stale_profile_details_cannot_overwrite_a_concurrent_saved_change(monkeypatch, tmp_path):
    app, old, candidate, working = details_app(monkeypatch, tmp_path)
    newer = replace(old, title="Other editor's newer group")
    library.save_profile(newer, expected_revision=1, actor="Other editor", confirmed=True)
    next(item for item in app.button if item.label == "Save report details").click().run()
    assert not app.exception
    assert any("changed while you were editing" in item.value for item in app.warning)
    assert library.load_profile(old.contract, old.key).profile == newer


def test_refreshed_profile_read_does_not_silently_acknowledge_a_concurrent_revision(monkeypatch, tmp_path):
    _, old, candidate, working = details_app(monkeypatch, tmp_path)
    app = AppTest.from_string("""
import streamlit as st
from dataclasses import replace
from app import monthly_report_guided as guided, monthly_report_library as library
original, proposed, working, actor = guided._test_report_details
current = library.load_profile(original.contract, original.key).profile
candidate = replace(current, title=proposed.title, scope_type=proposed.scope_type,
                    facilities=proposed.facilities)
prefix = 'report_guided_' + guided._signature((current.contract, current.key, working.period.key))
st.session_state.setdefault(prefix + '_prepared', actor)
st.session_state.setdefault(prefix + '_draft', working)
guided._render_report_details_action(candidate, current, working.period, 'd' * 32)
""").run()
    assert not app.exception
    newer = replace(old, title="Other editor's newer group")
    library.save_profile(newer, expected_revision=1, actor="Other editor", confirmed=True)
    next(item for item in app.button if item.label == "Save report details").click().run()
    assert not app.exception
    assert any("while your changes were pending" in item.value for item in app.warning)
    assert library.load_profile(old.contract, old.key).profile == newer
    assert not any(item.label == "Save report details" for item in app.button)
    next(item for item in app.button if item.label == "Continue with these report details").click().run()
    assert not app.exception
    assert library.load_profile(old.contract, old.key).profile == newer
    next(item for item in app.button if item.label == "Save report details").click().run()
    assert not app.exception
    saved = library.load_profile(old.contract, old.key)
    assert saved.revision == 3 and saved.profile == candidate


@pytest.mark.parametrize("qa", [None, "isolated", "fixtures"])
def test_empty_contract_result_links_to_the_actual_directory_without_report_identity(monkeypatch, tmp_path, qa):
    from app import monthly_report_start_ui as start
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(start, "contract_choices", lambda: ("Existing contract",))
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_start_ui import choose_contract
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
choose_contract('', field)
""")
    if qa:
        app.query_params["monthly_qa"] = qa
    app.query_params["contract"] = "PRIVATE SITE"
    app.run()
    next(item for item in app.text_input if item.label == "Find a contract").set_value("No matching client").run()
    assert not app.exception
    links = app.get("link_button")
    link = next(item for item in links if item.proto.label == "Open contract directory")
    assert link.proto.url.startswith("?workflow=monthly")
    assert "monthly_admin=directory" in link.proto.url and "PRIVATE" not in link.proto.url
    if qa:
        assert "monthly_qa=" + qa in link.proto.url
