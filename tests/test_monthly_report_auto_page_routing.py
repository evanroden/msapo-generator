"""A14: deterministic per-page placement; originals and manual decisions prevail."""
from dataclasses import replace
from hashlib import sha256

import pymupdf
import pytest

from app.monthly_report_auto_page_routing import route_pages
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_model import ReportSource, synthetic_profiles
from app.monthly_report_sources import SourceContent, prepare_pages, source_reference


def content(*texts, classification="Reference only", facility=None, selected=None, reviewed=True):
    profile = synthetic_profiles()[0]
    site = profile.facilities[0].title if facility is None else facility
    digest = sha256("\n".join(texts).encode()).hexdigest()
    source = ReportSource(digest, "synthetic-mixed.pdf", digest, ".pdf",
        classification=classification, facility=site, page_texts=tuple(texts),
        selected_pages=tuple(range(1, len(texts) + 1)) if selected is None else tuple(selected))
    if reviewed:
        source = replace(source, client_page_reviews=tuple(
            (n, page_fingerprint(source, n)) for n in range(1, len(texts) + 1)))
    return SourceContent(source)


@pytest.mark.parametrize("heading,section,destination", [
    ("SERVICE REPORT\nPump inspected.", "activity", "improvements"),
    ("WATER TREATMENT REPORT\nConductivity 250 uS/cm.", "water", "water_reports"),
    ("MBCx REPORT\nAHU performance verified.", "mbcx", "mbcx_report"),
    ("UTILITY ANALYSIS\nEnergy use 120 kWh.", "utility", "utility_analysis"),
    ("PROPOSAL\nReplacement pending review.", "proposals", None),
    ("CAPITAL RENEWAL\nEquipment condition documented.", "capital", None),
    ("TRAINING RECORD\nSession completed.", "training", None),
    ("WORK ORDER SUMMARY\nPM closed.", "work_orders", None),
    ("PROGRESS PHOTO\nReplacement documented.", "photos", "improvements"),
    ("ORGANIZATIONAL CHART\nReporting lines.", "standing", None),
])
def test_ten_section_matrix(heading, section, destination):
    decision, = route_pages((content(heading),), synthetic_profiles()[0])
    assert decision.section == section
    assert decision.destination == destination
    assert decision.action == ("ready" if destination else "reference")


def test_priced_adjacent_page_and_review_or_scope_fail_closed():
    profile = synthetic_profiles()[0]
    src = content("QUOTE TOTAL: $7,500", "SERVICE REPORT\nVerified chiller test.")
    first, second = route_pages((src,), profile)
    assert (first.page, first.action, first.destination) == (1, "blocked", None)
    assert (second.page, second.action, second.destination) == (2, "ready", "improvements")
    unreviewed = replace(src, source=replace(src.source, client_page_reviews=()))
    assert route_pages((unreviewed,), profile)[1].action == "review"
    foreign = replace(src, source=replace(src.source, facility="Unrelated facility"))
    assert all(choice.action == "blocked" for choice in route_pages((foreign,), profile))
    unknown = replace(src, source=replace(src.source, facility=""))
    assert [choice.action for choice in route_pages((unknown,), profile)] == ["blocked", "ready"]
    assert route_pages((replace(unknown, source=replace(unknown.source, client_page_reviews=())),), profile)[1].action == "review"


def test_duplicate_import_existing_owner_manual_omission_and_override():
    profile = synthetic_profiles()[0]
    src = content("SERVICE REPORT\nVisited.", "WATER TREATMENT REPORT\nReadings.")
    duplicate = route_pages((src, src), profile)
    assert len(duplicate) == 2
    owned = {(src.source.id, 1): {"improvements"}}
    prior = route_pages((src,), profile, owned=owned)
    assert prior[0].action == "retained" and prior[1].destination == "water_reports"
    omitted = replace(src.source, selected_pages=(2,),
        client_page_exclusions=((1, page_fingerprint(src.source, 1)),))
    decisions = route_pages((replace(src, source=omitted),), profile)
    assert decisions[0].action == "excluded"
    assert decisions[1].action == "ready"
    override = route_pages((src,), profile, overrides={src.source.id: "utility_analysis"})
    assert [d.destination for d in override] == ["utility_analysis", "utility_analysis"]
    assert route_pages((src,), profile, owned={(src.source.id, 1): {"improvements", "water_reports"}})[0].action == "blocked"


def test_same_source_page_can_be_prepared_once_from_mixed_routes(monkeypatch, tmp_path):
    from app import monthly_report_sources as sources
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "QUOTE TOTAL: $7,500")
        page = pdf.new_page()
        page.insert_text((50, 50), "SERVICE REPORT: Chiller pressure checked.")
        raw = pdf.tobytes()
    original, _ = sources.ingest(profile, "mixed.pdf", raw)
    source = replace(original.source, facility=profile.facilities[0].title,
        selected_pages=(1, 2))
    source = replace(source, client_page_reviews=tuple(
        (n, page_fingerprint(source, n)) for n in (1, 2)))
    reviewed = replace(original, source=source)
    planned = route_pages((reviewed,), profile)
    assert [d.action for d in planned] == ["blocked", "ready"]
    route = (source.id, planned[1].destination, 2)
    before = sources.source_bytes(profile, source)
    result = prepare_pages(profile, (reviewed,), (route,))
    assert len(result) == 1 and len(result[0].asset_hashes) == 1
    assert result[0].references == (source_reference(source, 2),)
    assert sources.source_bytes(profile, source) == before == raw
    with pytest.raises(ValueError, match="once|duplicate"):
        prepare_pages(profile, (reviewed,), (route, route))
    with pytest.raises(ValueError, match="Check page 1"):
        prepare_pages(profile, (reviewed,), ((source.id, "improvements", 1),))



def test_mixed_source_foreign_page_identity_cannot_ride_same_site_metadata():
    profile = synthetic_profiles()[0]
    site = profile.facilities[0].title
    src = content("SERVICE REPORT\nSite: " + site + "\nPump inspected.",
                  "SERVICE REPORT\nSite: Different Hospital\nMotor replaced.")
    first, second = route_pages((src,), profile)
    assert first.action == "ready" and first.destination == "improvements"
    assert second.action == "blocked" and second.destination is None
    assert second.page == 2 and "site" in second.reason


def test_report_period_warning_does_not_reclassify_previous_month_activity():
    from app.monthly_report_model import ReportPeriod
    src = content("SERVICE REPORT\nRoutine inspection performed.")
    dated = replace(src, source=replace(src.source, service_date="2026-08-12"))
    decision, = route_pages((dated,), synthetic_profiles()[0], period=ReportPeriod(2026, 9))
    assert decision.action == "blocked" and "month" in decision.reason
    assert decision.page == 1
    assert route_pages((dated,), synthetic_profiles()[0], period=ReportPeriod(2026, 8))[0].action == "ready"


def test_no_empty_mbcx_or_narrative_cross_section_duplicate():
    src = content("SERVICE REPORT\nInspection reviewed the water treatment team's notes.",
                  "UTILITY ANALYSIS\nMonthly meter consumption data.")
    result = route_pages((src,), synthetic_profiles()[0])
    assert [(item.page, item.destination, item.action) for item in result] == [
        (1, "improvements", "ready"), (2, "utility_analysis", "ready")]
    assert all(item.destination != "mbcx_report" for item in result)


def test_duplicate_source_with_conflicting_human_edits_fails_closed():
    src = content("SERVICE REPORT\nFilter replaced.")
    changed = replace(src, source=replace(src.source, classification="MBCx"))
    with pytest.raises(ValueError, match="Conflicting revisions"):
        route_pages((src, changed), synthetic_profiles()[0])


def test_missing_and_malformed_inputs_do_not_invent_routes():
    profile = synthetic_profiles()[0]
    assert route_pages((), profile) == ()
    assert route_pages((content(),), profile) == ()
    src = content("SERVICE REPORT\nInspected.", selected=(2,))
    with pytest.raises(ValueError, match="Selected source page"):
        route_pages((src,), profile)


def test_reviewed_mbcx_financial_page_routes_only_to_mbcx(monkeypatch, tmp_path):
    """Codex review on #959: a priced ENFRA MBCx page with a valid financial-page
    review stays admissible for the MBCx section and nowhere else."""
    from tests.test_monthly_report_mbcx_financial_pages import reviewed, setup
    from app.monthly_report_auto_page_routing import route_pages
    from app.monthly_report_model import ReportPeriod

    profile, content, _ = setup(monkeypatch, tmp_path)
    period = ReportPeriod(2026, 9)
    unreviewed, = route_pages((content,), profile, period=period)
    assert unreviewed.action == "blocked"
    approved = reviewed(profile, content)
    route, = route_pages((approved,), profile, period=period)
    assert (route.destination, route.action) == ("mbcx_report", "ready")
    moved, = route_pages((approved,), profile, period=period,
                         overrides={approved.source.id: "water_reports"})
    assert (moved.destination, moved.action) == (None, "blocked")
