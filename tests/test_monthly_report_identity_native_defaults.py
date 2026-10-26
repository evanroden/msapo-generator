"""Report identity controls declare their kept value as the browser default.

After a reload the browser can register a native control from its declared
default before it reports the value restored from session state. Option 0 or
an unchecked box then replaced the report period (January 2000) or its sites
on the next ordinary click, and the editor opened a different, empty draft.
Server-side values are unchanged by these declarations; only the browser's
fallback is. AppTest proves the declared protocol defaults, not browser timing.
"""
from test_monthly_report_ui import monthly


def _sites(app):
    return [item for item in app.checkbox if item.key.startswith("report_sites_") and "_region_" not in item.key]


def _declared_choice(select):
    return select.options[select.proto.default] if select.proto.HasField("default") else None


def test_kept_period_and_sites_are_the_declared_native_defaults(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    _sites(app)[0].check().run()
    _sites(app)[-1].check().run()
    app.selectbox("report_month_number").set_value(3).run()
    app.selectbox("report_year").set_value(2025).run()
    next(item for item in app.text_input if item.label == "Name for this group (optional)").input("Synthetic Group").run()
    next(item for item in app.checkbox if item.label == "This is a regional report").check().run()
    assert not app.exception

    for _ in range(2):  # the edit's own run, then an ordinary rerun
        month, year = app.selectbox("report_month_number"), app.selectbox("report_year")
        assert (month.value, year.value) == (3, 2025)
        # A browser falling back to these keeps March 2025, never option 0.
        assert (_declared_choice(month), _declared_choice(year)) == ("March", "2025")
        chosen = [item for item in _sites(app) if item.value]
        assert len(chosen) == 2 and all(item.proto.default for item in chosen)
        regional = next(item for item in app.checkbox if item.label == "This is a regional report")
        assert regional.value and regional.proto.default
        texts = [item for item in app.text_input if item.key.startswith("report_sites_")]
        assert any(item.label == "Name for this group (optional)" for item in texts)
        assert all(item.proto.default == item.value for item in texts), [(item.label, item.proto.default, item.value) for item in texts]
        app.run()
        assert not app.exception


def test_unchecked_sites_still_declare_unchecked(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    _sites(app)[0].check().run()
    _sites(app)[0].uncheck().run()
    assert not app.exception
    assert all(item.proto.default is False and item.value is False for item in _sites(app))
    month = app.selectbox("report_month_number")
    assert month.value == 9 and _declared_choice(month) == "September"
