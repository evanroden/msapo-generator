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
    Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock,
    profile_sections,
)
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
    return ReportProfile(
        CONTRACT, "qa-two-sites", "QA North and South - Synthetic",
        (Facility("qa-north", "Demo North", ("Demonstration North Facility",)),
         Facility("qa-south", "Demo South", ("Demonstration South Facility",))),
        "multi_site",
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
            ResolvedBlock("training_summary", "This month", text=EXPECTED["training"]),
            ResolvedBlock("equipment_issues", "This month", text="Synthetic actuator feedback follow-up."),
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
                          references=(sources.source_reference(txt.source, 1),)),
            ResolvedBlock("equipment_issues", "This month",
                          text="Open actuator issue: parts pending.",
                          references=(sources.source_reference(txt.source, 1),)),
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
        "all report section definitions present": len(draft.sections) >= 11,
    }
    return {"mode": "source replay" if replay else "known-value prefill", "checks": checks,
            "source_count": len(draft.sources),
            "section_count": len(draft.sections),
            "expected": EXPECTED}
