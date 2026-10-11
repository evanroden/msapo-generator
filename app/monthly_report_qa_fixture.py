"""Deterministic, invented QA fixtures for the real report pipeline.

Known-value prefill does not read a source file. Original-source replay runs
normal ingestion and extractive routing. Neither touches any live client data.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from app import monthly_report_library as library
from app import monthly_report_directory as directory
from app import monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, Facility, OrgChartNode, ReportDraft, ReportPeriod,
    ReportProfile, ReportTable, ResolvedBlock, profile_sections,
)
from app.monthly_report_training import MATRIX_REF, EVENT_REF
from app.monthly_report_work_order_csv import work_order_evidence
from app.monthly_report_testing import scope


CONTRACT = "QA Demonstration - Synthetic Only"
PERIOD = ReportPeriod(2026, 9)
ACTOR = "Synthetic QA Operator"
WO_CSV = (b"Work Order,Date,Status,Facility,Asset\n"
          b"WO-TEST-1001,2026-09-03,Completed,Demo North,PUMP-TEST-02\n"
          b"WO-TEST-1002,2026-09-20,Completed,Demo North,AHU-TEST-07\n"
          b"WO-TEST-1003,2026-09-24,Open,Demo North,VAV-TEST-03\n")
ACTIVITY_TXT = (b"TEST ONLY - ALL RECORDS INVENTED\n"
                b"2026-09-03 | WO-TEST-1001 | PUMP-TEST-02 | In-house maintenance\n"
                b"Completed strainer cleaning and inspection; no leakage found.\n"
                b"2026-09-20 | WO-TEST-1002 | AHU-TEST-07 | Sub-Contractor Status\n"
                b"Synthetic Mechanical Vendor replaced filter-bank inserts and retensioned belt.\n"
                b"2026-09-24 | WO-TEST-1003 | VAV-TEST-03 | Equipment Performance Issues\n"
                b"Open actuator issue: parts pending.\n"
                b"2026-09-25 | TRAIN-TEST-01 | Training Summary\n"
                b"Hospital staff completed a synthetic lockout refresher.\n")

EXPECTED = {
    "total": 3, "completed": 2, "open": 1, "closure": "66.7%",
    "prefill_activity": "Three September work orders: 3 total, 2 completed, 1 open (66.7%).",
    "replay_activity": "Completed strainer cleaning and inspection",
    "training": "Hospital staff completed a synthetic training exercise.",
    "intentionally_empty": ("water_reports", "utility_analysis", "mbcx_report"),
}


def profile() -> ReportProfile:
    # A six-column selected design exercises Project Number, Status and
    # engineering values without reproducing private company artwork.
    proposals = BlockSpec("proposals", "table", columns=tuple(
        ColumnSpec("qa-" + str(i), heading) for i, heading in enumerate((
            "Project Number", "Facility", "Vendor", "Work Description",
            "Status", "Technical Notes"))))
    return ReportProfile(
        CONTRACT, "qa-two-sites", "QA North and South - Synthetic",
        (Facility("qa-north", "Demo North", ("Demonstration North Facility",)),
         Facility("qa-south", "Demo South", ("Demonstration South Facility",))),
        "multi_site", block_overrides=(proposals,),
    )


def _training_tables():
    return (
        ReportTable(("Team member", "Site", "Lockout safety"), (
            ("Synthetic Person North", "Demo North", "Pending"),
            ("Synthetic Person South", "Demo South", "Not recorded"),
        ), MATRIX_REF),
        ReportTable(("Training", "Date", "Format", "Participants", "Hours"), (
            ("Synthetic safety refresher", "2026-09-25", "In person", "4", "0.75"),
        ), EVENT_REF),
    )


def _standing_blocks(chosen):
    selected = directory.load_directory(CONTRACT)
    contacts, missing = directory.contact_block(selected, chosen.facilities)
    if missing or contacts is None:
        raise ValueError("Synthetic QA contact fixture did not resolve its exact sites.")
    return (
        ResolvedBlock("org_chart", "This month", org_nodes=(
            OrgChartNode("qa-lead", "Synthetic Site Lead", "Site Lead", team="Demo North"),
            OrgChartNode("qa-operator", "Synthetic Technician", "Technician",
                         reports_to="qa-lead", team="Demo South"),
        )),
        contacts,
        ResolvedBlock("work_orders", "This month", extra_tables=(
            ReportTable(("Work order", "Date", "Status"), (
                ("WO-TEST-1001", "2026-09-03", "Completed"),
                ("WO-TEST-1002", "2026-09-20", "Completed"),
                ("WO-TEST-1003", "2026-09-24", "Open"),
            ), "synthetic:workorders"),)),
        ResolvedBlock("thermal_capacity", "This month", extra_tables=(
            ReportTable(("Facility", "Service", "Required", "Available", "Units"), (
                ("Demo North", "Chilled water", "NR", "200", "tons"),
                ("Demo South", "Steam", "150", "NR", "klb/h"),
            ), "synthetic:thermal"),)),
        ResolvedBlock("service_calls", "This month", extra_tables=(
            ReportTable(("WO #", "Date", "Area", "Task", "Asset"), (
                ("WO-TEST-1005", "2026-09-18", "Demo South",
                 "Synthetic ENFRA onsite inspection", "AHU-TEST-04"),
            ), "synthetic:onsite"),)),
        ResolvedBlock("subcontractor_matrix", "This month", extra_tables=(
            ReportTable(("Facility", "Discipline", "Vendor", "Contact", "Phone", "MSA"), (
                ("Demo North", "Mechanical", "Synthetic Mechanical Vendor",
                 "Invented Vendor Contact", "555-0300", "Pending"),
            ), "synthetic:subcontractors"),)),
        ResolvedBlock("capital_renewal", "This month",
                      rows=(("Demo South", "2", "Review synthetic aging pump"),)),
        ResolvedBlock("proposals", "This month", rows=(
            ("Q-TEST-731", "Demo North", "Synthetic Mechanical Vendor",
             "Inspect supply valve", "Pending", "45 gpm"),
        )),
        ResolvedBlock("footer_text", "This month", text="SYNTHETIC QA ONLY"),
    )


def manifest() -> dict:
    return {
        "contract": CONTRACT,
        "profile_key": profile().key,
        "sites": [s.key for s in profile().facilities],
        "period": PERIOD.key,
        "design_pin": profile().template,
        "sources": [
            {"name": name, "sha256": sha256(raw).hexdigest()}
            for name, raw in (("synthetic-workorders.csv", WO_CSV),
                              ("synthetic-activity.txt", ACTIVITY_TXT))
        ],
        "expected": EXPECTED,
        "exceptions": ["All names, numbers, sites and events are synthetic.",
                       "No authentic Word design reference is present in this fixture."],
    }


def _assert_isolated() -> None:
    if scope() is None:
        raise ValueError("QA fixture installation is blocked outside isolated testing.")


def _seed_profile():
    _assert_isolated()
    chosen = profile()
    existing = library.list_profiles(chosen.contract)
    if not any(record.key == chosen.key for record in existing):
        library.save_profile(chosen, expected_revision=0, actor=ACTOR, confirmed=True)
    if directory.load_directory(CONTRACT) is None:
        sites = (
            directory.DirectorySite("qa-north", "Demo North", contacts=(
                directory.DirectoryContact("Engineer", "Synthetic Person North", "555-0100"),)),
            directory.DirectorySite("qa-south", "Demo South", contacts=(
                directory.DirectoryContact("Technician", "Synthetic Person South", "555-0200"),)),
        )
        directory.save_directory(CONTRACT, sites, expected_revision=0, actor=ACTOR, confirmed=True)
    return chosen


def prepare(mode: str) -> ReportDraft:
    """Install a real immutable snapshot in this isolated namespace only."""
    if mode not in ("prefill", "replay"):
        raise ValueError("Choose known-value prefill or original-source replay.")
    chosen = _seed_profile()
    if mode == "prefill":
        blocks = (
            ResolvedBlock("activity_summary", "This month", text=EXPECTED["prefill_activity"]),
            ResolvedBlock("training_summary", "This month", text=EXPECTED["training"],
                          extra_tables=_training_tables()),
            ResolvedBlock("equipment_issues", "This month", text="Synthetic actuator feedback follow-up."),
            *_standing_blocks(chosen),
        )
        evidence = ()
    else:
        csv, _ = sources.ingest(chosen, "synthetic-workorders.csv", WO_CSV)
        txt, _ = sources.ingest(chosen, "synthetic-activity.txt", ACTIVITY_TXT)
        finding, = work_order_evidence(csv, PERIOD, chosen)
        if (finding.total, finding.completed, finding.open) != (3, 2, 1):
            raise ValueError("Synthetic source totals do not match independent expected values.")
        # The TXT extraction is separately tested; the CSV does not secretly
        # supply the activity prose or get counted twice.
        activity = structured.native_update((txt,), "activity_summary")
        blocks = (
            ResolvedBlock("activity_summary", "This month",
                          text=finding.text + "\n\n" + activity.text,
                          references=(finding.reference, *activity.references)),
            ResolvedBlock("training_summary", "This month",
                          text="Hospital staff completed a synthetic lockout refresher.",
                          references=(sources.source_reference(txt.source, 1),),
                          extra_tables=_training_tables()),
            ResolvedBlock("equipment_issues", "This month",
                          text="Open actuator issue: parts pending.",
                          references=(sources.source_reference(txt.source, 1),)),
            *_standing_blocks(chosen),
        )
        evidence = (csv.source, txt.source)
    draft = ReportDraft(chosen, PERIOD, ACTOR, profile_sections(chosen), blocks,
                        synthetic=True, sources=evidence)
    saved = library.load_snapshot(CONTRACT, chosen.key, PERIOD)
    library.save_snapshot(draft, expected_revision=saved.revision if saved else 0,
                          entered_editor=ACTOR)
    return draft


def compare(draft: ReportDraft) -> dict:
    _assert_isolated()
    actual = {block.key: block for block in draft.blocks}
    activity = actual.get("activity_summary", ResolvedBlock("activity_summary", "This month")).text
    replay = bool(draft.sources)
    training = actual.get("training_summary", ResolvedBlock("training_summary", "This month"))
    issues = actual.get("equipment_issues", ResolvedBlock("equipment_issues", "This month"))
    expected_sources = {item["name"]: item["sha256"] for item in manifest()["sources"]}
    observed_sources = {source.filename: source.sha256 for source in draft.sources}
    checks = {
        "synthetic identity": draft.profile.contract == CONTRACT and draft.synthetic,
        "correct period": draft.period == PERIOD,
        "correct selected site identities": tuple(f.key for f in draft.profile.facilities)
                                              == ("qa-north", "qa-south"),
        "work-order totals": "3 total, 2 completed, 1 open" in activity,
        "work-order closure rate": "66.7%" in activity,
        "prefill/replay differ in Activity": (EXPECTED["replay_activity"] in activity) if replay
                                           else EXPECTED["prefill_activity"] in activity,
        "source manifests exact": observed_sources == expected_sources if replay
                                  else not observed_sources,
        "CSV provenance linked in Activity": (
            any(source.sha256 in ref for source in draft.sources
                if source.filename.endswith(".csv") for ref in
                actual["activity_summary"].references)
        ) if replay else not actual["activity_summary"].references,
        "Training routed outside Activity": (
            "synthetic lockout refresher" in training.text and
            "synthetic lockout refresher" not in activity and bool(training.references)
        ) if replay else EXPECTED["training"] == training.text,
        "open equipment issue routed outside Activity": (
            "Open actuator issue: parts pending." in issues.text and
            "Open actuator issue: parts pending." not in activity
        ) if replay else "Synthetic actuator feedback" in issues.text,
        "intentionally empty design slots": not any(
            key in actual for key in EXPECTED["intentionally_empty"]
        ),
        "verified two-position organization chart": len(
            actual["org_chart"].org_nodes) == 2,
        "site-mapped standing contacts": (
            len(actual["contact_matrix"].rows) == 2 and
            {r[0] for r in actual["contact_matrix"].rows} ==
            {"Demo North", "Demo South"}),
        "thermal NR stays literal": (
            len(actual["thermal_capacity"].extra_tables) == 1 and
            sum(cell == "NR" for row in actual["thermal_capacity"].extra_tables[0].rows
                for cell in row) == 2),
        "proposal identifier and Status retained without prices": (
            any(row[0] == "Q-TEST-731" and row[4] == "Pending"
                for row in actual["proposals"].rows) and
            not any("$" in cell for row in actual["proposals"].rows for cell in row)),
        "vendor and onsite calls use different blocks": (
            "Synthetic Mechanical Vendor" in activity if replay else True) and
            any("ENFRA onsite inspection" in cell for table in
                actual["service_calls"].extra_tables for row in table.rows for cell in row),
        "monthly training events are explicit": (
            len(training.extra_tables) == 2 and
            training.extra_tables[1].rows[0][1] == "2026-09-25" and
            training.extra_tables[0].rows[0][2] == "Pending"),
        "all report section definitions present": len(draft.sections) >= 11,
    }
    return {"mode": "source replay" if replay else "known-value prefill", "checks": checks,
            "source_count": len(draft.sources),
            "section_count": len(draft.sections),
            "expected": EXPECTED}
