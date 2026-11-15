"""Synthetic equivalents of the master's two six-month work-order bands."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from docx import Document
import pymupdf
import pytest

from app import monthly_report_library as library, monthly_report_master_tables as masters
from app import monthly_report_sources as sources, pdf_converter
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import BandedWorkOrderTable, ReportPeriod, ReportTable
from app.monthly_report_native_layout import NativeLayoutError, build_native_docx
from app.monthly_report_rolling_workflow import check_binding, remove
from app import monthly_report_work_order_review_flow as flow
from test_monthly_report_rolling_workflow import apply_grid, prepared
from tests.conftest import requires_libreoffice


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def banded_master(path, *, duplicate_location=False, ambiguous_category=False,
                  received_label="WO Received"):
    document = Document()
    document.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    document.add_paragraph("WORK ORDER STATUS")
    for location in (1, 2):
        for category in ("Non-PM", "PM"):
            actual = 1 if duplicate_location else location
            document.add_paragraph(f"Work Orders for Location {actual}")
            label = "PM and Non-PM" if ambiguous_category else category
            document.add_paragraph(f"{label} Work Orders")
            table = document.add_table(rows=8, cols=7)
            for row, first, months in (
                (0, received_label, MONTHS[:6]), (2, "", MONTHS[6:]),
                (4, "Closed", MONTHS[:6]), (6, "", MONTHS[6:]),
            ):
                table.cell(row, 0).text = first
                for column, month in enumerate(months, 1):
                    table.cell(row, column).text = month
            for row in (1, 3, 5, 7):
                table.cell(row, 1).text = "OLD TEMPLATE VALUE"
            table.cell(0, 0).merge(table.cell(3, 0))
            table.cell(4, 0).merge(table.cell(7, 0))
    document.save(path)
    return path


def banded_draft(tmp_path, monkeypatch, **options):
    draft, content, bundle, raw, _, manual = prepared(tmp_path, monkeypatch)
    path = banded_master(tmp_path / "synthetic-banded-master.docx", **options)
    original = path.read_bytes()
    digest = sha256(original).hexdigest()
    master_dir = tmp_path / "monthly_reports" / "designs" / "master"
    master_dir.mkdir(parents=True, exist_ok=True)
    (master_dir / (digest + ".docx")).write_bytes(original)
    frames = tuple(t for t in masters.from_inspection(inspect_docx(path))
                   if t.slot == "work_orders")
    assert len(frames) == 4 and all(len(t.columns) == 7 for t in frames)
    monkeypatch.setattr(masters, "for_profile", lambda _: frames)
    profile = replace(draft.profile, template="enfra_master:" + digest)
    empty = tuple(ReportTable(t.columns, (), t.reference) for t in frames)
    block = replace(draft.blocks[0], extra_tables=(*empty, manual))
    return path, replace(draft, profile=profile, blocks=(block,)), content, bundle, original


def test_source_counts_reach_correct_two_site_banded_word_tables(tmp_path, monkeypatch):
    path, draft, content, bundle, original = banded_draft(tmp_path, monkeypatch)
    result = apply_grid(draft, bundle)
    assert check_binding(result) is None
    tables = result.blocks[0].extra_tables
    assert len(tables) == 5 and tables[-1].rows == (("Keep this",),)
    word = Document(BytesIO(build_native_docx(result, path, master=True)))
    assert len(word.tables) == 5  # The separate manual table is retained too.
    north_nonpm, north_pm, south_nonpm, south_pm = word.tables[:4]
    assert north_nonpm.cell(2, 5).text == "Dec 2026"
    assert north_nonpm.cell(2, 6).text == "Jan 2027"
    assert north_nonpm.cell(3, 5).text == "1"  # North December received.
    assert north_nonpm.cell(7, 6).text == "1"  # North January closed.
    assert north_pm.cell(3, 5).text == ""  # PM was not selected.
    assert south_nonpm.cell(3, 5).text == ""  # South coverage was not confirmed.
    assert south_pm.cell(7, 6).text == ""
    for table in word.tables[:4]:
        # Preserve the master's two vertical Received/Closed label bands.
        assert all(table.rows[row]._tr.tc_lst[0].tcPr.vMerge is not None
                   for row in range(8))
    text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    assert "Example North" in text and "Example South" in text
    assert all("OLD TEMPLATE VALUE" not in c.text
               for table in word.tables for row in table.rows for c in row.cells)
    assert path.read_bytes() == original
    library.save_profile(result.profile, expected_revision=0, actor="Synthetic AM", confirmed=True)
    library.save_snapshot(result, expected_revision=0)
    reopened = library.load_snapshot(result.profile.contract, result.profile.key, result.period).draft
    assert reopened == result and check_binding(reopened) is None
    assert isinstance(reopened.blocks[0].extra_tables[0], BandedWorkOrderTable)
    saved = flow.saved_bundle(result, content.source.id, "workorders")
    restored = remove(result, saved, expected_revision=flow.revision(saved),
        expected_block=result.blocks[0].fingerprint, confirmed=True)
    assert restored.blocks[0].extra_tables == draft.blocks[0].extra_tables


def test_banded_grid_rollover_preserves_month_site_and_unknown_values(tmp_path, monkeypatch):
    path, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    previous = apply_grid(draft, bundle)
    initial = previous.blocks[0]
    next_draft = replace(draft, period=ReportPeriod(2027, 2))
    carried = masters.rebind_carried_master_tables(next_draft, {"work_orders": initial},
                                                   draft.profile.template)
    north = carried.blocks[0].extra_tables[0]
    assert north.band_site_key == "north" and north.band_category == "non_pm"
    assert north.rows[1][4:7] == ("Dec 2026", "Jan 2027", "Feb 2027")
    assert north.rows[2][4:7] == ("1", "0", "")
    assert north.rows[6][4:7] == ("0", "1", "")
    assert previous.blocks[0] == initial  # The prior report remains immutable.
    word = Document(BytesIO(build_native_docx(carried, path, master=True)))
    assert word.tables[0].cell(2, 4).text == "Dec 2026"
    assert word.tables[0].cell(3, 4).text == "1"
    assert word.tables[0].cell(7, 5).text == "1"
    assert word.tables[0].cell(3, 6).text == ""  # Future February remains unknown.
    library.save_profile(carried.profile, expected_revision=0, actor="Synthetic AM", confirmed=True)
    library.save_snapshot(carried, expected_revision=0)
    reopened = library.load_snapshot(carried.profile.contract, carried.profile.key, carried.period).draft
    assert reopened == carried and reopened.blocks[0].extra_tables[0].band_site_key == "north"

    swapped = replace(next_draft, profile=replace(next_draft.profile,
        facilities=tuple(reversed(next_draft.profile.facilities))))
    with pytest.raises(ValueError, match="identity|location|category"):
        masters.rebind_carried_master_tables(swapped, {"work_orders": initial}, draft.profile.template)
    changed_master = replace(next_draft, profile=replace(next_draft.profile, template="enfra_master:" + "b" * 64))
    with pytest.raises(ValueError, match="master changed"):
        masters.rebind_carried_master_tables(changed_master, {"work_orders": initial}, draft.profile.template)


def test_single_site_never_binds_or_labels_the_second_location(tmp_path, monkeypatch):
    path, draft, _, _, _ = banded_draft(tmp_path, monkeypatch)
    profile = replace(draft.profile, facilities=draft.profile.facilities[:1], scope_type="individual")
    source, _ = sources.ingest(profile, "one-site.csv",
        b"Work Order #,Site,Received Date,Closed Date,Status,PM/Non-PM\n"
        b"N-1,North,2026-12-05,2027-01-03,Closed,Non-PM\n")
    draft = replace(draft, profile=profile, sources=(source.source,), source_row_reviews=())
    bundle = flow.prepare_bundle(draft, source)
    bundle = flow.confirm_coverage(draft, bundle, table_number=1, site="north",
        start_month="2026-12", end_month="2027-01", evidence="Synthetic full export", confirmed=True)
    draft = flow.store_bundle(draft, bundle)
    result = apply_grid(draft, bundle)
    assert result.blocks[0].extra_tables[2].rows == ()
    assert result.blocks[0].extra_tables[3].rows == ()
    word = Document(BytesIO(build_native_docx(result, path, master=True)))
    text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    assert "Example North" in text and "Example South" not in text
    assert "Location 2" not in text
    assert all("OLD TEMPLATE VALUE" not in c.text
               for table in word.tables for row in table.rows for c in row.cells)


def test_two_confirmed_sites_get_independent_counts(tmp_path, monkeypatch):
    path, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    both = flow.confirm_coverage(draft, bundle, table_number=1, site="south",
        start_month="2026-12", end_month="2027-01", evidence="Synthetic south export", confirmed=True)
    draft = flow.store_bundle(draft, both, expected_revision=flow.revision(bundle))
    result = apply_grid(draft, both)
    word = Document(BytesIO(build_native_docx(result, path, master=True)))
    north, south = word.tables[0], word.tables[2]
    assert north.cell(3, 5).text == "1" and north.cell(7, 6).text == "1"
    assert south.cell(3, 5).text == "1" and south.cell(7, 6).text == "0"
    assert result.blocks[0].extra_tables[0].band_site_key == "north"
    assert result.blocks[0].extra_tables[2].band_site_key == "south"


def test_existing_manual_grid_edits_are_not_overwritten(tmp_path, monkeypatch):
    _, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    published = apply_grid(draft, bundle)
    current = published.blocks[0]
    band = current.extra_tables[0]
    edited_rows = list(band.rows)
    edited_rows[2] = (*edited_rows[2][:5], "99", *edited_rows[2][6:])
    edited = replace(band, rows=tuple(edited_rows))
    altered = replace(published, blocks=(replace(current, extra_tables=(edited, *current.extra_tables[1:])),))
    saved = flow.saved_bundle(altered, bundle["source_id"], "workorders")
    with pytest.raises(ValueError, match="grid values changed"):
        apply_grid(altered, saved)
    assert altered.blocks[0].extra_tables[0].rows[2][5] == "99"


def test_changed_source_or_site_identity_cannot_reuse_published_grid(tmp_path, monkeypatch):
    path, draft, content, bundle, _ = banded_draft(tmp_path, monkeypatch)
    published = apply_grid(draft, bundle)
    saved = flow.saved_bundle(published, content.source.id, "workorders")
    row = flow.restored_group(saved, saved["groups"][0]).rows[0]
    changed = flow.change_row(saved, 0, row.key, {"work_date": "2026-11-05"})
    stale = flow.store_bundle(published, changed, expected_revision=flow.revision(saved))
    assert check_binding(stale) is not None

    block = published.blocks[0]
    wrong_site = replace(block.extra_tables[0], band_site_key="south")
    tampered = replace(published, blocks=(replace(block, extra_tables=(wrong_site, *block.extra_tables[1:])),))
    assert check_binding(tampered) is not None
    with pytest.raises(NativeLayoutError, match="site or category changed"):
        build_native_docx(tampered, path, master=True)


@requires_libreoffice
def test_banded_grids_have_readable_site_and_month_labels_in_pdf(tmp_path, monkeypatch):
    path, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    result = apply_grid(draft, bundle)
    docx_path = tmp_path / "synthetic-banded-output.docx"
    docx_path.write_bytes(build_native_docx(result, path, master=True))
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pdf_converter, "PDF_BACKEND", "libreoffice")
    pdf_path = pdf_converter.convert_to_pdf(docx_path)
    with pymupdf.open(pdf_path) as pdf:
        text = " ".join(" ".join(page.get_text().split()) for page in pdf)
    for expected in ("Example North", "Example South", "Non-PM", "PM", "Dec 2026", "Jan 2027"):
        assert expected in text
    assert "OLD TEMPLATE VALUE" not in text


@pytest.mark.parametrize("options", [{"duplicate_location": True},
                                      {"ambiguous_category": True}])
def test_banded_frame_identity_must_be_unambiguous(tmp_path, monkeypatch, options):
    _, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch, **options)
    with pytest.raises(ValueError, match="site|location|category|grid|mapping"):
        apply_grid(draft, bundle)


def test_other_seven_column_tables_do_not_disable_legacy_grids(tmp_path, monkeypatch):
    draft, _, bundle, _, frames, _ = prepared(tmp_path, monkeypatch)
    unrelated = masters.MasterTable("work_orders", 99, "master-table:other:99",
        ("Other details", "A", "B", "C", "D", "E", "F"), tuple(range(7)), 7)
    monkeypatch.setattr(masters, "for_profile", lambda _: (*frames, unrelated))
    result = apply_grid(draft, bundle)
    assert result.blocks[0].extra_tables[1].rows[0][-2:] == ("1", "0")


def test_competing_grid_layouts_require_review(tmp_path, monkeypatch):
    draft, _, _, _, frames, _ = prepared(tmp_path, monkeypatch)
    recognized = masters.MasterTable("work_orders", 99, "master-table:other:99",
        ("WO Received", "Jan", "Feb", "Mar", "Apr", "May", "Jun"), tuple(range(7)), 7,
        band_site_index=0, band_category="pm")
    monkeypatch.setattr(masters, "for_profile", lambda _: (*frames, recognized))
    with pytest.raises(ValueError, match="competing"):
        apply_grid(draft, flow.saved_bundle(draft, draft.sources[0].id, "workorders"))


def test_omitted_legacy_grid_with_new_master_keeps_existing_behavior(tmp_path, monkeypatch):
    draft, _, bundle, _, _, _ = prepared(tmp_path, monkeypatch)
    previous = apply_grid(draft, bundle)
    omitted = replace(draft.blocks[0], source="Omit")
    next_draft = replace(draft, blocks=(omitted,),
        profile=replace(draft.profile, template="enfra_master:" + "b" * 64))
    result = masters.rebind_carried_master_tables(
        next_draft, {"work_orders": previous.blocks[0]}, draft.profile.template)
    assert result == next_draft


def test_expanded_received_heading_recognizes_and_populates_all_four_bands(tmp_path, monkeypatch):
    _, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch,
                                         received_label="Work Orders Received")
    result = apply_grid(draft, bundle)
    assert result.blocks[0].extra_tables[0].band_site_key == "north"
    assert result.blocks[0].extra_tables[0].rows[2][5] == "1"


def test_returning_report_carries_bands_and_reopens_the_next_month(tmp_path, monkeypatch):
    from app.monthly_report_start import returning_draft
    path, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    previous = apply_grid(draft, bundle)
    state = library.save_profile(previous.profile, expected_revision=0, actor="Synthetic AM", confirmed=True)
    library.save_snapshot(previous, expected_revision=0)
    carried, saved = returning_draft(state, ReportPeriod(2027, 2), "Synthetic AM")
    assert saved.draft == previous
    north = carried.blocks[0].extra_tables[0]
    assert isinstance(north, BandedWorkOrderTable)
    assert north.band_site_key == "north" and north.rows[2][4:7] == ("1", "0", "")
    library.save_snapshot(carried, expected_revision=0)
    reopened = library.load_snapshot(carried.profile.contract, carried.profile.key, carried.period).draft
    assert reopened == carried
    word = Document(BytesIO(build_native_docx(reopened, path, master=True)))
    assert word.tables[0].cell(3, 4).text == "1"
    assert library.load_snapshot(previous.profile.contract, previous.profile.key, previous.period).draft == previous


def test_next_month_blocks_changed_site_identity_before_carrying_bands(tmp_path, monkeypatch):
    from app.monthly_report_setup import new_month_draft
    _, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    previous = apply_grid(draft, bundle)
    swapped = replace(previous.profile, facilities=tuple(reversed(previous.profile.facilities)))
    with pytest.raises(ValueError, match="identity|location|category"):
        new_month_draft(previous, ReportPeriod(2027, 2), profile=swapped)


def test_normal_next_month_flow_carries_legacy_twelve_month_grid(tmp_path, monkeypatch):
    from app.monthly_report_setup import new_month_draft
    draft, _, bundle, _, _, _ = prepared(tmp_path, monkeypatch)
    previous = apply_grid(draft, bundle)
    carried = new_month_draft(previous, ReportPeriod(2027, 2))
    non_pm = carried.blocks[0].extra_tables[1]
    assert non_pm.reference == previous.blocks[0].extra_tables[1].reference
    assert non_pm.rows[0][-3:] == ("1", "0", "")


@pytest.mark.parametrize("banded", [True, False])
def test_next_month_does_not_discard_values_when_master_is_missing(tmp_path, monkeypatch, banded):
    from app.monthly_report_setup import new_month_draft
    if banded:
        _, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    else:
        draft, _, bundle, _, _, _ = prepared(tmp_path, monkeypatch)
    previous = apply_grid(draft, bundle)
    monkeypatch.setattr(masters, "for_profile", lambda _: ())
    with pytest.raises(ValueError, match="master is unavailable"):
        new_month_draft(previous, ReportPeriod(2027, 2))
    assert previous.blocks[0].extra_tables[0].rows


def test_next_month_does_not_carry_across_report_profiles(tmp_path, monkeypatch):
    from app.monthly_report_setup import new_month_draft
    _, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    previous = apply_grid(draft, bundle)
    other_profile = replace(previous.profile, key="another-profile")
    with pytest.raises(ValueError, match="different report profile"):
        new_month_draft(previous, ReportPeriod(2027, 2), profile=other_profile)


def test_different_sites_can_reuse_master_layout_without_other_site_counts(tmp_path, monkeypatch):
    from app.monthly_report_model import Facility
    from app.monthly_report_start import design_seed
    path, draft, _, bundle, _ = banded_draft(tmp_path, monkeypatch)
    previous = apply_grid(draft, bundle)
    state = library.save_profile(previous.profile, expected_revision=0, actor="Synthetic AM", confirmed=True)
    library.save_snapshot(previous, expected_revision=0)
    target = replace(previous.profile, key="other-sites", facilities=(
        Facility("east", "Example East"), Facility("west", "Example West")))
    fresh, _ = design_seed(target, ReportPeriod(2027, 2), "Synthetic AM", state)
    source_tables = previous.blocks[0].extra_tables[:4]
    target_tables = next(block for block in fresh.blocks if block.key == "work_orders").extra_tables[:4]
    assert tuple(t.reference for t in target_tables) == tuple(t.reference for t in source_tables)
    assert all(not t.rows and not isinstance(t, BandedWorkOrderTable) for t in target_tables)
    content, _ = sources.ingest(fresh.profile, "east.csv",
        b"Work Order #,Site,Received Date,Closed Date,Status,PM/Non-PM\n"
        b"E-1,East,2027-02-05,,Open,Non-PM\n")
    fresh = replace(fresh, sources=(content.source,))
    review = flow.prepare_bundle(fresh, content)
    review = flow.confirm_coverage(fresh, review, table_number=1, site="east",
        start_month="2027-02", end_month="2027-02", evidence="Synthetic east export", confirmed=True)
    fresh = flow.store_bundle(fresh, review)
    from datetime import date
    result = apply_grid(fresh, review, as_of=date(2027, 3, 1))
    east = next(block for block in result.blocks if block.key == "work_orders").extra_tables[0]
    assert east.band_site_key == "east" and east.rows[2][6] == "1"
    assert previous.blocks[0].extra_tables[0].band_site_key == "north"
    word = Document(BytesIO(build_native_docx(result, path, master=True)))
    captions = "\n".join(paragraph.text for paragraph in word.paragraphs)
    assert "Example East" in captions and "Example North" not in captions
    assert word.tables[0].cell(3, 6).text == "1"


def test_different_sites_get_empty_legacy_master_grids(tmp_path, monkeypatch):
    from app.monthly_report_model import Facility
    from app.monthly_report_start import design_seed
    draft, _, bundle, _, _, _ = prepared(tmp_path, monkeypatch)
    synthetic = Document()
    synthetic.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    path = tmp_path / "synthetic-legacy-master.docx"
    synthetic.save(path)
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
    folder = tmp_path / "monthly_reports" / "designs" / "master"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (digest + ".docx")).write_bytes(raw)
    draft = replace(draft, profile=replace(draft.profile, template="enfra_master:" + digest))
    previous = apply_grid(draft, bundle)
    state = library.save_profile(previous.profile, expected_revision=0, actor="Synthetic AM", confirmed=True)
    library.save_snapshot(previous, expected_revision=0)
    target = replace(previous.profile, key="other-sites", facilities=(
        Facility("east", "Example East"), Facility("west", "Example West")))
    fresh, _ = design_seed(target, ReportPeriod(2027, 2), "Synthetic AM", state)
    tables = next(block for block in fresh.blocks if block.key == "work_orders").extra_tables[:4]
    assert tuple(t.reference for t in tables) == tuple(t.reference for t in previous.blocks[0].extra_tables[:4])
    assert all(not table.rows for table in tables)
