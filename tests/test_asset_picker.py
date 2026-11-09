"""Synthetic large-site search and single-asset workflow regressions."""

from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from app.asset_picker import ASSET_SEARCH_LIMIT, search_asset_uids
from app import web_ui


def _site():
    rows = [
        {
            "uid": f"SYN-AHU-{n:04d}",
            "asset": f"AHU-{n:04d}",
            "equipment": "Air Handling Unit",
            "serves": "North Wing",
        }
        for n in range(3000)
    ]
    rows[2987].update(
        uid="SYN-SLR-2987",
        asset="SLR-2987",
        equipment="Steam Sterilizer",
        serves="Pharmacy Wing",
    )
    return rows


def test_3000_asset_search_finds_distinctive_uid_or_tag_fragments():
    rows = _site()
    for query in ("2987", "SLR", "SYN-SLR", "synslr"):
        assert search_asset_uids(rows, query) == ["SYN-SLR-2987"]


def test_3000_asset_search_matches_equipment_serves_and_multiword_terms():
    rows = _site()
    for query in ("sterilizer", "Pharmacy", "steam pharmacy"):
        assert search_asset_uids(rows, query) == ["SYN-SLR-2987"]


def test_search_is_explicit_and_always_bounded():
    rows = _site()
    assert search_asset_uids(rows, "") == []
    assert search_asset_uids(rows, "not-in-registry") == []
    assert len(search_asset_uids(rows, "AHU")) == ASSET_SEARCH_LIMIT
    assert len(search_asset_uids(rows, "north", limit=5)) == 5
    assert search_asset_uids(rows, "AHU", limit=0) == []


def test_large_registry_type_only_quote_does_not_guess_a_unit(monkeypatch):
    rows = _site()
    monkeypatch.setattr(web_ui.contracts, "assets_for_site", lambda *_: rows)
    monkeypatch.setattr(web_ui.contracts, "guess_uid", lambda *args, **kwargs: None)
    analysis = SimpleNamespace(
        asset_reference="Steam Sterilizer",
        project_description="Repair steam sterilizer",
        scope_of_work="Repair steam sterilizer",
    )
    _, _, guessed = web_ui._asset_control_data(
        analysis=analysis,
        quote_text="Repair steam sterilizer",
        contract="Synthetic Contract",
        rrh=False,
        site="Synthetic Site",
        rrh_site_key=None,
    )
    assert guessed is None


def _app_for_asset_control(tmp_path, *, rrh):
    script = tmp_path / "synthetic_asset_control.py"
    script.write_text(
        "from types import SimpleNamespace\n"
        "from app.web_ui import _render_asset_control\n"
        "_render_asset_control(\n"
        "    analysis=SimpleNamespace(asset_reference=None),\n"
        "    quote_text='', token='synthetic',\n"
        "    contract='Synthetic Contract', site='Synthetic Site',\n"
        f"    rrh={rrh!r}, rrh_site_key=None,\n"
        ")\n",
        encoding="utf-8",
    )
    return AppTest.from_file(script, default_timeout=20).run()


def test_large_picker_renders_bounded_options_and_preserves_unanswered_state(
    monkeypatch, tmp_path
):
    rows = _site()
    labels = {row["uid"]: row["asset"] for row in rows}
    monkeypatch.setattr(
        web_ui,
        "_asset_control_data",
        lambda **_: (rows, labels, None),
    )
    app = _app_for_asset_control(tmp_path, rrh=False)
    key = "asset_synthetic_Synthetic Contract_Synthetic Site"
    assert not app.exception
    assert app.session_state[key] == web_ui.ASSET_PLACEHOLDER
    assert len(app.selectbox) == 1
    assert len(app.selectbox[0].options) == 2

    search = next(field for field in app.text_input if field.label.startswith("Find an asset"))
    search.set_value("SLR").run()
    assert not app.exception
    assert len(app.selectbox[0].options) <= ASSET_SEARCH_LIMIT + 3
    assert any("SYN-SLR-2987" in option for option in app.selectbox[0].options)
    assert app.session_state[key] == web_ui.ASSET_PLACEHOLDER

    app.selectbox[0].set_value("SYN-SLR-2987").run()
    assert not app.exception
    assert app.session_state[key] == "SYN-SLR-2987"

    search = next(field for field in app.text_input if field.label.startswith("Find an asset"))
    search.set_value("not-in-registry").run()
    assert not app.exception
    assert len(app.selectbox[0].options) == 2
    assert app.session_state[key] == "SYN-SLR-2987"
    assert any("SYN-SLR-2987" in option for option in app.selectbox[0].options)


def test_rrh_asset_picker_keeps_original_single_selectbox(monkeypatch, tmp_path):
    rows = _site()[:2]
    labels = {row["uid"]: row["asset"] for row in rows}
    monkeypatch.setattr(
        web_ui,
        "_asset_control_data",
        lambda **_: (rows, labels, rows[0]["uid"]),
    )
    app = _app_for_asset_control(tmp_path, rrh=True)
    assert not app.exception
    assert len(app.selectbox) == 1
    assert len(app.selectbox[0].options) == 3
    assert not any(field.label.startswith("Find an asset") for field in app.text_input)
    assert app.session_state[
        "asset_synthetic_Synthetic Contract_Synthetic Site"
    ] == rows[0]["uid"]
