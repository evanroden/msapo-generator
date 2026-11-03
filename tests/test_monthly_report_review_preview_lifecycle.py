"""Successful whole-copy actions retire only their temporary Review preview."""
from dataclasses import replace
from types import SimpleNamespace

import pymupdf as fitz
import pytest

from app import monthly_report_active_work as active, monthly_report_library as library
from app import monthly_report_review_preview_ui as review_ui, monthly_report_sources as sources
from app.monthly_report_preview import ReportPreview
from app.monthly_report_preview_store import PreviewStore
from app.monthly_report_source_view_runtime import preview_fingerprint
from test_monthly_report_active_recovery_ui import TOKEN, _visit
from test_monthly_report_identity_history_ui import widget
from test_monthly_report_ui import monthly


def _preview(draft, loader):
    # Exercise actual PDF files and raster retention without a converter job.
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Synthetic Review lifecycle")
        return ReportPreview(pdf.tobytes(), len(pdf), preview_fingerprint(draft), draft.period.label)


def _draft(app):
    return next(value for key, value in app.session_state.filtered_state.items()
                if key.startswith("report_guided_") and key.endswith("_draft")
                and hasattr(value, "blocks"))


def _records(*roots):
    return {path: path.read_bytes() for root in roots for path in root.rglob("*")
            if path.is_file() and not path.name.endswith(".lock")}


@pytest.fixture
def ready(monkeypatch, tmp_path):
    _visit(monkeypatch)
    store = PreviewStore()
    monkeypatch.setattr(review_ui, "STORE", store)
    monkeypatch.setattr(review_ui, "preview_report", _preview)
    try:
        app = monthly(monkeypatch, tmp_path)
        widget(app, "text_input", "Prepared by").set_value("Synthetic lifecycle editor").run()
        for text in ("First saved wording.", "Second saved wording."):
            widget(app, "text_area", "Activity summary").set_value(text).run()
            widget(app, "button", "Save shared version").click().run()
        widget(app, "text_area", "Activity summary").set_value("Unfinished local wording.").run()
        assert not app.exception
        draft = _draft(app)
        raw = b"Synthetic retained source original; inspection follow-up remains pending."
        original, _ = sources.ingest(draft.profile, "synthetic-retained-original.txt", raw)
        identity = draft.profile.contract, draft.profile.key, draft.period
        folders = (library._profile_path(*identity[:2]), library._profile_path(*identity[:2], snapshots=True))
        durable = _records(*folders)
        widget(app, "button", "Preview current draft").click().run()
        assert not app.exception
        state_key = next(key for key in app.session_state.filtered_state if key.endswith("_review_draft_preview"))
        prefix = state_key.removesuffix("_review_draft_preview")
        state = app.session_state[state_key]
        owner_key = prefix + "_review_preview_owner"
        owner = app.session_state[owner_key]
        old_path = store._files[state["ticket"].key].path
        other = store.put("independent-visitor", _preview(draft, None))
        other_pages = store.pages("independent-visitor", other, (0,))
        other_path = store._files[other.key].path
        assert store.stats()["pdf_entries"] == store.stats()["raster_entries"] == 2
        yield SimpleNamespace(
            app=app, store=store, draft=draft, identity=identity, folders=folders, durable=durable,
            source=original.source, raw=raw, state_key=state_key, owner_key=owner_key,
            state=state, owner=owner, old_path=old_path, other=other,
            other_path=other_path, other_raw=other_path.read_bytes(), other_pages=other_pages,
        )
    finally:
        store.close()


def _unchanged_durable_and_other(ready):
    assert _records(*ready.folders) == ready.durable
    assert sources.source_bytes(ready.draft.profile, ready.source) == ready.raw
    assert ready.store.available("independent-visitor", ready.other)
    assert ready.other_path.read_bytes() == ready.other_raw
    assert ready.store.pages("independent-visitor", ready.other, (0,)) == ready.other_pages


def _retired_then_rebuilt(ready):
    assert not ready.store.available(ready.owner, ready.state["ticket"])
    assert not ready.old_path.exists()
    assert not any(key[0] == ready.state["ticket"].key for key in ready.store._rasters)
    assert ready.state_key not in ready.app.session_state.filtered_state
    assert ready.app.session_state[ready.owner_key] != ready.owner
    assert ready.store.stats()["pdf_entries"] == ready.store.stats()["raster_entries"] == 1
    _unchanged_durable_and_other(ready)
    widget(ready.app, "button", "Preview current draft").click().run()
    assert not ready.app.exception
    assert ready.app.session_state[ready.state_key]["ticket"] != ready.state["ticket"]
    assert ready.store.stats()["pdf_entries"] == ready.store.stats()["raster_entries"] == 2
    _unchanged_durable_and_other(ready)


def _retained(ready):
    assert ready.app.session_state[ready.state_key] == ready.state
    assert ready.app.session_state[ready.owner_key] == ready.owner
    assert ready.store.available(ready.owner, ready.state["ticket"])
    assert ready.old_path.exists()
    assert ready.store.stats()["pdf_entries"] == ready.store.stats()["raster_entries"] == 2
    assert _draft(ready.app) == ready.draft
    _unchanged_durable_and_other(ready)


def test_confirmed_start_over_retires_review_pdf_and_raster_before_losing_owner(ready):
    widget(ready.app, "checkbox", "Discard my unfinished changes for this report").check().run()
    widget(ready.app, "button", "Start this report over").click().run()
    assert not ready.app.exception
    assert widget(ready.app, "text_area", "Activity summary").value == "Second saved wording."
    _retired_then_rebuilt(ready)


@pytest.mark.parametrize("refusal", ("stale-revision", "unavailable-storage"))
def test_refused_reset_keeps_current_review_ticket_and_edits(ready, monkeypatch, refusal):
    widget(ready.app, "checkbox", "Discard my unfinished changes for this report").check().run()
    current = active.load(TOKEN, *ready.identity)
    if refusal == "stale-revision":
        latest = active.save(TOKEN, replace(current.draft, prepared_by="Synthetic later tab"),
            expected_revision=current.revision, expected_generation=current.generation,
            base_snapshot_revision=current.base_snapshot_revision, assets=dict(current.assets))
    else:
        latest = current

        def unavailable(*args, **kwargs):
            raise OSError("Synthetic recovery storage unavailable")

        monkeypatch.setattr(active, "discard", unavailable)
    widget(ready.app, "button", "Start this report over").click().run()
    assert not ready.app.exception
    assert any("could not be discarded" in item.value for item in ready.app.error)
    assert active.load(TOKEN, *ready.identity) == latest
    _retained(ready)


@pytest.mark.parametrize("changed_during_choice", (False, True))
def test_native_use_newer_copy_retires_preview_only_after_success(ready, monkeypatch, changed_during_choice):
    current = active.load(TOKEN, *ready.identity)
    newer_draft = replace(current.draft, blocks=tuple(
        replace(block, text="Synthetic newer browser wording.") if block.key == "activity_summary" else block
        for block in current.draft.blocks))
    newer = active.save(TOKEN, newer_draft, expected_revision=current.revision,
        expected_generation=current.generation, base_snapshot_revision=current.base_snapshot_revision,
        assets=dict(current.assets))
    ready.app.run()
    widget(ready.app, "button", "Compare browser copies").click().run()
    assert not ready.app.exception
    _retained(ready)
    load = active.load
    intervening = []
    if changed_during_choice:
        calls = []

        def race(*args, **kwargs):
            calls.append(None)
            if len(calls) == 2:
                intervening.append(active.save(TOKEN, replace(newer.draft, prepared_by="Synthetic intervening editor"),
                    expected_revision=newer.revision, expected_generation=newer.generation,
                    base_snapshot_revision=newer.base_snapshot_revision, assets=dict(newer.assets)))
            return load(*args, **kwargs)

        monkeypatch.setattr(active, "load", race)
    widget(ready.app, "button", "Use the newer browser copy").click().run()
    assert not ready.app.exception
    if changed_during_choice:
        assert len(intervening) == 1
        assert any("copy changed again" in item.value for item in ready.app.error)
        assert load(TOKEN, *ready.identity) == intervening[0]
        _retained(ready)
    else:
        assert widget(ready.app, "text_area", "Activity summary").value == "Synthetic newer browser wording."
        assert load(TOKEN, *ready.identity) == newer
        _retired_then_rebuilt(ready)
