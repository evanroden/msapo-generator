"""Damaged shared procedure metadata cannot strand independent report work."""
from dataclasses import replace
from datetime import date
from io import BytesIO
from zipfile import ZipFile

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided, monthly_report_library as library
from app import monthly_report_workflow_standards as workflows
from app.contracts import RRH_CONTRACT
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ResolvedBlock, default_sections, profile_sections,
    synthetic_profiles,
)
from test_monthly_report_authentic_legacy_adoption import seeded
from test_monthly_report_contract_workflows import image_block, report
from test_monthly_report_contract_workflow_ui import start, button
from test_monthly_report_contract_workflow_outputs import selected_contract
from test_monthly_report_workflow_standards import publish
from test_monthly_report_ui import ROOT, choose_report


FIELDS = ("origin_contract", "origin_profile", "origin_fingerprint", "saved_at")
BAD_TEXT = [
    pytest.param(123, id="integer"),
    pytest.param(True, id="boolean"),
    pytest.param(["retained text"], id="list"),
    pytest.param({"value": "retained text"}, id="object"),
    pytest.param("", id="empty"),
    pytest.param(None, id="null"),
]
ACTOR = "Synthetic Procedure Editor"
OTHER_CONTRACT = "Other Synthetic Contract"


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")


def files(root=None):
    root = library._root() if root is None else root
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and path.name != ".write-lock"}


def stored(scope):
    if scope == "legacy":
        draft, _ = seeded()
        return draft, workflows._path() / "manifest.json"
    draft, _, _, _ = publish()
    return draft, workflows._path(draft.profile.contract) / "manifest.json"


def damage(path, field, value, key="business_hours_workflow"):
    manifest = library._read(path)
    item = next(item for item in manifest["workflows"] if item["key"] == key)
    item[field] = value
    path.write_bytes(library._json(manifest))


def activity(app):
    return next(value for value in app.text_area if value.label == "Activity summary")


def open_monthly(profile):
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, profile.facilities[0].title)
    next(value for value in app.text_input if value.label == "Prepared by").set_value(ACTOR).run()
    return app


@pytest.mark.parametrize("scope", ["contract", "legacy"])
@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("invalid", BAD_TEXT)
def test_required_text_metadata_is_rejected_without_rewriting(scope, field, invalid):
    draft, path = stored(scope)
    damage(path, field, invalid)
    before = files()
    with pytest.raises(library.LibraryError, match="could not be read"):
        workflows.load_standards(draft.profile.contract if scope == "contract" else None)
    assert files() == before


@pytest.mark.parametrize("scope", ["contract", "legacy"])
def test_nonempty_legacy_text_keeps_its_existing_format(scope):
    draft, path = stored(scope)
    contract = draft.profile.contract if scope == "contract" else None
    original = workflows.load_standards(contract)
    assert isinstance(original.workflows[0].origin_fingerprint, str)
    manifest = library._read(path)
    manifest["workflows"][0].update(
        origin_profile="historic-profile", origin_fingerprint="opaque historical fingerprint",
        saved_at="2026-01-01",
    )
    path.write_bytes(library._json(manifest))
    before = files()
    loaded = workflows.load_standards(contract)
    assert loaded.workflows[0] == replace(original.workflows[0],
        origin_profile="historic-profile", origin_fingerprint="opaque historical fingerprint",
        saved_at="2026-01-01")
    assert files() == before


@pytest.mark.parametrize("invalid,key", [
    pytest.param(123, "business_hours_workflow", id="integer-business-hours"),
    pytest.param(True, "after_hours_workflow", id="boolean-after-hours"),
    pytest.param(["2026-10-01"], "business_hours_workflow", id="list-business-hours"),
    pytest.param({"date": "2026-10-01"}, "after_hours_workflow", id="object-after-hours"),
])
def test_actual_monthly_report_remains_editable_with_damaged_shared_metadata(
        monkeypatch, invalid, key):
    # Only section PDF previews are stubbed. This is the actual Monthly entry
    # point; the independent output test below assembles real DOCX bytes.
    monkeypatch.setattr("app.web_ui.device_token", lambda cookies: "")
    monkeypatch.setattr(guided, "operator_today", lambda tz: date(2026, 10, 7))
    monkeypatch.setattr("app.monthly_report_section_preview_ui.render_section_preview",
                        lambda *args, **kwargs: None)
    publish(RRH_CONTRACT)
    publish(RRH_CONTRACT, "blue", key="after_hours_workflow", revision=1)
    publish(OTHER_CONTRACT, "green")
    profile = replace(synthetic_profiles()[0], contract=RRH_CONTRACT,
        key="synthetic-procedure", template="enfra_builtin:monthly_review_v1",
        excluded_sections=tuple(section.key for section in default_sections()
                                if section.key not in {"activity", "organization"}))
    library.save_profile(profile, expected_revision=0, actor=ACTOR, confirmed=True)
    own, assets = image_block(key, "red")
    other_key = next(value for value in workflows.WORKFLOW_KEYS if value != key)
    adjacent, adjacent_assets = image_block(other_key, "yellow")
    assets.update(adjacent_assets)
    draft = ReportDraft(profile, ReportPeriod(2026, 9), ACTOR, profile_sections(profile),
        (ResolvedBlock("activity_summary", "This month", text="Synthetic retained monthly work."),
         own, adjacent))
    saved = library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()))
    profile_before = files(library._profile_path(profile.contract, profile.key))
    healthy_defaults = files(workflows._path())
    path = workflows._path(RRH_CONTRACT) / "manifest.json"
    original = path.read_bytes()
    edit_label = ("Edit business-hours outage procedure" if key == "business_hours_workflow"
                  else "Edit after-hours outage procedure")
    app = open_monthly(profile)
    button(app, edit_label).click().run()
    assert not app.exception
    assert button(app, "Use contract default in this report")
    assert button(app, "Save shared version")

    damage(path, "saved_at", invalid, key)
    damaged_defaults = files(workflows._path())
    app.run()
    assert not app.exception
    assert any("procedures" in warning.value for warning in app.warning)
    assert not any(b.label in {"Use contract default in this report", "Replace contract default"}
                   for b in app.button)
    assert activity(app).value == "Synthetic retained monthly work."
    activity(app).set_value("Synthetic edit while shared procedures are unavailable.").run()
    button(app, "Save shared version").click().run()
    assert not app.exception
    updated = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert updated.revision == saved.revision + 1
    assert next(b for b in updated.draft.blocks if b.key == key).asset_hashes == own.asset_hashes
    assert next(b for b in updated.draft.blocks if b.key == other_key).asset_hashes == adjacent.asset_hashes
    assert next(b.text for b in updated.draft.blocks if b.key == "activity_summary") == (
        "Synthetic edit while shared procedures are unavailable.")
    assert library.load_snapshot_version(profile.contract, profile.key, draft.period, saved.revision) == saved
    assert files(workflows._path()) == damaged_defaults
    assert files(library._profile_path(profile.contract, profile.key)) == profile_before

    reopened = open_monthly(profile)
    button(reopened, edit_label).click().run()
    reopened.run()
    assert not reopened.exception
    assert activity(reopened).value == "Synthetic edit while shared procedures are unavailable."
    assert button(reopened, "Save shared version")
    assert files(workflows._path()) == damaged_defaults
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == updated

    # Repair of the temporary fixture restores the ordinary explicit action.
    # Applying it updates this report only and must not rewrite standing data.
    path.write_bytes(original)
    app.run()
    button(app, "Use contract default in this report").click().run()
    button(app, "Save shared version").click().run()
    assert not app.exception
    adopted = library.load_snapshot(profile.contract, profile.key, draft.period)
    expected = next(item.block for item in workflows.load_standards(RRH_CONTRACT).workflows if item.key == key)
    assert next(b for b in adopted.draft.blocks if b.key == key).asset_hashes == expected.asset_hashes
    assert next(b for b in adopted.draft.blocks if b.key == other_key).asset_hashes == adjacent.asset_hashes
    assert next(b.text for b in adopted.draft.blocks if b.key == "activity_summary") == (
        "Synthetic edit while shared procedures are unavailable.")
    assert library.load_snapshot_version(profile.contract, profile.key, draft.period, updated.revision) == updated
    assert files(workflows._path()) == healthy_defaults


@pytest.mark.parametrize("operation,field", [
    ("apply", "saved_at"), ("use", "saved_at"), ("save", "saved_at"),
    *(("adopt", field) for field in FIELDS),
])
def test_shared_actions_refuse_damaged_metadata_without_partial_changes(operation, field):
    publish(OTHER_CONTRACT, "green")
    draft, path = stored("legacy" if operation == "adopt" else "contract")
    damage(path, field, 123)
    before = files()
    caller_assets = {}
    with pytest.raises(library.LibraryError):
        if operation == "apply":
            workflows.apply_defaults(report(), caller_assets)
        elif operation == "use":
            block = draft.blocks[0]
            workflows.use_standard(draft, block, caller_assets, expected_revision=1,
                                   expected_fingerprint=block.fingerprint)
        elif operation == "save":
            block, incoming = image_block(color="red")
            changed = replace(draft, blocks=(block,))
            workflows.save_standard(changed, block, incoming, expected_revision=1,
                                    expected_fingerprint=block.fingerprint, confirmed=True)
        else:
            # Use the public review/adoption sequence, including the real
            # historical record format and its current content-bound receipt.
            item = workflows.legacy_candidate(draft.profile.contract, "business_hours_workflow")
            receipt = workflows.legacy_review_receipt(item)
            workflows.adopt_legacy(draft, item.key, expected_revision=0,
                expected_legacy_fingerprint=item.block.fingerprint,
                expected_legacy_receipt=receipt, confirmed=True)
    assert caller_assets == {} and files() == before


@pytest.mark.parametrize("field", FIELDS)
def test_legacy_editor_contains_bad_metadata_and_can_retry_after_recovery(field):
    draft, path = stored("legacy")
    original = path.read_bytes()
    damage(path, field, 123)
    before = files()
    app = start(draft)
    assert not app.exception
    assert any("Legacy procedure is unavailable" in warning.value for warning in app.warning)
    assert not any(b.label in {"Preview legacy procedure", "Adopt legacy procedure for this contract"}
                   for b in app.button)
    assert app.session_state["draft"] == draft and files() == before
    app.run()
    assert not app.exception and files() == before
    path.write_bytes(original)
    app.run()
    button(app, "Preview legacy procedure").click().run()
    button(app, "Adopt legacy procedure for this contract").click().run()
    assert not app.exception
    assert workflows.load_standards(draft.profile.contract).revision == 1
    assert app.session_state["draft"] == draft
    assert path.read_bytes() == original
    for name, raw in before.items():
        if name != str(path.relative_to(library._root())):
            assert files()[name] == raw


def test_saved_procedure_word_output_uses_its_own_pixels_despite_bad_shared_metadata():
    draft, assets = selected_contract("Contract A")
    saved = library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()))
    load_asset = lambda ref: library.read_asset(draft.profile.contract, draft.profile.key, ref)
    original = assemble_docx(saved.draft, asset_loader=load_asset)
    path = workflows._path("Contract A") / "manifest.json"
    damage(path, "saved_at", {"date": "2026-10-01"})
    before = files()
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    output = assemble_docx(reopened.draft, asset_loader=load_asset)
    with ZipFile(BytesIO(original)) as left, ZipFile(BytesIO(output)) as right:
        assert {name: left.read(name) for name in left.namelist()} == {
            name: right.read(name) for name in right.namelist()}
        assert b"Synthetic contacts retained." in right.read("word/document.xml")
    assert reopened == saved and files() == before
    own = library._profile_path(draft.profile.contract, draft.profile.key) / "assets" / next(iter(assets))
    missing = own.with_suffix(".temporarily-missing")
    own.rename(missing)
    try:
        with pytest.raises(library.LibraryError, match="unavailable"):
            assemble_docx(reopened.draft, asset_loader=load_asset)
    finally:
        missing.rename(own)
    assert files() == before
