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
