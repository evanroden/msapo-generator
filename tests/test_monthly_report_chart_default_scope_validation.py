"""Damaged shared-chart scopes must never become contract-wide defaults."""

from dataclasses import replace
from datetime import date
from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided
from app import monthly_report_library as library
from app import monthly_report_org_chart_defaults as charts
from app.contracts import RRH_CONTRACT
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ResolvedBlock, default_sections,
    profile_sections, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft
from app.monthly_report_ui_text import literal
from test_monthly_report_org_chart_defaults import (
    chart, fresh, picture, publish, scopes, with_chart,
)
from test_monthly_report_org_chart_defaults_ui import button, start
from test_monthly_report_ui import ROOT, choose_report


UNREADABLE = "Saved chart defaults could not be read. Originals were retained."
FALSY_SCOPES = [
    pytest.param(None, id="null"),
    pytest.param(False, id="false"),
    pytest.param(0, id="integer-zero"),
    pytest.param(0.0, id="float-zero"),
]


def stored_files(root):
    # Real Linux locks remain active; only their bookkeeping byte is excluded.
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != ".write-lock"
    }


def damage_site_scope(profile, value):
    path = charts._path(profile.contract) / "manifest.json"
    original = path.read_bytes()
    data = json.loads(original)
    assert len(data["charts"]) == 1
    assert data["charts"][0]["site_key"] == profile.facilities[0].key
    data["charts"][0]["site_key"] = value
    path.write_bytes(library._json(data))
    return path, original


def blank_chart(profile):
    return with_chart(fresh(profile), ResolvedBlock("org_chart", "This month"))


def decoded_pixels(raw):
    with Image.open(BytesIO(raw)) as image:
        return image.size, image.convert("RGB").tobytes()


def docx_pixels(draft, assets):
    # Exercise the final public review gate, without an acknowledgment override.
    output = assemble_docx(draft, asset_loader=assets.__getitem__)
    with ZipFile(BytesIO(output)) as package:
        return [
            decoded_pixels(package.read(name))
            for name in package.namelist() if name.startswith("word/media/")
        ]


@pytest.mark.parametrize("bad_scope", FALSY_SCOPES)
@pytest.mark.parametrize("operation", ["load", "apply", "initial", "use", "publish"])
def test_falsy_nonstring_scope_is_refused_at_public_boundaries(scopes, bad_scope, operation):
    north, south, other, _ = scopes
    empty = blank_chart(south)
    initial_state = library.load_profile(south.contract, south.key)
    own, assets = picture("blue")
    own = approve_all_assets(replace(own, text="Synthetic South report-only note."))
    active = with_chart(empty, own)
    publish(north, scope="site")
    _, independent, _ = publish(other, "green")
    other_draft = blank_chart(other)
    damage_site_scope(north, bad_scope)
    original_files = stored_files(library._root())
    original_assets = dict(assets)
    original_fingerprint = active.fingerprint
    assert charts.eligible(own)

    with pytest.raises(library.LibraryError) as refused:
        if operation == "load":
            charts.load_defaults(north.contract)
        elif operation == "apply":
            charts.apply_defaults(empty, assets)
        elif operation == "initial":
            guided._initial_draft(initial_state, empty.period, empty.prepared_by, assets=assets)
        elif operation == "use":
            charts.use_default(active, own, assets, expected_revision=1,
                               expected_fingerprint=own.fingerprint)
        else:
            charts.save_default(active, own, assets, scope="contract", expected_revision=1,
                                expected_fingerprint=own.fingerprint, confirmed=True)

    assert str(refused.value) == UNREADABLE
    assert active.fingerprint == original_fingerprint
    assert assets == original_assets
    assert chart(charts.apply_defaults(other_draft, {})).asset_hashes == independent.asset_hashes
    assert stored_files(library._root()) == original_files


@pytest.mark.parametrize("bad_scope", [
    pytest.param(True, id="true"),
    pytest.param(1, id="positive-number"),
    pytest.param([], id="empty-list"),
    pytest.param({}, id="empty-object"),
    pytest.param(["a1"], id="list"),
    pytest.param({"site": "a1"}, id="object"),
    pytest.param("../a1", id="path"),
    pytest.param(" a1", id="whitespace"),
])
def test_already_invalid_scope_values_still_refuse_without_writes(scopes, bad_scope):
    north, _, _, _ = scopes
    publish(north, scope="site")
    damage_site_scope(north, bad_scope)
    before = stored_files(library._root())
    with pytest.raises(library.LibraryError) as refused:
        charts.load_defaults(north.contract)
    assert str(refused.value) == UNREADABLE
    assert stored_files(library._root()) == before


def test_empty_contract_scope_and_string_zero_site_keep_precedence_and_isolation(scopes):
    north, south, other, combined = scopes
    zero = replace(north, key="zero", facilities=(Facility("0", "Synthetic Zero Site"),))
    library.save_profile(zero, expected_revision=0, actor="Synthetic Tester", confirmed=True)
    assert charts.load_defaults(north.contract) == charts.ChartDefaults()
    _, red, _ = publish(north)
    _, blue, _ = publish(zero, "blue", scope="site", revision=1)
    _, green, _ = publish(north, "green", scope="site", revision=2)
    before = stored_files(library._root())
    state = charts.load_defaults(north.contract)
    assert {item.site_key for item in state.charts} == {"", "0", north.facilities[0].key}
    for profile, expected in ((zero, blue), (north, green), (south, red), (combined, red)):
        assets = {}
        result = guided._initial_draft(library.load_profile(profile.contract, profile.key),
                                       ReportPeriod(2026, 10), "Synthetic Tester", assets=assets)
        assert chart(result).asset_hashes == expected.asset_hashes
        assert set(assets) == set(expected.asset_hashes)
    other_draft = blank_chart(other)
    assert charts.apply_defaults(other_draft, {}) == other_draft
    assert charts.load_defaults(other.contract) == charts.ChartDefaults()
    assert stored_files(library._root()) == before


@pytest.mark.parametrize("kind", ["saved", "carried", "populated", "omitted", "excluded"])
def test_damaged_defaults_do_not_disturb_existing_report_choices(scopes, kind):
    north, south, _, _ = scopes
    empty = blank_chart(south)
    own, assets = picture("blue")
    active = with_chart(empty, replace(own, text="Synthetic South standing note."))
    saved = library.save_snapshot(active, expected_revision=0, assets=tuple(assets.items()))
    if kind == "saved":
        active = library.load_snapshot(south.contract, south.key, active.period).draft
    elif kind == "carried":
        active = new_month_draft(active, ReportPeriod(2026, 11))
    elif kind == "populated":
        active = with_chart(empty, ResolvedBlock("org_chart", "This month", text="Own chart notes."))
    elif kind == "omitted":
        active = with_chart(active, replace(chart(active), source="Omit"))
    else:
        active = replace(empty, sections=tuple(
            replace(section, included=False) if section.key == "organization" else section
            for section in empty.sections))
    publish(north, scope="site")
    damage_site_scope(north, None)
    before = stored_files(library._root())
    original_assets = dict(assets)

    assert charts.apply_defaults(active, assets) == active
    assert assets == original_assets
    assert library.load_snapshot(south.contract, south.key, saved.draft.period) == saved
    assert library.load_snapshot_version(south.contract, south.key, saved.draft.period, 1) == saved
    assert stored_files(library._root()) == before


def test_wrong_site_pixels_cannot_reach_public_docx_after_refused_use(scopes):
    north, south, _, _ = scopes
    own, assets = picture("blue")
    draft = with_chart(blank_chart(south), own)
    draft = replace(draft, sections=tuple(s for s in draft.sections if s.key == "organization"),
                    blocks=(own,))
    _, wrong, wrong_assets = publish(north, "red", scope="site")
    blue_pixels = decoded_pixels(assets[own.asset_hashes[0]])
    red_pixels = decoded_pixels(wrong_assets[wrong.asset_hashes[0]])
    assert blue_pixels in docx_pixels(draft, assets)
    damage_site_scope(north, None)
    before = stored_files(library._root())
    original_assets = dict(assets)

    # Model the editor's retained-report behavior when its public use is refused.
    # Before the fix this succeeds, and the actual DOCX contains the wrong pixels.
    try:
        applied = charts.use_default(draft, own, assets, expected_revision=1,
                                     expected_fingerprint=own.fingerprint)
    except library.LibraryError as refused:
        assert str(refused) == UNREADABLE
    else:
        draft = with_chart(draft, applied)

    rendered = docx_pixels(draft, assets)
    assert blue_pixels in rendered, "The report's own chart must survive damaged shared metadata."
    assert red_pixels not in rendered, "A different site's chart must not enter generated output."
    assert assets == original_assets
    assert stored_files(library._root()) == before


def test_chart_controls_withhold_damaged_scope_then_retry_restored_catalogue(scopes):
    north, south, _, _ = scopes
    own, assets = picture("blue")
    own = replace(own, text="Keep Synthetic South notes.")
    draft = with_chart(blank_chart(south), own)
    publish(north, "red", scope="site")
    app = start(draft, dict(assets))
    assert not app.exception
    assert not any(b.label == "Use saved chart in this report" for b in app.button)
    path, original = damage_site_scope(north, False)
    before = stored_files(library._root())
    app.run()

    assert not app.exception
    assert any(literal(UNREADABLE) in warning.value for warning in app.warning)
    assert not any(b.label in {"Use saved chart in this report", "Publish chart default"}
                   for b in app.button)
    assert app.session_state["draft"] == draft
    assert app.session_state["assets"] == assets
    assert not app.session_state["explicit"]
    assert stored_files(library._root()) == before

    path.write_bytes(original)
    app.run()
    assert not app.exception
    assert not any(literal(UNREADABLE) in warning.value for warning in app.warning)
    assert not any(b.label == "Use saved chart in this report" for b in app.button)
    assert button(app, "Publish chart default").disabled
    assert app.session_state["draft"] == draft
    _, contract, _ = publish(north, "red", scope="contract", revision=1)
    before = stored_files(library._root())
    app.run()
    assert any("Contract default" in caption.value for caption in app.caption)
    assert app.session_state["draft"] == draft
    button(app, "Use saved chart in this report").click().run()
    app.run()
    assert not app.exception
    assert chart(app.session_state["draft"]).asset_hashes == contract.asset_hashes
    assert chart(app.session_state["draft"]).text == own.text
    assert stored_files(library._root()) == before


def open_monthly(profile):
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, profile.facilities[0].title)
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Scope Editor").run()
    assert not app.exception
    return app


def test_actual_monthly_saved_chart_edits_save_reopen_with_damaged_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.web_ui.device_token", lambda cookies: "")
    monkeypatch.setattr(guided, "operator_today", lambda tz: date(2026, 10, 7))
    # This checks the actual Monthly editor/storage path; PDF preview rendering
    # is covered separately and is not claimed by this synthetic AppTest.
    monkeypatch.setattr("app.monthly_report_section_preview_ui.render_section_preview", lambda *a, **kw: None)
    north = replace(synthetic_profiles()[0], contract=RRH_CONTRACT, key="synthetic-north",
                    title="Synthetic North Report", template="enfra_builtin:monthly_review_v1",
                    facilities=(Facility("north", "Synthetic North Facility"),),
                    excluded_sections=tuple(s.key for s in default_sections()
                                            if s.key not in {"organization", "activity"}))
    south = replace(north, key="synthetic-south", title="Synthetic South Report",
                    facilities=(Facility("south", "Synthetic South Facility"),))
    for profile in (north, south):
        library.save_profile(profile, expected_revision=0, actor="Synthetic Scope Editor", confirmed=True)
    publish(north, "red", scope="site")
    own, assets = picture("blue")
    draft = ReportDraft(south, ReportPeriod(2026, 9), "Synthetic Scope Editor", profile_sections(south),
                        (own, ResolvedBlock("activity_summary", "This month", text="Synthetic South saved work.")))
    saved = library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()))
    owned_files = stored_files(library._profile_path(south.contract, south.key))
    app = open_monthly(south)
    button(app, "Edit chart").click().run()
    assert not any(b.label == "Use saved chart in this report" for b in app.button)
    path, original = damage_site_scope(north, None)
    shared_files = stored_files(charts._path(north.contract))
    app.run()

    assert not app.exception
    assert any(literal(UNREADABLE) in warning.value for warning in app.warning)
    assert not any(b.label == "Use saved chart in this report" for b in app.button)
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Synthetic South new work remains editable.").run()
    button(app, "Save shared version").click().run()
    assert not app.exception
    updated = library.load_snapshot(south.contract, south.key, draft.period)
    assert updated.revision == saved.revision + 1
    assert chart(updated.draft).asset_hashes == own.asset_hashes
    assert next(b.text for b in updated.draft.blocks if b.key == "activity_summary") == (
        "Synthetic South new work remains editable.")
    assert library.load_snapshot_version(south.contract, south.key, draft.period, 1) == saved
    assert stored_files(library._profile_path(south.contract, south.key)) == owned_files
    assert stored_files(charts._path(north.contract)) == shared_files

    reopened = open_monthly(south)
    assert next(w for w in reopened.text_area if w.label == "Activity summary").value == (
        "Synthetic South new work remains editable.")
    button(reopened, "Edit chart").click().run()
    assert not reopened.exception
    assert any(literal(UNREADABLE) in warning.value for warning in reopened.warning)
    assert not any(b.label == "Use saved chart in this report" for b in reopened.button)
    assert library.load_snapshot(south.contract, south.key, draft.period) == updated
    path.write_bytes(original)
    reopened.run()
    assert not reopened.exception
    assert not any(literal(UNREADABLE) in warning.value for warning in reopened.warning)
    assert not any(b.label == "Use saved chart in this report" for b in reopened.button)
    assert library.load_snapshot(south.contract, south.key, draft.period) == updated
