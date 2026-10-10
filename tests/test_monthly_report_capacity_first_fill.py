"""Synthetic capacity first-fill must be site-scoped and preserve NR."""
from dataclasses import replace

from app import monthly_report_capacity as cap
from app.monthly_report_capacity import CapacityTable, CapacityState


def table(sites, values, *, source="a" * 64):
    return CapacityTable("synthetic-table", "Thermal requirements",
        ("Facility", "Required tons", "Available tons"),
        tuple((site, required, available) for site, (required, available) in zip(sites, values)),
        tuple(sites), source, "synthetic.csv", ".csv", 1, 0)


def test_first_fill_accepts_only_missing_sites_and_preserves_nr():
    existing = table(("north",), (("1000", "NR"),))
    state = CapacityState("Synthetic contract", 1, (existing,), "Editor", "today")
    uploaded = table(("north", "south"),
                     (("9999", "NR"), ("2400", "NR")))
    first = cap.first_fill_tables(state, (uploaded,))
    assert len(first) == 1
    assert first[0].site_keys == ("south",)
    assert first[0].rows == (("south", "2400", "NR"),)
    assert existing.rows == (("north", "1000", "NR"),)
    assert cap.first_fill_tables(None, (uploaded,)) == (uploaded,)
    assert cap.first_fill_tables(state, (existing,)) == ()


def test_unmatched_rows_do_not_enter_automatic_first_fill():
    uploaded = table(("", "south"), (("100", "NR"), ("2400", "NR")))
    result = cap.first_fill_tables(None, (uploaded,))
    assert result[0].site_keys == ("south",)
