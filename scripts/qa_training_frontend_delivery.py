"""Exact repaired assets naturally requested by one Training document.

Expectations come from pinned-source reconstruction, not served filenames or
self-reported hashes. No browser request or layout observation is introduced.
"""
from pathlib import Path
import re
from urllib.parse import urlparse

from scripts.qa_shared_fixture_testing import (
    _expected_frontend, _expected_overlay, _frontend_response_receipt,
    _overlay_response_receipt, _asset_response_receipt,
)


def _expected_combobox(static_dir=None):
    from hashlib import sha256
    import streamlit
    from scripts import patch_streamlit_frontend as compat
    root = static_dir or Path(streamlit.__file__).parent / "static"
    selected = compat.selected_frontend(root)
    if not selected["selection_safe_close"]:
        raise RuntimeError("The pinned frontend lacks selection-safe ComboBox close compatibility.")
    raw = (root / "static/js" / selected["combobox_bundle"]).read_bytes()
    if sha256(raw).hexdigest() != selected["combobox_sha256"]:
        raise RuntimeError("Pinned ComboBox frontend changed after validation.")
    return selected["combobox_bundle"], raw


def _combobox_response_receipt(response, expected):
    from scripts.streamlit_combobox_close import CLOSE_REPAIRED
    receipt, raw = _asset_response_receipt(response, expected)
    receipt["selection_safe_close_count"] = raw.count(CLOSE_REPAIRED)
    receipt["matches"] = bool(receipt.get("matches") and receipt["selection_safe_close_count"] == 1)
    return receipt


class TrainingFrontendDelivery:
    def __init__(self, static_dir=None):
        self.expected = {"primary": _expected_frontend(static_dir),
                         "overlay": _expected_overlay(static_dir),
                         "combobox": _expected_combobox(static_dir)}
        self.receipts = {kind: [] for kind in self.expected}

    def attach(self, page):
        page.on("response", self.observe)

    def observe(self, response):
        path = urlparse(response.url).path
        name = Path(path).name
        # index.esm vendor preloads can finish before the much larger entry.
        # Only known main-entry variants may consume the primary observation.
        kind = ("primary" if re.fullmatch(
                    r"/static/js/index\.(?:enfra-(?:frontend|date)-[0-9a-f]{12}|bE3scgDe)\.js", path) else
                "overlay" if name.startswith("Tooltip.DJg7muty") else
                "combobox" if name.startswith("fuzzyFilterSelectOptions.Bf8rcmtM") else None)
        if kind is None or self.receipts[kind]:
            return
        rows = self.receipts[kind]
        # Mark consumption before reading the actual response body. A later
        # reload cannot replace an incomplete or wrong first delivery.
        rows.append({"matches": False, "error": "response observation incomplete"})
        try:
            observe = {"primary": lambda response, expected: _frontend_response_receipt(
                           response, expected, require_instant_expander=True), "overlay": _overlay_response_receipt,
                       "combobox": _combobox_response_receipt}[kind]
            rows[0] = observe(response, self.expected[kind])
        except Exception as exc:
            rows[0] = {"matches": False, "error": type(exc).__name__ + ": " + str(exc)[:300]}

    def require(self):
        for kind, rows in self.receipts.items():
            assert len(rows) == 1 and rows[0].get("matches"), (
                "Training browser must receive the exact pinned repaired " + kind + " asset", rows)
