"""Native monthly suggestions retain real page origins and never import prices."""
from dataclasses import replace
import json

import fitz

from app import monthly_report_sources as sources
from app.monthly_report_model import ReportSource, synthetic_profiles


def source():
    return ReportSource(
        "synthetic", "synthetic-service.pdf", "a" * 64, ".pdf",
        page_texts=(
            "Service report\nInspected pump.\nReplaced filter.",
            "Invoice amount: $500. Inspected pump.",
            "Terms and conditions. Limitation of liability. Inspected equipment.",
            "",
            "Service report\nInspected pump.\nRepaired valve.",
            "Inspected unrelated equipment.",
        ), selected_pages=(1, 5),
    )


def test_native_suggestions_exclude_unselected_priced_legal_blank_and_unreadable_pages():
    original = source()
    suggested = sources.suggest_facts(original, synthetic_profiles()[0])
    assert suggested.actions == "Inspected pump.\nReplaced filter.\nRepaired valve."
    assert sources.native_action_lines(suggested) == (
        ("Inspected pump.", (1, 5)), ("Replaced filter.", (1,)), ("Repaired valve.", (5,)),
    )
    # Even an accidental page selection cannot suggest commercial/legal content.
    unsafe = replace(original, selected_pages=(1, 2, 3, 4, 5), needs_vision=(5,))
    assert sources.native_action_lines(unsafe) == (("Inspected pump.", (1,)), ("Replaced filter.", (1,)))
    assert original.actions == ""


def test_removed_page_invalidates_action_origin_without_erasing_human_work():
    original = replace(source(), actions="Inspected pump.\nRepaired valve.\nUpdated human summary.")
    changed = replace(original, selected_pages=(1,))
    accepted, unresolved = sources.action_evidence(changed)
    assert accepted == (("Inspected pump.", (1,)),)
    assert unresolved == ("Repaired valve.", "Updated human summary.")
    assert changed.actions == original.actions


def test_old_priced_action_never_gets_citations_to_selected_technical_pages():
    candidate = replace(source(), actions="Invoice amount: $500. Inspected pump.\nInspected pump.")
    accepted, unresolved = sources.action_evidence(candidate)
    assert accepted == (("Inspected pump.", (1, 5)),)
    assert unresolved == ("Invoice amount: $500. Inspected pump.",)


def test_ingestion_and_legacy_extraction_cache_keep_original_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    with fitz.open() as pdf:
        for text in source().page_texts:
            page = pdf.new_page()
            if text:
                page.insert_text((50, 50), text)
        raw = pdf.tobytes()
    content, _ = sources.ingest(profile, "synthetic-service.pdf", raw)
    assert "$500" not in content.source.actions
    assert "Limitation" not in content.source.actions
    assert sources.source_bytes(profile, content.source) == raw
    cache = sources._path(profile, content.source.sha256, ".json")
    cached = json.loads(cache.read_text())
    cached.pop("native_action_policy")
    cached["source"]["actions"] += "\nInvoice amount: $500. Inspected pump."
    cache.write_text(json.dumps(cached))
    restored, _ = sources.ingest(profile, "synthetic-service.pdf", raw)
    assert restored.source.actions == content.source.actions
    assert sources.source_bytes(profile, restored.source) == raw
