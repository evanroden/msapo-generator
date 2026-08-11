from app.job_numbers import (
    ARKANSAS_UNITY_JOB_NUMBERS,
    JOB_NUMBER_OPTIONS,
    RRH_JOB_NUMBERS,
    UNITY_DISAMBIGUATION_GUIDANCE,
    job_numbers_for_contract,
    suggest_job_number,
)
from app.quote_analyzer import SYSTEM_PROMPT
from app.smartsheet import validate_submission_fields


def test_complete_catalog_is_unique_and_preserves_verified_groups():
    assert len(JOB_NUMBER_OPTIONS) == 87
    assert len(set(JOB_NUMBER_OPTIONS)) == 87
    assert RRH_JOB_NUMBERS == (
        "RRH-695400022-O&M",
        "RRH-695400023-START UP",
        "RRH-695400030-ISDC",
        "RRH-695400034-ES JOB CCJ",
    )
    assert ARKANSAS_UNITY_JOB_NUMBERS == (
        "Unity 695000029 - CCJ",
        "Unity VI100036 - O&M",
        "Unity VI100056 - ISDC",
    )


def test_rrh_unity_and_arkansas_unity_never_share_job_options():
    rrh = job_numbers_for_contract("Rochester Regional Health")
    arkansas = job_numbers_for_contract("Unity Health System")

    assert rrh == RRH_JOB_NUMBERS
    assert arkansas == ARKANSAS_UNITY_JOB_NUMBERS
    assert set(rrh).isdisjoint(arkansas)


def test_contract_filtering_and_exact_quote_identifier_suggestion():
    tulane = job_numbers_for_contract("Tulane")

    assert len(tulane) == 4
    assert all(value.startswith("TULANE") for value in tulane)
    assert suggest_job_number(
        tulane, "Please charge this work to VI100018."
    ) == "TULANE EA- VI100018-O&M"
    assert suggest_job_number(tulane, "No job identifier is stated.") is None


def test_smartsheet_validation_rejects_free_text_job_numbers():
    assert not validate_submission_fields(
        {"job_number": "RRH-695400022-O&M"}
    )
    problems = validate_submission_fields({"job_number": "TUL-100"})

    assert len(problems) == 1
    assert problems[0].startswith("JOB NUMBER must exactly match one of:")


def test_analyzer_prompt_contains_the_unity_disambiguation_policy():
    assert UNITY_DISAMBIGUATION_GUIDANCE.strip() in SYSTEM_PROMPT
    compact_prompt = " ".join(SYSTEM_PROMPT.split())
    assert "Unity Health System in Arkansas" in compact_prompt
    assert "Rochester Regional Health (RRH)" in compact_prompt
    assert "Never" in compact_prompt
