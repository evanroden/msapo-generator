from pathlib import Path

from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

import app.web_ui as web_ui
from app.quote_analyzer import QuoteAnalysis


ROOT = Path(__file__).parents[1]


def _configure_smartsheet(monkeypatch):
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)


def test_synthetic_rrh_quick_path_generates_two_files_and_native_new_tab_link(
    monkeypatch,
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_ENABLE_SYNTHETIC_SAMPLE", "true")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert [item.label for item in app.expander] == [
        "Review scope, inclusions, and exclusions (optional)",
        "Change a value the tool already filled",
    ]
    assert app.button[1].disabled

    app.text_input[0].set_value("Synthetic Asset Manager").run()
    assert not app.button[1].disabled
    app.button[1].click().run()

    assert not app.exception
    assert len(app.get("download_button")) == 2
    links = app.get("link_button")
    assert len(links) == 1
    assert links[0].label == "Open Smartsheet in a new tab ↗"
    assert "REQUESTER=Synthetic%20Asset%20Manager" in links[0].url
    assert "DESCRIPTION%20OF%20WORK=Chiller%20Repair" in links[0].url
    assert "ASSET%20ID=EEA-CH-1-CSHC" in links[0].url
    assert "DISPATCH%20WO%20TO%20SERVICE%20CENTER%3F=NA" in links[0].url


def test_synthetic_sample_control_is_absent_from_the_production_path(monkeypatch):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_ENABLE_SYNTHETIC_SAMPLE", "false")

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    assert not app.exception
    assert "Load synthetic sample (testing)" not in {
        item.label for item in app.button
    }


def test_unresolved_fields_are_visible_stable_and_not_in_correction_panel(
    monkeypatch,
):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setattr(
        web_ui,
        "analyze_quote",
        lambda _text: QuoteAnalysis(
            scope_of_work="Repair unidentified equipment.",
            purchase_route_guess="materials_purchase",
            request_type_guess="PO",
            tax_status="unclear",
        ),
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()

    app.radio[0].set_value("Paste text").run()
    app.text_area[0].set_value("Quote without usable routing fields").run()

    assert not app.exception
    assert any(
        'class="tax-alert" role="alert"' in item.value
        and "No tax was found" in item.value
        for item in app.markdown
    )
    unresolved_labels = {
        "PO/CO amount — final total including every fee and tax *",
        "Vendor name *",
        "Short description (20 characters maximum)",
    }
    assert unresolved_labels <= {item.label for item in app.text_input}
    assert not unresolved_labels & {
        item.label for item in app.expander[1].text_input
    }

    app.text_input[0].set_value("123.45").run()

    assert unresolved_labels <= {item.label for item in app.text_input}
    assert not unresolved_labels & {
        item.label for item in app.expander[1].text_input
    }
    warnings = [item.value for item in app.warning]
    assert not any("all-in PO/CO amount" in message for message in warnings)
    assert not any(".." in message for message in warnings)
