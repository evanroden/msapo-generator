"""Source acceptance follows the accepted facts and the current included use."""
from dataclasses import asdict, replace
from datetime import date

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_cmms import CMMSMapping, map_cmms
from app.monthly_report_model import (
    OrgChartNode, ReportDraft, ReportFollowUp, ReportPeriod, ResolvedBlock,
    SectionSpec, default_sections, synthetic_profiles,
)
from app.monthly_report_source_scope import included_scope_valid
from app.monthly_report_source_status import source_manager_status


@pytest.fixture
def mapped(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile, period = synthetic_profiles()[1], ReportPeriod(2026, 9)
    raw = (b"ID,Finished,Facility,Task,Area,Tag,Type\n"
           b"001,2026-09-02,Demo North,Inspected pump,Plant A,P-1,PM\n"
           b"002,2026-09-03,Demo South,Checked fan,Plant B,F-1,CM\n")
    content, _ = sources.ingest(profile, "synthetic-reviewed-rows.csv", raw)
    source = replace(content.source, facility="")
    result = map_cmms(content.tables[0], CMMSMapping("Finished", "ID", facility="Facility",
        description="Task", area="Area", tag="Tag", category="Type",
        finish_date_means_completed=True, complete_months=(period.key,),
        complete_facilities=tuple(site.key for site in profile.facilities)),
        profile, period, sources.source_reference(source, 1), scope_source=source)
    draft = ReportDraft(profile, period, "Synthetic editor",
        (SectionSpec("maintenance", "5", "Onsite service calls", result.specs),),
        result.blocks, sources=(source,), synthetic=True)
    assert included_scope_valid(draft, source)
    return draft, replace(content, source=source), raw


@pytest.mark.parametrize("block_key,column,new_value", [
    ("work_orders", "Total completed", "999999"),
    ("work_orders", "Month", "2026-10"),
    ("service_calls", "Finish Date", "2026-09-30"),
    ("service_calls", "WO #", "999999"),
    ("service_calls", "Area", "Different plant"),
    ("service_calls", "Tag #", "P-99"),
    ("service_calls", "Facility", "Demonstration South Facility"),
])
def test_changed_accepted_row_facts_reopen_the_exact_source(mapped, block_key, column, new_value):
    draft, content, raw = mapped
    block = next(b for b in draft.blocks if b.key == block_key)
    spec = next(s for s in draft.sections[0].blocks if s.key == block_key)
    position = next(i for i, col in enumerate(spec.columns) if col.title == column)
    row_index = next(i for i, row in enumerate(block.rows)
                     if "Demonstration North Facility" in row and row[position] != new_value)
    changed_row = list(block.rows[row_index]); changed_row[position] = new_value
    changed = replace(block, rows=tuple(tuple(changed_row) if i == row_index else row
                                       for i, row in enumerate(block.rows)))
    current = replace(draft, blocks=tuple(changed if b.key == block_key else b for b in draft.blocks))
    assert not included_scope_valid(current, content.source)
    status, = source_manager_status(current, (content,))
    assert status.needs_correction and not status.resolved
    assert "changed totals or mapped rows" in status.reason
    assert library.draft_from_dict(asdict(current)) == current
    assert sources.source_bytes(draft.profile, content.source) == raw


def test_extra_duplicate_row_cannot_reuse_one_accepted_row(mapped):
    draft, content, _ = mapped
    block = draft.blocks[0]
    current = replace(draft, blocks=(replace(block, rows=(*block.rows, block.rows[0])), *draft.blocks[1:]))
    assert not included_scope_valid(current, content.source)


def test_explicit_row_removal_and_service_description_edit_preserve_other_accepted_facts(mapped):
    draft, content, _ = mapped
    block = draft.blocks[0]
    row = block.rows[0]
    changed = replace(block, rows=((*row[:4], "Human description correction", row[5]),))
    current = replace(draft, blocks=(changed, *draft.blocks[1:]))
    assert included_scope_valid(current, content.source)


def test_legacy_exact_receipts_remain_valid_but_value_edits_reopen(mapped):
    from app.monthly_report_source_scope import USE_PREFIX, _decode, _encode
    draft, content, _ = mapped
    def legacy(ref):
        if not ref.startswith(USE_PREFIX):
            return ref
        record = _decode(ref[len(USE_PREFIX):]); record.pop("row_values")
        return USE_PREFIX + _encode(record)
    restored = replace(draft, blocks=tuple(replace(b, references=tuple(map(legacy, b.references)))
                                           for b in draft.blocks))
    assert included_scope_valid(restored, content.source)
    first = restored.blocks[0]
    altered = replace(first, rows=((*first.rows[0][:5], "Different tag"), *first.rows[1:]))
    assert not included_scope_valid(replace(restored, blocks=(altered, *restored.blocks[1:])), content.source)


def test_complementary_accepted_rows_merge_but_stale_other_source_cannot_supply_facts(monkeypatch, tmp_path):
    from app.monthly_report_setup import merge_report_block
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile, period = synthetic_profiles()[1], ReportPeriod(2026, 9)
    mapped, records = [], []
    for name, area, tag in (("area", "Plant A", ""), ("tag", "", "P-1")):
        content, _ = sources.ingest(profile, "synthetic-" + name + ".csv",
            f"ID,Finished,Facility,Area,Tag\n001,2026-09-02,Demo North,{area},{tag}\n".encode())
        source = replace(content.source, facility="")
        records.append(source)
        mapped.append(map_cmms(content.tables[0], CMMSMapping("Finished", "ID", facility="Facility",
            area="Area", tag="Tag", finish_date_means_completed=True), profile, period,
            sources.source_reference(source, 1), scope_source=source))
    first, second = mapped
    blocks = tuple(merge_report_block(a, b, x, y)
                   for a, b, x, y in zip(first.blocks, second.blocks, first.specs, second.specs))
    draft = ReportDraft(profile, period, "Synthetic editor",
        (SectionSpec("maintenance", "5", "Onsite service calls", first.specs),), blocks,
        sources=tuple(records), synthetic=True)
    assert len(blocks[0].rows) == 1 and blocks[0].rows[0][3:] == ("Plant A", "", "P-1")
    assert all(included_scope_valid(draft, source) for source in records)
    stale = replace(draft, sources=(records[0], replace(records[1], findings="Changed source facts")))
    assert not included_scope_valid(stale, records[0])


def test_ai_review_does_not_accept_an_unreviewed_block_level_source(mapped):
    from app.monthly_report_ai import ai_references, evidence_fingerprint, reviewed_block
    from app.monthly_report_model import BlockSpec, DraftParagraph
    from app.monthly_report_source_readiness import content_readiness
    draft, content, _ = mapped
    other, _ = sources.ingest(draft.profile, "synthetic-extra-reference.txt", b"Unreviewed evidence.")
    current_sources = (content.source, other.source)
    first_ref = sources.source_reference(content.source, 1)
    other_ref = sources.source_reference(other.source, 1)
    paragraph = DraftParagraph("Synthetic inspected pump.", (), (first_ref,))
    block = ResolvedBlock("activity_summary", "This month", text=paragraph.text,
        ai_written=True, ai_paragraphs=(paragraph,), references=(first_ref, other_ref))
    block = replace(block, ai_evidence_fingerprint=evidence_fingerprint(current_sources, ai_references(block)))
    block = reviewed_block(block, current_sources)
    current = replace(draft, sources=current_sources, blocks=(block,),
        sections=(SectionSpec("activity", "2", "Monthly Activity", (BlockSpec(block.key, "rich_text"),)),))
    assert content_readiness(current, content.source).accepted
    assert not content_readiness(current, other.source).accepted
    changed = replace(other.source, findings="Changed unreviewed evidence")
    assert not content_readiness(replace(current, sources=(content.source, changed)), changed).accepted


@pytest.mark.parametrize("kind", ["issue", "proposal", "organization"])
@pytest.mark.parametrize("suffix", [".txt", ".csv"])
@pytest.mark.parametrize("facility", ["", "Foreign facility"])
def test_nontext_included_evidence_retains_its_exact_correction(monkeypatch, tmp_path, kind, suffix, facility):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile, period = synthetic_profiles()[0], ReportPeriod(2026, 9)
    raw = b"Item,Finding\nSynthetic,Inspection pending\n"
    content, _ = sources.ingest(profile, "synthetic-evidence" + suffix, raw)
    source = replace(content.source, facility=facility, service_date="2026-09-16")
    content = replace(content, source=source)
    reference = sources.source_reference(source, 1)
    blocks, follow_ups = (), ()
    if kind == "organization":
        blocks = (ResolvedBlock("org_chart", "This month",
            org_nodes=(OrgChartNode("person", "Synthetic person", "Technician"),), references=(reference,)),)
    else:
        follow_ups = (ReportFollowUp("item", kind, "Synthetic pending item", "2026-09",
                                     references=(reference,)),)
    draft = ReportDraft(profile, period, "Synthetic editor", default_sections(), blocks,
                        sources=(source,), follow_ups=follow_ups, synthetic=True)
    status, = source_manager_status(draft, (content,))
    assert status.needs_correction and not status.resolved
    assert status.source_id == source.id and status.destinations
    assert status.summary.startswith("Included content")
    assert "site" in status.reason.casefold() or "facility" in status.reason.casefold()
    omitted = replace(draft, blocks=tuple(replace(b, source="Omit") for b in blocks),
                      follow_ups=tuple(replace(item, included=False) for item in follow_ups))
    unused, = source_manager_status(omitted, (content,))
    assert unused.summary == "Not included" and not unused.needs_correction
    assert library.draft_from_dict(asdict(draft)) == draft
    assert sources.source_bytes(profile, source) == raw


def advanced_artwork(monkeypatch, tmp_path, *, operational=False):
    from app import monthly_report_editor as editor, monthly_report_guided as guided
    from streamlit.testing.v1 import AppTest
    from test_monthly_report_source_review_regressions import saved_source, ROOT
    original, source, raw, _ = saved_source(monkeypatch, tmp_path, artwork=True, operational=operational)
    monkeypatch.setattr(editor, "operator_today", lambda tz: date(2026, 10, 7))
    monkeypatch.setattr(guided, "render_guided_workflow", editor.render_profile_workflow)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    assert not app.exception
    return app, original, source, raw


def test_advanced_saved_artwork_allows_a_date_only_correction(monkeypatch, tmp_path):
    app, original, source, raw = advanced_artwork(monkeypatch, tmp_path)
    next(w for w in app.date_input if w.label == "Source date").set_value(date(2026, 9, 18))
    next(b for b in app.button if b.label == "Use these source details").click().run()
    assert not app.exception
    contents = next(v for k, v in app.session_state.filtered_state.items() if k.endswith("_evidence"))
    assert contents[0].source.service_date == "2026-09-18"
    assert not any("shared report artwork" in e.value for e in app.error)
    assert sources.source_bytes(original.profile, contents[0].source) == raw
    assert library.load_snapshot(original.profile.contract, original.profile.key, original.period).draft == original


@pytest.mark.parametrize("change", ["omit", "activity", "same_event_include"])
def test_advanced_artwork_does_not_reuse_previous_ownership_after_controls_change(monkeypatch, tmp_path, change):
    app, original, source, raw = advanced_artwork(monkeypatch, tmp_path, operational=change != "omit")
    if change == "same_event_include":
        next(w for w in app.toggle if w.key.endswith("_activity_include")).set_value(False).run()
        next(w for w in app.toggle if w.key.endswith("_activity_include")).set_value(True)
    elif change == "activity":
        next(w for w in app.selectbox if w.key.endswith("_activity_summary_source")).set_value("Last month")
    else:
        next(w for w in app.selectbox if w.key.endswith("_client_logo_source")).set_value("Omit")
    next(w for w in app.date_input if w.label == "Source date").set_value(date(2026, 9, 18))
    next(b for b in app.button if b.label == "Use these source details").click().run()
    assert not app.exception
    contents = next(v for k, v in app.session_state.filtered_state.items() if k.endswith("_evidence"))
    assert contents[0].source == source
    assert any("shared report artwork" in e.value for e in app.error)
    assert sources.source_bytes(original.profile, source) == raw
    assert library.load_snapshot(original.profile.contract, original.profile.key, original.period).draft == original


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("service_description", [False, True])
def test_exact_accepted_rows_do_not_consume_separate_blank_rows(reverse, service_description):
    from app.monthly_report_source_scope import _accepted_rows_cover, _table_digest
    columns = ("Facility", "WO #", "Finish Date", "Area", "Task Code-Description", "Tag #")
    blank = ("Demo North", "001", "2026-09-02", "", "Inspected pump", "P-1")
    populated = (*blank[:3], "Plant A", *blank[4:])
    accepted = [list(blank), list(populated)]
    record = {"columns": list(columns), "row_values": accepted,
              "table": _table_digest(columns, accepted)}
    rows = (populated, blank) if reverse else (blank, populated)
    if service_description:
        rows = tuple((*row[:4], "Human description correction", row[5]) for row in rows)
    assert _accepted_rows_cover("service_calls", columns, rows, (record,))


@pytest.mark.parametrize("selection", [(1, 1), (0, 0), (0, 1, 1), (1, 0, 0)])
@pytest.mark.parametrize("repeat_receipt", [False, True])
def test_exact_row_preference_does_not_invent_accepted_occurrences(selection, repeat_receipt):
    from app.monthly_report_source_scope import _accepted_rows_cover, _table_digest
    columns = ("Identity", "Optional detail")
    accepted = [["001", ""], ["001", "Accepted detail"]]
    record = {"columns": list(columns), "row_values": accepted,
              "table": _table_digest(columns, accepted)}
    rows = tuple(tuple(accepted[index]) for index in selection)
    records = (record, record) if repeat_receipt else (record,)
    assert not _accepted_rows_cover("custom_table", columns, rows, records)


def test_exact_row_preference_keeps_accepted_duplicate_multiplicity():
    from app.monthly_report_source_scope import _accepted_rows_cover, _table_digest
    columns = ("Identity", "Optional detail")
    accepted = [["001", ""], ["001", "Accepted detail"], ["001", "Accepted detail"]]
    record = {"columns": list(columns), "row_values": accepted,
              "table": _table_digest(columns, accepted)}
    assert _accepted_rows_cover("custom_table", columns,
        (tuple(accepted[1]), tuple(accepted[0]), tuple(accepted[2])), (record,))


@pytest.mark.parametrize("selection,valid", [((0, 1), True), ((1, 0), True),
                                            ((0, 0), False), ((1, 0, 1), False)])
def test_reordered_current_mapped_receipts_keep_exact_scope_and_readiness(
        monkeypatch, tmp_path, selection, valid):
    from app.monthly_report_checks import preflight
    from app.monthly_report_source_readiness import content_readiness
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile, period = synthetic_profiles()[1], ReportPeriod(2026, 9)
    contents, results, originals = [], [], []
    for name, tag in (("populated", "P-1"), ("blank", "")):
        raw = ("ID,Finished,Facility,Task,Area,Tag\n"
               f"001,2026-09-02,Demo North,Synthetic inspected pump,Plant A,{tag}\n").encode()
        content, _ = sources.ingest(profile, "synthetic-" + name + ".csv", raw)
        source = replace(content.source, facility="")
        content = replace(content, source=source)
        contents.append(content)
        originals.append(raw)
        results.append(map_cmms(content.tables[0], CMMSMapping("Finished", "ID",
            facility="Facility", description="Task", area="Area", tag="Tag",
            finish_date_means_completed=True), profile, period,
            sources.source_reference(source, 1), scope_source=source))
    blocks = [result.blocks[0] for result in results]
    references = tuple(dict.fromkeys(ref for block in blocks for ref in block.references))
    block = replace(blocks[0], rows=tuple(blocks[index].rows[0] for index in selection),
                    references=references)
    draft = ReportDraft(profile, period, "Synthetic reviewer",
        (SectionSpec("maintenance", "5", "Onsite service calls", (results[0].specs[0],)),),
        (block,), sources=tuple(content.source for content in contents), synthetic=True)
    assert all(included_scope_valid(draft, content.source) == valid for content in contents)
    assert all(content_readiness(draft, content.source).accepted == valid for content in contents)
    statuses = source_manager_status(draft, tuple(contents))
    assert all(status.resolved == valid and status.needs_correction != valid for status in statuses)
    checks = [check for check in preflight(draft) if check.code.startswith("source_")]
    assert bool(checks) != valid
    if not valid:
        assert all(check.blocking for check in checks)
    assert all(sources.source_bytes(profile, content.source) == raw
               for content, raw in zip(contents, originals))


@pytest.mark.parametrize("accepted,rows", [
    ((("id", "A", ""), ("id", "", "T"), ("id", "", "")),
     (("id", "A", "T"), ("id", "", ""))),
    ((("id", "a", "", ""), ("id", "", "b", ""),
      ("id", "a", "", "c"), ("id", "", "b", "c")),
     (("id", "a", "b", "c"), ("id", "a", "b", ""))),
    ((("id", "a", "", ""), ("id", "", "b", ""),
      ("id", "", "b", "c1"), ("id", "a", "", "c1"), ("id", "a", "", "c2")),
     (("id", "a", "b", "c1"), ("id", "a", "b", "c2"))),
])
def test_complementary_evidence_uses_distinct_minimal_covers_in_every_order(accepted, rows):
    from itertools import permutations
    from app.monthly_report_source_scope import _accepted_rows_cover, _table_digest
    columns = tuple("Column " + str(i) for i in range(len(accepted[0])))
    for accepted_order in permutations(accepted):
        values = [list(row) for row in accepted_order]
        record = {"columns": list(columns), "row_values": values,
                  "table": _table_digest(columns, values)}
        for order in permutations(rows):
            assert _accepted_rows_cover("custom_table", columns, order, (record,))
            assert not _accepted_rows_cover("custom_table", columns, (*order, *order), (record,))
            invented = (*order[0][:-1], "Unaccepted fact")
            assert not _accepted_rows_cover("custom_table", columns, (invented, order[1]), (record,))


def test_complementary_search_budget_fails_closed_without_limiting_exact_tables(monkeypatch):
    from app import monthly_report_source_scope as scope
    columns = ("ID", "Area", "Tag")
    values = [["001", "Plant A", ""], ["001", "", "P-1"]]
    record = {"columns": list(columns), "row_values": values,
              "table": scope._table_digest(columns, values)}
    monkeypatch.setattr(scope, "_ROW_COVER_WORK_LIMIT", 0)
    assert not scope._accepted_rows_cover("custom_table", columns,
                                         (("001", "Plant A", "P-1"),), (record,))
    assert scope._accepted_rows_cover("custom_table", columns, tuple(reversed(values)), (record,))
