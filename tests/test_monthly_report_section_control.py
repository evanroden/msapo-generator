"""Synthetic, contract-separated coverage for opt-in section/profile primitives."""

from dataclasses import asdict, replace
from io import BytesIO

import pytest
from docx import Document

from app.monthly_report_docx import assemble_docx, generate_report
from app.monthly_report_library import draft_from_dict
from app.monthly_report_model import (
    Facility, ReportPeriod, ReportProfile, ResolvedBlock, included_sections,
    profile_sections, synthetic_draft,
)
from app.monthly_report_section_control import (
    ContractPage, install_text_page, report_only_sections, standing_sections,
    verify_custom_page_scope, visible_outline,
)
from tests.conftest import requires_libreoffice


def make_draft(contract="Synthetic Contract A", key="north", *, facilities=None):
    sites = facilities or (Facility("north", "Synthetic North"),)
    profile = ReportProfile(
        contract, key, "Synthetic report", sites,
        "individual" if len(sites) == 1 else "multi_site",
    )
    return synthetic_draft(profile, ReportPeriod(2026, 10))


def page_for(draft):
    return ContractPage.for_report(draft, "plumbing_electrical_allowance",
                                   "Plumbing & Electrical Allowance")


def add_page(draft, text="Synthetic scope update without monetary amounts."):
    page = page_for(draft)
    return install_text_page(draft, page, ResolvedBlock(page.block_key, "This month", text=text))


def test_standing_choices_are_optional_and_scoped_to_one_contract():
    a, b = make_draft(), make_draft("Synthetic Contract B")
    changed = standing_sections(a.profile, {"training": False, "water": False})
    assert a.profile.excluded_sections == ()
    assert b.profile.excluded_sections == ()
    assert set(changed.excluded_sections) == {"training", "water"}
    assert {s.key for s in profile_sections(changed) if s.included}.isdisjoint({"training", "water"})
    restored = standing_sections(changed, {"water": True})
    assert restored.excluded_sections == ("training",)
    assert next(s for s in profile_sections(restored) if s.key == "water").included


def test_standing_changes_are_validated_and_do_not_make_new_month_widgets():
    profile = make_draft().profile
    for change in ({"not_in_master": False}, {"water": 0}, {"water": "off"}):
        with pytest.raises(ValueError):
            standing_sections(profile, change)
    assert standing_sections(profile, {}) == profile


def test_report_only_override_preserves_all_saved_content_and_reload():
    before = make_draft()
    original = next(b for b in before.blocks if b.key == "demo_training")
    disabled = report_only_sections(before, {"training": False, "water": False})
    assert disabled.profile == before.profile
    assert disabled.blocks == before.blocks
    assert "training" not in [key for key, _, _ in visible_outline(disabled)]
    saved_and_reloaded = draft_from_dict(asdict(disabled))
    assert next(s for s in saved_and_reloaded.sections if s.key == "training").included is False
    restored = report_only_sections(saved_and_reloaded, {"training": True})
    assert next(b for b in restored.blocks if b.key == "demo_training") == original
    assert next(s for s in restored.sections if s.key == "water").included is False
    assert [num for _, num, _ in visible_outline(restored) if num.isdigit()] == [
        str(i) for i in range(1, len([s for s in included_sections(restored.sections) if not s.appendix]) + 1)
    ]


def test_all_on_all_off_and_unchanged_appendix_numbers():
    draft = make_draft()
    keys = [s.key for s in draft.sections]
    none = report_only_sections(draft, {key: False for key in keys})
    assert visible_outline(none) == ()
    all_on = report_only_sections(none, {key: True for key in keys})
    assert len(visible_outline(all_on)) == len(keys)
    assert visible_outline(all_on)[-1][1] == "G"
    assert [int(n) for _, n, _ in visible_outline(all_on) if n.isdigit()] == list(range(1, len(keys)))
    with pytest.raises(ValueError, match="Unknown section"):
        report_only_sections(draft, {"unmapped_master_heading": False})


def test_two_sites_in_same_contract_are_not_equivalent_to_one_site():
    north = make_draft("Synthetic UNO", "north")
    south = make_draft("Synthetic UNO", "south", facilities=(Facility("south", "Synthetic South"),))
    combined = make_draft("Synthetic UNO", "region", facilities=(
        Facility("north", "Synthetic North"), Facility("south", "Synthetic South"),
    ))
    p = page_for(north)
    assert p.matches(north)
    assert not p.matches(south)
    assert not p.matches(combined)
    assert p.key != page_for(south).key
    assert p.key != page_for(combined).key
    with pytest.raises(ValueError, match="scope"):
        install_text_page(south, p, ResolvedBlock(p.block_key, "This month", text="Synthetic"))


def test_contract_isolation_and_content_preserved_in_history_round_trip():
    a = add_page(make_draft("Synthetic UNO"))
    b = make_draft("Other Contract")
    assert "Plumbing & Electrical Allowance" in [s.title for s in a.sections]
    assert all("Allowance" not in s.title for s in b.sections)
    restored = draft_from_dict(asdict(a))
    verify_custom_page_scope(restored)
    assert restored.sections == a.sections and restored.blocks == a.blocks
    hidden = report_only_sections(restored, {page_for(a).key: False})
    verify_custom_page_scope(hidden)
    shown = report_only_sections(draft_from_dict(asdict(hidden)), {page_for(a).key: True})
    assert shown == a
    swapped = replace(a, profile=b.profile)
    with pytest.raises(ValueError, match="another contract"):
        verify_custom_page_scope(swapped)


def test_custom_page_is_idempotent_only_through_explicit_edit_not_duplicate_add():
    original = make_draft("Synthetic UNO")
    added = add_page(original)
    assert added.sections[-2].key == page_for(original).key  # Before appendix G.
    with pytest.raises(ValueError, match="already exists"):
        add_page(added)
    with pytest.raises(ValueError, match="unknown scope"):
        verify_custom_page_scope(replace(added, sections=(
            *added.sections[:-2], replace(added.sections[-2], key="custom_unknown"), added.sections[-1],
        )))


def test_unknown_financial_content_and_unreviewed_ai_never_gain_client_permission():
    draft = make_draft("Synthetic UNO")
    page = page_for(draft)
    with pytest.raises(ValueError, match="field/page review"):
        install_text_page(draft, page, ResolvedBlock(page.block_key, "This month",
                          text="Synthetic vendor invoice total: $1,250.00"))
    with pytest.raises(ValueError, match="field/page review"):
        install_text_page(draft, page, ResolvedBlock(page.block_key, "This month",
                          rows=(("amount", "1250"),)))
    with pytest.raises(ValueError, match="Review AI"):
        install_text_page(draft, page, ResolvedBlock(page.block_key, "This month",
                          text="Synthetic unreviewed suggestion", ai_written=True))


def test_pinned_native_master_fails_closed_without_rewriting_old_report():
    a = make_draft("Synthetic UNO")
    pinned = replace(a, profile=replace(a.profile, template="enfra_master:2"))
    original = asdict(pinned)
    page = page_for(pinned)
    with pytest.raises(ValueError, match="native designs"):
        install_text_page(pinned, page, ResolvedBlock(page.block_key, "This month", text="Synthetic"))
    assert asdict(pinned) == original
    assert draft_from_dict(original) == pinned


def test_generated_generic_docx_has_no_orphan_heading_divider_or_custom_content():
    draft = add_page(make_draft("Synthetic UNO"))
    draft = report_only_sections(draft, {"training": False, page_for(draft).key: False})
    doc = Document(BytesIO(assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Plumbing & Electrical Allowance" not in text
    assert "Synthetic scope update without monetary amounts." not in text
    assert "11. Training Summary" not in text
    assert "10. Training Summary" not in text
    assert "Monthly Activity Summary" in text
    enabled = report_only_sections(draft, {page_for(draft).key: True})
    doc2 = Document(BytesIO(assemble_docx(enabled, acknowledged_fingerprint=enabled.fingerprint)))
    shown = "\n".join(p.text for p in doc2.paragraphs)
    assert "Plumbing & Electrical Allowance" in shown
    assert "Synthetic scope update without monetary amounts." in shown


@requires_libreoffice
def test_generated_generic_pdf_matches_visible_custom_page_order():
    import pymupdf as fitz
    draft = add_page(make_draft("Synthetic UNO"))
    draft = report_only_sections(draft, {"training": False})
    package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
    assert package.pdf, package.pdf_error
    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        assert "Plumbing & Electrical Allowance" in text
        assert "Synthetic scope update without monetary amounts." in text
        assert "Training Summary" not in text
