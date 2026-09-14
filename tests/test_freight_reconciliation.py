"""A quote carrying freight must not be rejected as internally inconsistent.

Reported from production: a Grainger water-softener-salt quote could not be
completed. The page blocked on "Subtotal plus sales tax does not equal the total
amount" and named nothing the operator could act on.

The quote's arithmetic was correct:

    Sub Total                 513.45
    Estimated Shipping          0.00
    Estimated Other Shipping  209.00   <- freight
    Tax                        57.80
    Total  USD                780.25   = 513.45 + 209.00 + 57.80

The check was symmetric -- abs((subtotal + tax) - total) -- so it saw a 209.00
discrepancy that was simply the shipping line.

This was the tool contradicting ITSELF, not a bad extraction. quote_analyzer's
prompt defines total_amount as "the final grand total the customer pays,
including every stated tax, freight charge, delivery charge, surcharge, and
other fee", while subtotal_amount is the pre-tax subtotal. On any quote with
shipping those two fields are CORRECTLY unequal by the freight, and the
validator then refused the extraction its own prompt had asked for.

Nothing covered this warning before, which is how it shipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.po_context import build_po_context  # noqa: E402
from app.po_rules import MATERIALS_PURCHASE  # noqa: E402
from test_po_context import _analysis, _state  # noqa: E402

_RECONCILIATION = "Subtotal plus sales tax"


def _context(*, subtotal: str, tax: str, total: str):
    state = _state(route=MATERIALS_PURCHASE, total=total)
    state["analysis"] = _analysis(
        subtotal_amount=subtotal, tax_amount=tax, total_amount=total
    )
    return build_po_context(state)


def _reconciliation_warnings(context) -> list[str]:
    return [w for w in context.warnings if _RECONCILIATION in w]


def test_the_reported_grainger_salt_quote_is_not_blocked():
    """The exact case. 209.00 of freight sits between the subtotal and the tax."""
    context = _context(subtotal="$513.45", tax="$57.80", total="$780.25")

    assert _reconciliation_warnings(context) == []
    assert context.ready, f"still blocked by: {context.warnings}"


@pytest.mark.parametrize(
    ("label", "subtotal", "tax", "total"),
    [
        ("freight only", "$513.45", "$57.80", "$780.25"),
        ("delivery surcharge", "$100.00", "$8.00", "$135.00"),
        ("large freight on a small order", "$25.00", "$2.00", "$210.00"),
        ("no freight, exact", "$100.00", "$8.00", "$108.00"),
        ("vendor rounding, one cent high", "$100.00", "$8.00", "$108.01"),
        ("vendor rounding, one cent low", "$100.00", "$8.00", "$107.99"),
    ],
)
def test_a_total_at_or_above_subtotal_plus_tax_is_accepted(label, subtotal, tax, total):
    """A total may exceed subtotal + tax by ANY amount -- freight, delivery,
    surcharges, fees. The tolerance still absorbs the vendor's own rounding in
    the other direction."""
    assert _reconciliation_warnings(_context(subtotal=subtotal, tax=tax, total=total)) == [], label


@pytest.mark.parametrize(
    ("label", "subtotal", "tax", "total"),
    [
        ("subtotal captured as the total", "$500.00", "$40.00", "$300.00"),
        ("dropped leading digit", "$513.45", "$57.80", "$80.25"),
        ("two cents short -- past the tolerance", "$100.00", "$8.00", "$107.98"),
    ],
)
def test_a_total_below_subtotal_plus_tax_still_blocks(label, subtotal, tax, total):
    """The direction this check exists for. A total SHORT of subtotal plus tax
    cannot be explained by any additional charge -- it means a misread figure,
    and it must still stop the package."""
    context = _context(subtotal=subtotal, tax=tax, total=total)

    assert _reconciliation_warnings(context), label
    assert not context.ready, label


def test_the_message_says_which_direction_is_wrong():
    """"does not equal" gave the operator nothing to check. The surviving case
    is always the same one, so the message can name it."""
    context = _context(subtotal="$500.00", tax="$40.00", total="$300.00")
    assert "MORE than the stated total" in _reconciliation_warnings(context)[0]


def test_a_quote_with_no_stated_subtotal_is_still_silent():
    """Unchanged behaviour, and deliberate: a quote showing one all-in amount is
    normal, and warning about a missing subtotal would train operators to ignore
    the message."""
    context = _context(subtotal="", tax="", total="$780.25")
    assert _reconciliation_warnings(context) == []
