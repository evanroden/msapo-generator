"""Exact October 9 owner Activity TXT: keep safe facts despite a pricing-reference line.

The source intentionally uses the original unclarified training/vendor labels.
This test does not reclassify staff or certify the optional live AI reader.
"""
from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_structured_uploads import native_update
from app.monthly_report_content_policy import contains_price

ACTIVITY_TXT = "TEST ONLY - INVENTED DATA - Not an operational record\nContract label: Rochester Regional Health (RRH)\nSite: RRH Tester – UX Review 2026-10-09\nAuthor label: RRH Tester\nReporting period: September 1-30, 2026\nAll people, work, dates, measurements and records below are invented for QA.\n2026-09-03 | WO-TEST-1001 | PUMP-TEST-02 | In-house preventive maintenance\nCompleted strainer cleaning and leak inspection. Result: no leakage found.\n2026-09-12 | TRAIN-TEST-01 | Training Summary\nCompleted a 45-minute lockout/tagout refresher for 4 fictional technicians.\n2026-09-16 | WT-TEST-0916 | LOOP-TEST-01 | Water Treatment Reports\nSynthetic water check recorded pH 8.2. This value is test data, not clinical data.\n2026-09-20 | WO-TEST-1002 | AHU-TEST-07 | Sub-Contractor Status\nExample Mechanical QA Services replaced two filter-bank inserts and retensioned\nthe drive belt. Differential pressure: 1.20 before, 0.45 in. w.c. after.\nNo recurring belt vibration during a 30-minute observation. Service complete.\nProgress illustration: progress.png, explicitly labeled TEST ONLY.\n2026-09-24 | WO-TEST-1003 | VAV-TEST-03 | Equipment Performance Issues\nInvestigate intermittent actuator feedback. Open at month-end. Parts pending.\n2026-09-25 | RFI-TEST-004 | RFI Matrix\nQuestion: confirm the invented test plant shutdown window. Status: awaiting\nclient response. Needed by 2026-10-07. No communication has actually been sent.\n2026-09-30 | Monthly Scorecards\nThree September work orders: two completed, one open; closure rate 66.7%.\nMBCx finding MBCX-TEST-01: verify AHU-TEST-07 start/stop schedule in October.\nPending proposal Q-TEST-731 is a proposed drive replacement, not completed work.\nDistinctive quote prices are only in vendor.pdf page 2 and quote.pdf."


def test_exact_audit_activity_txt_safe_native_draft_and_provenance(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "activity.txt", ACTIVITY_TXT.encode("utf-8"))
    assert content.source.page_texts == (ACTIVITY_TXT,)
    # The reference-only sentence makes the whole page's conservative
    # pricing detector fire; safe operational sentences must still survive.
    assert contains_price(ACTIVITY_TXT)
    block = native_update((content,), "activity_summary")
    assert "Completed strainer cleaning and leak inspection." in block.text
    assert "Example Mechanical QA Services replaced two filter-bank inserts" in block.text
    assert "No recurring belt vibration during a 30-minute observation." in block.text
    assert "not completed work." in block.text
    assert "vendor.pdf page 2" not in block.text
    assert block.references and all(r.startswith(content.source.id + ":1:") for r in block.references)
    repeated = native_update((content,), "activity_summary", block)
    assert repeated.text == block.text and repeated.references == block.references


def test_mixed_actual_price_line_never_enters_native_activity_draft(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    text = ("Completed synthetic pump inspection.\n"
            "Invoice amount $12,345.67 for pump labor.\n"
            "The pump remains under observation until October.\n"
            "Price-free controls check completed.")
    content, _ = sources.ingest(profile, "inspection.txt", text.encode())
    result = native_update((content,), "activity_summary")
    assert "Completed synthetic pump inspection." in result.text
    assert "pump labor" not in result.text
    assert "$12,345.67" not in result.text
    assert "Price-free controls check completed." in result.text
