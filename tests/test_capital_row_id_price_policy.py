"""New capital row IDs never read as money to the client price check.

A bare 24-character hex ID ending in "<digit>cad" or "<digit>aed" reads as an
amount in Canadian dollars or dirhams. About one generated ID in 3,000 had
that shape, and the report then refused its capital details at random.
"""
from hashlib import sha256
from itertools import count

from app.monthly_report_capital_ui import _row_id
from app.monthly_report_content_policy import contains_price, table_has_pricing

DETAIL_COLUMNS = ("Facility", "Capital ID", "Field", "Value")


def _source_with_currency_like_digest(code):
    """A synthetic source whose digest ends "<digit><code>", like the old IDs."""
    for n in count():
        value = f"synthetic-capital-source-{n}"
        digest = sha256(value.encode()).hexdigest()[:24]
        if digest.endswith(code) and digest[-4].isdigit():
            return value, digest


def test_old_hex_ending_reads_as_money_and_new_id_does_not():
    for code in ("cad", "aed"):
        value, digest = _source_with_currency_like_digest(code)
        # The shape the policy rejected before: the bare hex ID.
        assert contains_price("Synthetic South\timport-" + digest + "\tCapital ID")
        for kind in ("import", "report"):
            row_id = _row_id(kind, value)
            assert row_id == f"{kind}-{digest}x"
            row = ("Synthetic South", row_id, "Capital ID", row_id)
            assert not contains_price("\t".join(row))
            assert not table_has_pricing(DETAIL_COLUMNS, (row,))


def test_new_id_does_not_join_a_following_currency_word():
    # A source column such as "CAD drawing" follows the ID in each detail row.
    # An ID ending in a digit would read as "<digit> CAD" with that cell.
    value, _ = _source_with_currency_like_digest("cad")
    row = ("Synthetic South", _row_id("import", value), "CAD drawing", "Updated")
    assert not contains_price("\t".join(row))
    assert not table_has_pricing(DETAIL_COLUMNS, (row,))


def test_amounts_in_detail_values_are_still_refused():
    value, _ = _source_with_currency_like_digest("aed")
    row = ("Synthetic South", _row_id("import", value), "Source note", "Budget 5,000 CAD")
    assert table_has_pricing(DETAIL_COLUMNS, (row,))
