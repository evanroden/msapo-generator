"""Fresh optional Water slots and retained omissions have distinct UI paths."""
from dataclasses import replace
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_upload_ui as ui
from app.monthly_report_model import ResolvedBlock, ReportTable, ReportDraft
from test_monthly_report_section_uploads import APP, button
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_ui import monthly
from test_monthly_report_water_auto_include import _water_app


def current_draft(app):
    return next(value for key, value in app.session_state.filtered_state.items()
                if key.startswith("report_guided_") and key.endswith("_draft")
                and isinstance(value, ReportDraft))


def test_normal_fresh_guided_water_placeholder_accepts_only_explicit_reviewed_pages(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    before = current_draft(app)
    empty = next(block for block in before.blocks if block.key == "water_reports")
    assert empty == ResolvedBlock("water_reports", "Omit")
    upload = BytesIO(pdf_bytes(2)); upload.name = "first-water.pdf"
    uploader = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *a, **kw:
                        [upload] if label == "Water-treatment files" else uploader(label, *a, **kw))
    app.run()
    assert not app.exception
    assert not button(app, "Include page").disabled
    assert next(block for block in current_draft(app).blocks if block.key == empty.key) == empty
    button(app, "Include page").click().run()
    assert not app.exception
    assert next(block for block in current_draft(app).blocks if block.key == empty.key) == empty
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 2
    button(app, "Exclude page").click().run()
    assert not app.exception
    after = current_draft(app)
    water = next(block for block in after.blocks if block.key == empty.key)
    assert water.source != "Omit" and len(water.asset_hashes) == 1
    source = next(s for s in after.sources if s.filename == upload.name)
    assert source.selected_pages == (1,) and 2 in dict(source.client_page_exclusions)
    assert [block for block in after.blocks if block.key != empty.key] == [
        block for block in before.blocks if block.key != empty.key]
    app.run()
    assert next(block for block in current_draft(app).blocks if block.key == empty.key) == water


def assetless_app(monkeypatch, tmp_path, block):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(APP, default_timeout=20)
    app.session_state["test_blocks"] = {block.key: block,
        "activity_summary": ResolvedBlock("activity_summary", "This month", text="Unrelated wording")}
    app.run()
    next(w for w in app.radio if w.label == "Section").set_value("water_reports").run()
    assert not app.exception
    assert app.session_state["test_sources"] == ()
    return app


@pytest.mark.parametrize("block", [
    ResolvedBlock("water_reports", "Omit", text="Retained manual finding"),
    ResolvedBlock("water_reports", "Omit", rows=(("0",),)),
    ResolvedBlock("water_reports", "Omit", extra_tables=(ReportTable(("Result",), (("NR",),)),)),
    ResolvedBlock("water_reports", "Omit", extra_tables=(ReportTable(("Result",), (("Approximately 5 gpm",),)),)),
    ResolvedBlock("water_reports", "Omit", asset_captions=("Retained caption metadata",)),
    ResolvedBlock("water_reports", "Omit", extra_tables=(ReportTable(("Custom retained column",), ()),)),
])
def test_actual_source_empty_return_keeps_explicit_assetless_section_recovery(monkeypatch, tmp_path, block):
    app = assetless_app(monkeypatch, tmp_path, block)
    assert app.session_state["test_blocks"][block.key] == block
    include = button(app, "Include Water treatment section in this report")
    assert not include.disabled
    include.click().run()
    assert not app.exception
    assert app.session_state["test_blocks"][block.key] == replace(
        block, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint="")
    assert app.session_state["test_sources"] == ()
    assert app.session_state["test_additions"] == {}
    assert app.session_state["test_blocks"]["activity_summary"].text == "Unrelated wording"


@pytest.mark.parametrize("block", [
    ResolvedBlock("water_reports", "Omit", text="0"),
    ResolvedBlock("water_reports", "Omit", rows=(("NR",),)),
    ResolvedBlock("water_reports", "Omit", extra_tables=(ReportTable(("Result",), (("5 gpm - estimated",),)),)),
    ResolvedBlock("water_reports", "Omit", asset_captions=("Retained caption",)),
    ResolvedBlock("water_reports", "Omit", extra_tables=(ReportTable(("Retained field",), ()),)),
])
def test_new_file_cannot_replace_explicit_retained_omission(monkeypatch, tmp_path, block):
    app = _water_app(monkeypatch, tmp_path, pdf_bytes(1))
    app.session_state["test_blocks"][block.key] = block
    source = app.session_state["test_sources"][0]
    request_key = "synthetic_evidence_section_water_reports_auto_include"
    app.session_state[request_key] = {"source_id": source.id, "fingerprint": source.fingerprint, "pages": (1,)}
    app.run()
    assert not app.exception
    assert button(app, "Include page").disabled
    assert app.session_state["test_blocks"][block.key] == block
    assert app.session_state["test_additions"] == {}
    assert request_key not in app.session_state.filtered_state
    assert "test_apply_count" not in app.session_state.filtered_state


@pytest.mark.parametrize("changed", ["block", "incarnation", "qa-generation"])
def test_assetless_recovery_rejects_stale_choice_in_actual_empty_source_path(monkeypatch, tmp_path, changed):
    from app.monthly_report_editor import _signature
    from app.monthly_report_page_controls import omitted_section_request
    block = ResolvedBlock("water_reports", "Omit", text="Retained writer correction")
    app = assetless_app(monkeypatch, tmp_path, block)
    scope = _signature(("synthetic", app.session_state["synthetic_rich_text_epoch"], ""))
    request = omitted_section_request(block, (), scope=scope)
    if changed == "block":
        block = replace(block, text="A newer retained correction")
        app.session_state["test_blocks"][block.key] = block
    elif changed == "incarnation":
        app.session_state["synthetic_rich_text_epoch"] = "new-reset-incarnation"
    else:
        app.session_state["_monthly_qa_generation"] = "new-qa-generation"
    app.session_state["synthetic_evidence_section_water_reports_reinclude_omitted"] = request
    app.run()
    assert not app.exception
    assert app.session_state["test_blocks"][block.key] == block
    assert any("changed after" in warning.value for warning in app.warning)
    assert app.session_state["test_additions"] == {}


def test_missing_source_artwork_keeps_omission_and_visible_blocked_recovery(monkeypatch, tmp_path):
    block = ResolvedBlock("water_reports", "Omit", asset_hashes=("missing.png",),
                          asset_captions=("Retained page caption",), references=("missing-source:1:fingerprint",))
    app = assetless_app(monkeypatch, tmp_path, block)
    assert button(app, "Include Water treatment section in this report").disabled
    assert app.session_state["test_blocks"][block.key] == block
    assert any("Review every retained page" in caption.value for caption in app.caption)


def test_restoring_native_wording_does_not_waive_export_price_checks(monkeypatch, tmp_path):
    from app.monthly_report_checks import preflight
    from app.monthly_report_model import ReportPeriod, default_sections, synthetic_profiles
    block = ResolvedBlock("water_reports", "Omit", text="Retained service amount $250")
    app = assetless_app(monkeypatch, tmp_path, block)
    button(app, "Include Water treatment section in this report").click().run()
    actual = app.session_state["test_blocks"][block.key]
    # The compact synthetic_draft uses demo_water, not the production slot.
    # Exercise the real Water section/spec so its normal preflight is eligible.
    report = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), "Writer",
                         default_sections(), (actual,))
    assert any(check.code == "pricing" and check.blocking for check in preflight(report))
