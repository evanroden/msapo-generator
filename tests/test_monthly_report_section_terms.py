"""Plain-language section guidance is available without opening onboarding."""
from app.monthly_report_section_help import SECTION_HELP, section_help


def test_mbcx_and_enfra_connect_defined_where_section_is_edited():
    guidance = section_help("mbcx").guidance
    assert "MBCx means monitoring-based commissioning" in guidance
    assert "ENFRA Connect" in guidance
    assert "platform" in guidance
    assert "verified" in guidance
    assert "without inventing" in guidance


def test_rfi_acronym_expanded_with_clear_workflow():
    guidance = section_help("rfi").guidance
    assert "RFI means Request for Information" in guidance
    assert "site and status" in guidance
    assert "only when confirmed" in guidance


def test_training_excludes_enfra_staff_without_mislabeling_external_events():
    guidance = section_help("training").guidance
    assert "hospital or client staff" in guidance
    assert "not ENFRA" in guidance
    assert "hours only when known" in guidance


def test_plain_help_is_defined_for_all_standard_report_sections():
    expected = {
        "cover", "organization", "activity", "scorecards", "mbcx",
        "maintenance", "subcontractors", "water", "issues", "capital",
        "proposals", "training", "rfi",
    }
    assert expected <= set(SECTION_HELP)
    assert all(section_help(key).guidance.strip() for key in expected)
