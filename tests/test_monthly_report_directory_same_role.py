"""People who share a role are kept exactly once across imports (Refs #288).

G2-directory-6: a batch import could not save two people with the same role.
G2-directory-7: each single-sheet re-import duplicated same-role contacts.
Synthetic contacts only.
"""
import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import detail, summary
from test_monthly_report_directory_reimport_growth import import_and_save, resaved

Contact = directory.DirectoryContact
SECOND = {"A13": "Executive Director", "B13": "Synthetic Second Executive", "A14": "Phone",
          "B14": "202-555-0102", "A15": "Email", "B15": "second@example.invalid"}
THIRD = {"A17": "Executive Director", "B17": "Synthetic Third Executive", "A18": "Phone",
         "B18": "202-555-0103", "A19": "Email", "B19": "third@example.invalid"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def _sheets(**contract_cells):
    return (("Active Contracts", summary(**contract_cells)), ("Synthetic Contract Sites", detail()))


def _names():
    return [c.name for c in directory.load_directory("Synthetic Contract").contract_contacts]


def test_batch_saves_two_people_with_one_role_once_and_reimport_is_unchanged():
    plan, result = import_and_save(resaved(0, _sheets(**SECOND)))
    assert plan.entries[0].conflicts == () and result.saved == ("Synthetic Contract",)
    assert _names() == ["Synthetic Executive", "Synthetic Second Executive"]
    for variant in range(1, 4):
        plan, result = import_and_save(resaved(variant, _sheets(**SECOND)))
        assert not plan.entries[0].changed and result.unchanged == ("Synthetic Contract",)
    assert _names() == ["Synthetic Executive", "Synthetic Second Executive"]


def test_batch_adds_a_new_same_role_person_while_everyone_saved_is_still_listed():
    import_and_save(resaved(0, _sheets(**SECOND)))
    plan, result = import_and_save(resaved(1, _sheets(**SECOND, **THIRD)))
    assert plan.entries[0].conflicts == () and result.saved == ("Synthetic Contract",)
    assert _names() == ["Synthetic Executive", "Synthetic Second Executive", "Synthetic Third Executive"]


def test_batch_asks_for_review_when_a_saved_same_role_person_may_have_been_replaced():
    import_and_save(resaved(0, _sheets(**SECOND)))
    replaced = {**SECOND, "B13": "Synthetic Replacement", "B14": "202-555-0104", "B15": "new@example.invalid"}
    plan, result = import_and_save(resaved(1, _sheets(**replaced)))
    assert any("more than one saved contact has role Executive Director" in c for c in plan.entries[0].conflicts)
    assert result.blocked and not result.saved
    assert _names() == ["Synthetic Executive", "Synthetic Second Executive"]


def _supervisors(source):
    return (Contact("Maintenance Supervisor", "Synthetic Day Lead", "202-555-0110", "", source + "!B9"),
            Contact("Maintenance Supervisor", "Synthetic Night Lead", "202-555-0111", "", source + "!C9"))


def test_single_sheet_reimport_never_duplicates_people_who_share_a_role():
    saved = _supervisors("wb1:Sheet")
    once = directory.proposed_contacts(saved, _supervisors("wb2:Sheet"))
    twice = directory.proposed_contacts(once, _supervisors("wb3:Sheet"))
    assert once == saved and twice == saved


def test_single_sheet_fills_the_matching_person_and_adds_a_new_one_once():
    saved = _supervisors("wb1:Sheet")
    day, night = _supervisors("wb2:Sheet")
    incoming = (day, Contact(night.role, night.name, night.phone, "night@example.invalid", night.source),
                Contact("Maintenance Supervisor", "Synthetic Weekend Lead", "202-555-0112", "", "wb2:Sheet!D9"))
    proposed = directory.proposed_contacts(saved, incoming)
    assert [(c.name, c.email) for c in proposed] == [
        ("Synthetic Day Lead", ""), ("Synthetic Night Lead", "night@example.invalid"),
        ("Synthetic Weekend Lead", "")]
    assert proposed[0] == saved[0]
    assert directory.proposed_contacts(proposed, incoming) == proposed


def test_single_sheet_identical_single_role_reimport_keeps_the_saved_record():
    saved = (Contact("Facility Director", "Synthetic Site Lead", "202-555-0101", "site@example.invalid", "wb1:S!B9"),)
    again = (Contact("Facility Director", "Synthetic Site Lead", "202-555-0101", "site@example.invalid", "wb2:S!B9"),)
    assert directory.proposed_contacts(saved, again) == saved
    replaced = (Contact("Facility Director", "Synthetic New Lead", "202-555-0105", "", "wb2:S!B9"),)
    assert directory.proposed_contacts(saved, replaced) == replaced  # reviewed replacement unchanged


def _repeated_person_sheets(scope, *, conflicting_field=None):
    role, name = (("Executive Director", "Synthetic Executive") if scope == "contract"
                  else ("Facility Director", "Synthetic Site Lead"))
    repeated = {"A13": role.lower(), "B13": "  ".join(name.upper().split()),
                "A14": "Phone", "B14": "", "A15": "Email", "B15": ""}
    if conflicting_field:
        repeated["B14" if conflicting_field == "phone" else "B15"] = (
            "202-555-0199" if conflicting_field == "phone" else "different@example.invalid")
    else:
        repeated.update(B11="", B15="filled@example.invalid")
    contract_cells = repeated if scope == "contract" else {}
    site_cells = repeated if scope == "site" else {}
    return (("Active Contracts", summary(**contract_cells)),
            ("Synthetic Contract Sites", detail(**site_cells)))


@pytest.mark.parametrize("scope", ["contract", "site"])
@pytest.mark.parametrize("field", ["phone", "email"])
@pytest.mark.parametrize("preexisting", [False, True])
def test_conflicting_incoming_rows_for_one_person_block_only_the_affected_contract(scope, field, preexisting):
    neighbor = directory.save_directory(
        "Synthetic Untouched", (), expected_revision=0, actor="Synthetic Editor", confirmed=True,
        contract_contacts=(Contact("Manager", "Synthetic Neighbor"),))
    if preexisting:
        import_and_save(resaved(0, _sheets()))
    before = directory.load_directory("Synthetic Contract")
    sheets = list(_repeated_person_sheets(scope, conflicting_field=field))
    sheets[0] = (sheets[0][0], {**sheets[0][1], "C6": "Synthetic Healthy", "C9": "Synthetic Healthy Lead"})
    plan, result = import_and_save(resaved(1, sheets))
    entry = next(entry for entry in plan.entries if entry.contract == "Synthetic Contract")
    assert any(field in conflict for conflict in entry.conflicts)
    assert not entry.can_save
    assert [contract for contract, _ in result.blocked] == ["Synthetic Contract"]
    assert result.saved == ("Synthetic Healthy",)
    assert directory.load_directory("Synthetic Contract") == before
    assert directory.load_directory("Synthetic Untouched") == neighbor


@pytest.mark.parametrize("scope", ["contract", "site"])
def test_complementary_incoming_rows_save_one_person_with_both_sources_and_reimport_is_unchanged(scope):
    sheets = _repeated_person_sheets(scope)
    plan, result = import_and_save(resaved(0, sheets))
    assert not plan.entries[0].conflicts and result.saved == ("Synthetic Contract",)
    saved = directory.load_directory("Synthetic Contract")
    contacts = saved.contract_contacts if scope == "contract" else saved.sites[0].contacts
    assert len(contacts) == 1
    contact = contacts[0]
    assert contact.phone == ("202-555-0100" if scope == "contract" else "202-555-0101")
    assert contact.email == "filled@example.invalid"
    assert len(contact.source) <= batch._MAX_SOURCE_TEXT
    assert [source.rsplit("!", 1)[-1] for source in contact.source.split(";")] == [
        "B9,B10,B11", "B13,B14,B15"]
    for variant in range(1, 4):
        plan, result = import_and_save(resaved(variant, sheets))
        assert not plan.entries[0].changed and result.unchanged == ("Synthetic Contract",)
        assert directory.load_directory("Synthetic Contract") == saved


def test_unnamed_incoming_contacts_are_not_assumed_to_be_the_same_person():
    sheets = _sheets(B9="", **{**SECOND, "B13": ""})
    plan, result = import_and_save(resaved(0, sheets))
    assert not plan.entries[0].conflicts and result.saved == ("Synthetic Contract",)
    saved = directory.load_directory("Synthetic Contract")
    assert [(c.name, c.phone) for c in saved.contract_contacts] == [
        ("", "202-555-0100"), ("", "202-555-0102")]
