"""Exact repaired assets naturally requested by one Training document.

Expectations come from pinned-source reconstruction, not served filenames or
self-reported hashes. No browser request or layout observation is introduced.
"""
from pathlib import Path
import re
from urllib.parse import urlparse

from scripts.qa_shared_fixture_testing import (
    _expected_frontend, _expected_overlay, _frontend_response_receipt,
    _overlay_response_receipt,
)


class TrainingFrontendDelivery:
    def __init__(self, static_dir=None):
        self.expected = {"primary": _expected_frontend(static_dir),
                         "overlay": _expected_overlay(static_dir)}
        self.receipts = {"primary": [], "overlay": []}

    def attach(self, page):
        page.on("response", self.observe)

    def observe(self, response):
        path = urlparse(response.url).path
        name = Path(path).name
        # index.esm vendor preloads can finish before the much larger entry.
        # Only known main-entry variants may consume the primary observation.
        kind = ("primary" if re.fullmatch(
                    r"/static/js/index\.(?:enfra-(?:frontend|date)-[0-9a-f]{12}|bE3scgDe)\.js", path) else
                "overlay" if name.startswith("Tooltip.DJg7muty") else None)
        if kind is None or self.receipts[kind]:
            return
        rows = self.receipts[kind]
        # Mark consumption before reading the actual response body. A later
        # reload cannot replace an incomplete or wrong first delivery.
        rows.append({"matches": False, "error": "response observation incomplete"})
        try:
            observe = _frontend_response_receipt if kind == "primary" else _overlay_response_receipt
            rows[0] = observe(response, self.expected[kind])
        except Exception as exc:
            rows[0] = {"matches": False, "error": type(exc).__name__ + ": " + str(exc)[:300]}

    def require(self):
        for kind, rows in self.receipts.items():
            assert len(rows) == 1 and rows[0].get("matches"), (
                "Training browser must receive the exact pinned repaired " + kind + " asset", rows)
