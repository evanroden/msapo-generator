"""Shared names stay literal while their saved identity and actions survive."""

from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding, monthly_report_directory as directory
from test_monthly_report_branding import collection
from test_monthly_report_directory_access_ui import DIRECTORY_APP, enter_directory


NAME = "[Synthetic](https://example.invalid) **Account**"
EDITOR = "[Reviewer](https://example.invalid) _Synthetic_"
ESCAPED_NAME = r"\[Synthetic\]\(https\:\/\/example\.invalid\) \*\*Account\*\*"
ESCAPED_EDITOR = r"\[Reviewer\]\(https\:\/\/example\.invalid\) \_Synthetic\_"


def seed(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return directory.save_directory(NAME, (directory.DirectorySite("synthetic", "Synthetic Site"),),
                                    expected_revision=0, actor=EDITOR, confirmed=True)


def test_contract_card_and_selected_title_preserve_literal_name_and_identity(monkeypatch, tmp_path):
    original = seed(monkeypatch, tmp_path)
    logos, assets = collection()
    branding.save_branding((replace(logos[0], title=NAME, contracts=(NAME,)),), assets,
                          expected_revision=0, actor=EDITOR, confirmed=True)
    app = AppTest.from_string('''
from app.monthly_report_start_ui import choose_contract
from app.monthly_report_ui import _field
choose_contract('', _field)
''').run()
    button = next(b for b in app.button if "Synthetic" in b.label)
    assert button.label == ESCAPED_NAME
    button.click().run()
    assert not app.exception
    assert app.session_state["report_contract"] == NAME
    assert app.subheader[0].value == ESCAPED_NAME
    app.run()
    assert app.session_state["report_contract"] == NAME
    assert directory.load_directory(NAME) == original


def test_directory_editor_history_and_archive_copy_keep_metadata_literal(monkeypatch, tmp_path):
    original = seed(monkeypatch, tmp_path)
    app = enter_directory(AppTest.from_string(DIRECTORY_APP).run())
    captions = [c.value for c in app.caption if "Reviewer" in c.value]
    assert len(captions) == 2
    assert all(ESCAPED_EDITOR in value for value in captions)
    archive = next(m.value for m in app.markdown if "Archive the shared contact list" in m.value)
    assert ESCAPED_NAME in archive
    assert directory.load_directory(NAME) == original


def test_batch_result_contract_names_are_literal():
    app = AppTest.from_string('''
from app.monthly_report_directory_batch import BatchSaveResult
from app.monthly_report_directory_batch_ui import _show_result
name = '[Synthetic](https://example.invalid) **Account**'
_show_result(BatchSaveResult(saved=(name,), unchanged=(name,)))
''').run()
    assert not app.exception
    results = [c.value for c in app.caption if "Synthetic" in c.value]
    assert len(results) == 2
    assert all(ESCAPED_NAME in value for value in results)


def test_site_summary_keeps_group_and_site_names_literal_after_selection():
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_model import Facility, ReportProfile
from app.monthly_report_start_ui import identity_summary, select_sites
from app.monthly_report_ui import _field
name = '[Synthetic](https://example.invalid) **Account**'
profile = ReportProfile('Synthetic Contract', 'synthetic-group', name,
                        (Facility('synthetic-site', name),
                         Facility('synthetic-south', 'Synthetic South')), 'multi_site')
candidate, existing = select_sites(profile.contract, (profile,), profile.key, _field)
if candidate:
    st.caption(identity_summary(candidate))
    st.session_state['selected_site_titles'] = tuple(site.title for site in candidate.facilities)
''').run()
    assert not app.exception
    assert app.caption[0].value == (
        ESCAPED_NAME + " · Combined report · Sites: " + ESCAPED_NAME + "; Synthetic South")
    assert app.session_state["selected_site_titles"] == (NAME, "Synthetic South")
    next(box for box in app.checkbox if box.label == "Synthetic South").uncheck().run()
    assert not app.exception
    assert app.caption[0].value == "Site: " + ESCAPED_NAME
    assert app.session_state["selected_site_titles"] == (NAME,)
    assert next(box for box in app.checkbox if box.label == ESCAPED_NAME).value
