from dataclasses import replace

import pytest

from app import monthly_report_directory as directory
from app.monthly_report_model import ReportDraft, ReportPeriod, ReportTable, ResolvedBlock, default_sections, synthetic_profiles


@pytest.fixture
def draft(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    site = directory.DirectorySite("directory-north", "Directory North", aliases=(profile.facilities[0].title,),
        contacts=(directory.DirectoryContact("Site Lead", "Synthetic North Lead"),))
    directory.save_directory(profile.contract, (site,), expected_revision=0,
        actor="Synthetic Editor", confirmed=True,
        contract_contacts=(directory.DirectoryContact("Contract Lead", "Synthetic Contract Lead"),))
    return ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", default_sections(), ())


def test_first_report_reuses_contract_and_exact_site_contacts(draft):
    updated = directory.apply_defaults(draft)
    block = next(b for b in updated.blocks if b.key == "contact_matrix")
    assert len(block.rows) == 2
    assert block.rows[1][2] == "Synthetic North Lead"
    assert "directory-site:north:directory-north" in block.references
    assert directory.apply_defaults(updated) == updated
    assert directory.load_directory(draft.profile.contract).revision == 1


def test_existing_contacts_and_unnamed_visitors_are_not_changed(draft):
    existing = replace(draft, blocks=(ResolvedBlock("contact_matrix", "This month", text="Synthetic manual contacts"),))
    assert directory.apply_defaults(existing) == existing
    unnamed = replace(draft, prepared_by="")
    assert directory.apply_defaults(unnamed) == unnamed


def test_another_site_receives_only_contract_wide_contacts(draft):
    other = replace(draft, profile=replace(draft.profile, facilities=(synthetic_profiles()[1].facilities[1],)))
    block = directory.apply_defaults(other).blocks[0]
    assert len(block.rows) == 1 and block.rows[0][2] == "Synthetic Contract Lead"
    assert not any(r.startswith("directory-site:") for r in block.references)


def test_reused_empty_table_headings_do_not_prevent_saved_contacts(draft):
    empty = replace(draft, blocks=(ResolvedBlock("contact_matrix", "This month",
        extra_tables=(ReportTable(("Name", "Role"), ()),)),))
    assert len(directory.apply_defaults(empty).blocks[0].rows) == 2
