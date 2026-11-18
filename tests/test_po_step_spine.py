"""Synthetic U10 journey through the unchanged purchase-order gate."""
import re
from pathlib import Path

from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

import app.web_ui as web_ui
from app.po_step_spine import PO_STEPS, po_step_spine, po_step_states

ROOT = Path(__file__).parents[1]


def _configure_smartsheet(monkeypatch):
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)


def _spine(app: AppTest) -> tuple[str, tuple[str, ...]]:
    spines = [item.value for item in app.markdown
              if 'class="po-step-spine"' in item.value]
    assert len(spines) == 1
    return spines[0], tuple(re.findall(r'data-state="(complete|current|pending)"', spines[0]))


def test_states_and_anchor_links_are_ordered_and_accessible():
    assert po_step_states() == ("current", "pending", "pending", "pending")
    assert po_step_states(quote_ready=True) == ("complete", "current", "pending", "pending")
    assert po_step_states(quote_ready=True, scope_ready=True) == (
        "complete", "complete", "current", "pending"
    )
    ready = po_step_states(quote_ready=True, scope_ready=True, details_ready=True)
    assert ready == ("complete", "complete", "complete", "current")
    assert po_step_states(quote_ready=True, scope_ready=True, details_ready=True,
                          generated=True) == ("complete",) * 4
    assert po_step_states(quote_ready=False, generated=True)[-1] == "pending"

    markup = po_step_spine(ready)
    assert markup.count('aria-current="step"') == 1
    assert markup.count('class="step-num"') == 4
    for anchor, title, summary in PO_STEPS:
        assert f'href="#po-step-{anchor}"' in markup
        assert title in markup and summary in markup


def test_po_step_spine_app_test_paste_journey_with_mocked_model(monkeypatch):
    _configure_smartsheet(monkeypatch)
    # Reuse only the built-in synthetic model output; no vendor call is made.
    monkeypatch.setattr(
        web_ui, "analyze_quote", lambda _quote: web_ui._build_test_analysis()
    )
    monkeypatch.setattr(
        web_ui, "build_msapo_pdf",
        lambda **_kwargs: b"%PDF-1.7\\nSynthetic package",
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    assert not app.exception
    markup, states = _spine(app)
    assert states == ("current", "pending", "pending", "pending")
    assert markup.count('aria-current="step"') == 1

    app.radio[0].set_value("Paste text").run()
    app.text_area[0].set_value(web_ui._build_test_analysis().scope_of_work).run()
    assert not app.exception
    _, states = _spine(app)
    assert states == ("complete", "complete", "current", "pending")
    for anchor, _, _ in PO_STEPS:
        assert any(f'id="po-step-{anchor}"' in item.value for item in app.markdown)
    generate = next(b for b in app.button if b.label == "Generate both files and Smartsheet link")
    assert generate.disabled

    requester = next(field for field in app.text_input
                     if field.label == "Your name (Requester / Asset Manager) *")
    requester.set_value("Synthetic Requester").run()
    assert not app.exception
    generate = next(b for b in app.button if b.label == "Generate both files and Smartsheet link")
    assert not generate.disabled
    assert _spine(app)[1] == ("complete", "complete", "complete", "current")

    generate.click().run()
    assert not app.exception
    assert _spine(app)[1] == ("complete",) * 4
    assert len(app.get("download_button")) == 2
    assert len(app.get("link_button")) == 1

    requester = next(field for field in app.text_input
                     if field.label == "Your name (Requester / Asset Manager) *")
    requester.set_value("").run()
    assert not app.exception
    assert next(b for b in app.button
                if b.label == "Generate both files and Smartsheet link").disabled
    assert _spine(app)[1] == ("complete", "complete", "current", "pending")
