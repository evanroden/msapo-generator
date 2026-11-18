"""A73 synthetic source-table decisions, privacy and exclusion replay."""
from dataclasses import asdict, replace
import json

from app import monthly_report_library as library
from app.monthly_report_followups import seed_followups
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ReportTable, ResolvedBlock,
    default_sections, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft


SEPTEMBER = ReportPeriod(2026, 9)
OCTOBER = ReportPeriod(2026, 10)
NOVEMBER = ReportPeriod(2026, 11)
DECEMBER = ReportPeriod(2026, 12)
COLUMNS = ("Proposal ID", "Vendor", "Scope", "Status", "Amount", "Unit Rate", "Total")
ROWS = (
    ("P-1", "Synthetic Controls", "Check actuator", "Proposed", "$12,321.98", "$40", "$12,321.98"),
    ("P-2", "Synthetic Controls", "Check actuator", "Approved", "$2,222", "$20", "$2,222"),
    ("P-3", "Synthetic Airflow", "Replace damper", "Pending", "$3,333", "$30", "$3,333"),
    ("P-4", "Synthetic Airflow", "Replace damper", "Declined", "$4,444", "$40", "$4,444"),
    ("P-5", "Synthetic Controls", "Investigate controls", "Awaiting review", "$5,555", "$50", "$5,555"),
)


def initial_draft():
    section = next(s for s in default_sections() if s.key == "proposals")
    block = ResolvedBlock("proposals", "This month",
                          extra_tables=(ReportTable(COLUMNS, ROWS, reference="synthetic:table"),))
    return ReportDraft(synthetic_profiles()[0], SEPTEMBER, "Synthetic Reviewer", (section,), (block,))


def test_explicit_decisions_duplicate_vendor_scope_and_price_canaries():
    prior = initial_draft()
    before = asdict(prior)
    carried = new_month_draft(prior, OCTOBER)
    assert [item.status for item in carried.follow_ups] == [
        "not_confirmed", "approved", "pending", "declined", "not_confirmed",
    ]
    assert len({item.key for item in carried.follow_ups}) == len(ROWS)
    assert all("Amount:" not in item.text and "Unit Rate:" not in item.text
               and "Total:" not in item.text and "$" not in item.text
               for item in carried.follow_ups)
    assert "Status: Proposed" in carried.follow_ups[0].text
    assert "Status: Awaiting review" in carried.follow_ups[-1].text
    assert asdict(prior) == before


def test_edited_and_excluded_source_row_survives_reimport_and_two_rollovers(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    prior = initial_draft()
    current = new_month_draft(prior, OCTOBER)
    changed = tuple(
        replace(item, text=item.text + "; Review note: retain bracket",
                status="on_hold", evidence_note="Operator confirmed revised status")
        if index == 2 else replace(item, included=False)
        if index == 3 else item
        for index, item in enumerate(current.follow_ups)
    )
    current = replace(current, follow_ups=changed)
    library.save_snapshot(current, expected_revision=0)
    reopened = library.load_snapshot(current.profile.contract, current.profile.key, current.period).draft
    assert reopened.follow_ups == changed
    for month in (NOVEMBER, DECEMBER):
        # A separately supplied copy of the same reviewed source table must not
        # erase the author's correction or resurrect an explicitly left-out row.
        repeated = replace(reopened, blocks=prior.blocks)
        seeded = seed_followups(repeated)
        assert len(seeded) == len(ROWS)
        assert seeded[2].status == "on_hold"
        assert seeded[2].evidence_note == "Operator confirmed revised status"
        assert seeded[3].included is False
        following = new_month_draft(repeated, month)
        assert len(following.follow_ups) == len(ROWS)
        assert [item.included for item in following.follow_ups] == [True, True, True, False, True]
        assert following.follow_ups[2].text == changed[2].text
        assert following.follow_ups[2].status == "on_hold"
        assert asdict(prior.blocks[0]) == asdict(initial_draft().blocks[0])
        library.save_snapshot(following, expected_revision=0)
        reopened = library.load_snapshot(following.profile.contract, following.profile.key, month).draft
        assert reopened.follow_ups == following.follow_ups
        assert library.draft_from_dict(json.loads(json.dumps(asdict(reopened)))) == reopened
