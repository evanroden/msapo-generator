"""A reformatted phone number is the same contact detail (Refs #288, G2-directory-8).

Re-importing "(202) 555-0100" for a saved "202-555-0100" was reported as a
changed phone and blocked the whole contract; single-sheet import rewrote the
saved value. Synthetic contacts only.
"""
import pytest

from app import monthly_report_directory as directory
from test_monthly_report_directory_batch import detail, summary
from test_monthly_report_directory_reimport_growth import import_and_save, resaved

Contact = directory.DirectoryContact
SAME_NUMBER = ["(202) 555-0100", "202.555.0100", "+1 202 555 0100", "1-202-555-0100", "202 555 0100",
               "202-555-\n0100"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def _sheets(phone="202-555-0100", **extra):
    return (("Active Contracts", summary(B10=phone, **extra)), ("Synthetic Contract Sites", detail()))


def _saved_phone():
    return directory.load_directory("Synthetic Contract").contract_contacts[0].phone


@pytest.mark.parametrize("phone", SAME_NUMBER)
def test_batch_reimport_of_a_reformatted_phone_is_unchanged_not_blocked(phone):
    import_and_save(resaved(0, _sheets()))
    plan, result = import_and_save(resaved(1, _sheets(phone)))
    assert plan.entries[0].conflicts == () and not plan.entries[0].changed
    assert result.unchanged == ("Synthetic Contract",) and not result.blocked
    assert _saved_phone() == "202-555-0100"
    assert directory.load_directory("Synthetic Contract").revision == 1


@pytest.mark.parametrize("phone", ["202-555-0199", "202-555-0100 x12"])
def test_a_different_number_or_new_extension_is_a_change_to_review(phone):
    import_and_save(resaved(0, _sheets()))
    plan, result = import_and_save(resaved(1, _sheets(phone)))
    change, = plan.entries[0].changes
    assert change.after.phone == phone
    assert result.unchanged == ("Synthetic Contract",) and _saved_phone() == "202-555-0100"


def test_rows_for_one_person_that_differ_only_in_phone_punctuation_combine():
    second_row = {"A13": "Executive Director", "B13": "Synthetic Executive", "A14": "Phone", "B14": "(202) 555-0100",
                  "A15": "Email", "B15": "executive@example.invalid"}
    plan, result = import_and_save(resaved(0, _sheets(**second_row)))
    assert plan.entries[0].conflicts == () and result.saved == ("Synthetic Contract",)
    assert [(c.name, c.phone) for c in directory.load_directory("Synthetic Contract").contract_contacts] == [
        ("Synthetic Executive", "202-555-0100")]


@pytest.mark.parametrize(("saved", "incoming", "same"), [
    ("202-555-0100 ext. 12", "(202) 555-0100 x12", True),
    ("202-555-0100 ext. 12", "202-555-\n0100\next. 12", True),
    ("202-555-0100 x12", "202-555-0100 x13", False),
    ("See front desk", "see  front DESK", True),
    ("See front desk", "Call the operator", False),
    ("555-01", "55501", False),
])
def test_phone_comparison_keeps_extensions_and_text(saved, incoming, same):
    assert directory.same_contact_value("phone", saved, incoming) is same


def test_single_sheet_import_keeps_the_saved_phone_format_and_record():
    saved = Contact("Executive Director", "Synthetic Executive", "202-555-0100", "executive@example.invalid", "first")
    incoming = Contact("Executive Director", "Synthetic Executive", "(202) 555-0100", "executive@example.invalid", "second")
    assert directory.proposed_contacts((saved,), (incoming,)) == (saved,)
    newer = Contact("Executive Director", "Synthetic Executive", "(202) 555-0100", "new@example.invalid", "second")
    merged, = directory.proposed_contacts((saved,), (newer,))
    assert (merged.phone, merged.email) == ("202-555-0100", "new@example.invalid")
