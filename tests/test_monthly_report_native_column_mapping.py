"""Imported proposal/capital rows preserve native Word table schema and price exclusions."""
from app.monthly_report_model import ReportSource
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_structured_uploads import mapped_rows, native_update, reader_update


def source(columns, rows):
    source = ReportSource("f"*64, "synthetic.csv", "f"*64, ".csv",
        page_texts=("\n".join(("\t".join(columns),
                                *("\t".join(row) for row in rows))),))
    return SourceContent(source,(SourceTable("Synthetic",columns,rows),))


def test_proposal_native_six_columns_preserve_status_id_and_technical_notes():
    cols = ("Proposal Total","Project Number","Work Description","Status","Vendor","Facility","Technical Notes")
    rows = (("48,500.00","Q-TEST-731","Repair the chilled-water valve","Pending",
             "Synthetic Mechanical","North","Inspection at 1.20 psi"),)
    content=source(cols,rows)
    target=("Project Number","Facility","Vendor","Work Description","Status","Technical Notes")
    expected=(("Q-TEST-731","North","Synthetic Mechanical","Repair the chilled-water valve",
               "Pending","Inspection at 1.20 psi"),)
    assert mapped_rows(content,"proposals",target)==expected
    block=native_update((content,),"proposals",table_columns=target)
    assert block.rows==expected
    assert all(len(row)==len(target) for row in block.rows)
    assert all("48,500" not in cell for row in block.rows for cell in row)


def test_capital_native_five_columns_accept_exact_extra_asset_and_status():
    cols=("Project Budget","Facility","Priority","Recommendation","Equipment Tag","Status")
    content=source(cols,(("250,000","North","1","Review condenser capacity",
                         "CH-TEST-02","Under review"),))
    target=("Equipment Tag","Facility","Recommendation","Priority","Status")
    assert mapped_rows(content,"capital_renewal",target)==(
        ("CH-TEST-02","North","Review condenser capacity","1","Under review"),)


def test_reader_dynamic_table_shape_keeps_status_and_rejects_invented_values():
    cols=("Project Number","Facility","Vendor","Work Description","Status","Technical Notes")
    table=source(cols,(("Q-TEST-731","North","Synthetic Mechanical","Inspect control panel",
                        "Pending","45 gpm"),))
    identity=table.source.id
    same={"items":[{"source":identity,"page":1,
            "row":["Q-TEST-731","North","Synthetic Mechanical",
                   "Inspect control panel","Pending","45 gpm"]}]}
    block,pages=reader_update((table,),"proposals",same,table_columns=cols)
    assert block.rows==(tuple(same["items"][0]["row"]),)
    assert not pages
    invalid={"items":[{"source":identity,"page":1,
            "row":["Q-TEST-731","North","Synthetic Mechanical",
                   "Invented replacement","Pending","45 gpm"]}]}
    import pytest
    with pytest.raises(ValueError,match="not present"):
        reader_update((table,),"proposals",invalid,table_columns=cols)


def test_monetary_native_column_is_blank_even_when_target_design_has_budget():
    content=source(("Facility","Scope of Work","Budget","Status"),
                   (("North","Repair pump","12,400","Open"),))
    target=("Facility","Scope of Work","Budget","Status")
    assert mapped_rows(content,"proposals",target)==(
        ("North","Repair pump","","Open"),)
