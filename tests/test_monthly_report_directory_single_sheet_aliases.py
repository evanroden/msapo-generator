"""Single-sheet import uses the batch's reviewed contract and site aliases (Refs #288, G2-directory-9).

A tab titled with a reviewed contract alias defaulted to "Add another contract"
with the raw title, so saving created a duplicate directory and landing card,
while the batch saved the same tab under the canonical contract. Reviewed site
aliases did not suggest the listed site either. Synthetic contacts only.
"""
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import detail, workbook

APP = """
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
render_directory(_field)
"""
CONTRACT = "Synthetic Aliased Contract"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setitem(batch.CONTRACT_ALIASES, "SYNTHETIC ALIAS HEADING", CONTRACT)
    monkeypatch.setitem(batch.SITE_ALIASES, CONTRACT, {"SYNTH NORTH CAMPUS": "Synthetic North"})
    directory.save_directory(CONTRACT, (directory.DirectorySite("north", "Synthetic North"),),
                             expected_revision=0, actor="Synthetic Editor", confirmed=True)


def sheet_named(name):
    return directory.inspect_workbook(workbook(((name, detail()),))).sheets[0]


@pytest.mark.parametrize(("name", "expected"), [
    ("SYNTHETIC ALIAS HEADING Sites", CONTRACT),
    ("2 - synthetic aliased contract", CONTRACT),
    ("Synthetic Unreviewed Heading Sites", ""),
])
def test_worksheet_contract_matches_the_batch_resolution(name, expected):
    assert batch.worksheet_contract(sheet_named(name)) == expected


def test_single_sheet_import_saves_an_aliased_tab_under_the_canonical_contract_and_site():
    raw = workbook((("SYNTHETIC ALIAS HEADING Sites", detail(B6="SYNTH NORTH CAMPUS")),))
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["report_directory_workbook"] = (raw, directory.inspect_workbook(raw))
    app.run()
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    assert not app.exception
    assert next(box for box in app.selectbox if box.label == "Save under contract").value == CONTRACT
    next(box for box in app.checkbox if box.label ==
         "I reviewed all included sites and contacts and confirm this shared save").check().run()
    next(button for button in app.button if button.label == "Save contract directory").click().run()
    assert not app.exception
    assert directory.directory_contracts() == (CONTRACT,)
    site, = directory.load_directory(CONTRACT).sites
    assert (site.key, site.title) == ("north", "Synthetic North")
    assert "SYNTH NORTH CAMPUS" in site.aliases
    assert [c.name for c in site.contacts] == ["Synthetic Site Lead"]
