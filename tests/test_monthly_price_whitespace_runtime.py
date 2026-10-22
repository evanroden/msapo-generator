"""Refs #276: extracted whitespace must not stall the monthly price gate.

Use a killable subprocess and a generous bound, rather than a tight benchmark,
so a regex regression cannot wedge the main test runner. Text reaches the public
predicate unchanged, including whitespace within approximate amounts.
"""

import json
from pathlib import Path
import subprocess
import sys

import pytest


_GAP = " " * 10_000
_ROOT = Path(__file__).resolve().parents[1]
_WORKER = """
import json
import sys
from app.monthly_report_content_policy import contains_price

texts = json.load(sys.stdin)
print(json.dumps([contains_price(text) for text in texts]))
"""


def _check_bounded(cases):
    texts, expected = zip(*cases)
    try:
        result = subprocess.run(
            [sys.executable, "-c", _WORKER], cwd=_ROOT,
            input=json.dumps(texts), capture_output=True, text=True,
            timeout=5, check=True,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run kills and waits for its child before raising.
        pytest.fail("Price checks exceeded 5 seconds on 10,000-space inputs", pytrace=False)
    assert json.loads(result.stdout) == list(expected)


@pytest.mark.parametrize("texts", (
    pytest.param(("Quote" + _GAP + "x",), id="after-price-label"),
    pytest.param(("USD" + _GAP + "x", "$" + _GAP + "x"), id="after-currency-prefix"),
    pytest.param(("3200" + _GAP + "pending",), id="before-absent-currency-suffix"),
    pytest.param(("Quote (" + _GAP + "x)", "Quote (~" + _GAP + "x)"),
                 id="after-parenthesis-and-approximation"),
))
def test_long_whitespace_without_an_amount_finishes(texts):
    _check_bounded(tuple((text, False) for text in texts))


def test_long_whitespace_preserves_price_and_technical_meaning():
    _check_bounded((
        ("Quote" + _GAP + "3200", True),
        ("USD" + _GAP + "3200", True),
        ("$" + _GAP + "3200", True),
        ("3200" + _GAP + "USD", True),
        ("Quote (~" + _GAP + "3.2k)", True),
        ("Estimate" + _GAP + "125 psi", False),
        ("Estimate (~" + _GAP + "125) psi", False),
        ("3200" + _GAP + "kW", False),
    ))
