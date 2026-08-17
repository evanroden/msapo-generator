from app.asset_guess import guess_asset_uid


ASSETS = [
    {
        "uid": "EEA-CWP-07",
        "asset": "CWP-7",
        "equipment": "Chilled Water Pump",
        "serves": "Central Plant",
    },
    {
        "uid": "EEA-CWP-08",
        "asset": "CWP-8",
        "equipment": "Chilled Water Pump",
        "serves": "Central Plant",
    },
    {
        "uid": "EEA-CH-01",
        "asset": "CH-1",
        "equipment": "Chiller",
        "serves": "North Plant",
    },
]


def test_asset_guess_uses_quote_tag_and_returns_full_registry_uid():
    assert (
        guess_asset_uid(
            ASSETS,
            quote_text="Replace seal on chilled water pump CWP-7.",
            hint="CWP-7",
        )
        == "EEA-CWP-07"
    )


def test_asset_guess_can_use_a_normalized_unit_number_hint():
    assert (
        guess_asset_uid(
            ASSETS,
            quote_text="Work on chilled water pump number 8.",
            hint="CWP-8",
        )
        == "EEA-CWP-08"
    )


def test_asset_guess_does_not_choose_an_arbitrary_asset_on_an_equipment_only_tie():
    assert (
        guess_asset_uid(
            ASSETS,
            quote_text="Inspect one chilled water pump.",
            hint="Chilled Water Pump",
        )
        is None
    )


def test_asset_guess_never_invents_an_unconfigured_code():
    assert guess_asset_uid(ASSETS, quote_text="Repair AHU-99", hint="AHU-99") is None


def test_asset_uid_must_be_a_complete_bounded_identifier():
    assert (
        guess_asset_uid(
            ASSETS,
            quote_text="Reference XEEA-CWP-07Z in an unrelated serial number.",
        )
        is None
    )


def test_no_asset_uid_is_a_substring_of_another():
    """guess_asset_id matches UIDs with a BARE substring test and returns on the
    first hit, so this property is what keeps it correct.

    If an export ever produced a UID contained inside another one, the shorter
    would match inside the longer and win -- selecting the wrong asset with no
    error. The property holds today because every UID carries both a tag and a
    site suffix ("EEA-CH-1-CSHC" cannot sit inside "EEA-CH-1STR-CSHC").
    """
    from app.assets import ASSETS

    uids = [row["uid"].upper() for row in ASSETS]
    assert len(uids) == len(set(uids)), "duplicate UID in the registry"
    offenders = [
        (short, long)
        for short in uids
        for long in uids
        if short != long and short in long
    ]
    assert not offenders, f"UID contained inside another: {offenders[:3]}"
