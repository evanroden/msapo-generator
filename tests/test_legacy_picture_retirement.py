"""Legacy ownership ambiguity stays recoverable until an explicit choice saves."""
from dataclasses import replace
from datetime import date
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import contracts, monthly_report_editor as editor, monthly_report_library as library
from app import monthly_report_upload_ui as uploads
from app.monthly_report_docx import ReportPackage
from app.monthly_report_model import BlockSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, SectionSpec
from app.monthly_report_source_retirement import retire_contributions, record_retired_contributions
from test_source_page_retirement_lifecycle import APP


def legacy_pair(asset="same.png"):
    reference = "synthetic-legacy-source:1:reviewed-r1"
    accepted = ResolvedBlock("water_reports", "This month", asset_hashes=(asset,),
        asset_captions=("Matching diagram",), references=(reference,), asset_provenance=((asset, (reference,)),))
    combined = replace(accepted, asset_hashes=(asset, asset), asset_captions=("Matching diagram", "Matching diagram"))
    return accepted, combined


def test_ambiguous_legacy_removal_never_guesses_an_occurrence():
    accepted, combined = legacy_pair()
    assert retire_contributions(combined, (accepted,)) == combined


def test_ambiguous_legacy_receipt_needs_exact_explicit_resolution_before_acknowledgement():
    from app.monthly_report_asset_review import asset_context, pending_asset_indexes
    from app.monthly_report_source_retirement import acknowledge_retired_contributions, retirement_pending, resolve_legacy_retirement
    accepted, combined = legacy_pair()
    assert retirement_pending(combined, accepted)
    resolved = resolve_legacy_retirement(combined, accepted, 1)
    assert resolved.asset_hashes == accepted.asset_hashes
    assert resolved.asset_captions == accepted.asset_captions
    assert asset_context(resolved, 0) == ()
    assert pending_asset_indexes(resolved) == (0,), "Unknown historical ownership is not an approval."
    assert retire_contributions(resolved, (accepted,)) == resolved
    profile = ReportProfile("Synthetic Contract", "legacy", "Synthetic Facility", (Facility("west", "Synthetic West"),))
    draft = ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic Reviewer", (), (combined,))
    receipts = {accepted.key: (accepted,)}
    assert acknowledge_retired_contributions(receipts, receipts, SimpleNamespace(revision=2, draft=draft), draft, 1) == receipts
    updated = replace(draft, blocks=(resolved,))
    assert acknowledge_retired_contributions(receipts, receipts, SimpleNamespace(revision=2, draft=updated), updated, 1) == {}


def test_detailed_legacy_selector_removes_only_the_chosen_occurrence_and_saves(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    raw = BytesIO()
    Image.new("RGB", (80, 120), "steelblue").save(raw, "PNG")
    asset = library.asset_reference(raw.getvalue(), "png")
    accepted, combined = legacy_pair(asset)
    profile = ReportProfile("Synthetic Legacy Contract", "legacy", "Synthetic Facility", (Facility("west", "Synthetic West"),))
    period = ReportPeriod(2026, 10)
    draft = ReportDraft(profile, period, "Synthetic Reviewer", (
        SectionSpec("water", "6", "Water treatment", (BlockSpec("water_reports", "pdf_pages"),)),), (combined,))
    library.save_profile(profile, expected_revision=0, actor=draft.prepared_by, confirmed=True)
    library.save_snapshot(draft, expected_revision=0, assets=((asset, raw.getvalue()),), entered_editor=draft.prepared_by)
    monkeypatch.setattr(contracts, "contract_names", lambda: [profile.contract])
    monkeypatch.setattr(editor, "operator_today", lambda *a: date(2026, 11, 6))
    monkeypatch.setattr(uploads, "render_uploads", lambda *a, **kw: ((), {}, {}))
    monkeypatch.setattr(editor, "_preview", lambda *a, **kw: None)
    monkeypatch.setattr(editor, "preflight", lambda *a, **kw: ())
    observed = []
    monkeypatch.setattr(editor, "review_client_images", lambda draft, *a, **kw: observed.append(draft) or draft)
    monkeypatch.setattr(editor, "generate_report", lambda draft, **kw: ReportPackage(
        b"controlled-output-seam", b"controlled-output-seam", "fixture.docx", "fixture.pdf", draft.fingerprint))
    prefix = "report_draft_" + editor._signature((profile.contract, profile.key, period.key))
    retired_key = prefix + "_evidence_retired_contributions"
    app = AppTest.from_string(APP, default_timeout=30)
    # Controlled upstream removal receipt; the editor, selector and CAS storage
    # are real. This test does not claim real conversion or browser delivery.
    app.session_state[retired_key] = record_retired_contributions({}, {accepted.key: accepted}, {})
    app.run()
    assert not app.exception
    assert next(block for block in observed[-1].blocks if block.key == combined.key).asset_hashes == combined.asset_hashes
    assert next(button for button in app.button if button.label == "Generate DOCX and PDF").disabled
    next(widget for widget in app.selectbox if widget.label == "Picture to remove from this report").set_value(1).run()
    next(button for button in app.button if button.label == "Remove this imported occurrence").click().run()
    assert not app.exception
    assert next(block for block in observed[-1].blocks if block.key == combined.key).asset_hashes == (asset,)
    app.run()
    assert next(block for block in observed[-1].blocks if block.key == combined.key).asset_hashes == (asset,)
    assert app.session_state[retired_key], "The explicit choice is still pending until persistence succeeds."
    next(button for button in app.button if button.label == "Generate DOCX and PDF").click().run()
    assert not app.exception
    saved = library.load_snapshot(profile.contract, profile.key, period)
    assert saved.revision == 2
    assert next(block for block in saved.draft.blocks if block.key == combined.key).asset_hashes == (asset,)
    assert not app.session_state.filtered_state.get(retired_key)
    assert combined.asset_hashes == (asset, asset)
