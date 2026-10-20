"""Re-saved directory workbooks must not grow history until saving fails (Refs #288).

Excel rewrites package metadata on every save, so a monthly directory workbook
gets a new hash even when no contact changed. Synthetic contacts only.
"""
from io import BytesIO
from zipfile import ZipFile

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import detail, summary, workbook


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def resaved(variant, sheets=None):
    """The same cells with different package metadata, as Excel writes on save."""
    raw = workbook(sheets or (("Active Contracts", summary()), ("Synthetic Contract Sites", detail())))
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info))
        target.writestr("docProps/app.xml", f"<Properties><Saved>{variant}</Saved></Properties>")
    return output.getvalue()


def import_and_save(raw):
    plan = batch.prepare_workbook(directory.inspect_workbook(raw))
    return plan, batch.save_workbook_plan(plan, raw, actor="Synthetic Editor", confirmed=True)


def test_metadata_only_resaves_are_unchanged_and_never_exhaust_the_record_budget():
    _, first = import_and_save(resaved(0))
    assert first.saved == ("Synthetic Contract",)
    saved = directory.load_directory("Synthetic Contract")
    for variant in range(1, 26):
        plan, result = import_and_save(resaved(variant))
        assert plan.workbook_sha256 != saved.contract_contacts[0].source.split(":", 1)[0]
        assert not plan.entries[0].changed, variant
        assert result.unchanged == ("Synthetic Contract",) and not result.failed, variant
    state = directory.load_directory("Synthetic Contract")
    assert state.revision == saved.revision
    assert state.contract_contacts == saved.contract_contacts
    assert state.sites == saved.sites


def test_a_resave_that_omits_a_saved_field_adds_nothing_and_stays_unchanged():
    import_and_save(resaved(0))
    plan, result = import_and_save(resaved(1, (("Active Contracts", summary(B10="")),
                                               ("Synthetic Contract Sites", detail(B11="")))))
    assert not plan.entries[0].conflicts and not plan.entries[0].changed
    assert result.unchanged == ("Synthetic Contract",)
    contact = directory.load_directory("Synthetic Contract").contract_contacts[0]
    assert contact.phone == "202-555-0100"


def test_a_real_fill_in_still_saves_and_records_its_workbook():
    first, _ = import_and_save(resaved(0, (("Active Contracts", summary(B11="")),
                                           ("Synthetic Contract Sites", detail()))))
    plan, result = import_and_save(resaved(1))
    assert plan.entries[0].changed and result.saved == ("Synthetic Contract",)
    contact = directory.load_directory("Synthetic Contract").contract_contacts[0]
    assert contact.email == "executive@example.invalid"
    assert contact.source.split(";")[0].startswith(first.workbook_sha256)
    assert contact.source.split(";")[-1].startswith(plan.workbook_sha256)


def test_provenance_keeps_first_and_newest_references_within_its_bound():
    references = [f"{index:064x}:Synthetic Sheet!B{index},C{index},D{index}" for index in range(40)]
    joined = batch._source_union(*references)
    assert len(joined) <= batch._MAX_SOURCE_TEXT
    kept = joined.split(";")
    assert kept[0] == references[0] and kept[-1] == references[-1]
    assert kept[1:] == references[-(len(kept) - 1):]
    assert batch._source_union(references[0], references[0]) == references[0]
