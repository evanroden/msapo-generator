"""Native corrections retain scoped artwork and unavailable source records."""
from dataclasses import replace
from datetime import date

from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active, monthly_report_guided as guided
from app import monthly_report_library as library, monthly_report_sources as sources, web_ui
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import ReportPeriod, ResolvedBlock
from app.monthly_report_source_details import correct_source_details
from app.monthly_report_source_scope import CONTRACT_ARTWORK, included_scope_valid
from test_monthly_report_ui import ROOT, choose_report, monthly
from test_monthly_report_upload_ui import current_draft


def saved_source(monkeypatch, tmp_path, *, artwork=False, unavailable=False, operational=False):
    monthly(monkeypatch, tmp_path)
    token = "d" * 32
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: token)
    profile = library.list_profiles(RRH_CONTRACT)[0]
    raw = b"Synthetic source content; original bytes remain unchanged."
    content, _ = sources.ingest(profile, "synthetic-source.txt", raw)
    source = content.source
    assets = ()
    if artwork:
        source = correct_source_details(source, profile, date(2026, 9, 16), CONTRACT_ARTWORK,
                                        artwork_keys=("client_logo",))
        from PIL import Image
        from io import BytesIO
        image = BytesIO(); Image.new("RGB", (10, 10), "blue").save(image, "PNG")
        reference = library.asset_reference(image.getvalue(), "png")
        assets = ((reference, image.getvalue()),)
        block = ResolvedBlock("client_logo", "This month", asset_hashes=(reference,),
                              references=(sources.source_reference(source, 1),))
    else:
        block = ResolvedBlock("activity_summary", "This month", text="Independent approved note.",
                              references=(sources.source_reference(source, 1),))
    draft = guided._initial_draft(library.load_profile(profile.contract, profile.key), ReportPeriod(2026, 9), "Synthetic Editor")
    draft = replace(draft, sources=(source,), blocks=tuple(b for b in draft.blocks if b.key != block.key) + (block,))
    if operational:
        note = ResolvedBlock("activity_summary", "This month", text="Source-linked operating claim.",
                             references=(sources.source_reference(source, 1),))
        draft = replace(draft, blocks=tuple(b for b in draft.blocks if b.key != note.key) + (note,))
    library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor", assets=assets)
    if unavailable:
        sources._path(profile, source.sha256, source.suffix).unlink()
    return draft, source, raw, token


def reopen(profile):
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, profile.facilities[0].title)
    assert not app.exception
    return app


def test_existing_contract_artwork_can_correct_date_in_generic_manager(monkeypatch, tmp_path):
    original, source, raw, token = saved_source(monkeypatch, tmp_path, artwork=True)
    assert included_scope_valid(original, source)
    app = reopen(original.profile)
    next(b for b in app.button if b.label == "Manage source files").click().run()
    assert sum(w.label == "Source date" for w in app.date_input) == 1
    next(w for w in app.date_input if w.label == "Source date").set_value(date(2026, 9, 18))
    next(b for b in app.button if b.label == "Use these source details").click().run()
    assert not app.exception
    corrected = current_draft(app)
    assert corrected.sources[0].service_date == "2026-09-18"
    assert included_scope_valid(corrected, corrected.sources[0])
    assert sources.source_bytes(original.profile, corrected.sources[0]) == raw
    assert active.load(token, original.profile.contract, original.profile.key, original.period).draft == corrected
    assert library.load_snapshot(original.profile.contract, original.profile.key, original.period).draft == original


def test_missing_original_metadata_correction_survives_retention_and_reload(monkeypatch, tmp_path):
    original, source, raw, token = saved_source(monkeypatch, tmp_path, unavailable=True)
    app = reopen(original.profile)
    next(b for b in app.button if b.label == "Manage source files").click().run()
    next(w for w in app.date_input if w.label == "Source date").set_value(date(2026, 9, 18))
    next(w for w in app.selectbox if w.label == "Source facility").set_value(original.profile.facilities[0].key)
    next(b for b in app.button if b.label == "Use these source details").click().run()
    assert not app.exception
    corrected = current_draft(app)
    assert corrected.sources[0].service_date == "2026-09-18"
    assert corrected.sources[0].facility == original.profile.facilities[0].key
    assert corrected.sources[0].id == source.id and corrected.sources[0].sha256 == source.sha256
    assert next(b for b in app.button if b.label == "Create Word and PDF").disabled
    assert any("Could not read saved file" in w.value for w in app.warning)
    pending = next(value for key, value in app.session_state.filtered_state.items() if key.endswith("_unavailable_sources"))
    assert pending == corrected.sources
    app.run()
    assert current_draft(app) == corrected
    assert active.load(token, original.profile.contract, original.profile.key, original.period).draft == corrected
    restored = reopen(original.profile)
    assert current_draft(restored) == corrected
    assert next(b for b in restored.button if b.label == "Create Word and PDF").disabled
    assert library.load_snapshot(original.profile.contract, original.profile.key, original.period).draft == original
    assert not sources._path(original.profile, source.sha256, source.suffix).exists()


def test_shared_artwork_choice_cannot_approve_a_source_also_used_for_activity(monkeypatch, tmp_path):
    original, source, raw, _ = saved_source(monkeypatch, tmp_path, artwork=True, operational=True)
    assert not included_scope_valid(original, source)
    app = reopen(original.profile)
    next(b for b in app.button if b.label == "Manage source files").click().run()
    next(w for w in app.date_input if w.label == "Source date").set_value(date(2026, 9, 18))
    next(b for b in app.button if b.label == "Use these source details").click().run()
    assert not app.exception
    assert current_draft(app).sources == original.sources
    assert any("shared report artwork" in item.value for item in app.error)
    assert next(b for b in app.button if b.label == "Create Word and PDF").disabled
    assert sources.source_bytes(original.profile, source) == raw
