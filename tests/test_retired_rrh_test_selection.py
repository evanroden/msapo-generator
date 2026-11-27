"""Exact retired test identity is hidden, with deliberate non-destructive access."""
from dataclasses import replace
from app import monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import Facility, synthetic_profiles
from test_monthly_report_ui import monthly

KEY = 'rrh-tester-ux-review-2026-10-09'
TITLE = 'RRH Tester – UX Review 2026-10-09'


def test_retired_site_is_hidden_until_requested_and_saved_profile_unchanged(monkeypatch, tmp_path):
    monthly(monkeypatch, tmp_path, saved=False)
    profile = replace(synthetic_profiles()[0], contract=RRH_CONTRACT, key=KEY,
                      title=TITLE, facilities=(Facility(KEY, TITLE),))
    library.save_profile(profile, expected_revision=0, actor='Synthetic editor', confirmed=True)
    before = library.load_profile(RRH_CONTRACT, KEY)
    app = monthly(monkeypatch, tmp_path, saved=False)
    assert not app.exception
    assert not any(item.key and item.key.endswith('_' + KEY) for item in app.checkbox)
    show = next(item for item in app.checkbox if item.label == 'Show the retired RRH test site')
    show.check().run()
    assert not app.exception
    assert any(item.key and item.key.endswith('_' + KEY) and not item.value for item in app.checkbox)
    next(item for item in app.checkbox if item.key and item.key.endswith('_' + KEY)).check().run()
    assert not app.exception
    assert any('Site: ' + TITLE in item.value.replace(chr(92), '') for item in app.caption)
    assert library.load_profile(RRH_CONTRACT, KEY) == before
    next(item for item in app.checkbox if item.label == 'Show the retired RRH test site').uncheck().run()
    assert not any(item.key and item.key.endswith('_' + KEY) for item in app.checkbox)
    assert library.load_profile(RRH_CONTRACT, KEY) == before


def test_other_test_named_site_is_not_hidden(monkeypatch, tmp_path):
    from app import monthly_report_start_ui as ui
    app = monthly(monkeypatch, tmp_path, saved=False)
    original = ui._site_options
    monkeypatch.setattr(ui, '_site_options', lambda contract: (*original(contract), Facility('test-lab', 'Synthetic Test Laboratory')))
    app.run()
    assert any(item.label == 'Synthetic Test Laboratory' for item in app.checkbox)
