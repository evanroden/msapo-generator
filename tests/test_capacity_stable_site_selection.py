"""A reused directory name must not expand a saved report's site membership."""
from dataclasses import asdict, replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_capacity as capacity
from app import monthly_report_directory as directory
from app import monthly_report_library as library
from app.monthly_report_model import (
    BlockSpec, Facility, ReportDraft, ReportPeriod, ReportProfile,
    ResolvedBlock, SectionSpec,
)
from app.monthly_report_native_layout import _table
from app.monthly_report_setup import new_month_draft


CONTRACT = "Synthetic capacity site identity"
NORTH = Facility("north", "North Campus", ("NC",))
SOUTH = Facility("south", "North Hospital", ("SH",))
EAST = Facility("east", "East Campus")
SITES = tuple(directory.DirectorySite(f.key, f.title, f.aliases)
              for f in (NORTH, SOUTH, EAST))
PROFILE = ReportProfile(CONTRACT, "saved-north", "Saved North report",
                        (Facility("north", "North Hospital"),))
COLUMNS = ("Facility", "Service", "Capacity", "Units")
SECTION = SectionSpec("scorecards", "7", "Scorecards",
                      (BlockSpec("thermal_capacity", "table"),))


def shared_state():
    tables = tuple(capacity.CapacityTable(
        f"{site.key}-table", "Steam", COLUMNS,
        ((site.title, "Steam", value, "lb/hr"),), (site.key,), digest * 64,
        f"{site.key}-only.csv", ".csv", 1, 0,
    ) for site, value, digest in ((NORTH, "111", "a"), (SOUTH, "999", "b"),
                                 (EAST, "333", "c")))
    return capacity.CapacityState(CONTRACT, 2, tables, "Synthetic reviewer",
                                  "2026-11-04T17:00:00Z")


@pytest.fixture
def shared(monkeypatch):
    """Read providers supply valid synthetic records; persistence is tested below."""
    directory._validate_records(CONTRACT, SITES, ())
    library._validate_profile(PROFILE)
    state = shared_state()
    capacity._validate_tables(state.tables, (NORTH, SOUTH, EAST))
    current = directory.DirectoryState(CONTRACT, 2, SITES, "Synthetic reviewer",
                                       "2026-11-04T17:00:00Z")
    monkeypatch.setattr(directory, "load_directory", lambda contract: current if contract == CONTRACT else None)
    monkeypatch.setattr(library, "list_profiles", lambda contract: (PROFILE,) if contract == CONTRACT else ())
    monkeypatch.setattr(capacity, "load_capacity", lambda contract, revision=None: state if contract == CONTRACT else None)
    return state


def report(profile=PROFILE, block=None):
    return ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic reviewer",
                       (SECTION,), (block or ResolvedBlock("thermal_capacity", "Library"),),
                       synthetic=True)


def values(block):
    return tuple(row[-2] for table in block.extra_tables for row in table.rows) if block else ()


@pytest.mark.parametrize("facility, expected", (
    (Facility("north", "North Hospital"), ("111",)),
    (Facility("north", "North Campus", ("North Hospital",)), ("111",)),
    (NORTH, ("111",)),
    (SOUTH, ("999",)),
    (Facility("old-import-key", "North Campus"), ("111",)),
    (Facility("old-import-key", "SH"), ("999",)),
    (Facility("old-import-key", "North Campus", ("North Hospital",)), ()),
    (Facility("unknown", "Unknown Campus"), ()),
))
def test_known_keys_win_and_only_unambiguous_legacy_names_fall_back(shared, facility, expected):
    profile = replace(PROFILE, facilities=(facility,))
    before = asdict(shared)
    assert values(capacity.capacity_block(profile)) == expected
    assert asdict(shared) == before


def test_multiple_selected_sites_keep_their_keys_without_adding_a_name_match(shared):
    profile = replace(PROFILE, facilities=(*PROFILE.facilities, EAST), scope_type="multi_site")
    block = capacity.capacity_block(profile)
    assert values(block) == ("111", "333")
    assert not any("south-table" in reference for reference in block.references)
    assert directory.suggest_contact_bindings(
        directory.load_directory(CONTRACT), profile.facilities) == {"north": "north", "east": "east"}


def test_unambiguous_legacy_and_known_sites_can_be_selected_together(shared):
    profile = replace(PROFILE, facilities=(Facility("import-key", "NC"), SOUTH), scope_type="multi_site")
    assert values(capacity.capacity_block(profile)) == ("111", "999")


def test_retired_known_key_keeps_its_saved_rows_without_retargeting_a_reused_name(shared, monkeypatch):
    current = directory.load_directory(CONTRACT)
    retired = replace(current, sites=(replace(SITES[0], active=False), *SITES[1:]))
    monkeypatch.setattr(directory, "load_directory", lambda contract: retired)
    assert directory.suggest_contact_bindings(retired, PROFILE.facilities) == {"north": ""}
    assert values(capacity.capacity_block(PROFILE)) == ("111",)
    from app.monthly_report_capacity_ui import _saved_capacity_caption
    caption = _saved_capacity_caption(PROFILE, shared)
    assert "1 saved row for these sites" in caption
    assert "south" not in caption
    assert capacity.load_capacity(CONTRACT) == shared


def test_first_fill_and_native_word_table_exclude_the_other_site(shared):
    initial = report()
    resolved = capacity.resolve_capacity(initial)
    document = Document()
    for table in resolved.blocks[0].extra_tables:
        native = document.add_table(rows=1, cols=len(table.columns))
        _table(native._tbl, table.columns, table.rows)
    raw = BytesIO()
    document.save(raw)
    output = Document(BytesIO(raw.getvalue()))
    output_rows = tuple(tuple(cell.text for cell in row.cells)
                        for table in output.tables for row in table.rows)
    assert ("Steam", "North Campus", "Steam", "111", "lb/hr") in output_rows
    assert all("999" not in row for row in output_rows)
    assert initial.blocks[0].extra_tables == ()
    assert values(resolved.blocks[0]) == ("111",)


APP = '''
import streamlit as st
from app.monthly_report_capacity_ui import render_capacity_scope
if st.session_state.get('show', True):
    draft = st.session_state['draft']
    render_capacity_scope(draft.profile, draft.blocks[0])
'''


@pytest.mark.parametrize("block", (
    ResolvedBlock("thermal_capacity", "This month"),
    ResolvedBlock("thermal_capacity", "This month", text="Keep my report-only note",
                  rows=(("North Hospital", "Steam", "NR", "lb/hr"),)),
))
def test_actual_capacity_inventory_never_discloses_other_site_filename(shared, block):
    current = report(block=block)
    app = AppTest.from_string(APP)
    app.session_state["draft"] = current
    for visible in (True, False, True):
        app.session_state["show"] = visible
        app.run()
        assert not app.exception
        assert app.session_state["draft"] == current
        if visible:
            inventory, = (item.value for item in app.caption if item.value.startswith("Reusable capacity"))
            assert "1 saved row for these sites" in inventory
            assert "north" in inventory
            assert "south" not in inventory
            assert "east" not in inventory
    assert capacity.load_capacity(CONTRACT) == shared


@pytest.mark.parametrize("source", ("This month", "Library", "Omit"))
def test_manual_and_saved_prior_month_copies_remain_pinned(shared, source):
    block = ResolvedBlock("thermal_capacity", source,
                          rows=(("Saved site label", "Steam", "NR", "lb/hr"),),
                          references=("capacity:1:old-source:1:old-table",))
    current = report(block=block)
    reopened = library.draft_from_dict(asdict(current))
    assert capacity.resolve_capacity(reopened) is reopened
    future = new_month_draft(reopened, ReportPeriod(2026, 11))
    assert future.blocks[0].rows == block.rows
    assert capacity.resolve_capacity(future) is future
    assert current.blocks == (block,)


def test_another_contract_does_not_borrow_selected_rows(shared):
    profile = replace(PROFILE, contract="Other synthetic contract")
    assert capacity.capacity_block(profile) is None


def test_saved_reopened_directory_rename_preserves_sources_history_and_word(monkeypatch, tmp_path):
    """Real locking/save paths stay enabled for the Linux hosted suite."""
    from app.monthly_report_docx import assemble_docx
    from app.monthly_report_sources import source_bytes

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original_sites = (directory.DirectorySite("north", "North Hospital"),
                      directory.DirectorySite("south", "South Hospital"))
    directory.save_directory(CONTRACT, original_sites, expected_revision=0,
                             actor="Synthetic reviewer", confirmed=True)
    library.save_profile(PROFILE, expected_revision=0, actor="Synthetic reviewer", confirmed=True)
    raw = b"Facility,Service,Capacity,Units\nNorth Hospital,Steam,111,lb/hr\nSouth Hospital,Steam,999,lb/hr\n"
    inspection = capacity.inspect_capacity(PROFILE, "two-sites.csv", raw)
    saved_capacity = capacity.save_capacity(PROFILE, inspection.tables, expected_revision=0,
        actor="Synthetic reviewer", reviewed_fingerprint=capacity.review_fingerprint(inspection.tables))
    # Rename identities through the normal shared-directory save API.
    directory.save_directory(CONTRACT, SITES[:2], expected_revision=1,
                             actor="Synthetic reviewer", confirmed=True)
    profile = library.load_profile(CONTRACT, PROFILE.key).profile
    assert profile == PROFILE  # A directory rename does not rewrite saved profiles.
    filled = capacity.resolve_capacity(report(profile))
    assert values(filled.blocks[0]) == ("111",)
    saved = library.save_snapshot(filled, expected_revision=0, entered_editor="Synthetic reviewer")
    reopened = library.load_snapshot(CONTRACT, PROFILE.key, filled.period)
    assert reopened == saved
    document = Document(BytesIO(assemble_docx(reopened.draft,
        acknowledged_fingerprint=reopened.draft.fingerprint)))
    rows = tuple(tuple(cell.text for cell in row.cells) for table in document.tables for row in table.rows)
    assert any("111" in row for row in rows)
    assert all("999" not in row for row in rows)
    manual = replace(filled, blocks=(replace(filled.blocks[0], text="Keep report-only correction"),))
    library.save_snapshot(manual, expected_revision=1, entered_editor="Synthetic reviewer")
    assert library.load_snapshot_version(CONTRACT, PROFILE.key, filled.period, 1) == saved
    assert capacity.resolve_capacity(manual) is manual
    assert capacity.load_capacity(CONTRACT) == saved_capacity
    assert capacity.load_capacity(CONTRACT, 1) == saved_capacity
    assert source_bytes(PROFILE, inspection.content.source) == raw
