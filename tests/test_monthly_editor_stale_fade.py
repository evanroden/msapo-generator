"""Review F10: ordinary reruns must not gray out the whole Monthly editor."""
import re
from pathlib import Path

import streamlit

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app" / "workspace_initial.css").read_text(encoding="utf-8")
STALE = '.st-key-epc_workspace_monthly [data-testid="stElementContainer"][data-stale="true"]'


def _rule(selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, selector
    return dict(part.split(":", 1) for part in match.group(1).replace(" ", "").split(";") if part)


def test_streamlit_still_fades_stale_elements_the_way_the_override_expects():
    # The override is written against Streamlit's own stale style. If an
    # upgrade changes that style, this fails so the override is rechecked.
    bundle = Path(streamlit.__file__).parent / "static" / "static" / "js"
    text = "".join(p.read_text(encoding="utf-8", errors="ignore")
                   for p in bundle.glob("index.*.js"))
    assert "`1s ease-in 0.5s`" in text and "transition:`opacity ${" in text
    assert '"data-stale":' in text


def test_monthly_editor_stays_solid_through_ordinary_reruns():
    container = _rule(STALE)
    assert container["opacity"] == "1"
    delay = float(re.search(r"ease-in([\d.]+)s", container["transition"]).group(1))
    assert delay >= 3, "Only a long-running update may dim the editor"


def test_long_updates_dim_each_field_once_and_lightly():
    leaf = _rule(STALE + ':not(:has([data-testid="stElementContainer"]))')
    assert 0.6 <= float(leaf["opacity"]) < 1
    assert _rule('.st-key-epc_workspace_monthly [data-testid="stExpander"] summary')["opacity"] == "1"


def test_override_is_scoped_to_the_monthly_editor():
    for line in CSS.splitlines():
        if "data-stale" in line and "{" in line:
            assert line.startswith(".st-key-epc_workspace_monthly "), line
