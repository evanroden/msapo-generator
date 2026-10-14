"""Isolated QA generation freshness diagnostics: one-way hashes, no source text."""
from dataclasses import replace

from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app import monthly_report_testing_ui as ui


def draft():
    return synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))


def test_noop_keeps_every_generation_part_digest():
    original = draft()
    assert ui._generation_parts(original) == ui._generation_parts(replace(original))
    context = {"part_hashes": ui._generation_parts(original)}
    assert ui._generation_part_changes(context, original) == {}


def test_actor_vs_activity_vs_period_are_structurally_distinguishable():
    original = draft()
    context = {"part_hashes": ui._generation_parts(original)}
    actor = replace(original, prepared_by="Different invented author")
    changed = ui._generation_part_changes(context, actor)
    assert set(changed) == {"prepared_by"}
    assert all(len(x["accepted"]) == len(x["current"]) == 12 for x in changed.values())

    blocks = list(original.blocks)
    block = blocks[0]
    blocks[0] = replace(block, text="New synthetic text")
    changed = ui._generation_part_changes(context, replace(original, blocks=tuple(blocks)))
    assert set(changed) == {"block:" + block.key}
    new_period = replace(original, period=ReportPeriod(2026, 10))
    assert set(ui._generation_part_changes(context, new_period)) == {"period"}


def test_diagnostics_do_not_record_value_or_user_text():
    original = draft()
    changed = replace(original, prepared_by="Private source text never output")
    context = {"part_hashes": ui._generation_parts(original)}
    parts = ui._generation_part_changes(context, changed)
    assert "prepared_by" in parts
    assert "Private source" not in str(parts)
    assert "Private source" not in str(context)
