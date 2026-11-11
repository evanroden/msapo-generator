from app.monthly_report_recovery import load_active_draft, save_active_draft


def test_active_monthly_draft_round_trip_is_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    assert save_active_draft(
        "synthetic-browser",
        "Synthetic Contract",
        "September-2026",
        {"prepared_by": "Tester", "section": "Activity"},
    )

    assert load_active_draft(
        "synthetic-browser",
        "Synthetic Contract",
        "September-2026",
    ) == {"prepared_by": "Tester", "section": "Activity"}

    assert load_active_draft(
        "other-browser",
        "Synthetic Contract",
        "September-2026",
    ) is None
    assert load_active_draft(
        "synthetic-browser",
        "Other Contract",
        "September-2026",
    ) is None


def test_missing_identity_does_not_write_recovery(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    assert not save_active_draft("", "Synthetic Contract", "report", {"x": "y"})
    assert not (tmp_path / "epc_memory.db").exists()
