"""Synthetic detailed-editor persistence; conversion and intake are controlled seams.

These tests run the real saved-report fallback and compare-and-swap save handler.
They do not represent native browser delivery or DOCX/PDF output acceptance.
"""
from dataclasses import replace
from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import contracts, monthly_report_editor as editor, monthly_report_library as library
from app import monthly_report_upload_ui as uploads
from app.monthly_report_docx import ReportPackage
from app.monthly_report_model import (
    BlockSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, SectionSpec,
)
from app.monthly_report_source_retirement import record_retired_contributions


APP = """
from app.monthly_report_editor import render_profile_workflow
from app.monthly_report_ui import _field, _move
render_profile_workflow('', 'UTC', _field, _move)
"""


def retirement_editor(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    profile = ReportProfile("Synthetic Retirement Contract", "west-retirement", "Synthetic West",
                            (Facility("west", "Synthetic West"),))
    period = ReportPeriod(2026, 10)
    ref = "synthetic-west-source:1:reviewed-r1"
    image = BytesIO()
    Image.new("RGB", (16, 16), (25, 70, 110)).save(image, format="PNG")
    data = image.getvalue()
    asset = library.asset_reference(data, "png")
    page = ResolvedBlock("water_reports", "This month", asset_hashes=(asset,),
        asset_captions=("Water sample results",), references=(ref,),
        asset_provenance=((asset, (ref,)),))
    draft = ReportDraft(profile, period, "Synthetic Reviewer", (
        SectionSpec("water", "6", "Water treatment", (BlockSpec("water_reports", "pdf_pages"),)),), (page,))
    library.save_profile(profile, expected_revision=0, actor=draft.prepared_by, confirmed=True)
    first = library.save_snapshot(draft, expected_revision=0, assets=((asset, data),), entered_editor=draft.prepared_by)
    monkeypatch.setattr(contracts, "contract_names", lambda: [profile.contract])
    monkeypatch.setattr(editor, "operator_today", lambda *a: date(2026, 11, 6))
    monkeypatch.setattr(uploads, "render_uploads", lambda *a, **kw: ((), {}, {}))
    monkeypatch.setattr(editor, "_preview", lambda *a, **kw: None)
    monkeypatch.setattr(editor, "preflight", lambda *a, **kw: ())
    observed = []
    monkeypatch.setattr(editor, "review_client_images", lambda draft, *a, **kw: observed.append(draft) or draft)
    monkeypatch.setattr(editor, "generate_report", lambda draft, **kw: ReportPackage(
        b"synthetic-conversion-seam", b"synthetic-conversion-seam", "synthetic.docx", "synthetic.pdf", draft.fingerprint))
    prefix = "report_draft_" + editor._signature((profile.contract, profile.key, period.key))
    retired_key = prefix + "_evidence_retired_contributions"
    app = AppTest.from_string(APP, default_timeout=30)
    pending = record_retired_contributions({}, {page.key: page}, {})
    app.session_state[retired_key] = pending
    app.run()
    assert not app.exception
    assert not next(b for b in observed[-1].blocks if b.key == page.key).asset_hashes
    return app, draft, page, retired_key, observed, first


def save(app):
    next(button for button in app.button if button.label == "Generate DOCX and PDF").click().run()
    assert not app.exception


def test_successful_persisted_retirement_does_not_apply_to_a_later_saved_readdition(monkeypatch, tmp_path):
    app, draft, page, key, observed, first = retirement_editor(monkeypatch, tmp_path)
    save(app)
    removed = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert removed.revision == first.revision + 1
    assert not next(b for b in removed.draft.blocks if b.key == page.key).asset_hashes
    assert not app.session_state.filtered_state.get(key), "Only durably applied removal receipts should be acknowledged."
    restored = library.save_snapshot(draft, expected_revision=removed.revision, entered_editor="Synthetic Second Reviewer")
    app.run()
    assert not app.exception
    assert next(b for b in observed[-1].blocks if b.key == page.key).asset_hashes == page.asset_hashes
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == restored


def test_failed_snapshot_save_retains_the_exact_removal_for_retry(monkeypatch, tmp_path):
    app, draft, page, key, observed, first = retirement_editor(monkeypatch, tmp_path)
    pending = app.session_state[key]
    original_save = library.save_snapshot
    def fail(*args, **kwargs):
        raise OSError("Synthetic durable write failure")
    monkeypatch.setattr(library, "save_snapshot", fail)
    save(app)
    assert app.session_state[key] == pending
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == first
    assert any("Synthetic durable write failure" in error.value for error in app.error)
    monkeypatch.setattr(library, "save_snapshot", original_save)
    save(app)
    saved = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert saved.revision == first.revision + 1
    assert not next(b for b in saved.draft.blocks if b.key == page.key).asset_hashes
    assert not app.session_state.filtered_state.get(key)


def test_staging_a_replacement_does_not_acknowledge_an_unsaved_removal():
    old = ResolvedBlock("water_reports", "This month", asset_hashes=("old.png",), references=("origin:1:r1",))
    new = replace(old, asset_hashes=("new.png",), references=("new-origin:1:r1",))
    pending = record_retired_contributions({}, {old.key: old}, {})
    changed = record_retired_contributions(pending, {}, {new.key: new})
    assert changed == pending, "Prepared replacement data is not a durable-save acknowledgement."


def test_acknowledgement_is_bound_to_exact_report_revision_and_captured_receipts():
    from app.monthly_report_source_retirement import acknowledge_retired_contributions
    profile = ReportProfile("Synthetic Guard Contract", "north", "Synthetic North", (Facility("north", "North"),))
    first = ResolvedBlock("water_reports", "This month", asset_hashes=("old.png",),
                          references=("old-source:1:r1",), asset_provenance=(("old.png", ("old-source:1:r1",)),))
    newer = replace(first, asset_hashes=("new.png",), references=("new-source:1:r1",))
    applied = {first.key: (first,)}
    current = {first.key: (first, newer)}
    empty = replace(first, asset_hashes=(), asset_captions=(), asset_provenance=(), references=())
    draft = ReportDraft(profile, ReportPeriod(2026, 10), "Synthetic Reviewer", (), (empty,))
    saved = SimpleNamespace(revision=5, draft=draft)
    assert acknowledge_retired_contributions(current, applied, saved, draft, 4) == {first.key: (newer,)}
    assert acknowledge_retired_contributions(current, applied, saved, draft, 3) == current
    foreign = replace(draft, period=ReportPeriod(2026, 11))
    assert acknowledge_retired_contributions(current, applied, saved, foreign, 4) == current
    retained = replace(draft, blocks=(replace(first, source="Omit"),))
    assert acknowledge_retired_contributions(current, applied, SimpleNamespace(revision=5, draft=retained), retained, 4) == current
    still_present = replace(draft, blocks=(first,))
    assert acknowledge_retired_contributions(current, applied, SimpleNamespace(revision=5, draft=still_present), still_present, 4) == current
